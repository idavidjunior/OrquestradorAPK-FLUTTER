#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Flutter Build Orchestrator — Interface Gr\u00e1fica (entry point resiliente)

Caracter\u00edsticas:
  - Auto-instala customtkinter via pip se ausente
  - Fallback para CLI se a GUI n\u00e3o puder abrir
  - Verifica\u00e7\u00e3o de display dispon\u00edvel
  - Mensagens de erro claras e acion\u00e1veis
"""

import sys
import os
import subprocess
import importlib


# ---------------------------------------------------------------------------
#  Helpers
# ---------------------------------------------------------------------------

def _has_display():
    if os.name == "posix" and not os.environ.get("DISPLAY"):
        return False
    try:
        import tkinter as _tk
        r = _tk.Tk(); r.withdraw(); r.destroy()
        return True
    except Exception:
        return False


def _ensure_module(module_name: str, pip_name: str = None) -> bool:
    """
    Tenta importar um m\u00f3dulo. Se falhar, tenta instal\u00e1-lo via pip.
    Retorna True se o m\u00f3dulo estiver dispon\u00edvel ao final.
    """
    pip_name = pip_name or module_name
    try:
        importlib.import_module(module_name)
        return True
    except ImportError:
        print(f"[GUI] M\u00f3dulo '{module_name}' n\u00e3o encontrado. "
              f"Tentando instalar...")
        try:
            subprocess.run(
                [sys.executable, "-m", "pip", "install", pip_name,
                 "--quiet", "--no-warn-script-location"],
                check=True, timeout=120,
            )
            importlib.import_module(module_name)
            print(f"[GUI] '{module_name}' instalado com sucesso.")
            return True
        except Exception as e:
            print(f"[GUI] N\u00e3o foi poss\u00edvel instalar '{module_name}': {e}")
            print(f"       Comando manual: pip install {pip_name}")
            return False


# ---------------------------------------------------------------------------
#  Main
# ---------------------------------------------------------------------------

def main():
    # 1. Verifica display
    if not _has_display():
        print("GUI indispon\u00edvel (sem display gr\u00e1fico).")
        print("Use 'python flutter_orchestrator.py <caminho_do_projeto>' no terminal.")
        sys.exit(1)

    # 2. Garante customtkinter
    if not _ensure_module("customtkinter", "customtkinter>=5.2.0"):
        print()
        print("ERRO: customtkinter \u00e9 necess\u00e1rio para a interface gr\u00e1fica.")
        print("Instale com: pip install customtkinter")
        print()
        print("Alternativa: use o modo CLI:")
        print("  python flutter_orchestrator.py <caminho_do_projeto>")
        sys.exit(1)

    # 3. Garante PIL (tkinter pillow, depend\u00eancia do customtkinter)
    _ensure_module("PIL", "pillow")

    # 4. Inicializa GUI
    try:
        from gui.app import run as run_gui
        run_gui()
    except Exception as e:
        print(f"ERRO ao iniciar GUI: {e}")
        print()
        print("Tente usar o modo CLI:")
        print("  python flutter_orchestrator.py <caminho_do_projeto>")
        sys.exit(1)


if __name__ == "__main__":
    main()
