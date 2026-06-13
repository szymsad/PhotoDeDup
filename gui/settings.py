"""
settings.py — okno ustawień aplikacji (CTkToplevel).

Ustawienia:
  - próg pHash (suwak 0–20)
  - liczba wątków skanowania
  - strategia wyboru "najlepszego" pliku w grupie duplikatów
  - eksport raportu TSV
  - reset cache SQLite
"""

import os
import csv
from tkinter import filedialog, messagebox
from typing import Callable, Optional

import customtkinter as ctk

from core.deduplicator import DuplicateGroup
from core.grouper import PhotoGroup


class SettingsWindow(ctk.CTkToplevel):
    """
    Okno ustawień — otwiera się nad głównym oknem.
    on_apply(settings_dict) wywoływane gdy użytkownik kliknie Zastosuj.
    """

    def __init__(
        self,
        parent,
        current_settings: dict,
        on_apply: Callable[[dict], None],
        on_reset_cache: Callable[[], None],
        **kwargs
    ):
        super().__init__(parent, **kwargs)

        self.title("Ustawienia")
        self.geometry("480x540")
        self.resizable(False, False)
        self.grab_set()   # modal — blokuje główne okno

        self._on_apply = on_apply
        self._on_reset_cache = on_reset_cache

        # lokalne kopie wartości
        self._phash_threshold = ctk.IntVar(value=current_settings.get("phash_threshold", 8))
        self._workers = ctk.IntVar(value=current_settings.get("workers", 8))
        self._best_strategy = ctk.StringVar(value=current_settings.get("best_strategy", "resolution"))

        self._build_ui()
        self.after(50, lambda: (
            self.attributes("-topmost", True),
            self.after(200, lambda: self.attributes("-topmost", False)),
            self.lift(),
            self.focus_force()
        ))

    # ================================================================ UI

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        scroll = ctk.CTkScrollableFrame(self)
        scroll.grid(row=0, column=0, sticky="nsew", padx=0, pady=0)
        scroll.grid_columnconfigure(0, weight=1)

        row = 0

        # ---- sekcja: wykrywanie duplikatów ----
        row = self._section(scroll, row, "Wykrywanie duplikatów")

        row = self._slider_row(
            scroll, row,
            label="Próg podobieństwa pHash",
            description=(
                "Maksymalna różnica bitowa między dwoma zdjęciami aby uznać je za podobne.\n"
                "0 = tylko identyczne piksele  •  8 = domyślny (zalecany)  •  20+ = ryzyko fałszywych dopasowań"
            ),
            variable=self._phash_threshold,
            from_=0, to=20, steps=20,
            format_fn=lambda v: f"{int(v)} bitów",
        )

        row = self._radio_row(
            scroll, row,
            label="Który plik zachować w grupie",
            description="Kryterium wyboru 'zwycięzcy' — pozostałe trafią do usunięcia.",
            variable=self._best_strategy,
            options=[
                ("Najwyższa rozdzielczość", "resolution"),
                ("Najstarsza data EXIF (oryginał)", "oldest_exif"),
                ("Największy rozmiar pliku", "filesize"),
            ],
        )

        # ---- sekcja: skanowanie ----
        row = self._section(scroll, row, "Skanowanie")

        row = self._slider_row(
            scroll, row,
            label="Liczba wątków",
            description=(
                "Ile plików jest przetwarzanych równolegle.\n"
                "Więcej wątków = szybsze skanowanie, ale większe zużycie CPU.\n"
                "Zalecane: 4–12 (zależnie od liczby rdzeni procesora)"
            ),
            variable=self._workers,
            from_=1, to=16, steps=15,
            format_fn=lambda v: f"{int(v)} wątków",
        )

        # ---- sekcja: dane ----
        row = self._section(scroll, row, "Cache i dane")

        # reset cache
        cache_frame = ctk.CTkFrame(scroll)
        cache_frame.grid(row=row, column=0, sticky="ew", padx=16, pady=(0, 12))
        cache_frame.grid_columnconfigure(0, weight=1)
        row += 1

        ctk.CTkLabel(
            cache_frame,
            text="Resetuj cache hashów",
            font=ctk.CTkFont(size=13, weight="bold")
        ).grid(row=0, column=0, padx=12, pady=(10, 2), sticky="w")

        ctk.CTkLabel(
            cache_frame,
            text="Usuwa plik photo_dedup.db — przy następnym skanowaniu\nwszystkie pliki będą przetworzone od nowa.",
            font=ctk.CTkFont(size=11),
            text_color="gray",
            justify="left"
        ).grid(row=1, column=0, padx=12, pady=(0, 8), sticky="w")

        ctk.CTkButton(
            cache_frame,
            text="Resetuj cache",
            width=140, height=32,
            fg_color="#c0392b",
            hover_color="#a93226",
            command=self._on_reset_cache_click
        ).grid(row=2, column=0, padx=12, pady=(0, 12), sticky="w")

        # ---- przyciski na dole ----
        btn_bar = ctk.CTkFrame(self, fg_color="transparent")
        btn_bar.grid(row=1, column=0, sticky="ew", padx=16, pady=12)

        ctk.CTkButton(
            btn_bar,
            text="Anuluj",
            width=100,
            fg_color="transparent",
            border_width=1,
            text_color=("gray10", "gray90"),
            command=self.destroy
        ).pack(side="right", padx=(8, 0))

        ctk.CTkButton(
            btn_bar,
            text="Zastosuj",
            width=100,
            command=self._apply
        ).pack(side="right")

    # ================================================================ sekcje UI

    def _section(self, parent, row: int, title: str) -> int:
        ctk.CTkLabel(
            parent,
            text=title,
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=("gray30", "gray70")
        ).grid(row=row, column=0, sticky="w", padx=16, pady=(16, 4))
        return row + 1

    def _slider_row(
        self, parent, row: int,
        label: str, description: str,
        variable: ctk.IntVar,
        from_: int, to: int, steps: int,
        format_fn: Callable,
    ) -> int:
        frame = ctk.CTkFrame(parent)
        frame.grid(row=row, column=0, sticky="ew", padx=16, pady=(0, 10))
        frame.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(frame, text=label, font=ctk.CTkFont(size=13, weight="bold")).grid(
            row=0, column=0, padx=12, pady=(10, 2), sticky="w"
        )
        ctk.CTkLabel(
            frame, text=description,
            font=ctk.CTkFont(size=11), text_color="gray",
            justify="left", wraplength=380
        ).grid(row=1, column=0, padx=12, pady=(0, 6), sticky="w")

        slider_row = ctk.CTkFrame(frame, fg_color="transparent")
        slider_row.grid(row=2, column=0, padx=12, pady=(0, 12), sticky="ew")
        slider_row.grid_columnconfigure(0, weight=1)

        val_label = ctk.CTkLabel(
            slider_row,
            text=format_fn(variable.get()),
            font=ctk.CTkFont(size=12, weight="bold"),
            width=80
        )
        val_label.grid(row=0, column=1, padx=(8, 0))

        def on_change(v):
            variable.set(int(float(v)))
            val_label.configure(text=format_fn(int(float(v))))

        ctk.CTkSlider(
            slider_row,
            variable=variable,
            from_=from_, to=to,
            number_of_steps=steps,
            command=on_change
        ).grid(row=0, column=0, sticky="ew")

        return row + 1

    def _radio_row(
        self, parent, row: int,
        label: str, description: str,
        variable: ctk.StringVar,
        options: list[tuple[str, str]],
    ) -> int:
        frame = ctk.CTkFrame(parent)
        frame.grid(row=row, column=0, sticky="ew", padx=16, pady=(0, 10))
        frame.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(frame, text=label, font=ctk.CTkFont(size=13, weight="bold")).grid(
            row=0, column=0, padx=12, pady=(10, 2), sticky="w"
        )
        ctk.CTkLabel(
            frame, text=description,
            font=ctk.CTkFont(size=11), text_color="gray",
            justify="left"
        ).grid(row=1, column=0, padx=12, pady=(0, 6), sticky="w")

        for i, (label_text, value) in enumerate(options):
            ctk.CTkRadioButton(
                frame, text=label_text,
                variable=variable, value=value
            ).grid(row=2 + i, column=0, padx=20, pady=2, sticky="w")

        ctk.CTkFrame(frame, height=8, fg_color="transparent").grid(row=2 + len(options), column=0)

        return row + 1

    # ================================================================ akcje

    def _apply(self):
        self._on_apply({
            "phash_threshold": self._phash_threshold.get(),
            "workers": self._workers.get(),
            "best_strategy": self._best_strategy.get(),
        })
        self.destroy()

    def _on_reset_cache_click(self):
        if messagebox.askyesno(
            "Resetuj cache",
            "Czy na pewno chcesz usunąć cache hashów?\n\n"
            "Przy następnym skanowaniu wszystkie pliki będą\n"
            "przetwarzane od nowa (może to potrwać dłużej).",
            icon="warning"
        ):
            self._on_reset_cache()
            self.destroy()


# ================================================================ eksport raportu

def export_report(
    dup_groups: list[DuplicateGroup],
    photo_groups: list[PhotoGroup],
    parent_window=None,
) -> Optional[str]:
    """
    Eksportuje raport do pliku TSV.
    Zwraca ścieżkę zapisanego pliku lub None jeśli anulowano.
    """
    path = filedialog.asksaveasfilename(
        parent=parent_window,
        title="Zapisz raport",
        defaultextension=".tsv",
        filetypes=[("Plik TSV (Excel)", "*.tsv"), ("Wszystkie pliki", "*.*")],
        initialfile="photo_dedup_raport.tsv",
    )
    if not path:
        return None

    with open(path, "w", newline="", encoding="utf-8-sig") as f:  # utf-8-sig = BOM dla Excela
        writer = csv.writer(f, delimiter="\t")

        # --- sekcja 1: duplikaty ---
        writer.writerow(["=== DUPLIKATY ==="])
        writer.writerow(["Typ", "Grupa", "Ścieżka", "Rozmiar (B)", "Rozdzielczość", "Data EXIF", "Akcja"])

        for i, group in enumerate(dup_groups, 1):
            for file in group.files:
                res = f"{file.width}x{file.height}" if file.width else ""
                action = "zachowaj" if file is group.best else "usuń"
                writer.writerow([
                    group.group_type,
                    i,
                    file.path,
                    file.size,
                    res,
                    file.exif_date or "",
                    action,
                ])

        writer.writerow([])

        # --- sekcja 2: grupy ---
        writer.writerow(["=== GRUPY ZDJĘĆ ==="])
        writer.writerow(["Urządzenie", "Rok", "Miesiąc", "Sugerowany folder", "Liczba plików", "Rozmiar (B)", "Ścieżka pliku"])

        for group in photo_groups:
            for file in group.files:
                writer.writerow([
                    group.device or "",
                    group.year or "",
                    group.month or "",
                    group.suggested_folder,
                    len(group.files),
                    file.size,
                    file.path,
                ])

    return path