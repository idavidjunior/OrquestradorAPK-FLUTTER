#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Flutter Build Orchestrator — Interface Gr\u00e1fica (main application)
Todo o c\u00f3digo dependente de customtkinter fica dentro de run() para
permitir importa\u00e7\u00e3o segura do m\u00f3dulo mesmo sem a depend\u00eancia instalada.
"""

import os
import subprocess
import threading
from datetime import datetime
from pathlib import Path

from gui.logger import Logger
from gui.checklist import Checklist
from gui.knowledge_base import KnowledgeBase
from gui.gemini_fixer import GeminiCodeFixer
from gui.project_source import ProjectSourceManager


def run():
    """
    Inicializa e executa a GUI.
    Importa customtkinter apenas aqui (lazy) para evitar falha em importa\u00e7\u00e3o
    no n\u00edvel do m\u00f3dulo quando a depend\u00eancia n\u00e3o est\u00e1 instalada.
    """
    import customtkinter as ctk
    import tkinter as tk
    from tkinter import filedialog, messagebox

    ctk.set_appearance_mode("System")
    ctk.set_default_color_theme("blue")

    # --- Logger que escreve em CTkTextbox ---------------------------------
    class CtkLogger(Logger):
        """Logger adaptado para CTkTextbox (usa .after em vez de timer raw)."""

        def _drain(self):
            try:
                count = 0
                while count < 30:
                    level, msg = self._q.get_nowait()
                    ts = datetime.now().strftime("%H:%M:%S")
                    icon = self.ICONS.get(level, "\u2022")
                    line = (
                        f"[{ts}] {icon}  {msg}\n"
                        if level != "sep"
                        else f"\u2500" * 60 + "\n"
                    )
                    self._box.configure(state="normal")
                    self._box.insert("end", line)
                    self._box.see("end")
                    self._box.configure(state="disabled")
                    count += 1
            except Exception:
                pass
            self._box.after(40, self._drain)

    # --- Build pipeline (reuso do CLI) ------------------------------------
    class BuildPipeline:
        """
        Encapsula a l\u00f3gica de build para ser usada tanto pela GUI quanto
        por outros front-ends futuros.
        """

        def __init__(self, project_dir, log, kb=None):
            self.project_dir = Path(project_dir).resolve()
            self.log = log
            self.kb = kb
            self._cancelled = False

        def cancel(self):
            self._cancelled = True

        def run(self, release=True, skip_tests=False):
            steps = [
                ("Pr\u00e9-requisitos", self._step_checklist),
                ("Valida\u00e7\u00e3o", self._step_validate),
                ("Depend\u00eancias", self._step_get_deps),
                ("An\u00e1lise", self._step_analyze),
                ("Testes", lambda: self._step_tests(skip_tests)),
                ("Compila\u00e7\u00e3o APK", lambda: self._step_build(release)),
            ]
            for name, fn in steps:
                if self._cancelled:
                    self.log.warn("Build cancelado")
                    return False
                self.log.sep()
                self.log.info(f">>> {name}")
                if not fn():
                    self.log.err(f"Falhou em: {name}")
                    return False
            self.log.sep()
            self.log.ok("BUILD CONCLU\u00cdDO COM SUCESSO!")
            return True

        def _step_checklist(self):
            c = Checklist(self.log)
            return c.run()

        def _step_validate(self):
            pubspec = self.project_dir / "pubspec.yaml"
            if not pubspec.exists():
                self.log.err("pubspec.yaml n\u00e3o encontrado")
                return False
            ProjectSourceManager.validate_and_fix_pubspec(self.project_dir, self.log)
            return True

        def _step_get_deps(self):
            try:
                r = subprocess.run(
                    ["flutter", "pub", "get"],
                    cwd=self.project_dir,
                    capture_output=True,
                    text=True,
                    timeout=300,
                )
                if r.returncode == 0:
                    self.log.ok("Depend\u00eancias instaladas")
                    return True
                self.log.err(f"flutter pub get falhou: {r.stderr[:500]}")
                return False
            except Exception as e:
                self.log.err(f"Erro: {e}")
                return False

        def _step_analyze(self):
            try:
                r = subprocess.run(
                    ["flutter", "analyze"],
                    cwd=self.project_dir,
                    capture_output=True,
                    text=True,
                    timeout=300,
                )
                if r.returncode == 0:
                    self.log.ok("An\u00e1lise sem erros")
                else:
                    self.log.warn("An\u00e1lise com problemas (continuando)")
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
                self.log.info("Nenhum teste")
                return True
            try:
                r = subprocess.run(
                    ["flutter", "test"],
                    cwd=self.project_dir,
                    capture_output=True,
                    text=True,
                    timeout=600,
                )
                if r.returncode == 0:
                    self.log.ok("Testes OK")
                    return True
                self.log.err(f"Testes falharam: {r.stdout[:300]}")
                return False
            except Exception as e:
                self.log.err(f"Erro: {e}")
                return False

        def _step_build(self, release):
            try:
                mode = "--release" if release else "--debug"
                proc = subprocess.Popen(
                    ["flutter", "build", "apk", mode],
                    cwd=self.project_dir,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                )
                for line in proc.stdout:
                    if line.strip():
                        self.log.info(line.strip()[:200])
                proc.wait()
                if proc.returncode == 0:
                    self.log.ok("APK compilado")
                    return True
                self.log.err("Falha na compila\u00e7\u00e3o")
                return False
            except Exception as e:
                self.log.err(f"Erro: {e}")
                return False

    # --- GUI principal ----------------------------------------------------
    class BuildOrchestratorGUI(ctk.CTk):
        """Janela principal do Flutter Build Orchestrator."""

        def __init__(self):
            super().__init__()
            self.title("Flutter Build Orchestrator")
            self.geometry("1100x750")
            self.minsize(900, 600)

            self.project_dir = None
            self.pipeline = None
            self.build_running = False
            self._build_cancelled = False

            self._build_ui()

        # ---------- UI construction ----------

        def _build_ui(self):
            self.grid_rowconfigure(1, weight=1)
            self.grid_columnconfigure(0, weight=1)
            self.grid_columnconfigure(1, weight=2)

            # Top bar
            top = ctk.CTkFrame(self)
            top.grid(row=0, column=0, columnspan=2, sticky="ew", padx=5, pady=5)
            top.grid_columnconfigure(0, weight=1)

            ctk.CTkLabel(
                top,
                text="Flutter Build Orchestrator",
                font=ctk.CTkFont(size=18, weight="bold"),
            ).pack(side="left", padx=10, pady=5)

            self.btn_tema = ctk.CTkButton(
                top, text="Tema", width=80, command=self._toggle_theme
            )
            self.btn_tema.pack(side="right", padx=5)

            # Left panel
            left = ctk.CTkFrame(self)
            left.grid(row=1, column=0, sticky="nsew", padx=(5, 2), pady=5)
            left.grid_rowconfigure(4, weight=1)

            ctk.CTkLabel(
                left,
                text="Fonte do Projeto",
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

            # Gemini API
            ctk.CTkLabel(left, text="Chave Gemini (opcional)").grid(
                row=3, column=0, padx=10, pady=(10, 2), sticky="w"
            )
            self.gemini_entry = ctk.CTkEntry(left, placeholder_text="API Key...")
            self.gemini_entry.grid(
                row=3, column=0, padx=10, pady=(22, 0), sticky="ew"
            )
            self.btn_gemini = ctk.CTkButton(
                left,
                text="Validar Chave",
                command=self._validate_gemini_key,
                width=100,
            )
            self.btn_gemini.grid(row=3, column=0, padx=10, pady=(44, 0), sticky="w")

            # Actions
            ctk.CTkLabel(
                left, text="A\u00e7\u00f5es", font=ctk.CTkFont(size=14, weight="bold")
            ).grid(row=4, column=0, pady=(10, 5))

            btn_frame = ctk.CTkFrame(left, fg_color="transparent")
            btn_frame.grid(row=5, column=0, padx=10, pady=2, sticky="ew")

            self.btn_build = ctk.CTkButton(
                btn_frame,
                text="Iniciar Build",
                fg_color="#2E7D32",
                hover_color="#1B5E20",
                command=self._start_build,
            )
            self.btn_build.pack(fill="x", pady=2)

            self.btn_stop = ctk.CTkButton(
                btn_frame,
                text="Parar",
                state="disabled",
                fg_color="#C62828",
                hover_color="#B71C1C",
                command=self._stop_build,
            )
            self.btn_stop.pack(fill="x", pady=2)

            self.check_release = ctk.CTkCheckBox(
                btn_frame, text="Modo Release", checked=True
            )
            self.check_release.pack(fill="x", pady=2)

            self.check_skip_tests = ctk.CTkCheckBox(btn_frame, text="Pular Testes")
            self.check_skip_tests.pack(fill="x", pady=2)

            self.check_auto_install = ctk.CTkCheckBox(
                btn_frame, text="Auto-instalar Flutter"
            )
            self.check_auto_install.pack(fill="x", pady=2)

            # Right panel — log
            right = ctk.CTkFrame(self)
            right.grid(row=1, column=1, sticky="nsew", padx=(2, 5), pady=5)
            right.grid_rowconfigure(1, weight=1)
            right.grid_columnconfigure(0, weight=1)

            ctk.CTkLabel(
                right, text="Log de Build", font=ctk.CTkFont(size=14, weight="bold")
            ).grid(row=0, column=0, pady=(5, 5))

            self.log_text = ctk.CTkTextbox(right, state="disabled", wrap="word")
            self.log_text.grid(row=1, column=0, sticky="nsew", padx=5, pady=5)

            self._log = CtkLogger(self.log_text)
            self.kb = KnowledgeBase(self._log)

            self._log.ok("GUI pronta — selecione um projeto para come\u00e7ar")

        # ---------- Event handlers ----------

        def _toggle_theme(self):
            atual = ctk.get_appearance_mode()
            ctk.set_appearance_mode("Light" if atual == "Dark" else "Dark")

        def _select_folder(self):
            pasta = filedialog.askdirectory(
                title="Selecione a pasta do projeto Flutter"
            )
            if pasta:
                self.project_dir = Path(pasta).resolve()
                self._log.ok(f"Projeto: {self.project_dir}")

        def _clone_github(self):
            url = tk.simpledialog.askstring(
                "GitHub Clone", "URL do reposit\u00f3rio:", parent=self
            )
            if not url:
                return
            threading.Thread(target=self._do_clone, args=(url,), daemon=True).start()

        def _do_clone(self, url):
            self._set_build_state(True)
            self._log.info(f"Clonando {url}...")
            try:
                nome = url.rstrip("/").split("/")[-1].replace(".git", "")
                dest = Path.home() / "Downloads" / nome
                r = subprocess.run(
                    ["git", "clone", url, str(dest)],
                    capture_output=True, text=True, timeout=120,
                )
                if r.returncode == 0:
                    self.project_dir = dest
                    self._log.ok(f"Clonado: {dest}")
                else:
                    self._log.err(f"Falha: {r.stderr}")
            except Exception as e:
                self._log.err(f"Erro: {e}")
            finally:
                self._set_build_state(False)

        def _validate_gemini_key(self):
            key = self.gemini_entry.get().strip()
            if not key:
                messagebox.showwarning("Aviso", "Digite uma chave primeiro")
                return
            ok, msg = GeminiCodeFixer.validate_key(key)
            if ok:
                self.gemini = GeminiCodeFixer(key, self._log)
                messagebox.showinfo("Sucesso", msg)
                self._log.ok(f"Gemini: {msg}")
            else:
                messagebox.showerror("Erro", msg)

        def _start_build(self):
            if not self.project_dir:
                messagebox.showwarning(
                    "Aviso", "Selecione um projeto ou clone do GitHub primeiro"
                )
                return
            if self.build_running:
                return
            threading.Thread(target=self._run_build, daemon=True).start()

        def _run_build(self):
            self._set_build_state(True)
            try:
                release = self.check_release.get()
                skip = self.check_skip_tests.get()
                self._log.info(
                    f"Build em: {self.project_dir} "
                    f"({'Release' if release else 'Debug'})"
                )
                pipe = BuildPipeline(self.project_dir, self._log, kb=self.kb)
                self.pipeline = pipe
                pipe.run(release=release, skip_tests=skip)
            except Exception as e:
                self._log.err(f"Erro inesperado: {e}")
            finally:
                self._set_build_state(False)

        def _stop_build(self):
            self._build_cancelled = True
            if self.pipeline:
                self.pipeline.cancel()
            self._log.warn("Cancelando build...")

        def _set_build_state(self, running):
            self.build_running = running
            self._build_cancelled = False
            estado = "disabled" if running else "normal"
            self.btn_build.configure(state=estado)
            self.btn_pasta.configure(state=estado)
            self.btn_github.configure(state=estado)
            self.btn_stop.configure(
                state="normal" if running else "disabled"
            )

    # --- Bootstrap --------------------------------------------------------
    app = BuildOrchestratorGUI()
    app.mainloop()
