#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Flutter Build Orchestrator — Interface Gr\u00e1fica

Usa FlutterBuildOrchestrator (do CLI) como motor de build, com
log redirecionado para o widget de texto via log_callback.
Toda depend\u00eancia de customtkinter \u00e9 lazy (importada dentro de run()).
"""

import os
import subprocess
import threading
from datetime import datetime
from pathlib import Path

from gui.logger import Logger
from gui.knowledge_base import KnowledgeBase
from flutter_orchestrator import FlutterBuildOrchestrator


def run():
    """
    Inicializa e executa a GUI.
    customtkinter s\u00f3 \u00e9 importado aqui (lazy).
    """
    import customtkinter as ctk
    import tkinter as tk
    from tkinter import filedialog, messagebox

    ctk.set_appearance_mode("System")
    ctk.set_default_color_theme("blue")

    # --- Janela principal ---
    class BuildOrchestratorGUI(ctk.CTk):
        """Janela principal do Flutter Build Orchestrator."""

        def __init__(self):
            super().__init__()
            self.title("Flutter Build Orchestrator")
            self.geometry("1100x750")
            self.minsize(900, 600)

            self.project_dir = None
            self.orch = None
            self.build_running = False

            self._build_ui()
            self.log.ok("GUI pronta \u2014 selecione um projeto para come\u00e7ar")

        # ---------- UI ----------

        def _build_ui(self):
            self.grid_rowconfigure(1, weight=1)
            self.grid_columnconfigure(0, weight=1)
            self.grid_columnconfigure(1, weight=2)

            top = ctk.CTkFrame(self)
            top.grid(row=0, column=0, columnspan=2, sticky="ew", padx=5, pady=5)
            top.grid_columnconfigure(0, weight=1)
            ctk.CTkLabel(
                top, text="Flutter Build Orchestrator",
                font=ctk.CTkFont(size=18, weight="bold"),
            ).pack(side="left", padx=10, pady=5)
            self.btn_tema = ctk.CTkButton(
                top, text="Tema", width=80, command=self._toggle_theme
            )
            self.btn_tema.pack(side="right", padx=5)

            left = ctk.CTkFrame(self)
            left.grid(row=1, column=0, sticky="nsew", padx=(5, 2), pady=5)
            left.grid_rowconfigure(4, weight=1)

            ctk.CTkLabel(
                left, text="Fonte do Projeto",
                font=ctk.CTkFont(size=14, weight="bold"),
            ).grid(row=0, column=0, pady=(5, 5))
            self.btn_pasta = ctk.CTkButton(
                left, text="Selecionar Pasta Local", command=self._select_folder
            )
            self.btn_pasta.grid(row=1, column=0, padx=10, pady=2, sticky="ew")
            self.btn_github = ctk.CTkButton(
                left, text="Clonar Reposit\u00f3rio GitHub", command=self._clone_github
            )
            self.btn_github.grid(row=2, column=0, padx=10, pady=2, sticky="ew")

            ctk.CTkLabel(left, text="Chave Gemini (opcional)").grid(
                row=3, column=0, padx=10, pady=(10, 2), sticky="w"
            )
            self.gemini_entry = ctk.CTkEntry(left, placeholder_text="API Key...")
            self.gemini_entry.grid(row=3, column=0, padx=10, pady=(22, 0), sticky="ew")
            self.btn_gemini = ctk.CTkButton(
                left, text="Validar Chave", command=self._validate_gemini_key, width=100
            )
            self.btn_gemini.grid(row=3, column=0, padx=10, pady=(44, 0), sticky="w")

            ctk.CTkLabel(
                left, text="A\u00e7\u00f5es",
                font=ctk.CTkFont(size=14, weight="bold"),
            ).grid(row=4, column=0, pady=(10, 5))

            btn_frame = ctk.CTkFrame(left, fg_color="transparent")
            btn_frame.grid(row=5, column=0, padx=10, pady=2, sticky="ew")

            self.btn_build = ctk.CTkButton(
                btn_frame, text="Iniciar Build",
                fg_color="#2E7D32", hover_color="#1B5E20",
                command=self._start_build,
            )
            self.btn_build.pack(fill="x", pady=2)
            self.btn_stop = ctk.CTkButton(
                btn_frame, text="Parar", state="disabled",
                fg_color="#C62828", hover_color="#B71C1C",
                command=self._stop_build,
            )
            self.btn_stop.pack(fill="x", pady=2)

            # CTkCheckBox usa onvalue/offvalue, N\u00c3O 'checked'
            self._release_var = ctk.BooleanVar(value=True)
            self.check_release = ctk.CTkCheckBox(
                btn_frame, text="Modo Release",
                variable=self._release_var, onvalue=True, offvalue=False,
            )
            self.check_release.pack(fill="x", pady=2)

            self.check_skip_tests = ctk.CTkCheckBox(
                btn_frame, text="Pular Testes",
            )
            self.check_skip_tests.pack(fill="x", pady=2)

            self.check_auto_install = ctk.CTkCheckBox(
                btn_frame, text="Auto-instalar Flutter",
            )
            self.check_auto_install.pack(fill="x", pady=2)

            right = ctk.CTkFrame(self)
            right.grid(row=1, column=1, sticky="nsew", padx=(2, 5), pady=5)
            right.grid_rowconfigure(1, weight=1)
            right.grid_columnconfigure(0, weight=1)

            ctk.CTkLabel(
                right, text="Log de Build",
                font=ctk.CTkFont(size=14, weight="bold"),
            ).grid(row=0, column=0, pady=(5, 5))

            self.log_text = ctk.CTkTextbox(right, state="disabled", wrap="word")
            self.log_text.grid(row=1, column=0, sticky="nsew", padx=5, pady=5)

            self.log = Logger(self.log_text)
            self.kb = KnowledgeBase(self.log)

        # ---------- Handlers ----------

        def _toggle_theme(self):
            atual = ctk.get_appearance_mode()
            ctk.set_appearance_mode("Light" if atual == "Dark" else "Dark")

        def _select_folder(self):
            pasta = filedialog.askdirectory(title="Selecione a pasta do projeto Flutter")
            if pasta:
                self.project_dir = Path(pasta).resolve()
                self.log.ok(f"Projeto: {self.project_dir}")

        def _clone_github(self):
            url = tk.simpledialog.askstring("GitHub Clone", "URL do reposit\u00f3rio:", parent=self)
            if not url:
                return
            threading.Thread(target=self._do_clone, args=(url,), daemon=True).start()

        def _do_clone(self, url):
            self._set_build_state(True)
            self.log.info(f"Clonando {url}...")
            try:
                nome = url.rstrip("/").split("/")[-1].replace(".git", "")
                dest = Path.home() / "Downloads" / nome
                r = subprocess.run(
                    ["git", "clone", url, str(dest)],
                    capture_output=True, text=True, timeout=120,
                )
                if r.returncode == 0:
                    self.project_dir = dest
                    self.log.ok(f"Clonado: {dest}")
                else:
                    self.log.err(f"Falha: {r.stderr}")
            except Exception as e:
                self.log.err(f"Erro: {e}")
            finally:
                self._set_build_state(False)

        def _validate_gemini_key(self):
            key = self.gemini_entry.get().strip()
            if not key:
                messagebox.showwarning("Aviso", "Digite uma chave primeiro")
                return
            from gui.gemini_fixer import GeminiCodeFixer
            ok, msg = GeminiCodeFixer.validate_key(key)
            if ok:
                messagebox.showinfo("Sucesso", msg)
                self.log.ok(f"Gemini: {msg}")
            else:
                messagebox.showerror("Erro", msg)

        def _start_build(self):
            if not self.project_dir:
                messagebox.showwarning("Aviso", "Selecione um projeto primeiro")
                return
            if self.build_running:
                return
            threading.Thread(target=self._run_build, daemon=True).start()

        def _run_build(self):
            self._set_build_state(True)
            try:
                release = self._release_var.get()
                skip = self.check_skip_tests.get()
                auto_install = self.check_auto_install.get()

                self.log.info(
                    f"Build em: {self.project_dir} "
                    f"({'Release' if release else 'Debug'})"
                )

                # Usa o FlutterBuildOrchestrator do CLI com log redirecionado
                self.orch = FlutterBuildOrchestrator(
                    project_path=str(self.project_dir),
                    auto_install=auto_install,
                    log_callback=self._on_log,
                )
                self.orch.orchestrate(
                    skip_tests=skip,
                    debug=not release,
                )
            except Exception as e:
                self.log.err(f"Erro inesperado: {e}")
            finally:
                self._set_build_state(False)

        def _on_log(self, message: str, level: str):
            """Callback recebido pelo FlutterBuildOrchestrator a cada log."""
            level_map = {
                "INFO": self.log.info,
                "SUCCESS": self.log.ok,
                "WARNING": self.log.warn,
                "ERROR": self.log.err,
                "STEP": self.log.info,
            }
            level_map.get(level, self.log.info)(message)

        def _stop_build(self):
            self.log.warn("Cancelando build...")
            if self.orch:
                self.orch.cancel()

        def _set_build_state(self, running):
            self.build_running = running
            estado = "disabled" if running else "normal"
            self.btn_build.configure(state=estado)
            self.btn_pasta.configure(state=estado)
            self.btn_github.configure(state=estado)
            self.btn_stop.configure(state="normal" if running else "disabled")

    # --- Bootstrap ---
    app = BuildOrchestratorGUI()
    app.mainloop()
