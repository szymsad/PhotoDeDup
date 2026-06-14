"""
database.py — SQLite cache dla wyników skanowania.

Cel: przy kolejnych uruchomieniach pliki już zhaszowane są pomijane.
Jeśli plik nie zmienił rozmiaru ani daty modyfikacji — używamy cached hash.

Thread-safety: wszystkie operacje zapisu chronione przez threading.Lock().
SQLite w WAL mode jest bezpieczny dla wielu równoczesnych czytelników,
ale jeden zapis na raz — lock zapewnia że ThreadPoolExecutor nie koliduje.
"""

import sqlite3
import threading
from dataclasses import dataclass
from typing import Optional


SCHEMA = """
CREATE TABLE IF NOT EXISTS files (
    path        TEXT PRIMARY KEY,
    size        INTEGER NOT NULL,
    mtime       REAL NOT NULL,
    md5         TEXT,
    phash       TEXT,
    width       INTEGER,
    height      INTEGER,
    exif_date   TEXT,
    exif_make   TEXT,
    exif_model  TEXT,
    scanned_at  TEXT
);
CREATE INDEX IF NOT EXISTS idx_md5   ON files(md5);
CREATE INDEX IF NOT EXISTS idx_phash ON files(phash);
"""


@dataclass
class CachedFile:
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


class Database:
    def __init__(self, db_path: str = "photo_dedup.db"):
        self.db_path = db_path
        self._conn:  Optional[sqlite3.Connection] = None
        # ← POPRAWKA: lock chroni wszystkie operacje zapisu przed race condition
        self._lock = threading.Lock()

    def connect(self):
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        # Timeout zamiast natychmiastowego błędu gdy baza jest zajęta
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None

    # ---------------------------------------------------------------- odczyt
    # Odczyty nie wymagają locka — WAL mode pozwala na równoczesne czytanie

    def get_cached(self, path: str, size: int, mtime: float) -> Optional[CachedFile]:
        """
        Zwraca cached wynik jeśli plik nie zmienił się od ostatniego skanowania.
        Sprawdzamy rozmiar i datę modyfikacji — jeśli oba się zgadzają, hash jest aktualny.
        """
        row = self._conn.execute(
            "SELECT path, size, mtime, md5, phash, width, height, "
            "       exif_date, exif_make, exif_model "
            "FROM files WHERE path=? AND size=? AND mtime=?",
            (path, size, mtime)
        ).fetchone()
        return CachedFile(*row) if row else None

    def get_all_cached(self) -> dict[str, "CachedFile"]:
        """Zwraca wszystkie cached pliki jako słownik path → CachedFile."""
        rows = self._conn.execute(
            "SELECT path, size, mtime, md5, phash, width, height, "
            "       exif_date, exif_make, exif_model "
            "FROM files WHERE md5 IS NOT NULL"
        ).fetchall()
        return {row[0]: CachedFile(*row) for row in rows}

    # ---------------------------------------------------------------- zapis

    def upsert(self, file: CachedFile):
        """Zapisuje lub aktualizuje wynik skanowania pliku. Thread-safe."""
        from datetime import datetime
        with self._lock:
            self._conn.execute("""
                INSERT INTO files
                    (path, size, mtime, md5, phash, width, height,
                     exif_date, exif_make, exif_model, scanned_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(path) DO UPDATE SET
                    size=excluded.size,           mtime=excluded.mtime,
                    md5=excluded.md5,             phash=excluded.phash,
                    width=excluded.width,         height=excluded.height,
                    exif_date=excluded.exif_date,
                    exif_make=excluded.exif_make,
                    exif_model=excluded.exif_model,
                    scanned_at=excluded.scanned_at
            """, (
                file.path, file.size, file.mtime,
                file.md5,  file.phash,
                file.width, file.height,
                file.exif_date, file.exif_make, file.exif_model,
                datetime.now().isoformat()
            ))

    def flush(self):
        """Zapisuje batch do dysku. Thread-safe."""
        with self._lock:
            self._conn.commit()

    # ---------------------------------------------------------------- czyszczenie

    def remove_missing(self, existing_paths: set[str]) -> int:
        """Usuwa z cache pliki które już nie istnieją na dysku."""
        cached_paths = {
            row[0] for row in self._conn.execute("SELECT path FROM files").fetchall()
        }
        to_remove = cached_paths - existing_paths
        if to_remove:
            with self._lock:
                self._conn.executemany(
                    "DELETE FROM files WHERE path=?", [(p,) for p in to_remove]
                )
                self._conn.commit()
        return len(to_remove)

    def clear(self):
        """Czyści cały cache. Thread-safe."""
        with self._lock:
            self._conn.execute("DELETE FROM files")
            self._conn.commit()

    def stats(self) -> dict:
        """Zwraca statystyki cache."""
        total     = self._conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
        with_hash = self._conn.execute(
            "SELECT COUNT(*) FROM files WHERE md5 IS NOT NULL"
        ).fetchone()[0]
        return {"total": total, "with_hash": with_hash}