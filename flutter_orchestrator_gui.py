#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Flutter Build Orchestrator — Interface Gr\u00e1fica
Entry point thin wrapper. A implementa\u00e7\u00e3o est\u00e1 no pacote gui/.
"""

import sys
import os


def _has_display():
    if os.name == "posix" and not os.environ.get("DISPLAY"):
        return False
    try:
        import tkinter as _tk
        r = _tk.Tk(); r.withdraw(); r.destroy()
        return True
    except Exception:
        return False


if not _has_display():
    print("GUI indispon\u00edvel. Use flutter_orchestrator.py no terminal.")
    sys.exit(1)


def main():
    import customtkinter as ctk
    ctk.set_appearance_mode("System")
    ctk.set_default_color_theme("blue")

    from gui.app import BuildOrchestratorGUI
    app = BuildOrchestratorGUI()
    app.run()


if __name__ == "__main__":
    main()
