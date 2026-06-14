"""
tab_rename.py — zakładka zmiany nazw plików.

Dwie operacje:
  1. Zmień nazwy wg daty  — nadaje format PREFIX_YYYYMMDD_HHMMSS
  2. Dodaj tag            — dopisuje sufiks _TAG do wszystkich nazw

Wymaga wcześniejszego skanowania (scan_results) żeby mieć daty EXIF.
Można też uruchomić bez skanowania — wtedy używa mtime jako daty.
"""

import os
import threading

import customtkinter as ctk

from core.renamer import Renamer, RenameResult, FILENAME_PATTERNS, ALL_PREFIXES


class TabRename(ctk.CTkFrame):

    def __init__(self, parent, get_folder_fn, get_scan_results_fn, log_fn, **kwargs):
        """
        get_folder_fn()       → str   — aktualnie wybrany folder
        get_scan_results_fn() → list  — wyniki ostatniego skanowania (może być [])
        log_fn(msg)                   — wpisuje do głównego logu aplikacji
        """
        super().__init__(parent, fg_color="transparent", **kwargs)

        self._get_folder       = get_folder_fn
        self._get_scan_results = get_scan_results_fn
        self._log              = log_fn
        self._renamer          = Renamer()
        self._last_results:    list[RenameResult] = []

        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        self._build_ui()

    # ================================================================ UI

    def _build_ui(self):
        # Główny scrollowalny kontener — na wypadek małego okna
        scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        scroll.grid(row=0, column=0, sticky="nsew")
        scroll.grid_columnconfigure(0, weight=1)

        row = 0

        # ── Sekcja 1: Zmiana nazw wg daty ──────────────────────────────
        row = self._section(scroll, row, "Zmiana nazw plików wg daty")

        info1 = ctk.CTkFrame(scroll)
        info1.grid(row=row, column=0, sticky="ew", padx=16, pady=(0, 10))
        info1.grid_columnconfigure(0, weight=1)
        row += 1

        ctk.CTkLabel(
            info1,
            text=(
                "Nadaje jednolite nazwy w formacie PREFIX_YYYYMMDD_HHMMSS.\n"
                "Źródło daty: EXIF (jeśli skanowanie zostało uruchomione) → data modyfikacji pliku.\n"
                "Zdjęcia z aparatu → IMG_   •   Filmy → VID_   •   Screenshoty → SCR_\n"
                "Social media: FB_, MSG_, IG_, SNAP_, TWX_, TT_, TG_"
            ),
            font=ctk.CTkFont(size=11),
            text_color="gray",
            justify="left",
        ).grid(row=0, column=0, padx=12, pady=(10, 4), sticky="w")

        # Podgląd wzorców
        self.btn_show_patterns = ctk.CTkButton(
            info1, text="Pokaż wzorce wykrywania źródeł ▼",
            height=26, fg_color="transparent", border_width=1,
            text_color=("gray10", "gray90"), font=ctk.CTkFont(size=11),
            command=self._toggle_patterns,
        )
        self.btn_show_patterns.grid(row=1, column=0, padx=12, pady=(0, 8), sticky="w")

        self.patterns_frame = ctk.CTkFrame(info1, fg_color=("gray90", "gray15"))
        # ukryty domyślnie — pojawia się po kliknięciu

        self._patterns_visible = False
        self._build_patterns_table(self.patterns_frame)

        # Opcja: tryb suchy
        self._dry_run_var = ctk.BooleanVar(value=True)
        dry_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        dry_frame.grid(row=row, column=0, sticky="ew", padx=16, pady=(0, 8))
        row += 1

        ctk.CTkCheckBox(
            dry_frame,
            text="Tryb podglądu (dry run) — pokaż zmiany bez ich wykonania",
            variable=self._dry_run_var,
            font=ctk.CTkFont(size=12),
        ).pack(side="left")

        # Przycisk
        self.btn_rename = ctk.CTkButton(
            scroll,
            text="Zmień nazwy wg daty",
            height=38, font=ctk.CTkFont(size=13, weight="bold"),
            command=self._on_rename,
        )
        self.btn_rename.grid(row=row, column=0, sticky="ew", padx=16, pady=(0, 4))
        row += 1

        # ── Sekcja 2: Dodaj tag ────────────────────────────────────────
        row = self._section(scroll, row, "Dodaj tag do nazw plików")

        tag_frame = ctk.CTkFrame(scroll)
        tag_frame.grid(row=row, column=0, sticky="ew", padx=16, pady=(0, 10))
        tag_frame.grid_columnconfigure(1, weight=1)
        row += 1

        ctk.CTkLabel(
            tag_frame,
            text=(
                "Dopisuje sufiks _TAG do nazw wszystkich plików w folderze.\n"
                "Pliki które już mają ten sufiks są pomijane."
            ),
            font=ctk.CTkFont(size=11), text_color="gray", justify="left",
        ).grid(row=0, column=0, columnspan=3, padx=12, pady=(10, 8), sticky="w")

        ctk.CTkLabel(
            tag_frame, text="Tag:",
            font=ctk.CTkFont(size=12, weight="bold")
        ).grid(row=1, column=0, padx=(12, 6), pady=(0, 12), sticky="w")

        self.tag_entry = ctk.CTkEntry(
            tag_frame,
            placeholder_text="np. Wakacje2024",
            width=220, height=34,
        )
        self.tag_entry.grid(row=1, column=1, padx=(0, 8), pady=(0, 12), sticky="w")

        self.btn_tag = ctk.CTkButton(
            tag_frame,
            text="Dodaj tag",
            width=120, height=34,
            command=self._on_add_tag,
        )
        self.btn_tag.grid(row=1, column=2, padx=(0, 12), pady=(0, 12), sticky="w")

        # ── Sekcja 3: Log operacji ─────────────────────────────────────
        row = self._section(scroll, row, "Log operacji")

        log_outer = ctk.CTkFrame(scroll)
        log_outer.grid(row=row, column=0, sticky="ew", padx=16, pady=(0, 16))
        log_outer.grid_columnconfigure(0, weight=1)
        row += 1

        # Pasek nad logiem z licznikami i przyciskiem czyszczenia
        log_bar = ctk.CTkFrame(log_outer, fg_color="transparent")
        log_bar.grid(row=0, column=0, sticky="ew", padx=8, pady=(8, 4))
        log_bar.grid_columnconfigure(0, weight=1)

        self.lbl_summary = ctk.CTkLabel(
            log_bar, text="",
            font=ctk.CTkFont(size=11), text_color="gray"
        )
        self.lbl_summary.grid(row=0, column=0, sticky="w")

        ctk.CTkButton(
            log_bar, text="Wyczyść log",
            height=26, width=100,
            fg_color="transparent", border_width=1,
            text_color=("gray10", "gray90"),
            font=ctk.CTkFont(size=11),
            command=self._clear_log,
        ).grid(row=0, column=1)

        self.log_box = ctk.CTkTextbox(
            log_outer,
            state="disabled",
            font=ctk.CTkFont(family="Courier", size=11),
            height=280,
        )
        self.log_box.grid(row=1, column=0, sticky="ew", padx=8, pady=(0, 8))

    # ================================================================ helpers UI

    def _section(self, parent, row: int, title: str) -> int:
        ctk.CTkLabel(
            parent, text=title,
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=("gray30", "gray70"),
        ).grid(row=row, column=0, sticky="w", padx=16, pady=(16, 4))
        return row + 1

    def _build_patterns_table(self, parent):
        """Tabela wzorców wykrywania źródeł — widoczna po kliknięciu."""
        ctk.CTkLabel(
            parent,
            text="Prefix   Wzorce w nazwie pliku",
            font=ctk.CTkFont(family="Courier", size=11, weight="bold"),
            text_color="gray",
        ).pack(anchor="w", padx=12, pady=(8, 2))

        for patterns, prefix in FILENAME_PATTERNS:
            ctk.CTkLabel(
                parent,
                text=f"  {prefix:<6}  {', '.join(patterns)}",
                font=ctk.CTkFont(family="Courier", size=11),
            ).pack(anchor="w", padx=12)

        ctk.CTkLabel(
            parent, text="",
            font=ctk.CTkFont(size=4),
        ).pack()

    def _toggle_patterns(self):
        self._patterns_visible = not self._patterns_visible
        if self._patterns_visible:
            self.patterns_frame.grid(row=2, column=0, sticky="ew", padx=12, pady=(0, 10))
            self.btn_show_patterns.configure(text="Ukryj wzorce ▲")
        else:
            self.patterns_frame.grid_forget()
            self.btn_show_patterns.configure(text="Pokaż wzorce wykrywania źródeł ▼")

    # ================================================================ akcje

    def _on_rename(self):
        folder = self._get_folder()
        if not folder or not os.path.isdir(folder):
            self._log_line("⚠  Najpierw wybierz folder w panelu bocznym.")
            return

        scan_results = self._get_scan_results()
        dry_run      = self._dry_run_var.get()

        mode_label = "PODGLĄD" if dry_run else "WYKONANIE"
        self._log_line(f"\n─── Zmiana nazw wg daty [{mode_label}] ───")
        self._log_line(f"Folder: {folder}")
        self._log_line(f"Pliki ze skanowania w pamięci: {len(scan_results)}")

        self.btn_rename.configure(state="disabled", text="Trwa…")

        def _run():
            results = self._renamer.rename_files(
                scan_results=scan_results,
                folder=folder,
                dry_run=dry_run,
                on_progress=lambda cur, tot, fname: self.after(
                    0, lambda c=cur, t=tot, f=fname:
                    self.btn_rename.configure(text=f"Trwa… {c}/{t}")
                ),
            )
            self.after(0, lambda: self._finish_rename(results, dry_run))

        threading.Thread(target=_run, daemon=True).start()

    def _finish_rename(self, results: list[RenameResult], dry_run: bool):
        self._last_results = results
        summary = Renamer.summary(results)

        prefix = "[PODGLĄD] " if dry_run else ""

        for r in results:
            if r.skipped:
                continue
            if r.error:
                self._log_line(f"  ✗ BŁĄD: {r.original_name} — {r.error}")
            elif r.changed:
                self._log_line(f"  {prefix}✓  {r.original_name}  →  {r.new_name}")
            else:
                self._log_line(f"  —  bez zmian: {r.original_name}")

        self._log_line(
            f"\nPodsumowanie: zmieniono {summary['renamed']}, "
            f"bez zmian {summary['no_change']}, "
            f"błędy {summary['errors']}, "
            f"pominięto {summary['skipped']}"
        )
        self.lbl_summary.configure(
            text=f"Zmieniono: {summary['renamed']}  •  Bez zmian: {summary['no_change']}  "
                 f"•  Błędy: {summary['errors']}"
        )

        label = "Zmień nazwy wg daty"
        if dry_run and summary["renamed"] > 0:
            label = f"Zmień nazwy wg daty  (gotowe do wykonania: {summary['renamed']})"
        self.btn_rename.configure(state="normal", text=label)
        self._log(f"Rename: zmieniono {summary['renamed']} plików.")

    def _on_add_tag(self):
        folder = self._get_folder()
        if not folder or not os.path.isdir(folder):
            self._log_line("⚠  Najpierw wybierz folder w panelu bocznym.")
            return

        tag = self.tag_entry.get().strip()
        if not tag:
            self._log_line("⚠  Wpisz tag przed kliknięciem przycisku.")
            return

        self._log_line(f"\n─── Dodawanie tagu: _{tag} ───")
        self._log_line(f"Folder: {folder}")

        self.btn_tag.configure(state="disabled", text="Trwa…")

        def _run():
            results = self._renamer.add_tag(
                folder=folder,
                tag=tag,
                dry_run=False,
                on_progress=lambda cur, tot, fname: self.after(
                    0, lambda c=cur, t=tot, f=fname:
                    self.btn_tag.configure(text=f"Trwa… {c}/{t}")
                ),
            )
            self.after(0, lambda: self._finish_tag(results, tag))

        threading.Thread(target=_run, daemon=True).start()

    def _finish_tag(self, results: list[RenameResult], tag: str):
        summary = Renamer.summary(results)

        for r in results:
            if r.error:
                self._log_line(f"  ✗ BŁĄD: {r.original_name} — {r.error}")
            elif r.changed:
                self._log_line(f"  ✓  {r.original_name}  →  {r.new_name}")
            else:
                self._log_line(f"  —  bez zmian: {r.original_name}")

        self._log_line(
            f"\nPodsumowanie: otagowano {summary['renamed']}, "
            f"bez zmian {summary['no_change']}, błędy {summary['errors']}"
        )
        self.lbl_summary.configure(
            text=f"Otagowano: {summary['renamed']}  •  Bez zmian: {summary['no_change']}  "
                 f"•  Błędy: {summary['errors']}"
        )
        self.btn_tag.configure(state="normal", text="Dodaj tag")
        self._log(f"Tag _{tag}: otagowano {summary['renamed']} plików.")

    # ================================================================ log

    def _log_line(self, msg: str):
        """Wpisuje linię do lokalnego logu operacji."""
        self.log_box.configure(state="normal")
        self.log_box.insert("end", msg + "\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def _clear_log(self):
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.configure(state="disabled")
        self.lbl_summary.configure(text="")