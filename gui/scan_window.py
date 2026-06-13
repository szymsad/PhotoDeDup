"""
scan_window.py — osobne okno pokazywane podczas skanowania.
Mozna je minimalizowac. Zamyka sie samo po zakonczeniu.
"""

import customtkinter as ctk
from tkinter import ttk


class ScanWindow(ctk.CTkToplevel):
    """
    Okno postepuo skanowania.

    Uzycie:
        win = ScanWindow(parent)
        win.update_progress(50, 200, "foto.jpg")
        win.finish(total=200, errors=3)
        # lub
        win.on_cancel_callback = lambda: scanner.stop()
    """

    def __init__(self, parent, on_cancel=None, **kwargs):
        super().__init__(parent, **kwargs)

        self.title("Skanowanie...")
        self.geometry("520x340")
        self.resizable(False, False)

        # NIE robimy grab_set() — okno jest niezalezne, mozna klikac glowne okno
        self.protocol("WM_DELETE_WINDOW", self._on_close_btn)

        self._on_cancel = on_cancel
        self._cancelled = False
        self._finished  = False

        self._build_ui()
        self._force_focus()

    def _force_focus(self):
        """Wymusza pojawienie sie okna na wierzchu na Windows."""
        self.after(50, lambda: (
            self.attributes("-topmost", True),
            self.after(200, lambda: self.attributes("-topmost", False)),
            self.lift(),
            self.focus_force()
        ))

    # ================================================================ UI

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        # --- naglowek ---
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=20, pady=(20, 8))
        header.grid_columnconfigure(0, weight=1)

        self.lbl_title = ctk.CTkLabel(
            header, text="Skanowanie folderu...",
            font=ctk.CTkFont(size=16, weight="bold")
        )
        self.lbl_title.grid(row=0, column=0, sticky="w")

        self.lbl_counter = ctk.CTkLabel(
            header, text="0 / 0",
            font=ctk.CTkFont(size=12),
            text_color="gray"
        )
        self.lbl_counter.grid(row=1, column=0, sticky="w")

        # --- pasek postepu ---
        self.progress = ctk.CTkProgressBar(self, height=12)
        self.progress.set(0)
        self.progress.grid(row=1, column=0, sticky="ew", padx=20, pady=(0, 12))

        # --- log (ostatnie operacje) ---
        self.log_box = ctk.CTkTextbox(
            self,
            state="disabled",
            font=ctk.CTkFont(family="Courier", size=11),
            fg_color=("gray95", "gray10"),
            height=160
        )
        self.log_box.grid(row=2, column=0, sticky="nsew", padx=20, pady=(0, 12))

        # --- przyciski ---
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.grid(row=3, column=0, padx=20, pady=(0, 20), sticky="ew")
        btn_frame.grid_columnconfigure(0, weight=1)

        self.lbl_status = ctk.CTkLabel(
            btn_frame, text="Trwa skanowanie...",
            font=ctk.CTkFont(size=11), text_color="gray"
        )
        self.lbl_status.grid(row=0, column=0, sticky="w")

        self.btn_cancel = ctk.CTkButton(
            btn_frame,
            text="Anuluj",
            width=100, height=32,
            fg_color="#c0392b",
            hover_color="#a93226",
            command=self._do_cancel,
        )
        self.btn_cancel.grid(row=0, column=1, sticky="e")

    # ================================================================ publiczne API

    def update_progress(self, current: int, total: int, current_file: str):
        """Wywolywane z watku skanowania przez after()."""
        if self._finished:
            return

        pct = current / total if total else 0
        self.progress.set(pct)
        self.lbl_counter.configure(text=f"{current} / {total}  ({pct*100:.0f}%)")
        self.lbl_title.configure(text="Skanowanie folderu...")

        # dodaj do logu (max 200 linii)
        self.log_box.configure(state="normal")
        self.log_box.insert("end", f"{current_file}\n")
        # przytnij jesli za dlugi
        lines = int(self.log_box.index("end-1c").split(".")[0])
        if lines > 200:
            self.log_box.delete("1.0", "50.0")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def log_error(self, path: str, msg: str):
        """Wyswietla blad w logu."""
        self.log_box.configure(state="normal")
        self.log_box.insert("end", f"  BLAD: {path} — {msg}\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def set_phase(self, text: str):
        """Zmienia naglowek fazy — np. 'Szukam duplikatow...'"""
        self.lbl_title.configure(text=text)
        self.lbl_status.configure(text=text)

    def finish(self, total: int, errors: int = 0):
        """Wywolaj po zakonczeniu skanowania."""
        self._finished = True
        self.progress.set(1.0)
        self.lbl_counter.configure(text=f"{total} plikow przeskanowanych")
        self.lbl_title.configure(text="Skanowanie zakonczone")
        status = f"Gotowe. Bledow: {errors}" if errors else "Gotowe."
        self.lbl_status.configure(text=status, text_color="green")
        self.btn_cancel.configure(text="Zamknij", fg_color="gray40", hover_color="gray30",
                                  command=self.destroy)

    # ================================================================ wewnetrzne

    def _do_cancel(self):
        if self._finished:
            self.destroy()
            return
        self._cancelled = True
        self.lbl_status.configure(text="Anulowanie...", text_color="orange")
        self.btn_cancel.configure(state="disabled")
        if self._on_cancel:
            self._on_cancel()

    def _on_close_btn(self):
        """X na oknie — jesli trwa skanowanie, anuluj."""
        if not self._finished:
            self._do_cancel()
        else:
            self.destroy()