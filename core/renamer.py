"""
renamer.py — zmiana nazw plików wg daty i źródła.

Dwa tryby:
  change_date()  — nadaje jednolite nazwy wg schematu PREFIX_YYYYMMDD_HHMMSS
  add_tag()      — dodaje sufiks do istniejących nazw

Źródło daty (priorytet):
  1. exif_date z FileResult (już odczytane przez Scanner)
  2. data modyfikacji pliku (mtime)

Wykrywanie źródła zdjęcia:
  - Wzorce w nazwie pliku → prefix (SCR, FB, MSG, IG, SNAP, TWX, TT, TG)
  - Wzorce w EXIF Make/Model → prefix
  - Brak dopasowania → IMG_ (zdjęcie z aparatu) lub VID_ (film)
"""

import os
import datetime
from dataclasses import dataclass, field
from typing import Optional, Callable

from core.scanner import FileResult

# ------------------------------------------------------------------ Rozszerzenia

VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".3gp", ".m4v", ".wmv", ".ts"}

# ------------------------------------------------------------------ Wzorce źródeł

# (lista_fragmentów_nazwy_pliku, prefix)
FILENAME_PATTERNS: list[tuple[list[str], str]] = [
    (["screenshot", "screen_", "scr_", "zrzut"],       "SCR"),
    (["fb_img_", "facebook_", "fb-img"],                "FB"),
    (["received_", "messenger_", "msg_img"],            "MSG"),
    (["instagram", "ig_"],                              "IG"),
    (["snap_", "snapchat"],                             "SNAP"),
    (["twitter", "tweet_"],                             "TWX"),
    (["tiktok_", "tt_"],                                "TT"),
    (["telegram_", "tg_img"],                           "TG"),
    (["whatsapp"],                                      "MSG"),
]

# (lista_fragmentów_wartości_EXIF, prefix)  — sprawdzamy Make i Model
EXIF_DEVICE_PATTERNS: list[tuple[list[str], str]] = [
    (["screenshot", "screen capture"],  "SCR"),
    (["facebook"],                      "FB"),
    (["messenger"],                     "MSG"),
    (["instagram"],                     "IG"),
    (["snapchat"],                      "SNAP"),
    (["twitter", "tweetbot"],           "TWX"),
    (["tiktok"],                        "TT"),
    (["telegram"],                      "TG"),
    (["whatsapp"],                      "MSG"),
]

# Wszystkie znane prefixy — do sprawdzania czy plik już jest przemianowany
ALL_PREFIXES = {"SCR", "FB", "MSG", "IG", "SNAP", "TWX", "TT", "TG", "IMG", "VID"}


# ------------------------------------------------------------------ Wynik operacji

@dataclass
class RenameResult:
    """Wynik przemianowania jednego pliku."""
    original_path: str
    new_path:      Optional[str]   = None   # None = bez zmian
    error:         Optional[str]   = None
    skipped:       bool            = False   # plik pominięty (nieobsługiwany typ)

    @property
    def changed(self) -> bool:
        return self.new_path is not None and self.new_path != self.original_path

    @property
    def original_name(self) -> str:
        return os.path.basename(self.original_path)

    @property
    def new_name(self) -> Optional[str]:
        return os.path.basename(self.new_path) if self.new_path else None


# ------------------------------------------------------------------ Pomocnicze

def _detect_source(filename: str, exif_make: Optional[str], exif_model: Optional[str]) -> Optional[str]:
    """
    Zwraca prefix źródła (np. 'SCR', 'FB') lub None jeśli to normalne zdjęcie z aparatu.
    """
    name_lower = filename.lower()

    # 1. Wzorce w nazwie pliku
    for patterns, prefix in FILENAME_PATTERNS:
        for pat in patterns:
            if pat in name_lower:
                return prefix

    # 2. Wzorce w EXIF Make/Model
    for field_val in (exif_make or "", exif_model or ""):
        val_lower = field_val.lower()
        if not val_lower:
            continue
        for patterns, prefix in EXIF_DEVICE_PATTERNS:
            for pat in patterns:
                if pat in val_lower:
                    return prefix

    return None  # normalne zdjęcie z aparatu


def _is_already_renamed(name: str) -> bool:
    """Sprawdza czy plik już ma jeden z naszych prefixów."""
    for prefix in ALL_PREFIXES:
        if name.startswith(prefix + "_"):
            return True
    return False


def _resolve_conflict(folder: str, new_name: str, ext: str) -> str:
    """
    Jeśli plik o danej nazwie już istnieje, dodaje licznik: _1, _2, ...
    Zwraca pełną ścieżkę docelową (gwarantowanie wolną).
    """
    candidate = os.path.join(folder, new_name + ext)
    counter   = 1
    while os.path.exists(candidate):
        candidate = os.path.join(folder, f"{new_name}_{counter}{ext}")
        counter  += 1
    return candidate


def _date_from_mtime(path: str) -> Optional[datetime.datetime]:
    try:
        return datetime.datetime.fromtimestamp(os.path.getmtime(path))
    except Exception:
        return None


def _video_date(path: str) -> Optional[datetime.datetime]:
    """
    Data wideo: hachoir (jeśli dostępny) → mtime.
    """
    try:
        from hachoir.parser import createParser
        from hachoir.metadata import extractMetadata
        parser = createParser(path)
        if parser:
            with parser:
                meta = extractMetadata(parser)
                if meta:
                    for attr in ("creation", "last_modification", "date_time_original"):
                        try:
                            val = meta.get(attr)
                            if val:
                                if isinstance(val, datetime.datetime):
                                    return val
                                if isinstance(val, datetime.date):
                                    return datetime.datetime(val.year, val.month, val.day)
                        except Exception:
                            continue
    except Exception:
        pass
    return _date_from_mtime(path)


# ------------------------------------------------------------------ Główna logika

class Renamer:
    """
    Przemianowuje pliki z listy FileResult (już zeskanowanych) lub
    bezpośrednio z folderu (dla filmów nieobsługiwanych przez Scanner).

    Wywołuj w osobnym wątku — operacje na dysku mogą trwać.
    """

    def rename_files(
        self,
        scan_results:  list[FileResult],
        folder:        str,
        dry_run:       bool = False,
        on_progress:   Callable[[int, int, str], None] = None,
        on_done:       Callable[[list[RenameResult]], None] = None,
    ) -> list[RenameResult]:
        """
        Zmienia nazwy plików na format PREFIX_YYYYMMDD_HHMMSS.

        scan_results: wyniki Scannera (zdjęcia z EXIF)
        folder:       ten sam folder — potrzebny do obsługi filmów
        dry_run:      True = tylko oblicz, nie zmieniaj nic na dysku
        """
        results: list[RenameResult] = []

        # Słownik ścieżka → FileResult dla szybkiego dostępu
        result_map = {fr.path: fr for fr in scan_results}

        # Zbierz wszystkie pliki z folderu (zdjęcia + filmy)
        all_files: list[str] = []
        for fname in sorted(os.listdir(folder)):
            fpath = os.path.join(folder, fname)
            if os.path.isfile(fpath):
                ext = os.path.splitext(fname)[1].lower()
                from core.scanner import IMAGE_EXTENSIONS
                if ext in IMAGE_EXTENSIONS or ext in VIDEO_EXTENSIONS:
                    all_files.append(fpath)

        total = len(all_files)

        for idx, fpath in enumerate(all_files, 1):
            fname = os.path.basename(fpath)
            name, ext = os.path.splitext(fname)
            ext_lower  = ext.lower()

            if on_progress:
                on_progress(idx, total, fname)

            # ── ZDJĘCIA (dane z Scannera) ──
            from core.scanner import IMAGE_EXTENSIONS
            if ext_lower in IMAGE_EXTENSIONS:
                fr = result_map.get(fpath)
                exif_make  = fr.exif_make  if fr else None
                exif_model = fr.exif_model if fr else None
                exif_date  = fr.exif_date  if fr else None

                source_prefix = _detect_source(fname, exif_make, exif_model)

                # Data: EXIF → mtime
                date_dt: Optional[datetime.datetime] = None
                if exif_date:
                    try:
                        date_dt = datetime.datetime.fromisoformat(exif_date)
                    except Exception:
                        pass
                if date_dt is None:
                    date_dt = _date_from_mtime(fpath)

                new_name = self._build_image_name(name, source_prefix, date_dt)

            # ── FILMY ──
            elif ext_lower in VIDEO_EXTENSIONS:
                source_prefix = None   # filmy nie mają wzorców źródeł
                date_dt       = _video_date(fpath)
                new_name      = self._build_video_name(name, date_dt)

            else:
                results.append(RenameResult(original_path=fpath, skipped=True))
                continue

            # Bez zmian?
            if new_name == name:
                results.append(RenameResult(original_path=fpath, new_path=fpath))
                continue

            # Rozwiąż konflikty i przemianuj
            target_path = _resolve_conflict(folder, new_name, ext)

            if not dry_run:
                try:
                    os.rename(fpath, target_path)
                    results.append(RenameResult(original_path=fpath, new_path=target_path))
                except Exception as e:
                    results.append(RenameResult(original_path=fpath, error=str(e)))
            else:
                results.append(RenameResult(original_path=fpath, new_path=target_path))

        if on_done:
            on_done(results)

        return results

    def add_tag(
        self,
        folder:      str,
        tag:         str,
        dry_run:     bool = False,
        on_progress: Callable[[int, int, str], None] = None,
        on_done:     Callable[[list[RenameResult]], None] = None,
    ) -> list[RenameResult]:
        """
        Dodaje sufiks _TAG do nazw wszystkich plików w folderze.
        Pomija pliki które już mają ten sufiks.
        """
        if not tag:
            return []

        tag_clean = tag.strip().strip("_")
        suffix    = f"_{tag_clean}"

        all_files = sorted(
            f for f in os.listdir(folder)
            if os.path.isfile(os.path.join(folder, f))
        )
        total   = len(all_files)
        results: list[RenameResult] = []

        for idx, fname in enumerate(all_files, 1):
            fpath      = os.path.join(folder, fname)
            name, ext  = os.path.splitext(fname)

            if on_progress:
                on_progress(idx, total, fname)

            if name.endswith(suffix):
                results.append(RenameResult(original_path=fpath, new_path=fpath))
                continue

            new_name    = name + suffix
            target_path = _resolve_conflict(folder, new_name, ext)

            if not dry_run:
                try:
                    os.rename(fpath, target_path)
                    results.append(RenameResult(original_path=fpath, new_path=target_path))
                except Exception as e:
                    results.append(RenameResult(original_path=fpath, error=str(e)))
            else:
                results.append(RenameResult(original_path=fpath, new_path=target_path))

        if on_done:
            on_done(results)

        return results

    # ---------------------------------------------------------------- helpers

    @staticmethod
    def _build_image_name(
        original_name:  str,
        source_prefix:  Optional[str],
        date:           Optional[datetime.datetime],
    ) -> str:
        if source_prefix:
            if date:
                return f"{source_prefix}_{date.strftime('%Y%m%d_%H%M%S')}"
            # Brak daty — zostaw lub dodaj prefix jeśli go nie ma
            if not _is_already_renamed(original_name):
                return f"{source_prefix}_{original_name}"
            return original_name
        else:
            # Normalne zdjęcie z aparatu → IMG_
            if date:
                return f"IMG_{date.strftime('%Y%m%d_%H%M%S')}"
            if not original_name.startswith("IMG_"):
                return f"IMG_{original_name}"
            return original_name

    @staticmethod
    def _build_video_name(
        original_name: str,
        date:          Optional[datetime.datetime],
    ) -> str:
        if date:
            return f"VID_{date.strftime('%Y%m%d_%H%M%S')}"
        if not original_name.startswith("VID_"):
            return f"VID_{original_name}"
        return original_name

    # ---------------------------------------------------------------- statystyki

    @staticmethod
    def summary(results: list[RenameResult]) -> dict:
        renamed  = [r for r in results if r.changed]
        skipped  = [r for r in results if r.skipped]
        errors   = [r for r in results if r.error]
        no_change = [r for r in results if not r.changed and not r.skipped and not r.error]
        return {
            "renamed":   len(renamed),
            "no_change": len(no_change),
            "skipped":   len(skipped),
            "errors":    len(errors),
            "total":     len(results),
        }