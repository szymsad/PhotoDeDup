"""
scanner.py — skanowanie folderu, obliczanie MD5 / pHash, odczyt EXIF.

Architektura:
- scan() to główna funkcja, uruchamiana w osobnym wątku (żeby nie blokować GUI)
- postęp raportowany przez callback on_progress(current, total, path)
- wyniki zwracane przez callback on_done(results)
- błędy przez callback on_error(path, message)

Obsługiwane formaty:
- JPEG, PNG, GIF, BMP, TIFF, WebP  — natywne Pillow
- HEIC / HEIF (iPhone od iOS 11)   — wymaga pillow-heif
- RAW: CR2, NEF, ARW, DNG          — wymaga rawpy (opcjonalne)
"""

import os
import hashlib
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Optional, Callable
from datetime import datetime

from PIL import Image
import imagehash

from core.database import Database, CachedFile

# ------------------------------------------------------------------ HEIC support (iPhone)
try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
    HEIF_SUPPORTED = True
except ImportError:
    HEIF_SUPPORTED = False


IMAGE_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".gif", ".bmp",
    ".tiff", ".tif", ".webp",
    ".heic", ".heif",   # iPhone (domyślny format od iOS 11)
    ".raw", ".cr2", ".nef", ".arw", ".dng",
}

# Formaty które mogą zawierać EXIF (używamy szerszej listy niż wcześniej —
# pillow-heif udostępnia EXIF z HEIC przez standardowy interfejs)
EXIF_EXTENSIONS = {
    ".jpg", ".jpeg",
    ".tiff", ".tif",
    ".heic", ".heif",
    ".webp",
}

# Tagi EXIF
_TAG_DATETIME_ORIGINAL = 36867   # DateTimeOriginal
_TAG_DATETIME          = 306     # DateTime (fallback)
_TAG_MAKE              = 271     # Marka aparatu
_TAG_MODEL             = 272     # Model aparatu


@dataclass
class FileResult:
    """Wynik skanowania pojedynczego pliku."""
    path:       str
    size:       int
    mtime:      float
    md5:        Optional[str] = None
    phash:      Optional[str] = None
    width:      Optional[int] = None
    height:     Optional[int] = None
    exif_date:  Optional[str] = None
    exif_make:  Optional[str] = None
    exif_model: Optional[str] = None
    error:      Optional[str] = None

    @property
    def resolution(self) -> int:
        """Rozdzielczość w pikselach (do porównywania który plik zachować)."""
        if self.width and self.height:
            return self.width * self.height
        return 0

    @property
    def device_name(self) -> Optional[str]:
        """Czytelna nazwa urządzenia z EXIF."""
        if self.exif_make and self.exif_model:
            make  = self.exif_make.strip()
            model = self.exif_model.strip()
            # unikamy duplikowania nazwy marki w modelu (np. "Apple Apple iPhone 15")
            if model.lower().startswith(make.lower()):
                return model
            return f"{make} {model}"
        return None


# ------------------------------------------------------------------ helpers

def _md5(path: str, chunk: int = 1 << 20) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        while buf := f.read(chunk):
            h.update(buf)
    return h.hexdigest()


def _read_exif(img: Image.Image) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """
    Odczytuje z obrazu: datę, markę i model aparatu.
    Zwraca (exif_date, make, model) — każde może być None.

    Używa publicznego img.getexif() (Pillow 9+) który działa z JPEG, TIFF,
    WebP i HEIC (przez pillow-heif). Fallback do prywatnego _getexif()
    dla starszych plików.
    """
    # --- Próba 1: nowe publiczne API (Pillow 9+, kompatybilne z HEIC) ---
    try:
        exif = img.getexif()
        if exif:
            date  = exif.get(_TAG_DATETIME_ORIGINAL) or exif.get(_TAG_DATETIME)
            make  = exif.get(_TAG_MAKE)
            model = exif.get(_TAG_MODEL)

            if date:
                # Normalizuj format EXIF "2023:12:15 14:30:00" → "2023-12-15 14:30:00"
                date = date.replace(":", "-", 2)

            return (
                date.strip()  if isinstance(date,  str) and date.strip()  else None,
                make.strip()  if isinstance(make,  str) and make.strip()  else None,
                model.strip() if isinstance(model, str) and model.strip() else None,
            )
    except Exception:
        pass

    # --- Próba 2: stare prywatne API (JPEG legacy) ---
    try:
        exif_data = img._getexif()  # type: ignore[attr-defined]
        if exif_data:
            date  = exif_data.get(_TAG_DATETIME_ORIGINAL) or exif_data.get(_TAG_DATETIME)
            make  = exif_data.get(_TAG_MAKE)  or ""
            model = exif_data.get(_TAG_MODEL) or ""

            if date:
                date = date.replace(":", "-", 2)

            return (
                date.strip()  if date  and date.strip()  else None,
                make.strip()  if make  and make.strip()  else None,
                model.strip() if model and model.strip() else None,
            )
    except Exception:
        pass

    return None, None, None


def _process_file(path: str) -> "FileResult":
    """
    Przetwarza jeden plik: MD5 + pHash + EXIF.
    Uruchamiane w wątku roboczym.
    """
    try:
        stat   = os.stat(path)
        result = FileResult(path=path, size=stat.st_size, mtime=stat.st_mtime)

        result.md5 = _md5(path)

        with Image.open(path) as img:
            result.width, result.height = img.size

            # pHash na skali szarości — odporniejszy na zmianę nasycenia/balansu bieli
            gray         = img.convert("L").convert("RGB")
            result.phash = str(imagehash.phash(gray))

            ext = os.path.splitext(path)[1].lower()
            if ext in EXIF_EXTENSIONS:
                result.exif_date, result.exif_make, result.exif_model = _read_exif(img)

        return result

    except Exception as e:
        try:
            stat = os.stat(path)
        except OSError:
            stat = None
        return FileResult(
            path=path,
            size=stat.st_size  if stat else 0,
            mtime=stat.st_mtime if stat else 0,
            error=str(e),
        )


# ------------------------------------------------------------------ Scanner

class Scanner:
    """
    Skanuje folder z obrazami. Uruchom scan() w osobnym wątku żeby nie blokować GUI.

    Obsługuje HEIC/HEIF (iPhone) jeśli zainstalowane pillow-heif.

    Przykład użycia:
        scanner = Scanner(db)
        scanner.scan(
            folder="/Zdjęcia",
            on_progress=lambda cur, tot, path: ...,
            on_done=lambda results: ...,
            on_error=lambda path, msg: ...
        )
    """

    def __init__(self, db: Database, workers: int = 8):
        self.db      = db
        self.workers = workers
        self._stop_event = threading.Event()

    @property
    def heif_supported(self) -> bool:
        """Czy obsługa HEIC/HEIF jest dostępna."""
        return HEIF_SUPPORTED

    def stop(self):
        """Przerywa skanowanie (np. gdy użytkownik kliknie Anuluj)."""
        self._stop_event.set()

    def scan(
        self,
        folder:      str,
        on_progress: Callable[[int, int, str], None] = None,
        on_done:     Callable[[list], None]           = None,
        on_error:    Callable[[str, str], None]       = None,
    ):
        """
        Główna metoda skanowania. Uruchamiaj w threading.Thread żeby nie blokować GUI.

        on_progress(current, total, current_path) — wywoływane po każdym pliku
        on_done(results)                           — wywoływane po zakończeniu
        on_error(path, message)                    — wywoływane przy błędzie pliku
        """
        self._stop_event.clear()

        # 1. Znajdź wszystkie pliki obrazów
        all_paths = self._find_images(folder)
        total     = len(all_paths)

        if total == 0:
            if on_done:
                on_done([])
            return

        # 2. Sprawdź cache — które pliki już znamy
        results:    list[FileResult] = []
        to_process: list[str]        = []

        for path in all_paths:
            # ← POPRAWKA: sprawdzamy stop_event również w pętli cache
            if self._stop_event.is_set():
                break
            try:
                stat   = os.stat(path)
                cached = self.db.get_cached(path, stat.st_size, stat.st_mtime)
                if cached:
                    results.append(FileResult(
                        path=cached.path,
                        size=cached.size,
                        mtime=cached.mtime,
                        md5=cached.md5,
                        phash=cached.phash,
                        width=cached.width,
                        height=cached.height,
                        exif_date=cached.exif_date,
                        exif_make=cached.exif_make,
                        exif_model=cached.exif_model,
                    ))
                else:
                    to_process.append(path)
            except OSError:
                pass

        cached_count = len(results)
        processed    = cached_count
        batch: list[FileResult] = []
        BATCH_SIZE = 100

        # 3. Przetwórz nowe/zmienione pliki wielowątkowo
        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            futures = {pool.submit(_process_file, p): p for p in to_process}

            for future in as_completed(futures):
                if self._stop_event.is_set():
                    pool.shutdown(wait=False, cancel_futures=True)
                    break

                file_result = future.result()
                processed  += 1

                if file_result.error:
                    if on_error:
                        on_error(file_result.path, file_result.error)
                else:
                    results.append(file_result)
                    batch.append(file_result)

                    if len(batch) >= BATCH_SIZE:
                        self._save_batch(batch)
                        batch.clear()

                if on_progress:
                    on_progress(processed, total, file_result.path)

        # zapisz pozostały batch
        if batch:
            self._save_batch(batch)

        if on_done:
            on_done(results)

    # ---------------------------------------------------------------- helpers

    def _find_images(self, folder: str) -> list[str]:
        paths = []
        for dirpath, _, filenames in os.walk(folder):
            if self._stop_event.is_set():
                break
            for fname in filenames:
                if os.path.splitext(fname)[1].lower() in IMAGE_EXTENSIONS:
                    paths.append(os.path.join(dirpath, fname))
        return sorted(paths)

    def _save_batch(self, batch: list[FileResult]):
        for fr in batch:
            self.db.upsert(CachedFile(
                path=fr.path,       size=fr.size,       mtime=fr.mtime,
                md5=fr.md5,         phash=fr.phash,
                width=fr.width,     height=fr.height,
                exif_date=fr.exif_date,
                exif_make=fr.exif_make,
                exif_model=fr.exif_model,
            ))
        self.db.flush()