#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Flutter Build Orchestrator — Interface Gr\u00e1fica

Features:
  - Selecionar pasta local / Clonar GitHub / Colar c\u00f3digo (detec\u00e7\u00e3o inteligente)
  - Build com FlutterBuildOrchestrator (log redirecionado via log_callback)
  - Detec\u00e7\u00e3o de dispositivo Android via ADB + instala\u00e7\u00e3o autom\u00e1tica
  - Abertura r\u00e1pida da pasta de sa\u00edda do APK compilado

customtkinter \u00e9 lazy (importado apenas dentro de run()).
"""

import os
import re
import subprocess
import threading
import tempfile
from datetime import datetime
from pathlib import Path

from gui.logger import Logger
from gui.knowledge_base import KnowledgeBase
from gui.project_source import ProjectSourceManager
from flutter_orchestrator import FlutterBuildOrchestrator


def run():
    import customtkinter as ctk
    import tkinter as tk
    from tkinter import filedialog, messagebox

    ctk.set_appearance_mode("System")
    ctk.set_default_color_theme("blue")

    class BuildOrchestratorGUI(ctk.CTk):
        """Janela principal do Flutter Build Orchestrator."""

        def __init__(self):
            super().__init__()
            self.title("Flutter Build Orchestrator")
            self.geometry("1150x780")
            self.minsize(950, 650)

            self.project_dir = None
            self.orch = None
            self.build_running = False
            self.adb_available = False
            self.adb_device = ""

            self._build_ui()
            self.log.ok("GUI pronta \u2014 selecione/cole um projeto para come\u00e7ar")

        # ==================================================================
        #  UI
        # ==================================================================

        def _build_ui(self):
            self.grid_rowconfigure(1, weight=1)
            self.grid_columnconfigure(0, weight=1)
            self.grid_columnconfigure(1, weight=2)

            # ── Top bar ────────────────────────────────────────────────
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

            # ── Left panel (scrollable) ────────────────────────────────
            left = ctk.CTkScrollableFrame(self)
            left.grid(row=1, column=0, sticky="nsew", padx=(5, 2), pady=5)
            left.grid_columnconfigure(0, weight=1)

            r = 0

            # -- Fonte do Projeto --
            ctk.CTkLabel(
                left, text="Fonte do Projeto",
                font=ctk.CTkFont(size=14, weight="bold"),
            ).grid(row=r, column=0, pady=(5, 2), sticky="w"); r += 1

            self.btn_pasta = ctk.CTkButton(
                left, text="Selecionar Pasta Local",
                command=self._select_folder,
            )
            self.btn_pasta.grid(row=r, column=0, padx=10, pady=2, sticky="ew"); r += 1

            self.btn_github = ctk.CTkButton(
                left, text="Clonar Reposit\u00f3rio GitHub",
                command=self._clone_github,
            )
            self.btn_github.grid(row=r, column=0, padx=10, pady=2, sticky="ew"); r += 1

            # -- Colar C\u00f3digo --
            paste_lbl = ctk.CTkLabel(
                left, text="Colar C\u00f3digo (Dart / YAML / XML):",
                font=ctk.CTkFont(size=12),
            )
            paste_lbl.grid(row=r, column=0, padx=10, pady=(8, 0), sticky="w"); r += 1

            self.paste_text = ctk.CTkTextbox(left, height=130, wrap="word")
            self.paste_text.grid(row=r, column=0, padx=10, pady=2, sticky="ew"); r += 1

            paste_btn_row = ctk.CTkFrame(left, fg_color="transparent")
            paste_btn_row.grid(row=r, column=0, padx=10, pady=2, sticky="ew"); r += 1
            paste_btn_row.grid_columnconfigure(0, weight=1)
            paste_btn_row.grid_columnconfigure(1, weight=1)

            self.btn_analyze = ctk.CTkButton(
                paste_btn_row, text="Analisar e Usar",
                command=self._process_pasted_code,
            )
            self.btn_analyze.grid(row=0, column=0, padx=(0, 2), sticky="ew")

            self.btn_clear_paste = ctk.CTkButton(
                paste_btn_row, text="Limpar", fg_color="#555",
                command=lambda: self.paste_text.delete("0.0", "end"),
            )
            self.btn_clear_paste.grid(row=0, column=1, padx=(2, 0), sticky="ew")

            # -- Gemini --
            ctk.CTkLabel(left, text="Chave Gemini (opcional)").grid(
                row=r, column=0, padx=10, pady=(10, 2), sticky="w"); r += 1
            self.gemini_entry = ctk.CTkEntry(left, placeholder_text="API Key...")
            self.gemini_entry.grid(row=r, column=0, padx=10, pady=(0, 2), sticky="ew"); r += 1
            self.btn_gemini = ctk.CTkButton(
                left, text="Validar Chave",
                command=self._validate_gemini_key, width=100,
            )
            self.btn_gemini.grid(row=r, column=0, padx=10, pady=(0, 5), sticky="w"); r += 1

            # -- A\u00e7\u00f5es --
            ctk.CTkLabel(
                left, text="A\u00e7\u00f5es",
                font=ctk.CTkFont(size=14, weight="bold"),
            ).grid(row=r, column=0, pady=(8, 2), sticky="w"); r += 1

            btn_frame = ctk.CTkFrame(left, fg_color="transparent")
            btn_frame.grid(row=r, column=0, padx=10, pady=2, sticky="ew"); r += 1

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

            self._release_var = ctk.BooleanVar(value=True)
            self.check_release = ctk.CTkCheckBox(
                btn_frame, text="Modo Release",
                variable=self._release_var, onvalue=True, offvalue=False,
            )
            self.check_release.pack(fill="x", pady=2)
            self.check_skip_tests = ctk.CTkCheckBox(btn_frame, text="Pular Testes")
            self.check_skip_tests.pack(fill="x", pady=2)
            self.check_auto_install = ctk.CTkCheckBox(
                btn_frame, text="Auto-instalar Flutter",
            )
            self.check_auto_install.pack(fill="x", pady=2)

            # -- Utilit\u00e1rios --
            ctk.CTkLabel(
                left, text="Utilit\u00e1rios",
                font=ctk.CTkFont(size=14, weight="bold"),
            ).grid(row=r, column=0, pady=(8, 2), sticky="w"); r += 1

            util_frame = ctk.CTkFrame(left, fg_color="transparent")
            util_frame.grid(row=r, column=0, padx=10, pady=2, sticky="ew"); r += 1

            self.btn_detect_adb = ctk.CTkButton(
                util_frame, text="Detectar Dispositivo USB",
                command=self._detect_adb,
            )
            self.btn_detect_adb.pack(fill="x", pady=2)

            self.lbl_adb = ctk.CTkLabel(
                util_frame, text="", font=ctk.CTkFont(size=11),
            )
            self.lbl_adb.pack(fill="x", pady=1)

            self.check_install_adb = ctk.CTkCheckBox(
                util_frame, text="Instalar APK no dispositivo via ADB",
            )
            self.check_install_adb.pack(fill="x", pady=2)

            self.btn_open_output = ctk.CTkButton(
                util_frame, text="Abrir Pasta de Sa\u00edda",
                fg_color="#1565C0", hover_color="#0D47A1",
                command=self._open_output,
            )
            self.btn_open_output.pack(fill="x", pady=2)

            # ── Right panel (log) ──────────────────────────────────────
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

        # ==================================================================
        #  Handlers — fonte do projeto
        # ==================================================================

        def _toggle_theme(self):
            atual = ctk.get_appearance_mode()
            ctk.set_appearance_mode("Light" if atual == "Dark" else "Dark")

        def _select_folder(self):
            pasta = filedialog.askdirectory(
                title="Selecione a pasta do projeto Flutter"
            )
            if pasta:
                self.project_dir = Path(pasta).resolve()
                self.log.ok(f"Projeto selecionado: {self.project_dir}")

        def _clone_github(self):
            url = tk.simpledialog.askstring(
                "GitHub Clone", "URL do reposit\u00f3rio:", parent=self
            )
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

        # ==================================================================
        #  Handlers — colar c\u00f3digo (inteligente)
        # ==================================================================

        def _process_pasted_code(self):
            raw = self.paste_text.get("0.0", "end").strip()
            if not raw:
                messagebox.showwarning("Aviso", "Cole o c\u00f3digo primeiro!")
                return
            threading.Thread(
                target=self._do_process_paste, args=(raw,), daemon=True
            ).start()

        def _detect_project_type(self, raw: str) -> str:
            """Tenta identificar o tipo de projeto colado."""
            # 1. Projeto Flutter completo (pubspec.yaml embutido)
            if re.search(r"^name:\s*\S", raw, re.M) and re.search(
                r"^dependencies:", raw, re.M
            ):
                return "flutter_full"
            # 2. C\u00f3digo Flutter/Dart com import de material
            if re.search(r"package:flutter", raw):
                return "flutter_app"
            # 3. AndroidManifest.xml
            if "<manifest" in raw or "<uses-permission" in raw:
                return "android_manifest"
            # 4. pubspec.yaml puro
            if re.search(r"^name:\s*\S", raw, re.M):
                return "pubspec_only"
            # 5. Dart gen\u00e9rico
            if re.search(r"(import|void main|class\s+\w+|final\s+\w+)", raw):
                return "dart_generic"
            return "unknown"

        def _do_process_paste(self, raw: str):
            self._set_build_state(True)
            try:
                ptype = self._detect_project_type(raw)
                self.log.info(f"Tipo detectado: {ptype}")

                # Usa o ProjectSourceManager para separar e organizar
                dart_code, pubspec_frag, manifest_lines = (
                    ProjectSourceManager.organize_pasted_code(raw, self.log)
                )

                if not dart_code:
                    self.log.err("N\u00e3o foi poss\u00edvel extrair c\u00f3digo Dart v\u00e1lido")
                    return

                # Cria projeto tempor\u00e1rio
                tmp_dir = Path(tempfile.mkdtemp(prefix="flutter_build_"))
                project_dir = tmp_dir / "app"
                self.log.info(f"Criando projeto em: {project_dir}")

                # Tenta usar flutter create para gerar base
                try:
                    subprocess.run(
                        ["flutter", "create", "--project-name", "app",
                         "--org", "com.temp", "--platforms", "android",
                         str(project_dir)],
                        capture_output=True, text=True, timeout=120,
                    )
                except Exception:
                    self.log.warn("flutter create falhou, usando estrutura m\u00ednima")
                    project_dir.mkdir(parents=True, exist_ok=True)
                    (project_dir / "lib").mkdir(exist_ok=True)
                    self._write_minimal_project(project_dir)

                # Sobrescreve main.dart com o c\u00f3digo colado
                lib_main = project_dir / "lib" / "main.dart"
                lib_main.write_text(dart_code, encoding="utf-8")

                self.log.info(f"main.dart: {len(dart_code.splitlines())} linhas")

                # Mescla pubspec se veio colado junto
                if pubspec_frag:
                    ProjectSourceManager._merge_pubspec_fragment(
                        project_dir, pubspec_frag, self.log
                    )

                # Injeta permiss\u00f5es se veio AndroidManifest
                if manifest_lines:
                    ProjectSourceManager.inject_permissions(
                        project_dir, manifest_lines, self.log
                    )

                # Detecta e injeta depend\u00eancias
                ProjectSourceManager.inject_deps(
                    dart_code, project_dir, self.log, kb=self.kb
                )

                # Valida e corrige pubspec
                ProjectSourceManager.validate_and_fix_pubspec(
                    project_dir, self.log
                )

                self.project_dir = project_dir
                self.log.ok(f"Projeto preparado em: {project_dir}")
                self.log.info("Voc\u00ea j\u00e1 pode iniciar o build!")

            except Exception as e:
                self.log.err(f"Erro ao processar c\u00f3digo: {e}")
            finally:
                self._set_build_state(False)

        def _write_minimal_project(self, project_dir: Path):
            """Escreve estrutura m\u00ednima para um projeto Flutter."""
            (project_dir / "lib").mkdir(exist_ok=True)
            (project_dir / "android" / "app" / "src" / "main").mkdir(
                parents=True, exist_ok=True
            )
            (project_dir / "test").mkdir(exist_ok=True)

            # pubspec.yaml m\u00ednimo
            (project_dir / "pubspec.yaml").write_text(
                "name: app\n"
                "description: App gerado automaticamente\n"
                "version: 1.0.0+1\n"
                "environment:\n"
                "  sdk: ^3.0.0\n"
                "dependencies:\n"
                "  flutter:\n"
                "    sdk: flutter\n"
                "flutter:\n"
                "  uses-material-design: true\n",
                encoding="utf-8",
            )
            # AndroidManifest m\u00ednimo
            manifest = (
                project_dir / "android" / "app" / "src" / "main" / "AndroidManifest.xml"
            )
            manifest.write_text(
                '<?xml version="1.0" encoding="utf-8"?>\n'
                '<manifest xmlns:android="http://schemas.android.com/apk/res/android"\n'
                '    package="com.temp.app">\n'
                '    <application\n'
                '        android:label="App"\n'
                '        android:name="${applicationName}"\n'
                '        android:icon="@mipmap/ic_launcher">\n'
                '        <activity\n'
                '            android:name=".MainActivity"\n'
                '            android:exported="true">\n'
                '            <intent-filter>\n'
                '                <action android:name="android.intent.action.MAIN"/>\n'
                '                <category android:name="android.intent.category.LAUNCHER"/>\n'
                '            </intent-filter>\n'
                '        </activity>\n'
                '    </application>\n'
                '</manifest>\n',
                encoding="utf-8",
            )
            # build.gradle m\u00ednimo (app level)
            build_gradle = project_dir / "android" / "app" / "build.gradle"
            build_gradle.write_text(
                "plugins {\n"
                '    id "com.android.application"\n'
                '    id "kotlin-android"\n'
                '    id "dev.flutter.flutter-gradle-plugin"\n'
                "}\n"
                "android {\n"
                "    namespace 'com.temp.app'\n"
                "    compileSdk 34\n"
                "    defaultConfig {\n"
                "        applicationId 'com.temp.app'\n"
                "        minSdk 21\n"
                "        targetSdk 34\n"
                "        versionCode 1\n"
                "        versionName '1.0.0'\n"
                "    }\n"
                "}\n"
                "flutter {\n"
                "    source '../..'\n"
                "}\n",
                encoding="utf-8",
            )

        # ==================================================================
        #  Handlers — Gemini
        # ==================================================================

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

        # ==================================================================
        #  Handlers — Build
        # ==================================================================

        def _start_build(self):
            if not self.project_dir:
                messagebox.showwarning(
                    "Aviso", "Selecione um projeto ou cole um c\u00f3digo primeiro"
                )
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

                self.orch = FlutterBuildOrchestrator(
                    project_path=str(self.project_dir),
                    auto_install=auto_install,
                    log_callback=self._on_log,
                )
                success = self.orch.orchestrate(
                    skip_tests=skip,
                    debug=not release,
                )

                # P\u00f3s-build: instalar via ADB se solicitado
                if success and self.check_install_adb.get() and self.adb_available:
                    self._install_via_adb()

            except Exception as e:
                self.log.err(f"Erro inesperado: {e}")
            finally:
                self._set_build_state(False)

        def _on_log(self, message: str, level: str):
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
            est = "disabled" if running else "normal"
            self.btn_build.configure(state=est)
            self.btn_pasta.configure(state=est)
            self.btn_github.configure(state=est)
            self.btn_analyze.configure(state=est)
            self.btn_detect_adb.configure(state=est)
            self.btn_open_output.configure(state=est)
            self.btn_stop.configure(state="normal" if running else "disabled")

        # ==================================================================
        #  Handlers — ADB
        # ==================================================================

        def _detect_adb(self):
            threading.Thread(target=self._do_detect_adb, daemon=True).start()

        def _do_detect_adb(self):
            self.log.info("Detectando dispositivos Android via ADB...")
            try:
                r = subprocess.run(
                    ["adb", "devices"],
                    capture_output=True, text=True, timeout=15,
                )
                lines = r.stdout.strip().split("\n")
                devices = [
                    l.split("\t")[0]
                    for l in lines[1:]  # skip "List of devices attached"
                    if l.strip() and "device" in l and "unauthorized" not in l
                ]
                if devices:
                    self.adb_available = True
                    self.adb_device = devices[0]
                    self.lbl_adb.configure(
                        text=f"Dispositivo: {devices[0][:30]}",
                        text_color="#4CAF50",
                    )
                    self.log.ok(f"Dispositivo detectado: {devices[0]}")
                else:
                    self.adb_available = False
                    self.adb_device = ""
                    self.lbl_adb.configure(
                        text="Nenhum dispositivo encontrado",
                        text_color="#FF5722",
                    )
                    self.log.warn("Nenhum dispositivo Android via USB detectado")
            except FileNotFoundError:
                self.adb_available = False
                self.lbl_adb.configure(
                    text="ADB n\u00e3o encontrado no PATH",
                    text_color="#FF5722",
                )
                self.log.err("ADB n\u00e3o encontrado. Instale o Android SDK.")
            except Exception as e:
                self.adb_available = False
                self.lbl_adb.configure(text=f"Erro ADB: {e}", text_color="#FF5722")
                self.log.err(f"Erro ao detectar ADB: {e}")

        def _install_via_adb(self):
            apk = self.orch.last_apk_path if self.orch else None
            if not apk or not Path(apk).exists():
                self.log.err("APK n\u00e3o encontrado para instalar")
                return
            self.log.info(f"Instalando {Path(apk).name} no dispositivo...")
            try:
                r = subprocess.run(
                    ["adb", "-s", self.adb_device, "install", "-r", str(apk)],
                    capture_output=True, text=True, timeout=120,
                )
                if r.returncode == 0:
                    self.log.ok("APK instalado com sucesso no dispositivo!")
                else:
                    self.log.err(f"Falha na instala\u00e7\u00e3o: {r.stderr[:300]}")
            except Exception as e:
                self.log.err(f"Erro: {e}")

        # ==================================================================
        #  Handlers — pasta de sa\u00edda
        # ==================================================================

        def _open_output(self):
            if self.orch and self.orch.last_apk_path:
                pasta = Path(self.orch.last_apk_path).parent
            elif self.project_dir:
                pasta = Path(self.project_dir) / "build_output"
            else:
                pasta = Path("build_output").resolve()

            if not pasta.exists():
                pasta.mkdir(parents=True, exist_ok=True)

            try:
                if os.name == "nt":
                    os.startfile(str(pasta))
                elif os.uname().sysname == "Darwin":
                    subprocess.run(["open", str(pasta)])
                else:
                    subprocess.run(["xdg-open", str(pasta)])
                self.log.ok(f"Pasta aberta: {pasta}")
            except Exception as e:
                self.log.err(f"Erro ao abrir pasta: {e}")

    # --- Bootstrap ---
    app = BuildOrchestratorGUI()
    app.mainloop()
