"""
image_viewer.py — porównywarka zdjęć.

Pokazuje dwa zdjęcia obok siebie (układ poziomy) lub jedno pod drugim (pionowy).
Każde zdjęcie jest dopasowane do swojego panelu (fit).
Scroll myszy + przeciąganie działa niezależnie na każdym panelu.
Strzałki lewo/prawo przełączają które zdjęcie z grupy jest po prawej stronie.
"""

import os
import threading
import customtkinter as ctk
from tkinter import Canvas
from PIL import Image, ImageTk


class _PhotoPanel:
    """Jeden panel z jednym zdjęciem — canvas + zoom + drag."""

    ZOOM_STEP = 1.25
    MIN_ZOOM  = 0.02
    MAX_ZOOM  = 16.0

    def __init__(self, parent, bg="#1a1a1a"):
        self.canvas = Canvas(parent, bg=bg, highlightthickness=0, cursor="fleur")
        self._img_orig = None
        self._img_tk   = None
        self._zoom     = 1.0
        self._offset_x = 0
        self._offset_y = 0
        self._drag_x   = 0
        self._drag_y   = 0
        self._path     = ""
        self._render_job = None

        self.canvas.bind("<MouseWheel>", self._on_wheel)
        self.canvas.bind("<Button-4>",   lambda e: self._zoom_by(self.ZOOM_STEP))
        self.canvas.bind("<Button-5>",   lambda e: self._zoom_by(1 / self.ZOOM_STEP))
        self.canvas.bind("<ButtonPress-1>",  self._drag_start)
        self.canvas.bind("<B1-Motion>",      self._drag_move)
        self.canvas.bind("<Configure>",      lambda e: self._render())

    # ---- ladowanie ----

    def load(self, path: str):
        self._path = path
        self.canvas.delete("all")
        self.canvas.create_text(
            self.canvas.winfo_width() // 2 or 200,
            self.canvas.winfo_height() // 2 or 200,
            text="ładowanie…", fill="#666666", font=("Segoe UI", 12)
        )
        threading.Thread(target=self._load_thread, args=(path,), daemon=True).start()

    def _load_thread(self, path: str):
        try:
            img = Image.open(path)
            img = self._auto_rotate(img)
            self.canvas.after(0, lambda: self._set_image(img))
        except Exception as e:
            self.canvas.after(0, lambda: self.canvas.create_text(
                200, 200, text=f"Błąd: {e}", fill="#cc4444", font=("Segoe UI", 11)
            ))

    def _set_image(self, img: Image.Image):
        self._img_orig = img
        self._fit()

    def _auto_rotate(self, img):
        try:
            exif = img._getexif()
            if exif:
                rot = {3: 180, 6: 270, 8: 90}.get(exif.get(274))
                if rot:
                    return img.rotate(rot, expand=True)
        except Exception:
            pass
        return img

    # ---- fit / zoom ----

    def _fit(self):
        """Dopasuj zdjęcie do panelu (wypełnij, zachowaj proporcje)."""
        if self._img_orig is None:
            return
        self.canvas.update_idletasks()
        cw = self.canvas.winfo_width()
        ch = self.canvas.winfo_height()
        if cw < 2 or ch < 2:
            self.canvas.after(80, self._fit)
            return
        ow, oh = self._img_orig.size
        self._zoom    = min(cw / ow, ch / oh)
        self._offset_x = (cw - ow * self._zoom) / 2
        self._offset_y = (ch - oh * self._zoom) / 2
        self._render()

    def _zoom_by(self, factor: float, cx: int = None, cy: int = None):
        if self._img_orig is None:
            return
        new_zoom = max(self.MIN_ZOOM, min(self.MAX_ZOOM, self._zoom * factor))
        if cx is None:
            cx = self.canvas.winfo_width()  // 2
            cy = self.canvas.winfo_height() // 2
        # zachowaj punkt pod kursorem
        self._offset_x = cx - (cx - self._offset_x) * (new_zoom / self._zoom)
        self._offset_y = cy - (cy - self._offset_y) * (new_zoom / self._zoom)
        self._zoom = new_zoom
        self._render()

    # ---- render ----

    def _render(self):
        if self._img_orig is None:
            return
        if self._render_job:
            self.canvas.after_cancel(self._render_job)
        self._render_job = self.canvas.after(16, self._do_render)

    def _do_render(self):
        if self._img_orig is None:
            return
        cw = self.canvas.winfo_width()
        ch = self.canvas.winfo_height()
        if cw < 2 or ch < 2:
            return

        ow, oh  = self._img_orig.size
        new_w   = max(1, int(ow * self._zoom))
        new_h   = max(1, int(oh * self._zoom))

        resample = Image.LANCZOS if self._zoom <= 1.0 else Image.NEAREST
        try:
            resized = self._img_orig.resize((new_w, new_h), resample)
        except Exception:
            return

        self._img_tk = ImageTk.PhotoImage(resized)
        self.canvas.delete("all")
        self.canvas.create_image(
            int(self._offset_x), int(self._offset_y),
            anchor="nw", image=self._img_tk
        )

        # info na dole panelu
        fname = os.path.basename(self._path)
        w, h  = self._img_orig.size
        pct   = int(self._zoom * 100)
        self.canvas.create_text(
            cw // 2, ch - 12,
            text=f"{fname}  •  {w}×{h}  •  {pct}%",
            fill="#888888", font=("Segoe UI", 10),
            anchor="center"
        )

    # ---- drag ----

    def _drag_start(self, event):
        self._drag_x = event.x
        self._drag_y = event.y

    def _drag_move(self, event):
        dx = event.x - self._drag_x
        dy = event.y - self._drag_y
        self._offset_x += dx
        self._offset_y += dy
        self._drag_x = event.x
        self._drag_y = event.y
        self._render()

    def _on_wheel(self, event):
        factor = self.ZOOM_STEP if event.delta > 0 else 1 / self.ZOOM_STEP
        self._zoom_by(factor, event.x, event.y)

    # ---- info ----

    @property
    def info(self) -> str:
        if self._img_orig:
            w, h = self._img_orig.size
            return f"{os.path.basename(self._path)}  {w}×{h}"
        return ""


# ======================================================================

class ImageViewer(ctk.CTkToplevel):
    """
    Porównywarka: lewy panel = plik do zachowania (best),
    prawy panel = aktualny duplikat.
    Strzałki przełączają który duplikat jest po prawej.
    """

    def __init__(self, parent, paths: list[str], start_index: int = 0, **kwargs):
        super().__init__(parent, **kwargs)

        self._paths = paths          # [best, dup1, dup2, ...]
        self._right_index = max(1, start_index)  # prawy panel — domyślnie pierwszy duplikat

        self.title("Porównanie zdjęć")
        self.geometry("1400x700")
        self.minsize(700, 400)

        self._build_ui()
        self._load_both()
        self._force_focus()

        self.bind("<Escape>",  lambda e: self.destroy())
        self.bind("<Left>",    lambda e: self._navigate(-1))
        self.bind("<Right>",   lambda e: self._navigate(1))
        self.bind("<Key-f>",   lambda e: self._fit_both())
        self.bind("<Key-1>",   lambda e: self._zoom_both(1.0))

    # ================================================================ UI

    def _build_ui(self):
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)

        BG = "#1a1a1a"

        # lewy panel
        left_wrap = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        left_wrap.grid(row=0, column=0, sticky="nsew", padx=(0, 1))
        left_wrap.grid_rowconfigure(1, weight=1)
        left_wrap.grid_columnconfigure(0, weight=1)

        self.lbl_left = ctk.CTkLabel(
            left_wrap,
            text="✓ zachowaj",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#2ecc71",
            fg_color=BG,
            height=28,
        )
        self.lbl_left.grid(row=0, column=0, sticky="ew", padx=8, pady=(6, 0))

        self._panel_left = _PhotoPanel(left_wrap, bg=BG)
        self._panel_left.canvas.grid(row=1, column=0, sticky="nsew")

        # prawy panel
        right_wrap = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        right_wrap.grid(row=0, column=1, sticky="nsew", padx=(1, 0))
        right_wrap.grid_rowconfigure(1, weight=1)
        right_wrap.grid_columnconfigure(0, weight=1)

        self.lbl_right = ctk.CTkLabel(
            right_wrap,
            text="duplikat",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#e74c3c",
            fg_color=BG,
            height=28,
        )
        self.lbl_right.grid(row=0, column=0, sticky="ew", padx=8, pady=(6, 0))

        self._panel_right = _PhotoPanel(right_wrap, bg=BG)
        self._panel_right.canvas.grid(row=1, column=0, sticky="nsew")

        # dolny pasek nawigacji
        nav = ctk.CTkFrame(self, height=44, fg_color=("gray15", "gray10"), corner_radius=0)
        nav.grid(row=1, column=0, columnspan=2, sticky="ew")
        nav.grid_propagate(False)
        nav.grid_columnconfigure(2, weight=1)

        self.btn_prev = ctk.CTkButton(
            nav, text="← poprzedni duplikat", width=160, height=30,
            fg_color="transparent", border_width=1,
            text_color=("gray80", "gray80"),
            command=lambda: self._navigate(-1)
        )
        self.btn_prev.grid(row=0, column=0, padx=8, pady=6)

        self.btn_next = ctk.CTkButton(
            nav, text="następny duplikat →", width=160, height=30,
            fg_color="transparent", border_width=1,
            text_color=("gray80", "gray80"),
            command=lambda: self._navigate(1)
        )
        self.btn_next.grid(row=0, column=1, padx=(0, 8), pady=6)

        self.lbl_nav = ctk.CTkLabel(
            nav, text="",
            font=ctk.CTkFont(size=11), text_color="gray"
        )
        self.lbl_nav.grid(row=0, column=2, sticky="w", padx=8)

        # przyciski zoom
        for col, (txt, cmd) in enumerate([
            ("fit",  self._fit_both),
            ("1:1",  lambda: self._zoom_both(1.0)),
            ("2×",   lambda: self._zoom_both(2.0)),
        ], start=3):
            ctk.CTkButton(
                nav, text=txt, width=44, height=30,
                fg_color="transparent", border_width=1,
                text_color=("gray80","gray80"),
                command=cmd
            ).grid(row=0, column=col, padx=2, pady=6)

        ctk.CTkButton(
            nav, text="zamknij", width=80, height=30,
            fg_color="transparent", border_width=1,
            text_color=("gray80","gray80"),
            command=self.destroy
        ).grid(row=0, column=6, padx=(2, 8), pady=6)

    # ================================================================ ladowanie

    def _load_both(self):
        # lewy = zawsze paths[0] (best)
        if self._paths:
            self._panel_left.load(self._paths[0])

        # prawy = aktualny duplikat
        if self._right_index < len(self._paths):
            self._panel_right.load(self._paths[self._right_index])

        self._update_nav()

    def _update_nav(self):
        total_dups = len(self._paths) - 1
        self.lbl_nav.configure(
            text=f"duplikat {self._right_index} z {total_dups}  •  "
                 f"← / → aby przełączać  •  f = fit  •  1 = 1:1  •  Esc = zamknij"
        )
        self.btn_prev.configure(state="normal" if self._right_index > 1 else "disabled")
        self.btn_next.configure(state="normal" if self._right_index < len(self._paths) - 1 else "disabled")

        if self._right_index < len(self._paths):
            fname = os.path.basename(self._paths[self._right_index])
            self.lbl_right.configure(text=f"✗ duplikat — {fname}")

    # ================================================================ nawigacja i zoom

    def _navigate(self, delta: int):
        new_idx = self._right_index + delta
        if 1 <= new_idx < len(self._paths):
            self._right_index = new_idx
            self._panel_right.load(self._paths[self._right_index])
            self._update_nav()

    def _fit_both(self):
        self._panel_left._fit()
        self._panel_right._fit()

    def _zoom_both(self, zoom: float):
        for panel in (self._panel_left, self._panel_right):
            if panel._img_orig:
                panel._zoom = zoom
                panel._offset_x = 0
                panel._offset_y = 0
                panel._render()

    # ================================================================ focus

    def _force_focus(self):
        self.after(50, lambda: (
            self.attributes("-topmost", True),
            self.after(200, lambda: self.attributes("-topmost", False)),
            self.lift(),
            self.focus_force()
        ))