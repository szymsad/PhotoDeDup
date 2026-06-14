import os
import shutil
import threading
from tkinter import messagebox, filedialog, ttk
from typing import Optional
import re as _re

import customtkinter as ctk

from core.grouper import PhotoGroup, Grouper, NONAME_DEVICE


def _apply_treeview_style():
    style = ttk.Style()
    style.theme_use("default")
    style.configure("Custom.Treeview",
        background="#2b2b2b", foreground="#dce4ee",
        fieldbackground="#2b2b2b", borderwidth=0,
        rowheight=24, font=("Segoe UI", 11),
    )
    style.configure("Custom.Treeview.Heading",
        background="#1f1f1f", foreground="#aaaaaa",
        borderwidth=0, font=("Segoe UI", 11, "bold"),
    )
    style.map("Custom.Treeview",
        background=[("selected", "#1f538d")],
        foreground=[("selected", "#ffffff")],
    )


class TabGroups(ctk.CTkFrame):

    def __init__(self, parent, on_regroup=None, **kwargs):
        super().__init__(parent, fg_color="transparent", **kwargs)

        self._groups:         list[PhotoGroup] = []
        self._selected_group: Optional[PhotoGroup] = None
        self._on_regroup      = on_regroup
        self._folder_mode     = ctk.StringVar(value="device_month")
        self._device_aliases: dict[str, str] = {}

        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(1, weight=1)

        _apply_treeview_style()
        self._build_options_bar()
        self._build_tree_panel()
        self._build_detail_panel()

    # ================================================================ opcje

    def _build_options_bar(self):
        """
        Pasek opcji z dwoma rzędami radio buttonów — wszystkie kontrolki
        mieszczą się bez konieczności ręcznego rozszerzania okna.

        Rząd 1: tryby z urządzeniem (4 opcje)
        Rząd 2: tryby tylko z datą  (3 opcje) + podgląd ścieżki
        """
        bar = ctk.CTkFrame(self)
        bar.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        bar.grid_columnconfigure(0, weight=1)

        # --- Rząd 1: z urządzeniem ---
        row1 = ctk.CTkFrame(bar, fg_color="transparent")
        row1.grid(row=0, column=0, sticky="ew", padx=12, pady=(8, 2))

        ctk.CTkLabel(
            row1, text="Z urządzeniem:",
            font=ctk.CTkFont(size=12, weight="bold"),
            width=110, anchor="w"
        ).pack(side="left", padx=(0, 6))

        MODES_DEVICE = [
            ("Urządzenie",              "device"),
            ("Urządzenie / Rok",        "device_year"),
            ("Urządzenie / Rok / Mies", "device_month"),
            ("Urządzenie / R / M / D",  "device_day"),
        ]
        for label, val in MODES_DEVICE:
            ctk.CTkRadioButton(
                row1, text=label, value=val,
                variable=self._folder_mode,
                font=ctk.CTkFont(size=11),
                command=self._on_structure_change
            ).pack(side="left", padx=(0, 14))

        # --- Rząd 2: tylko data + podgląd ---
        row2 = ctk.CTkFrame(bar, fg_color="transparent")
        row2.grid(row=1, column=0, sticky="ew", padx=12, pady=(2, 8))

        ctk.CTkLabel(
            row2, text="Tylko data:",
            font=ctk.CTkFont(size=12, weight="bold"),
            width=110, anchor="w"
        ).pack(side="left", padx=(0, 6))

        MODES_DATE = [
            ("Rok",           "year"),
            ("Rok / Miesiąc", "month"),
            ("Rok / M / Dzień", "day"),
        ]
        for label, val in MODES_DATE:
            ctk.CTkRadioButton(
                row2, text=label, value=val,
                variable=self._folder_mode,
                font=ctk.CTkFont(size=11),
                command=self._on_structure_change
            ).pack(side="left", padx=(0, 14))

        # separator pionowy
        ctk.CTkFrame(row2, width=1, fg_color="gray50").pack(side="left", fill="y", padx=(4, 12))

        # podgląd ścieżki
        self.lbl_path_preview = ctk.CTkLabel(
            row2, text="",
            font=ctk.CTkFont(size=11), text_color="gray"
        )
        self.lbl_path_preview.pack(side="left")

        self._refresh_path_preview()

    def _refresh_path_preview(self):
        self.lbl_path_preview.configure(
            text=f"→  {_mode_to_example(self._folder_mode.get())}"
        )

    def _on_structure_change(self):
        self._refresh_path_preview()
        if self._on_regroup:
            use_dev, depth = _mode_to_params(self._folder_mode.get())
            self._on_regroup(use_dev, depth)

    # ================================================================ drzewo (lewy panel)

    def _build_tree_panel(self):
        panel = ctk.CTkFrame(self, width=280)
        panel.grid(row=1, column=0, sticky="nsew", padx=(0, 8))
        panel.grid_rowconfigure(1, weight=1)
        panel.grid_columnconfigure(0, weight=1)
        panel.grid_propagate(False)

        self.lbl_tree_header = ctk.CTkLabel(
            panel, text="Brak danych",
            font=ctk.CTkFont(size=12, weight="bold")
        )
        self.lbl_tree_header.grid(row=0, column=0, padx=12, pady=(10, 6), sticky="w")

        self.tree_scroll = ctk.CTkScrollableFrame(panel)
        self.tree_scroll.grid(row=1, column=0, sticky="nsew", padx=4, pady=(0, 4))
        self.tree_scroll.grid_columnconfigure(0, weight=1)

    # ================================================================ szczegoly (prawy panel)

    def _build_detail_panel(self):
        panel = ctk.CTkFrame(self, fg_color="transparent")
        panel.grid(row=1, column=1, sticky="nsew")
        panel.grid_rowconfigure(1, weight=1)
        panel.grid_columnconfigure(0, weight=1)

        action_bar = ctk.CTkFrame(panel, height=48)
        action_bar.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        action_bar.grid_propagate(False)
        action_bar.grid_columnconfigure(0, weight=1)

        self.lbl_group_info = ctk.CTkLabel(
            action_bar, text="Wybierz grupę z listy",
            font=ctk.CTkFont(size=12), text_color="gray"
        )
        self.lbl_group_info.grid(row=0, column=0, padx=12, sticky="w")

        btn_frame = ctk.CTkFrame(action_bar, fg_color="transparent")
        btn_frame.grid(row=0, column=1, padx=12, sticky="e")

        self.btn_copy = ctk.CTkButton(
            btn_frame, text="Kopiuj do folderów",
            width=150, height=32,
            fg_color="transparent", border_width=1,
            text_color=("gray10", "gray90"),
            command=lambda: self._on_organize(copy=True),
            state="disabled"
        )
        self.btn_copy.pack(side="left", padx=(0, 8))

        self.btn_move = ctk.CTkButton(
            btn_frame, text="Przenieś do folderów",
            width=160, height=32,
            command=lambda: self._on_organize(copy=False),
            state="disabled"
        )
        self.btn_move.pack(side="left")

        tree_frame = ctk.CTkFrame(panel, fg_color="transparent")
        tree_frame.grid(row=1, column=0, sticky="nsew")
        tree_frame.grid_rowconfigure(0, weight=1)
        tree_frame.grid_columnconfigure(0, weight=1)

        cols = ("nr", "nazwa", "rozmiar", "rozdzielczosc", "data", "zrodlo")
        self.file_tree = ttk.Treeview(
            tree_frame, columns=cols, show="headings",
            style="Custom.Treeview", selectmode="browse",
        )
        self.file_tree.heading("nr",            text="#")
        self.file_tree.heading("nazwa",         text="Nazwa pliku")
        self.file_tree.heading("rozmiar",       text="Rozmiar")
        self.file_tree.heading("rozdzielczosc", text="Rozdzielczość")
        self.file_tree.heading("data",          text="Data")
        self.file_tree.heading("zrodlo",        text="Źródło daty")
        self.file_tree.column("nr",            width=36,  minwidth=30,  stretch=False)
        self.file_tree.column("nazwa",         width=260, minwidth=120, stretch=True)
        self.file_tree.column("rozmiar",       width=80,  minwidth=60,  stretch=False)
        self.file_tree.column("rozdzielczosc", width=110, minwidth=80,  stretch=False)
        self.file_tree.column("data",          width=120, minwidth=90,  stretch=False)
        self.file_tree.column("zrodlo",        width=80,  minwidth=60,  stretch=False)

        vsb = ttk.Scrollbar(tree_frame, orient="vertical",   command=self.file_tree.yview)
        hsb = ttk.Scrollbar(tree_frame, orient="horizontal", command=self.file_tree.xview)
        self.file_tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self.file_tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")

    # ================================================================ dane

    def load_groups(self, groups: list, mode: str = ""):
        self._groups = groups
        self._selected_group = None
        self._clear_file_tree()
        self._render_tree()

    def _render_tree(self):
        for w in self.tree_scroll.winfo_children():
            w.destroy()

        if not self._groups:
            self.lbl_tree_header.configure(text="Brak grup")
            ctk.CTkLabel(
                self.tree_scroll,
                text="Brak danych.\nUruchom skanowanie.",
                text_color="gray", font=ctk.CTkFont(size=12)
            ).grid(row=0, column=0, pady=20)
            return

        total_files = sum(len(g.files) for g in self._groups)
        self.lbl_tree_header.configure(
            text=f"{len(self._groups)} grup  •  {total_files} plików"
        )

        seen_devices = []
        for g in self._groups:
            dev = g.device_label
            if dev not in seen_devices:
                seen_devices.append(dev)

        row = 0
        for device in seen_devices:
            device_groups = [g for g in self._groups if g.device_label == device]
            row = self._add_device_section(row, device, device_groups)

    def _add_device_section(self, row: int, device: str, groups: list) -> int:
        dev_files = sum(len(g.files) for g in groups)
        alias     = self._device_aliases.get(device, device)

        dev_frame = ctk.CTkFrame(
            self.tree_scroll,
            fg_color=("gray80", "gray22"),
            corner_radius=6
        )
        dev_frame.grid(row=row, column=0, sticky="ew", padx=4, pady=(8, 2))

        lbl = ctk.CTkLabel(
            dev_frame,
            text=f"  {alias}",
            font=ctk.CTkFont(size=12, weight="bold"),
            anchor="w"
        )
        lbl.pack(side="left", padx=8, pady=6, fill="x", expand=True)

        ctk.CTkLabel(
            dev_frame,
            text=f"{dev_files} pl.",
            font=ctk.CTkFont(size=11), text_color="gray"
        ).pack(side="right", padx=(0, 4))

        ctk.CTkButton(
            dev_frame, text="✎", width=28, height=26,
            fg_color="transparent", hover_color=("gray70", "gray30"),
            font=ctk.CTkFont(size=13),
            command=lambda d=device, l=lbl: self._edit_device_name(d, l)
        ).pack(side="right", padx=(0, 6))

        row += 1
        for g in groups:
            self._add_group_row(row, g)
            row += 1
        return row

    def _edit_device_name(self, device: str, label: ctk.CTkLabel):
        current = self._device_aliases.get(device, device)

        dialog = ctk.CTkToplevel(self)
        dialog.title("Zmień nazwę folderu")
        dialog.geometry("420x165")
        dialog.resizable(False, False)
        dialog.grab_set()
        dialog.after(50, lambda: (
            dialog.attributes("-topmost", True),
            dialog.after(200, lambda: dialog.attributes("-topmost", False)),
            dialog.lift(),
            dialog.focus_force()
        ))

        ctk.CTkLabel(
            dialog,
            text=f"Oryginalna nazwa: {device}",
            font=ctk.CTkFont(size=11), text_color="gray"
        ).pack(padx=16, pady=(14, 2), anchor="w")

        ctk.CTkLabel(
            dialog, text="Nazwa folderu docelowego:",
            font=ctk.CTkFont(size=12)
        ).pack(padx=16, anchor="w")

        entry_var = ctk.StringVar(value=current)
        entry = ctk.CTkEntry(dialog, textvariable=entry_var, width=388, height=34)
        entry.pack(padx=16, pady=(4, 10))
        entry.focus()
        entry.select_range(0, "end")

        def _apply():
            raw = entry_var.get().strip()
            if not raw:
                return
            clean = _re.sub(r'[\x00-\x1f<>:"/\\|?*]', '_', raw).strip().rstrip(".")
            if clean:
                self._device_aliases[device] = clean
                label.configure(text=f"  {clean}")
            dialog.destroy()

        def _reset():
            self._device_aliases.pop(device, None)
            label.configure(text=f"  {device}")
            dialog.destroy()

        btn_frame = ctk.CTkFrame(dialog, fg_color="transparent")
        btn_frame.pack(padx=16, fill="x")

        ctk.CTkButton(
            btn_frame, text="Przywróć oryginał", width=150, height=30,
            fg_color="transparent", border_width=1,
            text_color=("gray10", "gray90"),
            command=_reset
        ).pack(side="left")

        ctk.CTkButton(
            btn_frame, text="Zastosuj", width=100, height=30,
            command=_apply
        ).pack(side="right")

        entry.bind("<Return>", lambda e: _apply())
        entry.bind("<Escape>", lambda e: dialog.destroy())

    def _add_group_row(self, row: int, group: PhotoGroup):
        parts = []
        if group.year:  parts.append(group.label_year)
        if group.month: parts.append(group.label_month)
        if group.day:   parts.append(f"dzień {group.label_day}")
        label = " / ".join(parts) if parts else "Nieznana data"

        frame = ctk.CTkFrame(self.tree_scroll, cursor="hand2", fg_color="transparent")
        frame.grid(row=row, column=0, sticky="ew", padx=(20, 4), pady=1)
        frame.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(frame, text=label, font=ctk.CTkFont(size=12), anchor="w"
        ).grid(row=0, column=0, padx=10, pady=5, sticky="w")

        ctk.CTkLabel(frame, text=str(len(group.files)),
                     font=ctk.CTkFont(size=11), text_color="gray"
        ).grid(row=0, column=1, padx=10, sticky="e")

        frame.bind("<Button-1>", lambda e, g=group: self._on_group_click(g))
        frame.bind("<Enter>",    lambda e, f=frame: f.configure(fg_color=("gray85", "gray25")))
        frame.bind("<Leave>",    lambda e, f=frame, g=group: f.configure(
            fg_color=("gray75", "gray30") if self._selected_group is g else "transparent"
        ))
        for child in frame.winfo_children():
            child.bind("<Button-1>", lambda e, g=group: self._on_group_click(g))

    # ================================================================ szczegoly grupy

    def _on_group_click(self, group: PhotoGroup):
        self._selected_group = group
        self._render_files(group)

    def _render_files(self, group: PhotoGroup):
        self._clear_file_tree()

        size_human = _human_size(group.size_bytes)
        sources    = ", ".join(f"{s}:{c}" for s, c in sorted(group.date_sources.items()))
        self.lbl_group_info.configure(
            text=f"{group.label}  •  {len(group.files)} plików  •  {size_human}  •  daty: {sources}",
            text_color=("gray10", "gray90")
        )
        self.btn_copy.configure(state="normal")
        self.btn_move.configure(state="normal")

        for i, f in enumerate(sorted(group.files, key=lambda x: x.exif_date or ""), 1):
            res  = f"{f.width}x{f.height}" if f.width else "—"
            date = f.exif_date[:10] if f.exif_date else "—"
            src  = "EXIF" if f.exif_date else "mtime"
            self.file_tree.insert("", "end", values=(
                i, os.path.basename(f.path), _human_size(f.size), res, date, src
            ))

    def _clear_file_tree(self):
        for item in self.file_tree.get_children():
            self.file_tree.delete(item)

    # ================================================================ organizacja

    def _get_mode_params(self) -> tuple:
        return _mode_to_params(self._folder_mode.get())

    def _on_organize(self, copy: bool):
        if not self._groups:
            return
        dest = filedialog.askdirectory(title="Wybierz folder docelowy")
        if not dest:
            return

        use_device, depth = self._get_mode_params()
        action  = "Kopiowanie" if copy else "Przenoszenie"
        total   = sum(len(g.files) for g in self._groups)
        preview = self._build_preview(use_device, depth)

        if not messagebox.askyesno(
            "Potwierdzenie",
            f"{action} {total} plików do:\n{dest}\n\n"
            f"Przykładowa struktura:\n{preview}\n\nKontynuować?",
        ):
            return

        threading.Thread(
            target=self._do_organize,
            args=(dest, copy, use_device, depth),
            daemon=True
        ).start()

    def _build_preview(self, use_device: bool, depth: str) -> str:
        lines = []
        seen  = set()
        for g in self._groups[:4]:
            path = g.suggested_folder(use_device=use_device, depth=depth,
                                      device_aliases=self._device_aliases)
            if path not in seen:
                lines.append(f"  {path}{os.sep}")
                seen.add(path)
        if len(self._groups) > 4:
            lines.append(f"  ... i {len(self._groups) - 4} więcej")
        return "\n".join(lines)

    def _do_organize(self, dest: str, copy: bool, use_device: bool, depth: str):
        errors = []
        moved  = 0

        for group in self._groups:
            raw_folder = group.suggested_folder(
                use_device, depth, device_aliases=self._device_aliases
            )
            raw_folder = "".join(
                c for c in raw_folder if ord(c) >= 32 or c in (os.sep, "/", "\\")
            )
            target_dir = os.path.join(dest, raw_folder)
            try:
                os.makedirs(target_dir, exist_ok=True)
            except Exception as e:
                errors.append(f"Błąd tworzenia folderu '{raw_folder}': {e}")
                continue

            for f in group.files:
                fname  = os.path.basename(f.path)
                target = os.path.join(target_dir, fname)
                if os.path.exists(target):
                    name, ext = os.path.splitext(fname)
                    target = os.path.join(target_dir, f"{name}_dup{ext}")
                try:
                    shutil.copy2(f.path, target) if copy else shutil.move(f.path, target)
                    moved += 1
                except Exception as e:
                    errors.append(f"{fname}: {e}")

        action = "Skopiowano" if copy else "Przeniesiono"
        msg    = f"{action} {moved} plików."
        if errors:
            msg += f"\nBłędy ({len(errors)}):\n" + "\n".join(errors[:5])
        self.after(0, lambda: messagebox.showinfo("Gotowe", msg))


# ================================================================ module-level helpers

def _mode_to_params(mode: str) -> tuple:
    return {
        "device":       (True,  "none"),
        "device_year":  (True,  "year"),
        "device_month": (True,  "month"),
        "device_day":   (True,  "day"),
        "year":         (False, "year"),
        "month":        (False, "month"),
        "day":          (False, "day"),
    }.get(mode, (True, "month"))


def _mode_to_example(mode: str) -> str:
    return {
        "device":       "iPhone 15 Pro" + os.sep,
        "device_year":  os.path.join("iPhone 15 Pro", "2024") + os.sep,
        "device_month": os.path.join("iPhone 15 Pro", "2024", "03") + os.sep,
        "device_day":   os.path.join("iPhone 15 Pro", "2024", "03", "15") + os.sep,
        "year":         "2024" + os.sep,
        "month":        os.path.join("2024", "03") + os.sep,
        "day":          os.path.join("2024", "03", "15") + os.sep,
    }.get(mode, "")


def _human_size(n: int) -> str:
    for u in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {u}"
        n /= 1024
    return f"{n:.1f} TB"