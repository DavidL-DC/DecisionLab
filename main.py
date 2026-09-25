"""Application entry point for DecisionLab."""

from pathlib import Path
from sqlite3 import Error as DatabaseError
import tkinter as tk
from tkinter import messagebox

from database import DecisionRepository
from services import DecisionService
from ui import DecisionLabApp


def main() -> None:
    """Open one main window with a database beside this entry point."""
    root = tk.Tk()
    root.withdraw()
    try:
        repository = DecisionRepository(Path(__file__).resolve().with_name("decisionlab.db"))
    except (DatabaseError, OSError):
        messagebox.showerror("Start fehlgeschlagen", "Die Datenbank konnte nicht geöffnet werden. Bitte prüfen Sie die Schreibrechte im Projektordner.", parent=root)
        root.destroy()
        return
    DecisionLabApp(root, DecisionService(), repository)
    root.deiconify()
    root.mainloop()


if __name__ == "__main__":
    main()
