"""
grouper.py — grupowanie zdjec wedlug daty i/lub urzadzenia.

Hierarchia zrodel daty:
  1. EXIF DateTimeOriginal
  2. Regex z nazwy pliku
  3. mtime pliku

Parametr depth kontroluje glebokosc struktury folderow:
  "year"       -> 2023/
  "month"      -> 2023/12/
  "day"        -> 2023/12/15/
  (urzadzenie jest osobnym przelacznikiem)
"""

import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from core.scanner import FileResult


MONTH_NAMES_PL = {
    1: "01 Styczen",  2: "02 Luty",    3: "03 Marzec",
    4: "04 Kwiecien", 5: "05 Maj",     6: "06 Czerwiec",
    7: "07 Lipiec",   8: "08 Sierpien",9: "09 Wrzesien",
    10: "10 Pazdziernik", 11: "11 Listopad", 12: "12 Grudzien",
}

NONAME_DEVICE = "NoName"


def _sanitize_path_part(text: str) -> str:
    """
    Czyści jeden element ścieżki folderu:
    - usuwa null characters i inne znaki kontrolne (\x00-\x1f)
    - usuwa znaki niedozwolone w ścieżkach Windows
    - przycina białe znaki z początku i końca
    - zamienia ciągi spacji/podkreślników na jeden podkreślnik
    - jeśli po czyszczeniu jest pusty — zwraca NONAME_DEVICE
    """
    if not text:
        return NONAME_DEVICE
    # usuń znaki kontrolne (w tym \x00 null character)
    cleaned = re.sub(r'[\x00-\x1f\x7f]', '', text)
    # usuń znaki niedozwolone w Windows
    cleaned = re.sub(r'[<>:"/\\|?*]', '_', cleaned)
    # usuń kropki i spacje z końca (Windows nie lubi)
    cleaned = cleaned.strip().rstrip('.')
    # zamień wielokrotne spacje/podkreślniki
    cleaned = re.sub(r'[ _]{2,}', '_', cleaned)
    return cleaned if cleaned else NONAME_DEVICE

DATE_PATTERNS = [
    (re.compile(r"(?<!\d)(20\d{2})(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])(?!\d)"), "ymd"),
    (re.compile(r"(?<!\d)(20\d{2})[-._](0[1-9]|1[0-2])[-._](0[1-9]|[12]\d|3[01])(?!\d)"), "ymd"),
    (re.compile(r"(?<!\d)(0[1-9]|[12]\d|3[01])[-._](0[1-9]|1[0-2])[-._](20\d{2})(?!\d)"), "dmy"),
]


@dataclass
class PhotoDate:
    year: int
    month: int
    day: int
    source: str = "unknown"   # "exif" | "filename" | "mtime"


@dataclass
class PhotoGroup:
    device: Optional[str]    # None oznacza brak EXIF -> wyswietlamy NONAME_DEVICE
    year:   Optional[int]
    month:  Optional[int]
    day:    Optional[int]
    files:        list = field(default_factory=list)
    date_sources: dict = field(default_factory=dict)

    # ---- etykiety ----

    @property
    def device_label(self) -> str:
        return self.device if self.device else NONAME_DEVICE

    @property
    def label_year(self) -> str:
        return str(self.year) if self.year else "Nieznany rok"

    @property
    def label_month(self) -> str:
        if self.month:
            return MONTH_NAMES_PL.get(self.month, f"{self.month:02d}")
        return "Nieznany miesiac"

    @property
    def label_day(self) -> str:
        return f"{self.day:02d}" if self.day else "??"

    @property
    def label(self) -> str:
        parts = [self.device_label]
        if self.year:
            parts.append(str(self.year))
        if self.month:
            parts.append(MONTH_NAMES_PL.get(self.month, str(self.month)))
        if self.day:
            parts.append(str(self.day))
        return " / ".join(parts)

    # ---- inne ----

    @property
    def size_bytes(self) -> int:
        return sum(f.size for f in self.files)

    def suggested_folder(
        self,
        use_device: bool = True,
        depth: str = "month",   # "none" | "year" | "month" | "day"
        device_aliases: dict = None,
    ) -> str:
        """
        Buduje sciezke folderu wedlug ustawien uzytkownika.
        use_device:     czy dodac nazwe urzadzenia na poczatku
        depth:          jak gleboko schodzic w dacie
        device_aliases: slownik {oryginalna_nazwa: alias_folderu}
        """
        parts = []

        if use_device:
            # uzyj aliasu jesli jest, inaczej oryginalna nazwa
            raw_name = self.device_label
            if device_aliases and raw_name in device_aliases:
                raw_name = device_aliases[raw_name]
            safe = _sanitize_path_part(raw_name)
            parts.append(safe)

        if depth != "none" and self.year:
            parts.append(str(self.year))

            if depth in ("month", "day") and self.month:
                parts.append(f"{self.month:02d}")

                if depth == "day" and self.day:
                    parts.append(f"{self.day:02d}")

        return os.path.join(*parts) if parts else NONAME_DEVICE


class Grouper:
    """
    Grupuje pliki. Parametry:
      use_device: czy brac pod uwage urzadzenie z EXIF
      depth:      "year" | "month" | "day"
    """

    def __init__(self, use_device: bool = True, depth: str = "month"):
        self.use_device = use_device
        self.depth      = depth

    def run(self, files: list) -> list:
        groups: dict = {}

        for f in files:
            if f.error:
                continue

            device    = self._get_device(f) if self.use_device else None
            photo_date = self._get_date(f)
            key       = self._make_key(device, photo_date)

            if key not in groups:
                groups[key] = PhotoGroup(
                    device = device,
                    year   = photo_date.year  if photo_date else None,
                    month  = photo_date.month if photo_date and self.depth in ("month","day") else None,
                    day    = photo_date.day   if photo_date and self.depth == "day" else None,
                )

            groups[key].files.append(f)
            src = photo_date.source if photo_date else "unknown"
            groups[key].date_sources[src] = groups[key].date_sources.get(src, 0) + 1

        return self._sort(list(groups.values()))

    # ---- data ----

    def _get_date(self, f) -> Optional[PhotoDate]:
        if f.exif_date:
            try:
                dt = datetime.fromisoformat(f.exif_date)
                return PhotoDate(year=dt.year, month=dt.month, day=dt.day, source="exif")
            except Exception:
                pass

        d = self._date_from_filename(os.path.basename(f.path))
        if d:
            return d

        try:
            dt = datetime.fromtimestamp(f.mtime)
            return PhotoDate(year=dt.year, month=dt.month, day=dt.day, source="mtime")
        except Exception:
            pass

        return None

    def _date_from_filename(self, filename: str) -> Optional[PhotoDate]:
        name = os.path.splitext(filename)[0]
        for pattern, order in DATE_PATTERNS:
            m = pattern.search(name)
            if not m:
                continue
            g = m.groups()
            try:
                if order == "ymd":
                    year, month, day = int(g[0]), int(g[1]), int(g[2])
                else:
                    day, month, year = int(g[0]), int(g[1]), int(g[2])
                if not (1990 <= year <= 2099 and 1 <= month <= 12 and 1 <= day <= 31):
                    continue
                return PhotoDate(year=year, month=month, day=day, source="filename")
            except (ValueError, IndexError):
                continue
        return None

    # ---- urzadzenie ----

    def _get_device(self, f) -> Optional[str]:
        make  = (f.exif_make  or "").strip()
        model = (f.exif_model or "").strip()
        if make and model:
            return model if model.lower().startswith(make.lower()) else f"{make} {model}"
        return model or make or None

    # ---- klucz grupy ----

    def _make_key(self, device, date) -> tuple:
        y = date.year  if date else None
        m = date.month if date and self.depth in ("month","day") else None
        d = date.day   if date and self.depth == "day" else None
        dev = device   if self.use_device else None
        return (dev, y, m, d)

    # ---- sortowanie ----

    def _sort(self, groups: list) -> list:
        def key(g: PhotoGroup):
            dev = (0, g.device or "") if g.device else (1, "")
            return (dev, -(g.year or 0), g.month or 0, g.day or 0)
        return sorted(groups, key=key)

    # ---- statystyki ----

    @staticmethod
    def summary(groups: list) -> dict:
        total_files = sum(len(g.files) for g in groups)
        total_bytes = sum(g.size_bytes for g in groups)
        devices = sorted({g.device for g in groups if g.device})

        def human(n):
            for u in ("B","KB","MB","GB"):
                if n < 1024: return f"{n:.1f} {u}"
                n /= 1024
            return f"{n:.1f} TB"

        src: dict = {}
        for g in groups:
            for s, c in g.date_sources.items():
                src[s] = src.get(s, 0) + c

        return {
            "total_groups":     len(groups),
            "total_files":      total_files,
            "total_size_human": human(total_bytes),
            "devices":          devices,
            "device_count":     len(devices),
            "date_sources":     src,
        }