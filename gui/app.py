import threading
import os
import customtkinter as ctk
from tkinter import filedialog, messagebox

from core.database import Database
from core.scanner import Scanner, FileResult
from core.deduplicator import Deduplicator, DuplicateGroup
from core.grouper import Grouper, PhotoGroup
from gui.tab_duplicates import TabDuplicates
from gui.tab_groups import TabGroups
from gui.tab_rename import TabRename
from gui.settings import SettingsWindow, export_report
from gui.scan_window import ScanWindow


class App(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("Photo Dedup")
        self.geometry("1100x700")
        self.minsize(900, 600)

        self.db = Database("photo_dedup.db")
        self.db.connect()

        self.current_settings = {
            "phash_threshold": 8,
            "workers": 8,
            "best_strategy": "resolution",
        }
        self.scanner      = Scanner(self.db, workers=self.current_settings["workers"])
        self.deduplicator = Deduplicator(phash_threshold=self.current_settings["phash_threshold"])
        self.grouper      = Grouper(use_device=True, depth="month")

        self.scan_results:  list = []
        self.dup_groups:    list = []
        self.photo_groups:  list = []

        self.selected_folder = ctk.StringVar(value="")
        self.status_text     = ctk.StringVar(value="Wybierz folder aby rozpocząć")
        self.progress_value  = ctk.DoubleVar(value=0.0)
        self.stats = {
            "total":      ctk.StringVar(value="—"),
            "duplicates": ctk.StringVar(value="—"),
            "groups":     ctk.StringVar(value="—"),
            "savings":    ctk.StringVar(value="—"),
        }

        self._build_layout()

    # ================================================================ layout

    def _build_layout(self):
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self._build_sidebar()
        self._build_main_area()

    def _build_sidebar(self):
        sidebar = ctk.CTkFrame(self, width=260, corner_radius=0)
        sidebar.grid(row=0, column=0, sticky="nsew")
        sidebar.grid_rowconfigure(6, weight=1)
        sidebar.grid_propagate(False)

        ctk.CTkLabel(sidebar, text="Photo Dedup",
                     font=ctk.CTkFont(size=22, weight="bold")
        ).grid(row=0, column=0, padx=20, pady=(24, 4), sticky="w")

        ctk.CTkLabel(sidebar, text="deduplikacja i organizacja zdjęć",
                     font=ctk.CTkFont(size=11), text_color="gray"
        ).grid(row=1, column=0, padx=20, pady=(0, 20), sticky="w")

        ctk.CTkLabel(sidebar, text="Folder ze zdjęciami",
                     font=ctk.CTkFont(size=12, weight="bold")
        ).grid(row=2, column=0, padx=20, pady=(0, 6), sticky="w")

        folder_frame = ctk.CTkFrame(sidebar, fg_color="transparent")
        folder_frame.grid(row=3, column=0, padx=20, pady=(0, 6), sticky="ew")
        folder_frame.grid_columnconfigure(0, weight=1)

        ctk.CTkEntry(folder_frame, textvariable=self.selected_folder,
                     placeholder_text="ścieżka do folderu…", state="readonly"
        ).grid(row=0, column=0, sticky="ew", padx=(0, 6))

        ctk.CTkButton(folder_frame, text="…", width=32,
                      command=self._pick_folder
        ).grid(row=0, column=1)

        ctk.CTkLabel(sidebar, text="Statystyki",
                     font=ctk.CTkFont(size=12, weight="bold")
        ).grid(row=4, column=0, padx=20, pady=(16, 6), sticky="w")

        stats_frame = ctk.CTkFrame(sidebar)
        stats_frame.grid(row=5, column=0, padx=20, sticky="ew")
        stats_frame.grid_columnconfigure(1, weight=1)

        for i, (label, key) in enumerate([
            ("Wszystkich plików:", "total"),
            ("Duplikatów:",        "duplicates"),
            ("Grup zdjęć:",        "groups"),
            ("Do odzyskania:",     "savings"),
        ]):
            ctk.CTkLabel(stats_frame, text=label,
                         font=ctk.CTkFont(size=12), text_color="gray"
            ).grid(row=i, column=0, padx=12, pady=3, sticky="w")
            ctk.CTkLabel(stats_frame, textvariable=self.stats[key],
                         font=ctk.CTkFont(size=12, weight="bold")
            ).grid(row=i, column=1, padx=12, pady=3, sticky="e")

        actions = ctk.CTkFrame(sidebar, fg_color="transparent")
        actions.grid(row=7, column=0, padx=20, pady=20, sticky="sew")
        actions.grid_columnconfigure(0, weight=1)

        self.btn_scan = ctk.CTkButton(
            actions, text="Skanuj folder", height=40,
            font=ctk.CTkFont(size=13, weight="bold"),
            command=self._on_scan, state="disabled"
        )
        self.btn_scan.grid(row=0, column=0, pady=(0, 8), sticky="ew")

        self.btn_delete = ctk.CTkButton(
            actions, text="Usuń duplikaty", height=36,
            fg_color="transparent", border_width=1,
            text_color=("gray10", "gray90"),
            command=self._on_delete, state="disabled"
        )
        self.btn_delete.grid(row=1, column=0, pady=(0, 8), sticky="ew")

        self.btn_organize = ctk.CTkButton(
            actions, text="Organizuj w foldery", height=36,
            fg_color="transparent", border_width=1,
            text_color=("gray10", "gray90"),
            command=self._on_organize, state="disabled"
        )
        self.btn_organize.grid(row=2, column=0, pady=(0, 8), sticky="ew")

        # ← NOWY przycisk skrótu do zakładki zmiany nazw
        ctk.CTkButton(
            actions, text="Zmień nazwy plików", height=36,
            fg_color="transparent", border_width=1,
            text_color=("gray10", "gray90"),
            command=lambda: self.tabview.set("Zmiana nazw"),
        ).grid(row=3, column=0, pady=(0, 8), sticky="ew")

        ctk.CTkButton(
            actions, text="Eksportuj raport", height=32,
            fg_color="transparent", border_width=1,
            text_color=("gray10", "gray90"),
            command=self._on_export,
        ).grid(row=4, column=0, pady=(0, 8), sticky="ew")

        ctk.CTkButton(
            actions, text="Ustawienia", height=32,
            fg_color="transparent", border_width=1,
            text_color=("gray10", "gray90"),
            command=self._on_settings,
        ).grid(row=5, column=0, sticky="ew")

    def _build_main_area(self):
        main = ctk.CTkFrame(self, fg_color="transparent")
        main.grid(row=0, column=1, sticky="nsew")
        main.grid_rowconfigure(1, weight=1)
        main.grid_columnconfigure(0, weight=1)

        self._build_statusbar(main)

        self.tabview = ctk.CTkTabview(main)
        self.tabview.grid(row=1, column=0, sticky="nsew", padx=16, pady=(0, 16))

        self.tab_duplicates = self.tabview.add("Duplikaty")
        self.tab_groups     = self.tabview.add("Grupy zdjęć")
        self.tab_rename_tab = self.tabview.add("Zmiana nazw")   # ← NOWA zakładka
        self.tab_log        = self.tabview.add("Log")

        self._build_tab_duplicates()
        self._build_tab_groups()
        self._build_tab_rename()
        self._build_tab_log()

    def _build_statusbar(self, parent):
        bar = ctk.CTkFrame(parent, height=48, corner_radius=0,
                           fg_color=("gray90", "gray17"))
        bar.grid(row=0, column=0, sticky="ew")
        bar.grid_columnconfigure(0, weight=1)
        bar.grid_propagate(False)

        ctk.CTkLabel(bar, textvariable=self.status_text,
                     font=ctk.CTkFont(size=12)
        ).grid(row=0, column=0, padx=16, sticky="w")

        self.progress = ctk.CTkProgressBar(bar, variable=self.progress_value, width=200)
        self.progress.grid(row=0, column=1, padx=16)

    def _build_tab_duplicates(self):
        tab = self.tab_duplicates
        tab.grid_rowconfigure(0, weight=1)
        tab.grid_columnconfigure(0, weight=1)
        self.duplicates_widget = TabDuplicates(tab, on_deleted_callback=self._on_files_deleted)
        self.duplicates_widget.grid(row=0, column=0, sticky="nsew")

    def _build_tab_groups(self):
        tab = self.tab_groups
        tab.grid_rowconfigure(0, weight=1)
        tab.grid_columnconfigure(0, weight=1)
        self.groups_widget = TabGroups(tab, on_regroup=self._regroup)
        self.groups_widget.grid(row=0, column=0, sticky="nsew")

    def _build_tab_rename(self):
        tab = self.tab_rename_tab
        tab.grid_rowconfigure(0, weight=1)
        tab.grid_columnconfigure(0, weight=1)
        self.rename_widget = TabRename(
            tab,
            get_folder_fn=lambda: self.selected_folder.get(),
            get_scan_results_fn=lambda: self.scan_results,
            log_fn=self.log,
        )
        self.rename_widget.grid(row=0, column=0, sticky="nsew")

    def _build_tab_log(self):
        tab = self.tab_log
        tab.grid_rowconfigure(0, weight=1)
        tab.grid_columnconfigure(0, weight=1)
        self.log_box = ctk.CTkTextbox(
            tab, state="disabled",
            font=ctk.CTkFont(family="Courier", size=12)
        )
        self.log_box.grid(row=0, column=0, sticky="nsew")

    # ================================================================ publiczne

    def log(self, message: str):
        self.log_box.configure(state="normal")
        self.log_box.insert("end", message + "\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def set_status(self, text: str, progress: float = None):
        self.status_text.set(text)
        if progress is not None:
            self.progress_value.set(progress)

    def set_stats(self, total=None, duplicates=None, groups=None, savings=None):
        if total      is not None: self.stats["total"].set(str(total))
        if duplicates is not None: self.stats["duplicates"].set(str(duplicates))
        if groups     is not None: self.stats["groups"].set(str(groups))
        if savings    is not None: self.stats["savings"].set(savings)

    def enable_actions(self, scan=True, delete=False, organize=False):
        self.btn_scan.configure(state="normal" if scan else "disabled")
        self.btn_delete.configure(state="normal" if delete else "disabled")
        self.btn_organize.configure(state="normal" if organize else "disabled")

    # ================================================================ skanowanie

    def _pick_folder(self):
        folder = filedialog.askdirectory(title="Wybierz folder ze zdjęciami")
        if folder:
            self.selected_folder.set(folder)
            self.enable_actions(scan=True)
            self.set_status(f"Folder: {folder}")
            self.log(f"Wybrano folder: {folder}")

    def _on_scan(self):
        folder = self.selected_folder.get()
        if not folder:
            return

        self.btn_scan.configure(state="disabled", text="Skanowanie...")
        self.log(f"\n--- Skanowanie: {folder} ---")

        from gui.tab_groups import _mode_to_params
        use_device, depth = _mode_to_params(self.groups_widget._folder_mode.get())

        scan_win = ScanWindow(self, on_cancel=self.scanner.stop)
        scan_win.lift()

        def on_progress(current: int, total: int, path: str):
            self.after(0, lambda: scan_win.update_progress(
                current, total, os.path.basename(path)
            ))
            self.after(0, lambda: self.set_status(
                f"Skanowanie {current}/{total}", progress=current / total if total else 0
            ))

        def on_error(path: str, msg: str):
            self.after(0, lambda: scan_win.log_error(os.path.basename(path), msg))
            self.after(0, lambda: self.log(f"  BŁĄD: {os.path.basename(path)} — {msg}"))

        def on_done(results: list):
            self.scan_results = results
            total_files = len(results)
            errors = sum(1 for r in results if r.error)

            self.after(0, lambda: scan_win.set_phase("Szukam duplikatów..."))

            dup_groups   = self.deduplicator.run(results)
            grouper      = Grouper(use_device=use_device, depth=depth)
            photo_groups = grouper.run(results)

            def _finish():
                self.scan_results = results
                self.dup_groups   = dup_groups
                self.photo_groups = photo_groups

                dup_summary = Deduplicator.summary(dup_groups)
                grp_summary = Grouper.summary(photo_groups)

                scan_win.finish(total=total_files, errors=errors)

                self.set_status(
                    f"Gotowe — {dup_summary['total_groups']} grup duplikatów, "
                    f"{dup_summary['wasted_human']} do odzyskania",
                    progress=1.0
                )
                self.set_stats(
                    total=total_files,
                    duplicates=dup_summary["total_duplicates"],
                    groups=grp_summary["total_groups"],
                    savings=dup_summary["wasted_human"],
                )
                self.btn_scan.configure(state="normal", text="Skanuj ponownie")
                self.enable_actions(
                    scan=True,
                    delete=dup_summary["total_groups"] > 0,
                    organize=len(photo_groups) > 0,
                )
                self.log(
                    f"Znaleziono {total_files} plików. "
                    f"Duplikaty: {dup_summary['exact_groups']} identycznych + "
                    f"{dup_summary['similar_groups']} podobnych. "
                    f"Do odzyskania: {dup_summary['wasted_human']}."
                )

                self.duplicates_widget.load_groups(dup_groups)
                self.groups_widget.load_groups(photo_groups)

                if dup_summary["total_groups"] > 0:
                    self.tabview.set("Duplikaty")

            self.after(0, _finish)

        threading.Thread(
            target=self.scanner.scan,
            kwargs={"folder": folder, "on_progress": on_progress,
                    "on_done": on_done, "on_error": on_error},
            daemon=True
        ).start()

    # ================================================================ handlery

    def _regroup(self, use_device: bool, depth: str):
        if not self.scan_results:
            return

        def _calc():
            grouper_depth = depth if depth != "none" else "year"
            grouper       = Grouper(use_device=use_device, depth=grouper_depth)
            photo_groups  = grouper.run(self.scan_results)

            def _upd():
                self.photo_groups = photo_groups
                self.groups_widget.load_groups(photo_groups)
                g = Grouper.summary(photo_groups)
                self.set_stats(groups=g["total_groups"])

            self.after(0, _upd)

        threading.Thread(target=_calc, daemon=True).start()

    def _on_files_deleted(self, count: int):
        self.log(f"Usunięto {count} plików.")
        summary = Deduplicator.summary(self.dup_groups)
        self.set_stats(
            duplicates=summary["total_duplicates"],
            groups=summary["total_groups"],
            savings=summary["wasted_human"],
        )

    def _on_delete(self):
        self.tabview.set("Duplikaty")

    def _on_organize(self):
        self.tabview.set("Grupy zdjęć")

    def _on_settings(self):
        SettingsWindow(
            parent=self,
            current_settings=self.current_settings,
            on_apply=self._apply_settings,
            on_reset_cache=self._reset_cache,
        )

    def _apply_settings(self, new_settings: dict):
        self.current_settings.update(new_settings)
        self.scanner.workers              = new_settings["workers"]
        self.deduplicator.phash_threshold = new_settings["phash_threshold"]
        self.log(
            f"Ustawienia: próg pHash={new_settings['phash_threshold']}, "
            f"wątki={new_settings['workers']}"
        )
        if self.scan_results:
            def _recalc():
                dup_groups = self.deduplicator.run(self.scan_results)
                summary    = Deduplicator.summary(dup_groups)

                def _upd():
                    self.dup_groups = dup_groups
                    self.duplicates_widget.load_groups(dup_groups)
                    self.set_stats(
                        duplicates=summary["total_duplicates"],
                        groups=summary["total_groups"],
                        savings=summary["wasted_human"],
                    )
                    self.log(f"Przeliczono duplikaty: {summary['total_groups']} grup.")

                self.after(0, _upd)

            threading.Thread(target=_recalc, daemon=True).start()

    def _reset_cache(self):
        self.db.clear()
        self.scan_results = []
        self.dup_groups   = []
        self.photo_groups = []
        self.duplicates_widget.load_groups([])
        self.groups_widget.load_groups([])
        self.set_stats(total="—", duplicates="—", groups="—", savings="—")
        self.set_status("Cache wyczyszczony.", progress=0.0)
        self.log("Cache hashów wyczyszczony.")

    def _on_export(self):
        if not self.scan_results:
            messagebox.showinfo("Eksport", "Brak danych — najpierw uruchom skanowanie.")
            return
        path = export_report(
            dup_groups=self.dup_groups,
            photo_groups=self.photo_groups,
            parent_window=self,
        )
        if path:
            self.log(f"Raport zapisany: {path}")