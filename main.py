import customtkinter as ctk
from gui.app import App

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

if __name__ == "__main__":
    app = App()
    app.mainloop()