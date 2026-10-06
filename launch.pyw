"""Double-click entry, without a terminal window."""
from pathlib import Path
import contextlib
import io
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from codex_tps import main
from window_instance import focus_profiles_window

try:
    arguments = sys.argv[1:] or ['profiles-audit']
    reused = arguments == ['profiles-audit'] and focus_profiles_window(Path(__file__).resolve().parent / 'audits' / 'profiles-state.json')
    if not reused:
        if sys.stdout is None or sys.stderr is None:
            output = io.StringIO()
            with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
                result = main(arguments)
            if result:
                raise RuntimeError(output.getvalue().strip() or '工具启动失败，请从终端运行查看原因。')
        else:
            main(arguments)
except Exception:
    import traceback
    import tkinter as tk
    from tkinter import messagebox
    root = tk.Tk()
    root.withdraw()
    messagebox.showerror('Codex TPS 启动失败', traceback.format_exc())
    root.destroy()
