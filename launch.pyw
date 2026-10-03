"""Double-click entry, without a terminal window."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from codex_tps import main

try:
    main(['gui'])
except Exception:
    import traceback
    import tkinter as tk
    from tkinter import messagebox
    root = tk.Tk()
    root.withdraw()
    messagebox.showerror('Codex TPS 启动失败', traceback.format_exc())
    root.destroy()
