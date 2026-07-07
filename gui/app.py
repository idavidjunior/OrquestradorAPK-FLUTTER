#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Flutter Build Orchestrator — Interface Gr\u00e1fica (main application)
"""

import os
import subprocess
import threading
from datetime import datetime
from pathlib import Path

import customtkinter as ctk
import tkinter as tk
from tkinter import filedialog, messagebox

from gui.logger import Logger
from gui.checklist import Checklist
from gui.knowledge_base import KnowledgeBase
from gui.gemini_fixer import GeminiCodeFixer
from gui.project_source import ProjectSourceManager


class BuildOrchestratorGUI(ctk.CTk):
    """Main GUI window for the Flutter Build Orchestrator."""

    def __init__(self):
        super().__init__()
        self.title("Flutter Build Orchestrator")
        self.geometry("1100x750")
        self.minsize(900, 600)

        # State
        self.project_dir = None
        self.log = None
        self.kb = None
        self.gemini = None
        self.build_running = False

        self._build_ui()

    def _build_ui(self):
        # Grid layout
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=2)

        # Top bar
        top = ctk.CTkFrame(self)
        top.grid(row=0, column=0, columnspan=2, sticky="ew", padx=5, pady=5)
        top.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(top, text="Flutter Build Orchestrator",
                     font=ctk.CTkFont(size=18, weight="bold")).pack(
            side="left", padx=10, pady=5
        )

        self.btn_tema = ctk.CTkButton(
            top, text="\u263D Tema", width=80,
            command=self._toggle_theme
        )
        self.btn_tema.pack(side="right", padx=5)

        # Left panel
        left = ctk.CTkFrame(self)
        left.grid(row=1, column=0, sticky="nsew", padx=(5, 2), pady=5)
        left.grid_rowconfigure(4, weight=1)

        # Project source
        ctk.CTkLabel(left, text="Fonte do Projeto",
                     font=ctk.CTkFont(size=14, weight="bold")).grid(
            row=0, column=0, pady=(5, 5)
        )

        self.btn_pasta = ctk.CTkButton(
            left, text="Selecionar Pasta Local",
            command=self._select_folder
        )
        self.btn_pasta.grid(row=1, column=0, padx=10, pady=2, sticky="ew")

        self.btn_github = ctk.CTkButton(
            left, text="Clonar Reposit\u00f3rio GitHub",
            command=self._clone_github
        )
        self.btn_github.grid(row=2, column=0, padx=10, pady=2, sticky="ew")

        # Gemini API Key
        ctk.CTkLabel(left, text="Chave Gemini (opcional)",
                     font=ctk.CTkFont(size=12)).grid(
            row=3, column=0, padx=10, pady=(10, 2), sticky="w"
        )
        self.gemini_entry = ctk.CTkEntry(
            left, placeholder_text="API Key..."
        )
        self.gemini_entry.grid(row=3, column=0, padx=10, pady=(22, 0), sticky="ew")

        self.btn_gemini = ctk.CTkButton(
            left, text="Validar Chave", command=self._validate_gemini_key, width=100
        )
        self.btn_gemini.grid(row=3, column=0, padx=10, pady=(44, 0), sticky="w")

        # Build buttons
        ctk.CTkLabel(left, text="A\u00e7\u00f5es",
                     font=ctk.CTkFont(size=14, weight="bold")).grid(
            row=4, column=0, pady=(10, 5)
        )

        btn_frame = ctk.CTkFrame(left, fg_color="transparent")
        btn_frame.grid(row=5, column=0, padx=10, pady=2, sticky="ew")

        self.btn_build = ctk.CTkButton(
            btn_frame, text="Iniciar Build",
            fg_color="#2E7D32", hover_color="#1B5E20",
            command=self._start_build
        )
        self.btn_build.pack(fill="x", pady=2)

        self.btn_stop = ctk.CTkButton(
            btn_frame, text="Parar", state="disabled",
            fg_color="#C62828", hover_color="#B71C1C",
            command=self._stop_build
        )
        self.btn_stop.pack(fill="x", pady=2)

        self.check_release = ctk.CTkCheckBox(
            btn_frame, text="Modo Release", checked=True
        )
        self.check_release.pack(fill="x", pady=2)

        self.check_skip_tests = ctk.CTkCheckBox(
            btn_frame, text="Pular Testes"
        )
        self.check_skip_tests.pack(fill="x", pady=2)

        self.check_auto_install = ctk.CTkCheckBox(
            btn_frame, text="Auto-instalar Flutter"
        )
        self.check_auto_install.pack(fill="x", pady=2)

        # Right panel (log)
        right = ctk.CTkFrame(self)
        right.grid(row=1, column=1, sticky="nsew", padx=(2, 5), pady=5)
        right.grid_rowconfigure(1, weight=1)
        right.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(right, text="Log de Build",
                     font=ctk.CTkFont(size=14, weight="bold")).grid(
            row=0, column=0, pady=(5, 5)
        )

        self.log_text = ctk.CTkTextbox(right, state="disabled", wrap="word")
        self.log_text.grid(row=1, column=0, sticky="nsew", padx=5, pady=5)

        self.log = Logger(self.log_text)
        self.kb = KnowledgeBase(self.log)

    def _toggle_theme(self):
        current = ctk.get_appearance_mode()
        ctk.set_appearance_mode("Light" if current == "Dark" else "Dark")

    def _select_folder(self):
        folder = filedialog.askdirectory(title="Selecione a pasta do projeto Flutter")
        if folder:
            self.project_dir = Path(folder).resolve()
            self.log.ok(f"Projeto selecionado: {self.project_dir}")

    def _clone_github(self):
        url = tk.simpledialog.askstring(
            "GitHub Clone",
            "URL do reposit\u00f3rio GitHub:",
            parent=self
        )
        if not url:
            return
        threading.Thread(
            target=self._do_clone, args=(url,), daemon=True
        ).start()

    def _do_clone(self, url):
        self._set_build_state(True)
        self.log.info(f"Clonando {url}...")
        try:
            dest = Path.home() / "Downloads" / url.rstrip("/").split("/")[-1].replace(".git", "")
            result = subprocess.run(
                ["git", "clone", url, str(dest)],
                capture_output=True, text=True, timeout=120
            )
            if result.returncode == 0:
                self.project_dir = dest
                self.log.ok(f"Clonado com sucesso: {dest}")
            else:
                self.log.err(f"Falha ao clonar: {result.stderr}")
        except Exception as e:
            self.log.err(f"Erro: {e}")
        finally:
            self._set_build_state(False)

    def _validate_gemini_key(self):
        key = self.gemini_entry.get().strip()
        if not key:
            messagebox.showwarning("Aviso", "Digite uma chave API primeiro")
            return
        valid, msg = GeminiCodeFixer.validate_key(key)
        if valid:
            self.gemini = GeminiCodeFixer(key, self.log)
            messagebox.showinfo("Sucesso", msg)
            self.log.ok(f"Gemini: {msg}")
        else:
            messagebox.showerror("Erro", msg)
            self.log.err(f"Gemini: {msg}")

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
            checklist = Checklist(self.log)
            if not checklist.run():
                self.log.err("Build cancelado por falha nos pr\u00e9-requisitos")
                return

            release = self.check_release.get()
            skip_tests = self.check_skip_tests.get()
            auto_install = self.check_auto_install.get()

            self.log.info(f"Iniciando build em: {self.project_dir}")
            self.log.info(f"Modo: {'Release' if release else 'Debug'}")
            self._run_build_pipeline(release, skip_tests, auto_install)
        except Exception as e:
            self.log.err(f"Erro inesperado: {e}")
        finally:
            self._set_build_state(False)

    def _run_build_pipeline(self, release, skip_tests, auto_install):
        steps = [
            ("Valida\u00e7\u00e3o do Projeto", self._step_validate_project),
            ("Depend\u00eancias", self._step_get_deps),
            ("An\u00e1lise de C\u00f3digo", self._step_analyze),
            ("Testes", lambda: self._step_tests(skip_tests)),
            ("Compila\u00e7\u00e3o APK", lambda: self._step_build(release)),
        ]

        for name, func in steps:
            if self._build_cancelled:
                self.log.warn("Build cancelado pelo usu\u00e1rio")
                return
            self.log.sep()
            self.log.info(f">>> {name}")
            if not func():
                self.log.err(f"Falhou em: {name}")
                return

        self.log.sep()
        self.log.ok("BUILD CONCLU\u00cdDO COM SUCESSO!")

    def _step_validate_project(self):
        pubspec = self.project_dir / "pubspec.yaml"
        if not pubspec.exists():
            self.log.err("pubspec.yaml n\u00e3o encontrado")
            return False
        ProjectSourceManager.validate_and_fix_pubspec(self.project_dir, self.log)
        return True

    def _step_get_deps(self):
        try:
            result = subprocess.run(
                ["flutter", "pub", "get"],
                cwd=self.project_dir, capture_output=True, text=True, timeout=300
            )
            if result.returncode == 0:
                self.log.ok("Depend\u00eancias instaladas")
                return True
            self.log.err(f"flutter pub get falhou: {result.stderr[:500]}")
            return False
        except Exception as e:
            self.log.err(f"Erro: {e}")
            return False

    def _step_analyze(self):
        try:
            result = subprocess.run(
                ["flutter", "analyze"],
                cwd=self.project_dir, capture_output=True, text=True, timeout=300
            )
            if result.returncode == 0:
                self.log.ok("An\u00e1lise conclu\u00edda sem erros")
            else:
                self.log.warn("An\u00e1lise encontrou problemas (continuando...)")
                self.log.info(result.stdout[:500])
            return True
        except Exception as e:
            self.log.err(f"Erro: {e}")
            return False

    def _step_tests(self, skip):
        if skip:
            self.log.info("Testes pulados")
            return True
        test_dir = self.project_dir / "test"
        if not test_dir.exists():
            self.log.info("Nenhum teste encontrado")
            return True
        try:
            result = subprocess.run(
                ["flutter", "test"],
                cwd=self.project_dir, capture_output=True, text=True, timeout=600
            )
            if result.returncode == 0:
                self.log.ok("Testes passaram")
                return True
            self.log.err(f"Testes falharam: {result.stdout[:300]}")
            return False
        except Exception as e:
            self.log.err(f"Erro: {e}")
            return False

    def _step_build(self, release):
        try:
            mode = "--release" if release else "--debug"
            process = subprocess.Popen(
                ["flutter", "build", "apk", mode],
                cwd=self.project_dir,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True
            )
            for line in process.stdout:
                if line.strip():
                    self.log.info(line.strip()[:200])
            process.wait()
            if process.returncode == 0:
                self.log.ok("APK compilado com sucesso")
                return True
            self.log.err("Falha na compila\u00e7\u00e3o do APK")
            return False
        except Exception as e:
            self.log.err(f"Erro: {e}")
            return False

    def _stop_build(self):
        self._build_cancelled = True
        self.log.warn("Cancelando build...")

    def _set_build_state(self, running):
        self.build_running = running
        self._build_cancelled = False
        state = "disabled" if running else "normal"
        self.btn_build.configure(state=state)
        self.btn_pasta.configure(state=state)
        self.btn_github.configure(state=state)
        self.btn_stop.configure(state="normal" if running else "disabled")

    def run(self):
        self.log.ok("Flutter Build Orchestrator iniciado")
        self.log.info("Selecione uma pasta de projeto ou clone do GitHub para come\u00e7ar")
        self.kb.stats()
        self.mainloop()


def run():
    app = BuildOrchestratorGUI()
    app.run()


if __name__ == "__main__":
    run()
