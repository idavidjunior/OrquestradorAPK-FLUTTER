#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Flutter Build Orchestrator — Interface Gr\u00e1fica

Features:
  - Selecionar pasta local / Clonar GitHub / Colar c\u00f3digo (detec\u00e7\u00e3o inteligente)
  - Build com FlutterBuildOrchestrator (log redirecionado via log_callback)
  - Detec\u00e7\u00e3o autom\u00e1tica de dispositivo Android via ADB + instala\u00e7\u00e3o autom\u00e1tica
  - Abertura r\u00e1pida da pasta de sa\u00edda do APK compilado
  - M\u00faltiplas fontes de API (Gemini, OpenAI, Anthropic, OpenRouter, + personalizado)

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

        API_PROVIDERS = [
            "Gemini", "OpenAI", "Anthropic", "DeepSeek",
            "Mistral AI", "Groq", "Together AI", "NVIDIA",
            "Perplexity", "Cohere", "xAI (Grok)", "AI21 Labs",
            "OpenRouter", "Ollama (local)", "Personalizado..."
        ]

        API_KEY_PATTERNS = [
            (re.compile(r"^AIza"), "Gemini"),
            (re.compile(r"^sk-ant-"), "Anthropic"),
            (re.compile(r"^sk-or-"), "OpenRouter"),
            (re.compile(r"^gsk_"), "Groq"),
            (re.compile(r"^tgp_"), "Together AI"),
            (re.compile(r"^pplx-"), "Perplexity"),
            (re.compile(r"^nvapi-"), "NVIDIA"),
            (re.compile(r"^xai-"), "xAI (Grok)"),
            (re.compile(r"^sk-proj-"), "OpenAI"),
            (re.compile(r"^sk-"), "OpenAI"),
            (re.compile(r"^solfce-"), "OpenAI"),
            (re.compile(r"^sess-"), "OpenAI"),
        ]

        OPENAI_COMPATIBLE = {
            "DeepSeek":    ("https://api.deepseek.com/v1",          "deepseek-chat"),
            "Mistral AI":  ("https://api.mistral.ai/v1",           "mistral-large-latest"),
            "Groq":        ("https://api.groq.com/openai/v1",      "llama-3.3-70b-versatile"),
            "Together AI": ("https://api.together.xyz/v1",         "mistralai/Mixtral-8x7B-Instruct-v0.1"),
            "NVIDIA":      ("https://integrate.api.nvidia.com/v1", "meta/llama-3.1-8b-instruct"),
            "Perplexity":  ("https://api.perplexity.ai",           "sonar-pro"),
            "Cohere":      ("https://api.cohere.ai/v1",            "command-r-plus"),
            "xAI (Grok)":  ("https://api.x.ai/v1",                 "grok-2-latest"),
            "AI21 Labs":   ("https://api.ai21.com/studio/v1",      "jamba-1.5-mini"),
        }

        COMMON_ADB_PATHS = [
            Path(os.environ.get("LOCALAPPDATA", "C:\\")) / "Android" / "Sdk" / "platform-tools" / "adb.exe",
            Path(os.environ.get("ANDROID_HOME", "")) / "platform-tools" / "adb.exe",
            Path(os.environ.get("ANDROID_SDK_ROOT", "")) / "platform-tools" / "adb.exe",
            Path("C:\\Program Files\\Android\\android-sdk\\platform-tools\\adb.exe"),
            Path("C:\\Android\\Sdk\\platform-tools\\adb.exe"),
            Path("C:\\Program Files (x86)\\Android\\android-sdk\\platform-tools\\adb.exe"),
            Path.home() / "AppData" / "Local" / "Android" / "Sdk" / "platform-tools" / "adb.exe",
        ]

        def __init__(self):
            super().__init__()
            self.title("Flutter Build Orchestrator")
            self.geometry("1150x780")
            self.minsize(950, 650)

            self.project_dir = None
            self.orch = None
            self.build_running = False

            # ADB state
            self.adb_available = False
            self.adb_device = ""
            self._adb_prev_state = None
            self._adb_poll_active = True
            self._adb_path = self._find_adb_path()

            # API state
            self.api_provider = "Gemini"
            self.api_key = ""
            self._custom_providers = {}
            self._auto_validate_after_id = None

            self._build_ui()
            self._start_adb_poll()
            self.log.ok("GUI pronta \u2014 selecione/cole um projeto para come\u00e7ar")

        # ==================================================================
        #  ADB — localiza\u00e7\u00e3o autom\u00e1tica
        # ==================================================================

        @staticmethod
        def _find_adb_path():
            """Procura adb.exe em locais comuns do Android SDK."""
            for p in BuildOrchestratorGUI.COMMON_ADB_PATHS:
                if p.exists():
                    return str(p)
            # Tenta no PATH
            try:
                r = subprocess.run(["adb", "--version"], capture_output=True, text=True, timeout=5)
                if r.returncode == 0:
                    return "adb"
            except Exception:
                pass
            return None

        @staticmethod
        def _detect_provider_from_key(key: str):
            """Identifica o provedor de API pelo padr\u00e3o da chave."""
            for padrao, provider in BuildOrchestratorGUI.API_KEY_PATTERNS:
                if padrao.search(key):
                    return provider
            return None

        def _select_adb_path(self):
            caminho = filedialog.askopenfilename(
                title="Selecione o execut\u00e1vel ADB",
                filetypes=[("adb.exe", "adb.exe"), ("Todos os arquivos", "*.*")],
            )
            if caminho:
                self._adb_path = caminho
                self.log.ok(f"ADB manual: {caminho}")
                self.lbl_adb.configure(text=f"ADB: {Path(caminho).name}", text_color="#888")

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

            # -- Fonte de API --
            api_lbl = ctk.CTkLabel(
                left, text="Fonte de API (corre\u00e7\u00e3o inteligente)",
                font=ctk.CTkFont(size=14, weight="bold"),
            )
            api_lbl.grid(row=r, column=0, padx=10, pady=(10, 2), sticky="w"); r += 1

            provider_frame = ctk.CTkFrame(left, fg_color="transparent")
            provider_frame.grid(row=r, column=0, padx=10, pady=2, sticky="ew"); r += 1
            provider_frame.grid_columnconfigure(0, weight=1)
            provider_frame.grid_columnconfigure(1, weight=2)

            ctk.CTkLabel(provider_frame, text="Provedor:").grid(
                row=0, column=0, sticky="w", padx=(0, 5)
            )
            self.api_provider_menu = ctk.CTkOptionMenu(
                provider_frame,
                values=self.API_PROVIDERS,
                command=self._on_api_provider_change,
            )
            self.api_provider_menu.grid(row=0, column=1, sticky="ew")
            self.api_provider_menu.set("Gemini")

            self.api_key_entry = ctk.CTkEntry(
                left, placeholder_text="Cole sua chave de API aqui..."
            )
            self.api_key_entry.bind("<KeyRelease>", self._on_key_change)
            self.api_key_entry.bind("<<Paste>>", self._on_key_change)
            self.api_key_entry.grid(row=r, column=0, padx=10, pady=2, sticky="ew"); r += 1

            self.lbl_api_status = ctk.CTkLabel(
                left, text="", font=ctk.CTkFont(size=11),
            )
            self.lbl_api_status.grid(row=r, column=0, padx=10, pady=(0, 2), sticky="w"); r += 1

            api_btn_row = ctk.CTkFrame(left, fg_color="transparent")
            api_btn_row.grid(row=r, column=0, padx=10, pady=2, sticky="ew"); r += 1
            api_btn_row.grid_columnconfigure(0, weight=1)
            api_btn_row.grid_columnconfigure(1, weight=1)

            self.btn_validate_api = ctk.CTkButton(
                api_btn_row, text="Validar Chave",
                command=self._validate_api_key,
            )
            self.btn_validate_api.grid(row=0, column=0, padx=(0, 2), sticky="ew")

            self.btn_save_api = ctk.CTkButton(
                api_btn_row, text="Salvar", fg_color="#555",
                command=self._save_api_key,
            )
            self.btn_save_api.grid(row=0, column=1, padx=(2, 0), sticky="ew")

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

            self.lbl_adb = ctk.CTkLabel(
                util_frame, text="ADB: aguardando...", font=ctk.CTkFont(size=11),
            )
            self.lbl_adb.pack(fill="x", pady=1)

            self.btn_select_adb = ctk.CTkButton(
                util_frame, text="Selecionar ADB manualmente",
                command=self._select_adb_path,
            )
            self.btn_select_adb.pack(fill="x", pady=2)

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
            if re.search(r"^name:\s*\S", raw, re.M) and re.search(
                r"^dependencies:", raw, re.M
            ):
                return "flutter_full"
            if re.search(r"package:flutter", raw):
                return "flutter_app"
            if "<manifest" in raw or "<uses-permission" in raw:
                return "android_manifest"
            if re.search(r"^name:\s*\S", raw, re.M):
                return "pubspec_only"
            if re.search(r"(import|void main|class\s+\w+|final\s+\w+)", raw):
                return "dart_generic"
            return "unknown"

        def _do_process_paste(self, raw: str):
            self._set_build_state(True)
            try:
                ptype = self._detect_project_type(raw)
                self.log.info(f"Tipo detectado: {ptype}")

                dart_code, pubspec_frag, manifest_lines = (
                    ProjectSourceManager.organize_pasted_code(raw, self.log)
                )

                if not dart_code:
                    self.log.err("N\u00e3o foi poss\u00edvel extrair c\u00f3digo Dart v\u00e1lido")
                    return

                tmp_dir = Path(tempfile.mkdtemp(prefix="flutter_build_"))
                project_dir = tmp_dir / "app"
                self.log.info(f"Criando projeto em: {project_dir}")

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

                lib_main = project_dir / "lib" / "main.dart"
                lib_main.write_text(dart_code, encoding="utf-8")

                self.log.info(f"main.dart: {len(dart_code.splitlines())} linhas")

                if pubspec_frag:
                    ProjectSourceManager._merge_pubspec_fragment(
                        project_dir, pubspec_frag, self.log
                    )

                if manifest_lines:
                    ProjectSourceManager.inject_permissions(
                        project_dir, manifest_lines, self.log
                    )

                ProjectSourceManager.inject_deps(
                    dart_code, project_dir, self.log, kb=self.kb
                )

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
            (project_dir / "lib").mkdir(exist_ok=True)
            (project_dir / "android" / "app" / "src" / "main").mkdir(
                parents=True, exist_ok=True
            )
            (project_dir / "test").mkdir(exist_ok=True)

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
        #  Handlers — API Key (m\u00faltiplas fontes + personalizado)
        # ==================================================================

        def _on_api_provider_change(self, choice: str):
            if choice == "Personalizado...":
                self._add_custom_provider()
                return
            self.api_provider = choice
            self.log.info(f"Provedor de API selecionado: {choice}")

        def _add_custom_provider(self):
            dialogo = ctk.CTkToplevel(self)
            dialogo.title("Adicionar Provedor Personalizado")
            dialogo.geometry("480x320")
            dialogo.transient(self)
            dialogo.grab_set()

            campos = {}
            r = 0
            for label, key, placeholder in [
                ("Nome do provedor", "name", "ex: MeuProvedor"),
                ("URL Base", "url", "https://api.exemplo.com/v1"),
                ("Modelo (opcional)", "model", "ex: meu-modelo-v1"),
                ("Header de autentica\u00e7\u00e3o", "auth_header", "Authorization"),
                ("Prefixo do valor", "auth_prefix", "Bearer "),
            ]:
                ctk.CTkLabel(dialogo, text=label).grid(
                    row=r, column=0, padx=10, pady=4, sticky="w"
                )
                entry = ctk.CTkEntry(dialogo, width=300, placeholder_text=placeholder)
                entry.grid(row=r, column=1, padx=10, pady=4, sticky="ew")
                if key in ("auth_header", "auth_prefix"):
                    entry.insert(0, placeholder)
                campos[key] = entry
                r += 1

            def salvar():
                name = campos["name"].get().strip()
                url = campos["url"].get().strip()
                if not name or not url:
                    messagebox.showwarning("Aviso", "Nome e URL s\u00e3o obrigat\u00f3rios")
                    return
                cfg = {
                    "url": url,
                    "model": campos["model"].get().strip() or None,
                    "auth_header": campos["auth_header"].get().strip() or "Authorization",
                    "auth_prefix": campos["auth_prefix"].get().strip() or "Bearer ",
                }
                self._custom_providers[name] = cfg
                # Atualiza dropdown
                vals = [p for p in self.API_PROVIDERS if p != "Personalizado..."]
                vals.append(name)
                vals.append("Personalizado...")
                self.api_provider_menu.configure(values=vals)
                self.api_provider_menu.set(name)
                self.api_provider = name
                self.log.ok(f"Provedor personalizado adicionado: {name}")
                dialogo.destroy()

            ctk.CTkButton(
                dialogo, text="Salvar Provedor", command=salvar,
                fg_color="#2E7D32",
            ).grid(row=r, column=0, columnspan=2, pady=12)
            dialogo.grid_columnconfigure(1, weight=1)

        def _on_key_change(self, event=None):
            """Detecta provedor e auto-valida quando a chave \u00e9 colada/digitada."""
            # Cancela valida\u00e7\u00e3o pendente anterior (debounce 600ms)
            if self._auto_validate_after_id:
                self.after_cancel(self._auto_validate_after_id)

            raw = self.api_key_entry.get().strip()
            if len(raw) < 8:
                self.lbl_api_status.configure(text="")
                return

            detected = self._detect_provider_from_key(raw)
            if detected and detected != self.api_provider:
                self.api_provider = detected
                self.api_provider_menu.set(detected)
                self.log.info(f"Provedor detectado pela chave: {detected}")

            if self.api_provider != "Ollama (local)":
                self._auto_validate_after_id = self.after(
                    600, self._auto_validate
                )

        def _auto_validate(self):
            """Valida a chave em background sem mostrar popups."""
            self._auto_validate_after_id = None
            raw = self.api_key_entry.get().strip()
            if not raw:
                return
            self.api_key = raw
            threading.Thread(target=self._do_auto_validate, daemon=True).start()

        def _do_auto_validate(self):
            provider = self.api_provider
            if provider == "Gemini":
                from gui.gemini_fixer import GeminiCodeFixer
                ok, msg = GeminiCodeFixer.validate_key(self.api_key)
            elif provider == "OpenAI":
                ok, msg = self._validate_openai_key(self.api_key)
            elif provider == "Anthropic":
                ok, msg = self._validate_anthropic_key(self.api_key)
            elif provider == "OpenRouter":
                ok, msg = self._validate_openrouter_key(self.api_key)
            elif provider == "Ollama (local)":
                ok, msg = self._validate_ollama()
            elif provider in self.OPENAI_COMPATIBLE:
                url = self.OPENAI_COMPATIBLE[provider][0].rstrip("/") + "/models"
                ok, msg = self._validate_openai_compatible(self.api_key, provider, url)
            elif provider in self._custom_providers:
                ok, msg = self._validate_custom_provider(self.api_key)
            else:
                return
            self.after(0, self._show_auto_validate_result, ok, msg)

        def _show_auto_validate_result(self, ok: bool, msg: str):
            if ok:
                self.lbl_api_status.configure(
                    text=f"✓ {msg}", text_color="#4CAF50"
                )
                self.log.ok(f"{self.api_provider}: {msg}")
            else:
                self.lbl_api_status.configure(
                    text=f"✗ {msg}", text_color="#FF5722"
                )

        def _save_api_key(self):
            key = self.api_key_entry.get().strip()
            if not key:
                messagebox.showwarning("Aviso", "Digite uma chave primeiro")
                return
            self.api_key = key
            self.log.ok(
                f"Chave salva para {self.api_provider} "
                f"(termina em ...{key[-4:]})"
            )

        def _validate_api_key(self):
            key = self.api_key_entry.get().strip()
            if not key:
                messagebox.showwarning("Aviso", "Digite uma chave primeiro")
                return
            self.api_key = key

            provider = self.api_provider
            self.log.info(f"Validando chave {provider}...")

            if provider == "Gemini":
                from gui.gemini_fixer import GeminiCodeFixer
                ok, msg = GeminiCodeFixer.validate_key(key)
            elif provider == "OpenAI":
                ok, msg = self._validate_openai_key(key)
            elif provider == "Anthropic":
                ok, msg = self._validate_anthropic_key(key)
            elif provider == "OpenRouter":
                ok, msg = self._validate_openrouter_key(key)
            elif provider == "Ollama (local)":
                ok, msg = self._validate_ollama()
            elif provider in self.OPENAI_COMPATIBLE:
                url = self.OPENAI_COMPATIBLE[provider][0].rstrip("/") + "/models"
                ok, msg = self._validate_openai_compatible(key, provider, url)
            elif provider in self._custom_providers:
                ok, msg = self._validate_custom_provider(key)
            else:
                ok, msg = False, "Provedor desconhecido"

            if ok:
                self.lbl_api_status.configure(
                    text=f"✓ {msg}", text_color="#4CAF50"
                )
                messagebox.showinfo("Sucesso", msg)
                self.log.ok(f"{provider}: {msg}")
            else:
                self.lbl_api_status.configure(
                    text=f"✗ {msg}", text_color="#FF5722"
                )
                messagebox.showerror("Erro", msg)
                self.log.err(f"{provider}: {msg}")

        def _validate_openai_key(self, key: str):
            return self._validate_openai_compatible(key, "OpenAI",
                "https://api.openai.com/v1/models")

        def _validate_openai_compatible(self, key: str, provider: str,
                                         base_url: str = None):
            """Valida chave contra qualquer API compat\u00edvel com OpenAI (GET /models)."""
            url = base_url or self.OPENAI_COMPATIBLE.get(provider, [None])[0]
            if not url:
                # Tenta /models no base_url
                cfg = self.OPENAI_COMPATIBLE.get(provider)
                if cfg:
                    url = cfg[0].rstrip("/") + "/models"
            if not url:
                return False, "URL n\u00e3o configurada"
            try:
                req = __import__("urllib.request", fromlist=["Request", "urlopen"]).Request(
                    url,
                    headers={"Authorization": f"Bearer {key}"},
                )
                with __import__("urllib.request").urlopen(req, timeout=10) as r:
                    data = __import__("json").loads(r.read())
                models = data.get("data", [])
                if models:
                    return True, f"OK \u2014 {len(models)} modelos dispon\u00edveis"
                return True, f"Conectado (HTTP {r.status})"
            except Exception as e:
                err = str(e)
                if "401" in err:
                    return False, "Chave inv\u00e1lida"
                return False, f"Erro: {err[:100]}"

        def _validate_anthropic_key(self, key: str):
            try:
                req = __import__("urllib.request", fromlist=["Request"]).Request(
                    "https://api.anthropic.com/v1/messages",
                    data=__import__("json").dumps(
                        {"model": "claude-3-haiku-20240307",
                         "max_tokens": 10,
                         "messages": [{"role": "user", "content": "hi"}]}
                    ).encode(),
                    headers={
                        "Content-Type": "application/json",
                        "x-api-key": key,
                        "anthropic-version": "2023-06-01",
                    },
                    method="POST",
                )
                with __import__("urllib.request").urlopen(req, timeout=15) as r:
                    return True, "Chave v\u00e1lida"
            except Exception as e:
                err = str(e)
                if "401" in err or "invalid" in err.lower():
                    return False, "Chave inv\u00e1lida"
                if "403" in err:
                    return False, "Sem permiss\u00e3o"
                return False, f"Erro: {err}"

        def _validate_openrouter_key(self, key: str):
            try:
                req = __import__("urllib.request", fromlist=["Request"]).Request(
                    "https://openrouter.ai/api/v1/auth/key",
                    headers={"Authorization": f"Bearer {key}"},
                )
                with __import__("urllib.request").urlopen(req, timeout=10) as r:
                    return True, "Chave v\u00e1lida"
            except Exception as e:
                err = str(e)
                if "401" in err:
                    return False, "Chave inv\u00e1lida"
                return False, f"Erro: {err}"

        def _validate_ollama(self):
            try:
                req = __import__("urllib.request", fromlist=["Request"]).Request(
                    "http://localhost:11434/api/tags"
                )
                with __import__("urllib.request").urlopen(req, timeout=5) as r:
                    data = __import__("json").loads(r.read())
                models = data.get("models", [])
                if models:
                    return True, f"OK \u2014 {len(models)} modelos dispon\u00edveis"
                return True, "Ollama rodando (sem modelos)"
            except Exception:
                return False, "Ollama n\u00e3o encontrado em localhost:11434"

        def _validate_custom_provider(self, key: str):
            cfg = self._custom_providers.get(self.api_provider)
            if not cfg:
                return False, "Configura\u00e7\u00e3o do provedor n\u00e3o encontrada"
            url = cfg["url"]
            try:
                hdr = {cfg["auth_header"]: f"{cfg['auth_prefix']}{key}"}
                req = __import__("urllib.request", fromlist=["Request"]).Request(
                    url, headers=hdr, method="GET"
                )
                with __import__("urllib.request").urlopen(req, timeout=15) as r:
                    return True, f"Conectado (HTTP {r.status})"
            except Exception as e:
                err = str(e)
                if "401" in err:
                    return False, "Chave inv\u00e1lida para este provedor"
                return False, f"Erro: {err[:100]}"

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
            self.btn_open_output.configure(state=est)
            self.btn_validate_api.configure(state=est)
            self.btn_save_api.configure(state=est)
            self.btn_select_adb.configure(state=est)
            self.btn_stop.configure(state="normal" if running else "disabled")

        # ==================================================================
        #  ADB — detec\u00e7\u00e3o autom\u00e1tica com fallback de path
        # ==================================================================

        def _start_adb_poll(self):
            self._adb_poll_active = True
            self._do_adb_poll()

        def _stop_adb_poll(self):
            self._adb_poll_active = False

        def _do_adb_poll(self):
            if not self._adb_poll_active:
                return
            threading.Thread(target=self._run_adb_check, daemon=True).start()

        def _adb_cmd(self, *args):
            """Executa comando ADB usando o path resolvido."""
            if self._adb_path and self._adb_path != "adb":
                cmd = [self._adb_path] + list(args)
            else:
                cmd = ["adb"] + list(args)
            return subprocess.run(cmd, capture_output=True, text=True, timeout=10)

        def _run_adb_check(self):
            result = {"available": False, "device": "", "error": None}
            try:
                r = self._adb_cmd("devices")
                lines = r.stdout.strip().split("\n")
                devices = [
                    l.split("\t")[0]
                    for l in lines[1:]
                    if l.strip() and "device" in l and "unauthorized" not in l
                ]
                result["available"] = len(devices) > 0
                result["device"] = devices[0] if devices else ""
            except FileNotFoundError:
                # Tenta localizar ADB automaticamente
                found = self._find_adb_path()
                if found and found != self._adb_path:
                    self._adb_path = found
                    self.log.ok(f"ADB localizado automaticamente: {Path(found).name}")
                    # Reexecuta no pr\u00f3ximo ciclo
                else:
                    result["error"] = "ADB n\u00e3o encontrado — use 'Selecionar ADB manualmente'"
            except Exception as e:
                result["error"] = str(e)[:60]

            self.after(0, self._update_adb_ui, result)

        def _update_adb_ui(self, result):
            state = result["available"] if not result["error"] else "error"
            if not self._adb_path:
                self.lbl_adb.configure(
                    text="ADB: clique em 'Selecionar ADB manualmente'",
                    text_color="#FF5722",
                )
                if self._adb_prev_state != "nopath":
                    self.log.err("ADB n\u00e3o encontrado — selecione manualmente")
                    self._adb_prev_state = "nopath"
            elif result["error"]:
                self.adb_available = False
                self.adb_device = ""
                self.lbl_adb.configure(
                    text=f"ADB: {result['error']}", text_color="#FF5722"
                )
                if self._adb_prev_state != "error":
                    self.log.err(f"ADB: {result['error']}")
                    self._adb_prev_state = "error"
            elif result["available"]:
                self.adb_available = True
                self.adb_device = result["device"]
                self.lbl_adb.configure(
                    text=f"Dispositivo: {result['device'][:35]}",
                    text_color="#4CAF50",
                )
                if self._adb_prev_state is not True:
                    self.log.ok(f"Dispositivo ADB detectado: {result['device']}")
                    self._adb_prev_state = True
            else:
                self.adb_available = False
                self.adb_device = ""
                self.lbl_adb.configure(
                    text="Nenhum dispositivo conectado", text_color="#888"
                )
                if self._adb_prev_state is not False:
                    self.log.info("ADB: nenhum dispositivo conectado")
                    self._adb_prev_state = False

            self.after(3000, self._do_adb_poll)

        def _install_via_adb(self):
            apk = self.orch.last_apk_path if self.orch else None
            if not apk or not Path(apk).exists():
                self.log.err("APK n\u00e3o encontrado para instalar")
                return
            self.log.info(f"Instalando {Path(apk).name} no dispositivo...")
            try:
                r = self._adb_cmd("-s", self.adb_device, "install", "-r", str(apk))
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
