"""
tab_duplicates.py — panel duplikatów.

Dwa tryby zaznaczania:
1. Pojedyncza grupa — klik w wiersz otwiera szczegóły po prawej,
   użytkownik wybiera radio "Zachowaj to" i checkbox "Usuń" per plik.
2. Wiele grup naraz — checkbox przy każdej grupie na liście,
   przycisk "Usuń duplikaty z zaznaczonych grup" usuwa wszystko za jednym razem.
"""

import os
import threading
from tkinter import messagebox
from typing import Optional

import customtkinter as ctk
from PIL import Image, ImageTk

from core.deduplicator import DuplicateGroup
from core.scanner import FileResult
from gui.image_viewer import ImageViewer


THUMBNAIL_SIZE = (280, 280)
MAX_GROUPS_IN_LIST = 500


class TabDuplicates(ctk.CTkFrame):

    def __init__(self, parent, on_deleted_callback=None, **kwargs):
        super().__init__(parent, fg_color="transparent", **kwargs)

        self._groups:             list[DuplicateGroup] = []
        self._selected_group_idx: Optional[int] = None
        self._check_vars:         dict[str, ctk.BooleanVar] = {}   # path → usuń?
        self._keep_var:           Optional[ctk.StringVar]   = None  # path keepera
        self._thumbnails:         list = []
        self._on_deleted          = on_deleted_callback

        # checkboxy grup na liście: group_idx → BooleanVar
        self._group_check_vars:   dict[int, ctk.BooleanVar] = {}
        self._select_all_var      = ctk.BooleanVar(value=False)

        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)

        self._build_list_panel()
        self._build_detail_panel()
        self._show_empty_state()

    # ================================================================ lista grup (lewa kolumna)

    def _build_list_panel(self):
        panel = ctk.CTkFrame(self, width=300)
        panel.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        panel.grid_rowconfigure(2, weight=1)
        panel.grid_columnconfigure(0, weight=1)
        panel.grid_propagate(False)

        # --- nagłówek z filtrem ---
        header = ctk.CTkFrame(panel, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=8, pady=(8, 4))
        header.grid_columnconfigure(0, weight=1)

        self.lbl_group_count = ctk.CTkLabel(
            header, text="Brak wyników",
            font=ctk.CTkFont(size=12, weight="bold")
        )
        self.lbl_group_count.grid(row=0, column=0, sticky="w")

        filter_frame = ctk.CTkFrame(header, fg_color="transparent")
        filter_frame.grid(row=1, column=0, sticky="w", pady=(4, 0))
        self.filter_var = ctk.StringVar(value="all")
        for label, val in [("Wszystkie","all"),("Identyczne","exact"),("Podobne","similar")]:
            ctk.CTkRadioButton(
                filter_frame, text=label, value=val,
                variable=self.filter_var,
                font=ctk.CTkFont(size=11),
                command=self._apply_filter
            ).pack(side="left", padx=(0,8))

        # --- pasek zaznaczania wielu grup ---
        multi_bar = ctk.CTkFrame(panel, fg_color=("gray85","gray20"))
        multi_bar.grid(row=1, column=0, sticky="ew", padx=4, pady=(0,4))
        multi_bar.grid_columnconfigure(1, weight=1)

        self.cb_select_all = ctk.CTkCheckBox(
            multi_bar, text="Zaznacz wszystkie",
            variable=self._select_all_var,
            font=ctk.CTkFont(size=11),
            command=self._on_select_all
        )
        self.cb_select_all.grid(row=0, column=0, padx=8, pady=6, sticky="w")

        self.btn_delete_multi = ctk.CTkButton(
            multi_bar,
            text="Usuń zaznaczone grupy",
            height=28, width=170,
            fg_color="#c0392b", hover_color="#a93226",
            font=ctk.CTkFont(size=11),
            command=self._on_delete_multi,
            state="disabled"
        )
        self.btn_delete_multi.grid(row=0, column=1, padx=8, pady=6, sticky="e")

        # --- scrollowana lista ---
        self.groups_scroll = ctk.CTkScrollableFrame(panel)
        self.groups_scroll.grid(row=2, column=0, sticky="nsew", padx=4, pady=(0,4))
        self.groups_scroll.grid_columnconfigure(0, weight=1)

    # ================================================================ panel szczegółów (prawa kolumna)

    def _build_detail_panel(self):
        self.detail_panel = ctk.CTkFrame(self, fg_color="transparent")
        self.detail_panel.grid(row=0, column=1, sticky="nsew")
        self.detail_panel.grid_rowconfigure(1, weight=1)
        self.detail_panel.grid_columnconfigure(0, weight=1)

        action_bar = ctk.CTkFrame(self.detail_panel, height=48)
        action_bar.grid(row=0, column=0, sticky="ew", pady=(0,8))
        action_bar.grid_propagate(False)

        self.lbl_group_title = ctk.CTkLabel(
            action_bar, text="",
            font=ctk.CTkFont(size=13, weight="bold")
        )
        self.lbl_group_title.pack(side="left", padx=12)

        self.btn_delete_selected = ctk.CTkButton(
            action_bar,
            text="Usuń zaznaczone",
            width=150, height=32,
            fg_color="#c0392b", hover_color="#a93226",
            command=self._on_delete_selected,
            state="disabled"
        )
        self.btn_delete_selected.pack(side="right", padx=12)

        self.thumbs_scroll = ctk.CTkScrollableFrame(self.detail_panel)
        self.thumbs_scroll.grid(row=1, column=0, sticky="nsew")

    # ================================================================ dane

    def load_groups(self, groups: list[DuplicateGroup]):
        self._groups = groups
        self._group_check_vars.clear()
        self._select_all_var.set(False)
        self._selected_group_idx = None
        self._apply_filter()

    def _apply_filter(self):
        f = self.filter_var.get()
        filtered = [
            (i, g) for i, g in enumerate(self._groups)
            if f == "all" or g.group_type == f
        ]
        self._render_group_list(filtered)

    def _render_group_list(self, indexed_groups: list):
        for w in self.groups_scroll.winfo_children():
            w.destroy()

        count = len(indexed_groups)
        self.lbl_group_count.configure(text=f"{count} grup duplikatów")
        self.cb_select_all.configure(state="normal" if count else "disabled")

        if count == 0:
            ctk.CTkLabel(
                self.groups_scroll,
                text="Brak grup dla tego filtra.",
                text_color="gray", font=ctk.CTkFont(size=12)
            ).grid(row=0, column=0, pady=20)
            return

        for row_idx, (group_idx, group) in enumerate(indexed_groups[:MAX_GROUPS_IN_LIST]):
            self._add_group_row(row_idx, group_idx, group)

        if len(indexed_groups) > MAX_GROUPS_IN_LIST:
            ctk.CTkLabel(
                self.groups_scroll,
                text=f"… i {len(indexed_groups)-MAX_GROUPS_IN_LIST} więcej",
                text_color="gray", font=ctk.CTkFont(size=11)
            ).grid(row=MAX_GROUPS_IN_LIST, column=0, pady=8)

    def _add_group_row(self, row_idx: int, group_idx: int, group: DuplicateGroup):
        type_color = "#2ecc71" if group.group_type == "exact" else "#3498db"
        type_label = "identyczne" if group.group_type == "exact" else "podobne"

        # inicjalizuj BooleanVar dla tej grupy jeśli jeszcze nie ma
        if group_idx not in self._group_check_vars:
            self._group_check_vars[group_idx] = ctk.BooleanVar(value=False)
        group_var = self._group_check_vars[group_idx]

        frame = ctk.CTkFrame(self.groups_scroll)
        frame.grid(row=row_idx, column=0, sticky="ew", padx=4, pady=2)
        frame.grid_columnconfigure(2, weight=1)

        # checkbox grupy
        cb = ctk.CTkCheckBox(
            frame, text="", variable=group_var,
            width=24,
            command=self._on_group_checkbox_changed
        )
        cb.grid(row=0, column=0, rowspan=2, padx=(6,4), pady=4)

        # kolorowy pasek
        bar = ctk.CTkFrame(frame, width=4, fg_color=type_color)
        bar.grid(row=0, column=1, rowspan=2, sticky="ns", padx=(0,8), pady=4)
        bar.grid_propagate(False)

        # tekst
        keep_name = os.path.basename(group.best.path) if group.best else "?"
        ctk.CTkLabel(
            frame,
            text=f"{len(group.files)} pliki — {type_label}",
            font=ctk.CTkFont(size=12, weight="bold")
        ).grid(row=0, column=2, sticky="w", padx=(0,8), pady=(6,0))

        ctk.CTkLabel(
            frame,
            text=f"sugestia: {keep_name}  •  {_human_size(group.wasted_bytes)}",
            font=ctk.CTkFont(size=11), text_color="gray"
        ).grid(row=1, column=2, sticky="w", padx=(0,8), pady=(0,6))

        # klik w tekst/ramkę otwiera szczegóły
        for widget in (frame, bar):
            widget.bind("<Button-1>", lambda e, idx=group_idx: self._on_group_click(idx))
        frame.bind("<Enter>", lambda e, f=frame: f.configure(fg_color=("gray85","gray25")))
        frame.bind("<Leave>", lambda e, f=frame: f.configure(fg_color=("gray80","gray20")))

    # ================================================================ zaznaczanie wielu grup

    def _on_select_all(self):
        val = self._select_all_var.get()
        for var in self._group_check_vars.values():
            var.set(val)
        self._refresh_multi_button()

    def _on_group_checkbox_changed(self):
        # synchronizuj "zaznacz wszystkie"
        all_checked = all(v.get() for v in self._group_check_vars.values())
        self._select_all_var.set(all_checked)
        self._refresh_multi_button()

    def _refresh_multi_button(self):
        checked = sum(1 for v in self._group_check_vars.values() if v.get())
        if checked:
            self.btn_delete_multi.configure(
                text=f"Usuń duplikaty z {checked} grup",
                state="normal"
            )
        else:
            self.btn_delete_multi.configure(
                text="Usuń zaznaczone grupy",
                state="disabled"
            )

    def _on_delete_multi(self):
        """Usuwa duplikaty (nie-best) ze wszystkich zaznaczonych grup."""
        checked_indices = [idx for idx, var in self._group_check_vars.items() if var.get()]
        if not checked_indices:
            return

        # zbierz pliki do usunięcia ze wszystkich zaznaczonych grup
        to_delete: list[str] = []
        for idx in checked_indices:
            if idx >= len(self._groups):
                continue
            group = self._groups[idx]
            keep  = group.best.path if group.best else None
            for f in group.files:
                if f.path != keep:
                    to_delete.append(f.path)

        if not to_delete:
            return

        if not messagebox.askyesno(
            "Potwierdzenie",
            f"Usunąć trwale {len(to_delete)} plików\n"
            f"z {len(checked_indices)} grup duplikatów?\n\n"
            f"W każdej grupie zostanie zachowany plik\n"
            f"wskazany przez algorytm lub wybrany przez Ciebie.\n\n"
            f"Tej operacji nie można cofnąć.",
            icon="warning"
        ):
            return

        errors  = []
        deleted = 0
        for path in to_delete:
            try:
                os.remove(path)
                deleted += 1
            except Exception as e:
                errors.append(f"{os.path.basename(path)}: {e}")

        if errors:
            messagebox.showwarning("Błędy usuwania", "\n".join(errors[:5]))

        if self._on_deleted:
            self._on_deleted(deleted)

        # usuń przetworzone grupy z listy
        deleted_set = set(to_delete)
        for idx in sorted(checked_indices, reverse=True):
            if idx < len(self._groups):
                group = self._groups[idx]
                group.files = [f for f in group.files if f.path not in deleted_set]
                if len(group.files) < 2:
                    self._groups.pop(idx)

        self._group_check_vars.clear()
        self._select_all_var.set(False)
        self._selected_group_idx = None
        self._apply_filter()
        self._show_empty_state()
        self._refresh_multi_button()

    # ================================================================ szczegóły jednej grupy

    def _on_group_click(self, group_idx: int):
        self._selected_group_idx = group_idx
        self._render_detail(self._groups[group_idx])

    def _render_detail(self, group: DuplicateGroup):
        for w in self.thumbs_scroll.winfo_children():
            w.destroy()
        self._check_vars.clear()
        self._thumbnails.clear()

        initial_keep = group.best.path if group.best else (group.files[0].path if group.files else "")
        self._keep_var = ctk.StringVar(value=initial_keep)
        self._keep_var.trace_add("write", lambda *_: self._on_keep_changed(group))

        type_label = "Identyczne kopie" if group.group_type == "exact" else "Podobne zdjęcia"
        self.lbl_group_title.configure(
            text=f"{type_label} — {len(group.files)} pliki, {_human_size(group.wasted_bytes)}"
        )
        self.btn_delete_selected.configure(state="normal")

        COLS = 3
        for i, file in enumerate(group.files):
            self._add_thumb_card(file, group, i // COLS, i % COLS)

        self._refresh_delete_button()

    def _add_thumb_card(self, file: FileResult, group: DuplicateGroup, row: int, col: int):
        is_suggested = (file is group.best)

        card = ctk.CTkFrame(self.thumbs_scroll, border_width=2, border_color="gray30")
        card.grid(row=row, column=col, padx=8, pady=8, sticky="nsew")
        self.thumbs_scroll.grid_columnconfigure(col, weight=1)

        # miniaturka
        thumb_label = ctk.CTkLabel(
            card, text="⏳", width=THUMBNAIL_SIZE[0], height=THUMBNAIL_SIZE[1], cursor="hand2"
        )
        thumb_label.pack(pady=(8, 4))
        all_paths = [f.path for f in group.files]
        idx = group.files.index(file)
        thumb_label.bind("<Button-1>", lambda e, p=all_paths, i=idx: self._open_viewer(p, i))
        threading.Thread(target=self._load_thumbnail, args=(file.path, thumb_label), daemon=True).start()

        # nazwa
        fname = os.path.basename(file.path)
        ctk.CTkLabel(
            card,
            text=fname if len(fname) <= 24 else fname[:21]+"…",
            font=ctk.CTkFont(size=11, weight="bold"), wraplength=280
        ).pack(padx=8)

        # info
        res      = f"{file.width}×{file.height}" if file.width else "nieznana"
        date_str = file.exif_date[:10] if file.exif_date else "brak EXIF"
        ctk.CTkLabel(
            card,
            text=f"{res}  •  {_human_size(file.size)}\n{date_str}",
            font=ctk.CTkFont(size=10), text_color="gray", justify="center"
        ).pack(padx=8, pady=(2,4))

        # radio + checkbox
        choice_frame = ctk.CTkFrame(card, fg_color="transparent")
        choice_frame.pack(padx=8, pady=(2,8))

        ctk.CTkRadioButton(
            choice_frame, text="Zachowaj to",
            variable=self._keep_var, value=file.path,
            font=ctk.CTkFont(size=11),
            fg_color="#2ecc71", hover_color="#27ae60",
        ).pack(side="left", padx=(0,8))

        delete_var = ctk.BooleanVar(value=(file.path != self._keep_var.get()))
        self._check_vars[file.path] = delete_var

        cb = ctk.CTkCheckBox(
            choice_frame, text="Usuń",
            variable=delete_var,
            font=ctk.CTkFont(size=11),
            fg_color="#c0392b", hover_color="#a93226",
            command=self._refresh_delete_button
        )
        cb.pack(side="left")

        if is_suggested:
            ctk.CTkLabel(
                card, text="★ sugestia algorytmu",
                font=ctk.CTkFont(size=10), text_color="#f39c12"
            ).pack(pady=(0,4))

        def _update_card(*_, f=file, c=card, cv=delete_var, checkbox=cb):
            is_keeper = (self._keep_var.get() == f.path)
            c.configure(border_color="#2ecc71" if is_keeper else "gray30")
            if is_keeper:
                cv.set(False)
                checkbox.configure(state="disabled")
            else:
                checkbox.configure(state="normal")
            self._refresh_delete_button()

        self._keep_var.trace_add("write", _update_card)
        _update_card()

    # ================================================================ akcje pojedynczej grupy

    def _on_keep_changed(self, group: DuplicateGroup):
        keep_path = self._keep_var.get()
        for f in group.files:
            if f.path == keep_path:
                group.best = f
                break

    def _refresh_delete_button(self):
        if self._keep_var:
            keep_path = self._keep_var.get()
            if keep_path in self._check_vars:
                self._check_vars[keep_path].set(False)
        count = sum(
            1 for p, v in self._check_vars.items()
            if v.get() and p != (self._keep_var.get() if self._keep_var else "")
        )
        self.btn_delete_selected.configure(
            text=f"Usuń zaznaczone ({count})" if count else "Usuń zaznaczone",
            state="normal" if count else "disabled"
        )

    def _on_delete_selected(self):
        keep_path = self._keep_var.get() if self._keep_var else ""
        to_delete = [p for p, v in self._check_vars.items() if v.get() and p != keep_path]
        if not to_delete:
            return

        if not messagebox.askyesno(
            "Potwierdzenie",
            f"Usunąć trwale {len(to_delete)} "
            f"{'plik' if len(to_delete)==1 else 'pliki' if len(to_delete)<5 else 'plików'}?\n\n"
            f"Zachowany zostanie:\n{os.path.basename(keep_path)}\n\n"
            f"Tej operacji nie można cofnąć.",
            icon="warning"
        ):
            return

        errors  = []
        deleted = 0
        for path in to_delete:
            try:
                os.remove(path)
                deleted += 1
            except Exception as e:
                errors.append(f"{os.path.basename(path)}: {e}")

        if errors:
            messagebox.showwarning("Błędy usuwania", "\n".join(errors[:5]))

        if self._on_deleted:
            self._on_deleted(deleted)

        # usuń pliki z grupy i przejdź do następnej
        if self._selected_group_idx is not None:
            group = self._groups[self._selected_group_idx]
            group.files = [f for f in group.files if f.path not in set(to_delete)]

            if len(group.files) < 2:
                self._groups.pop(self._selected_group_idx)
                next_idx = min(self._selected_group_idx, len(self._groups) - 1)
                self._apply_filter()
                if self._groups and next_idx >= 0:
                    self._selected_group_idx = next_idx
                    self._render_detail(self._groups[next_idx])
                else:
                    self._selected_group_idx = None
                    self._show_empty_state()
            else:
                if group.best and group.best.path in set(to_delete):
                    group.best = group.files[0]
                self._render_detail(group)
                self._apply_filter()

    # ================================================================ viewer

    def _open_viewer(self, paths: list, index: int):
        if index == 0:
            start = 1 if len(paths) > 1 else 0
        else:
            ordered = [paths[0]] + [p for i, p in enumerate(paths) if i != 0]
            start   = ordered.index(paths[index]) if paths[index] in ordered else 1
            paths   = ordered
        ImageViewer(self, paths=paths, start_index=start)

    # ================================================================ helpers

    def _load_thumbnail(self, path: str, label: ctk.CTkLabel):
        try:
            with Image.open(path) as img:
                try:
                    exif = img._getexif()
                    if exif:
                        rot = {3:180, 6:270, 8:90}.get(exif.get(274))
                        if rot:
                            img = img.rotate(rot, expand=True)
                except Exception:
                    pass
                img.thumbnail(THUMBNAIL_SIZE, Image.LANCZOS)
                photo = ImageTk.PhotoImage(img)
                self._thumbnails.append(photo)
                label.after(0, lambda: label.configure(image=photo, text=""))
        except Exception:
            label.after(0, lambda: label.configure(text="brak podglądu"))

    def _show_empty_state(self):
        for w in self.thumbs_scroll.winfo_children():
            w.destroy()
        self._check_vars.clear()
        self._keep_var = None
        self.lbl_group_title.configure(text="")
        self.btn_delete_selected.configure(state="disabled", text="Usuń zaznaczone")
        ctk.CTkLabel(
            self.thumbs_scroll,
            text="Kliknij grupę na liście\naby zobaczyć szczegóły.",
            text_color="gray", font=ctk.CTkFont(size=13), justify="center"
        ).pack(expand=True, pady=40)


def _human_size(n: int) -> str:
    for u in ("B","KB","MB","GB"):
        if n < 1024: return f"{n:.1f} {u}"
        n /= 1024
    return f"{n:.1f} TB"