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

import json
import os
import re
import subprocess
import threading
import tempfile
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Optional

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

        PROVIDER_KEY_URLS = {
            "Gemini":       "https://aistudio.google.com/app/apikey",
            "OpenAI":       "https://platform.openai.com/api-keys",
            "Anthropic":    "https://console.anthropic.com/settings/keys",
            "DeepSeek":     "https://platform.deepseek.com/api_keys",
            "Mistral AI":   "https://console.mistral.ai/api-keys/",
            "Groq":         "https://console.groq.com/keys",
            "Together AI":  "https://api.together.xyz/settings/api-keys",
            "NVIDIA":       "https://build.nvidia.com/explore/discover",
            "Perplexity":   "https://www.perplexity.ai/settings/api",
            "Cohere":       "https://dashboard.cohere.com/api-keys",
            "xAI (Grok)":   "https://console.x.ai/",
            "AI21 Labs":    "https://www.ai21.com/settings/api-keys",
            "OpenRouter":   "https://openrouter.ai/settings/keys",
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
            self.state("zoomed")

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
            self._auto_selected_models = {}
            self._model_fallback_cache = {}
            self._ollama_models_cache = []
            self._bad_models = set()

            self._build_ui()
            self._load_state()
            self._start_adb_poll()
            self.after(100, self._auto_validate_on_startup)
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
            self.paste_text.bind("<KeyRelease>", self._on_paste_key)

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
            provider_frame.grid_columnconfigure(2, weight=0)

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

            self.lbl_ai_live_status = ctk.CTkLabel(
                provider_frame, text="◉", font=ctk.CTkFont(size=16), text_color="#888",
            )
            self.lbl_ai_live_status.grid(row=0, column=2, padx=(5, 0))

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

            self.btn_get_key = ctk.CTkButton(
                left, text="\u2197 Obter chave", fg_color="transparent",
                text_color="#64B5F6", hover_color="#1A237E",
                font=ctk.CTkFont(size=11, underline=True),
                command=self._open_provider_key_url,
            )
            self.btn_get_key.grid(row=r, column=0, padx=10, pady=(0, 2), sticky="w"); r += 1

            api_btn_row = ctk.CTkFrame(left, fg_color="transparent")
            api_btn_row.grid(row=r, column=0, padx=10, pady=2, sticky="ew"); r += 1
            api_btn_row.grid_columnconfigure(0, weight=1)
            api_btn_row.grid_columnconfigure(1, weight=1)

            self.btn_save_api = ctk.CTkButton(
                api_btn_row, text="Salvar Chave", fg_color="#555",
                command=self._save_api_key,
            )
            self.btn_save_api.grid(row=0, column=0, columnspan=2, sticky="ew")

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
                btn_frame, text="Auto-instalar Flutter", onvalue=True, offvalue=False,
            )
            self.check_auto_install.select()
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

            self._install_adb_var = ctk.BooleanVar(value=True)
            self.check_install_adb = ctk.CTkCheckBox(
                util_frame, text="Instalar APK no dispositivo via ADB",
                variable=self._install_adb_var, onvalue=True, offvalue=False,
            )
            self.check_install_adb.pack(fill="x", pady=2)

            self.btn_open_output = ctk.CTkButton(
                util_frame, text="Abrir Pasta de Sa\u00edda",
                fg_color="#1565C0", hover_color="#0D47A1",
                command=self._open_output,
            )
            self.btn_open_output.pack(fill="x", pady=2)

            # ── Right panel (progresso + reestruturação + log) ──────────
            right = ctk.CTkFrame(self)
            right.grid(row=1, column=1, sticky="nsew", padx=(2, 5), pady=5)
            right.grid_rowconfigure(5, weight=1)
            right.grid_columnconfigure(0, weight=1)

            ctk.CTkLabel(
                right, text="Progresso",
                font=ctk.CTkFont(size=14, weight="bold"),
            ).grid(row=0, column=0, pady=(5, 2))

            # -- Barra de progresso --
            self.progress_bar = ctk.CTkProgressBar(right, height=16)
            self.progress_bar.grid(row=1, column=0, padx=10, pady=(2, 0), sticky="ew")
            self.progress_bar.set(0)

            self.lbl_progress_status = ctk.CTkLabel(
                right, text="", font=ctk.CTkFont(size=11),
            )
            self.lbl_progress_status.grid(
                row=2, column=0, padx=10, pady=(0, 0), sticky="w"
            )

            # -- Reestruturação ao vivo --
            self.lbl_restructuring = ctk.CTkLabel(
                right, text="", font=ctk.CTkFont(size=11),
                text_color="#90CAF9",
            )
            self.lbl_restructuring.grid(
                row=3, column=0, padx=10, pady=(0, 0), sticky="w"
            )

            # -- Log --
            ctk.CTkLabel(
                right, text="Log de Build",
                font=ctk.CTkFont(size=14, weight="bold"),
            ).grid(row=4, column=0, pady=(5, 2))

            self.log_text = ctk.CTkTextbox(
                right, state="disabled", wrap="word",
                font=ctk.CTkFont(size=12, family="Consolas"),
            )
            self.log_text.grid(row=5, column=0, sticky="nsew", padx=5, pady=5)

            self.log = Logger(self.log_text)
            self.kb = KnowledgeBase(self.log)

        # ==================================================================
        #  Handlers — fonte do projeto
        # ==================================================================

        @property
        def _state_file(self) -> Path:
            p = Path.home() / ".flutter_orchestrator"
            p.mkdir(parents=True, exist_ok=True)
            return p / "state.json"

        def _load_state(self):
            try:
                if not self._state_file.exists():
                    return
                data = json.loads(self._state_file.read_text(encoding="utf-8"))
                prov = data.get("api_provider", "Gemini")
                if prov in self.API_PROVIDERS or prov in self._custom_providers:
                    self.api_provider = prov
                    self.api_provider_menu.set(prov)
                key = data.get("api_key", "")
                if key:
                    self.api_key = key
                    self.api_key_entry.insert(0, key)
                # N\u00e3o restaura modelos em cache — ser\u00e3o re-descobertos
                # na pr\u00f3xima valida\u00e7\u00e3o (evita modelo quebrado de sess\u00e3o anterior)
                proj = data.get("last_project_dir", "")
                if proj and Path(proj).exists():
                    self.project_dir = Path(proj)
                    self.log.ok(f"\u00daltimo projeto restaurado: {proj}")
                self.log.info("Estado restaurado da sess\u00e3o anterior")
            except Exception as e:
                self.log.warn(f"N\u00e3o foi poss\u00edvel restaurar estado: {e}")

        def _save_state(self):
            try:
                data = {
                    "api_provider": self.api_provider,
                    "api_key": self.api_key,
                    "auto_selected_models": dict(self._auto_selected_models),
                    "last_project_dir": str(self.project_dir)
                    if self.project_dir else "",
                }
                self._state_file.write_text(
                    json.dumps(data, indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )
            except Exception as e:
                self.log.warn(f"Erro ao salvar estado: {e}")

        def _toggle_theme(self):
            atual = ctk.get_appearance_mode()
            ctk.set_appearance_mode("Light" if atual == "Dark" else "Dark")

        def _select_folder(self):
            pasta = filedialog.askdirectory(
                title="Selecione a pasta do projeto Flutter"
            )
            if pasta:
                self.project_dir = Path(pasta).resolve()
                self._save_state()
                self.log.ok(f"Projeto selecionado: {self.project_dir}")
                self.after(500, self._start_build)

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
                    self.after(500, self._start_build)
                else:
                    self.log.err(f"Falha: {r.stderr}")
            except Exception as e:
                self.log.err(f"Erro: {e}")
            finally:
                self._set_build_state(False)

        # ==================================================================
        #  Handlers — colar c\u00f3digo (inteligente)
        # ==================================================================

        def _on_paste_key(self, event=None):
            raw = self.paste_text.get("0.0", "end").strip()
            if len(raw) < 50:
                return
            if getattr(self, "_paste_after_id", None):
                self.after_cancel(self._paste_after_id)
            self._paste_after_id = self.after(800, self._auto_process_paste)

        def _auto_process_paste(self):
            self._paste_after_id = None
            raw = self.paste_text.get("0.0", "end").strip()
            if len(raw) < 50:
                return
            if self.build_running:
                return
            self.log.info("C\u00f3digo detectado automaticamente — analisando...")
            threading.Thread(
                target=self._do_process_paste, args=(raw,), daemon=True
            ).start()

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
            def _rui(msg):
                self.after(0, lambda m=msg: self.lbl_restructuring.configure(text=m))
            try:
                ptype = self._detect_project_type(raw)
                _rui(">> Detectado: " + ptype)
                self.log.info(f"Tipo detectado: {ptype}")

                _rui(">> Organizando codigo colado...")
                dart_code, pubspec_frag, manifest_lines = (
                    ProjectSourceManager.organize_pasted_code(raw, self.log, kb=self.kb)
                )

                if not dart_code:
                    self.log.err("Nao foi possivel extrair codigo Dart valido")
                    _rui("ERRO: codigo Dart invalido")
                    return

                _rui(">> Criando projeto Flutter...")
                tmp_dir = Path(tempfile.mkdtemp(prefix="flutter_build_"))
                project_dir = tmp_dir / "app"
                self.log.info(f"Criando projeto em: {project_dir}")

                flutter_create_exe = "flutter"
                if hasattr(self, '_orch_flutter_path') and self._orch_flutter_path:
                    flutter_create_exe = self._orch_flutter_path
                else:
                    from flutter_orchestrator import FlutterBuildOrchestrator
                    f_path = FlutterBuildOrchestrator._find_flutter_path()
                    if f_path:
                        flutter_create_exe = f_path
                        self._orch_flutter_path = f_path
                try:
                    r = subprocess.run(
                        [flutter_create_exe, "create", "--project-name", "app",
                         "--org", "com.temp", "--platforms", "android",
                         str(project_dir)],
                        capture_output=True, text=True, timeout=120,
                    )
                    if r.returncode != 0:
                        err = r.stderr[:200] if r.stderr else r.stdout[:200]
                        self.log.warn(f"flutter create falhou ({r.returncode}): {err}")
                        raise Exception(err)
                except subprocess.TimeoutExpired:
                    self.log.warn("flutter create excedeu timeout, usando estrutura minima")
                except Exception as e:
                    self.log.warn(f"flutter create falhou, usando estrutura minima: {str(e)[:100]}")
                if not (project_dir / "pubspec.yaml").exists():
                    project_dir.mkdir(parents=True, exist_ok=True)
                    (project_dir / "lib").mkdir(exist_ok=True)
                    self._write_minimal_project(project_dir)

                self._ensure_local_properties(project_dir)

                _rui(">> Escrevendo main.dart...")
                lib_main = project_dir / "lib" / "main.dart"
                lib_main.write_text(dart_code, encoding="utf-8")
                self.log.info(f"main.dart: {len(dart_code.splitlines())} linhas")

                widget_test = project_dir / "test" / "widget_test.dart"
                if widget_test.exists():
                    widget_test.unlink()
                    self.log.info("widget_test.dart removido (codigo colado e independente)")

                _rui(">> Mesclando dependencias...")
                if pubspec_frag:
                    ProjectSourceManager._merge_pubspec_fragment(
                        project_dir, pubspec_frag, self.log
                    )

                if manifest_lines:
                    ProjectSourceManager.inject_permissions(
                        project_dir, manifest_lines, self.log
                    )

                _rui(">> Detectando e injetando deps...")
                ProjectSourceManager.inject_deps(
                    dart_code, project_dir, self.log, kb=self.kb
                )

                _rui(">> Validando pubspec.yaml...")
                ProjectSourceManager.validate_and_fix_pubspec(
                    project_dir, self.log
                )

                self.project_dir = project_dir
                self._save_state()
                _rui("OK: Projeto preparado com sucesso!")
                self.log.ok(f"Projeto preparado em: {project_dir}")
                self.log.info("Iniciando build automaticamente...")
                self.after(500, self._start_build)
            except Exception as e:
                self.log.err(f"Erro ao processar codigo: {e}")
            finally:
                self._set_build_state(False)
                self.after(100, lambda: self.lbl_restructuring.configure(text=""))

        def _ensure_local_properties(self, project_dir):
            """Escreve local.properties válido e salva flutter path."""
            lp = project_dir / "android" / "local.properties"
            from flutter_orchestrator import FlutterBuildOrchestrator
            f = FlutterBuildOrchestrator._find_flutter_path()
            if f:
                self._orch_flutter_path = f
                flutter_sdk = str(Path(f).parent.parent)
                android_home = os.environ.get(
                    "ANDROID_HOME",
                    str(Path.home() / "AppData" / "Local" / "Android" / "Sdk")
                )
                lp.write_text(
                    f"sdk.dir={android_home}\n"
                    f"flutter.sdk={flutter_sdk}\n"
                    f"flutter.buildMode=release\n"
                    f"flutter.versionName=1.0.0\n"
                    f"flutter.versionCode=1\n",
                    encoding="utf-8",
                )
                self.log.ok(f"local.properties gerado com flutter.sdk={flutter_sdk}")

        @staticmethod
        def _get_template_versions() -> dict:
            versions = {
                "agp": "8.1.4",
                "kotlin": "1.9.22",
                "gradle": "8.12",
                "compileSdk": "34",
                "targetSdk": "34",
                "minSdk": "21",
            }
            flutter_cmd = App._find_flutter_cmd()
            if not flutter_cmd:
                return versions
            try:
                temp_ref = Path(tempfile.mkdtemp(prefix="flutter_ref_"))
                subprocess.run(
                    [flutter_cmd, "create", "--project-name", "ref", "--platforms", "android", str(temp_ref / "ref")],
                    capture_output=True, text=True, timeout=120,
                )
                ref_bg = temp_ref / "ref" / "android" / "app" / "build.gradle"
                ref_bg2 = temp_ref / "ref" / "android" / "app" / "build.gradle.kts"
                ref_props = temp_ref / "ref" / "android" / "gradle" / "wrapper" / "gradle-wrapper.properties"
                if ref_bg2.exists():
                    text = ref_bg2.read_text(encoding="utf-8")
                    m = re.search(r'com\.android\.tools\.build:gradle:([\d.]+)', text)
                    if m: versions["agp"] = m.group(1)
                    m = re.search(r'compileSdk\s+(\d+)', text)
                    if m: versions["compileSdk"] = m.group(1)
                    m = re.search(r'minSdk\s+(\d+)', text)
                    if m: versions["minSdk"] = m.group(1)
                    m = re.search(r'targetSdk\s+(\d+)', text)
                    if m: versions["targetSdk"] = m.group(1)
                settings_gradle = temp_ref / "ref" / "android" / "settings.gradle"
                if settings_gradle.exists():
                    text = settings_gradle.read_text(encoding="utf-8")
                    m = re.search(r'org\.jetbrains\.kotlin\.android[^v]*version\s+"([\d.]+)"', text)
                    if m: versions["kotlin"] = m.group(1)
                    m = re.search(r'com\.android\.application[^v]*version\s+"([\d.]+)"', text)
                    if m: versions["agp"] = m.group(1)
                if ref_props.exists():
                    text = ref_props.read_text(encoding="utf-8")
                    m = re.search(r'gradle-([\d.]+)-all\.zip', text)
                    if m: versions["gradle"] = m.group(1)
                shutil.rmtree(temp_ref, ignore_errors=True)
            except Exception:
                pass
            return versions

        @staticmethod
        def _find_flutter_cmd() -> Optional[str]:
            for candidate in [
                "C:\\tools\\flutter\\bin\\flutter.bat", "C:\\flutter\\bin\\flutter.bat",
                str(Path.home() / "flutter" / "bin" / "flutter.bat"),
                str(Path.home() / ".flutter_auto" / "flutter" / "bin" / "flutter.bat"),
            ]:
                if Path(candidate).exists():
                    return candidate
            try:
                subprocess.run(["flutter", "--version"], capture_output=True, timeout=10)
                return "flutter"
            except Exception:
                return None

        @staticmethod
        def _write_minimal_project(project_dir: Path):
            """Gera estrutura Flutter completa para build Android."""
            versions = App._get_template_versions()
            dirs = [
                "lib",
                "test",
                "android/app/src/main/kotlin/com/temp/app",
                "android/app/src/main/res/values",
                "android/gradle/wrapper",
            ]
            for d in dirs:
                (project_dir / d).mkdir(parents=True, exist_ok=True)

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

            (project_dir / "analysis_options.yaml").write_text(
                "include: package:flutter_lints/flutter.yaml\n"
                "linter:\n"
                "  rules:\n"
                "    prefer_const_constructors: false\n"
                "    prefer_const_literals_to_create_immutables: false\n",
                encoding="utf-8",
            )

            # ── AndroidManifest.xml (v2 embedding obrigat\u00f3rio) ─────
            manifest = (
                project_dir / "android" / "app" / "src" / "main" / "AndroidManifest.xml"
            )
            manifest.write_text(
                '<?xml version="1.0" encoding="utf-8"?>\n'
                '<manifest xmlns:android="http://schemas.android.com/apk/res/android"\n'
                '    package="com.temp.app">\n'
                '    <uses-permission android:name="android.permission.INTERNET"/>\n'
                '    <application\n'
                '        android:label="App"\n'
                '        android:name="${applicationName}"\n'
                '        android:icon="@mipmap/ic_launcher">\n'
                '        <activity\n'
                '            android:name=".MainActivity"\n'
                '            android:exported="true"\n'
                '            android:launchMode="singleTop"\n'
                '            android:taskAffinity=""\n'
                '            android:theme="@android:style/Theme.Light.NoTitleBar"\n'
                '            android:configChanges="orientation|keyboardHidden|'
                'keyboard|screenSize|smallestScreenSize|locale|layoutDirection|'
                'fontScale|screenLayout|density|uiMode"\n'
                '            android:hardwareAccelerated="true"\n'
                '            android:windowSoftInputMode="adjustResize">\n'
                '            <meta-data\n'
                '                android:name="io.flutter.embedding.android.'
                'NormalTheme"\n'
                '                android:resource="@style/NormalTheme"/>\n'
                '            <intent-filter>\n'
                '                <action android:name="android.intent.action.MAIN"/>\n'
                '                <category android:name="android.intent.category.'
                'LAUNCHER"/>\n'
                '            </intent-filter>\n'
                '        </activity>\n'
                '        <meta-data\n'
                '            android:name="flutterEmbedding"\n'
                '            android:value="2"/>\n'
                '    </application>\n'
                '</manifest>\n',
                encoding="utf-8",
            )

            # ── MainActivity.kt ──────────────────────────────────────
            kotlin_dir = (
                project_dir / "android" / "app" / "src" / "main" / "kotlin"
                / "com" / "temp" / "app"
            )
            kotlin_dir.mkdir(parents=True, exist_ok=True)
            (kotlin_dir / "MainActivity.kt").write_text(
                "package com.temp.app\n\n"
                "import io.flutter.embedding.android.FlutterActivity\n\n"
                "class MainActivity: FlutterActivity()\n",
                encoding="utf-8",
            )

            # ── app/build.gradle ─────────────────────────────────────
            app_bg = project_dir / "android" / "app" / "build.gradle"
            app_bg.write_text(
                "plugins {\n"
                '    id "com.android.application"\n'
                '    id "kotlin-android"\n'
                '    id "dev.flutter.flutter-gradle-plugin"\n'
                "}\n"
                "android {\n"
                "    namespace 'com.temp.app'\n"
                f"    compileSdk {versions['compileSdk']}\n"
                "    defaultConfig {\n"
                "        applicationId 'com.temp.app'\n"
                f"        minSdk {versions['minSdk']}\n"
                f"        targetSdk {versions['targetSdk']}\n"
                "        versionCode 1\n"
                "        versionName '1.0.0'\n"
                "    }\n"
                "}\n"
                "flutter {\n"
                "    source '../..'\n"
                "}\n"
                "dependencies {\n"
                "    implementation 'androidx.core:core-ktx:1.12.0'\n"
                "}\n",
                encoding="utf-8",
            )

            # ── Project-level build.gradle ───────────────────────────
            (project_dir / "android" / "build.gradle").write_text(
                "buildscript {\n"
                f"    ext.kotlin_version = '{versions['kotlin']}'\n"
                "    repositories {\n"
                "        google()\n"
                "        mavenCentral()\n"
                "    }\n"
                "    dependencies {\n"
                f'        classpath "com.android.tools.build:gradle:{versions["agp"]}"\n'
                "        classpath \"org.jetbrains.kotlin:kotlin-gradle-plugin:"
                "$kotlin_version\"\n"
                "    }\n"
                "}\n"
                "allprojects {\n"
                "    repositories {\n"
                "        google()\n"
                "        mavenCentral()\n"
                "    }\n"
                "}\n"
                "rootProject.buildDir = '../build'\n"
                "subprojects {\n"
                "    project.buildDir = \"${rootProject.buildDir}/${project.name}\"\n"
                "}\n"
                "subprojects {\n"
                "    project.evaluationDependsOn(\":app\")\n"
                "}\n"
                "tasks.register(\"clean\", Delete) {\n"
                "    delete rootProject.buildDir\n"
                "}\n",
                encoding="utf-8",
            )

            # ── settings.gradle ──────────────────────────────────────
            (project_dir / "android" / "settings.gradle").write_text(
                "pluginManagement {\n"
                "    def flutterSdkPath = {\n"
                "        def properties = new Properties()\n"
                '        file("local.properties").withInputStream '
                "{ properties.load(it) }\n"
                '        def sdk = properties.getProperty("flutter.sdk")\n'
                "        assert sdk != null: "
                '"flutter.sdk not set in local.properties"\n'
                "        return sdk\n"
                "    }()\n"
                "    includeBuild(\"${flutterSdkPath}/packages/"
                "flutter_tools/gradle\")\n"
                "    repositories {\n"
                "        google()\n"
                "        mavenCentral()\n"
                "        gradlePluginPortal()\n"
                "    }\n"
                "}\n"
                "plugins {\n"
                '    id "dev.flutter.flutter-plugin-loader" version "1.0.0"\n'
                f'    id "com.android.application" version "{versions["agp"]}" apply false\n'
                f'    id "org.jetbrains.kotlin.android" version "{versions["kotlin"]}" apply false\n'
                "}\n"
                'include ":app"\n',
                encoding="utf-8",
            )

            # ── gradle.properties ────────────────────────────────────
            (project_dir / "android" / "gradle.properties").write_text(
                "org.gradle.jvmargs=-Xmx4G\n"
                "android.useAndroidX=true\n"
                "android.enableJetifier=true\n",
                encoding="utf-8",
            )

            # ── gradle-wrapper.properties (escape simples \\: ) ──────
            (project_dir / "android" / "gradle" / "wrapper"
             / "gradle-wrapper.properties").write_text(
                "distributionBase=GRADLE_USER_HOME\n"
                "distributionPath=wrapper/dists\n"
                "zipStoreBase=GRADLE_USER_HOME\n"
                "zipStorePath=wrapper/dists\n"
                "distributionUrl=https\\://services.gradle.org/"
                f"distributions/gradle-{versions['gradle']}-all.zip\n",
                encoding="utf-8",
            )

            # ── local.properties placeholder ─────────────────────────
            (project_dir / "android" / "local.properties").write_text(
                "# flutter.sdk será definido pelo FlutterBuildOrchestrator\n",
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

        def _update_ai_status(self, status: str, detail: str = ""):
            """Atualiza indicador visual ◉ e opcionalmente loga detalhe.
            status: idle(gray), testing(yellow), connected(green), error(red)
            """
            colors = {
                "idle": "#888888",
                "testing": "#FFA000",
                "connected": "#4CAF50",
                "error": "#FF5722",
            }
            labels = {
                "idle": "ocioso",
                "testing": "testando...",
                "connected": "conectado",
                "error": "falha",
            }
            color = colors.get(status, "#888888")
            self.lbl_ai_live_status.configure(text_color=color)
            if status == "connected":
                self.api_provider_menu.configure(fg_color="#1B5E20")
            elif status == "error":
                self.api_provider_menu.configure(fg_color="#BF360C")
            else:
                self.api_provider_menu.configure(fg_color=("gray75", "gray25"))
            if detail:
                tag = labels.get(status, status)
                self.log.info(f"[IA ◉ {tag}] {detail}")

        def _schedule_ai_health_check(self):
            """Testa silenciosamente (log apenas em mudanca de status, 60s)."""
            if not self.api_key:
                self.after(60000, self._schedule_ai_health_check)
                return
            provider = self.api_provider
            model = self._auto_selected_models.get(provider, "")
            if not model:
                self.after(60000, self._schedule_ai_health_check)
                return
            import time as _time
            start = _time.time()
            prev = getattr(self, "_health_prev_ok", None)
            ok = self._test_chat_model(provider, self.api_key, model)
            elapsed = (_time.time() - start) * 1000
            if ok != prev:
                detail = "Health-check " + ("OK" if ok else "FALHOU") + f" | {provider}/{model} | {elapsed:.0f}ms"
                self._update_ai_status("connected" if ok else "error", detail)
                self._health_prev_ok = ok
                if not ok:
                    self.log.info(
                        f"Modelo {model} falhou — procurando alternativa..."
                    )
                    threading.Thread(
                        target=self._do_recover_model,
                        args=(provider,), daemon=True
                    ).start()
            self.after(60000, self._schedule_ai_health_check)

        def _do_recover_model(self, provider: str):
            fallback_models = self._model_fallback_cache.get(provider, [])
            if not fallback_models:
                fallback_models = self._list_models_for_provider(provider, self.api_key)
                self._model_fallback_cache[provider] = fallback_models
            current = self._auto_selected_models.get(provider, "")
            candidates = [m for m in fallback_models if m != current]
            for mid in candidates[:5]:
                self._update_ai_status("testing", f"Testando fallback: {mid}...")
                ok = self._test_chat_model(provider, self.api_key, mid)
                if ok:
                    self._auto_selected_models[provider] = mid
                    if provider in self.OPENAI_COMPATIBLE:
                        self.OPENAI_COMPATIBLE[provider] = (
                            self.OPENAI_COMPATIBLE[provider][0], mid
                        )
                    elif provider in self._custom_providers:
                        self._custom_providers[provider]["model"] = mid
                    self._update_ai_status(
                        "connected",
                        f"Fallback \u2192 {provider}/{mid} OK"
                    )
                    self.log.ok(
                        f"Modelo recuperado automaticamente: {mid}"
                    )
                    return
            self._update_ai_status(
                "error",
                f"{provider}: nenhum modelo alternativo funcional"
            )
            self.log.warn(
                "Nenhum modelo funcional encontrado — "
                "clique em 'Salvar Chave' para re-validar ou obtenha uma nova chave"
            )

        def _auto_validate_on_startup(self):
            if not self.api_key:
                self.after(5000, self._schedule_ai_health_check)
                return
            self._update_ai_status("testing", "Validando chave salva...")
            threading.Thread(target=self._do_startup_validation, daemon=True).start()

        def _do_startup_validation(self):
            provider = self.api_provider
            self._update_ai_status("testing", f"Auto-validando {provider}...")
            working = self._auto_select_model(provider, self.api_key, force=True)
            if working:
                kb_fixes = self.kb._db.get("fixes", [])
                self._update_ai_status(
                    "connected",
                    f"{provider}/{working} OK — KB: {len(kb_fixes)} correções"
                )
                self.after(0, lambda: self.log.ok(
                    "Conexão IA+KB estabelecida automaticamente"
                ))
            else:
                self._update_ai_status(
                    "error",
                    f"{provider}: nenhum modelo funcional encontrado"
                )
                self.after(0, lambda: self.log.warn(
                    "Nenhum modelo funcional — clique em 'Salvar Chave' "
                    "para re-validar ou obtenha uma nova chave de API"
                ))
            self.after(60000, self._schedule_ai_health_check)

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
            self._update_ai_status("testing", f"Auto-validando chave {provider}...")
            if provider == "Gemini":
                from gui.gemini_fixer import GeminiCodeFixer
                ok, msg = GeminiCodeFixer.validate_key(self.api_key)
                if ok:
                    working = self._auto_select_model("Gemini", self.api_key, force=True)
                    if working:
                        msg = f"OK \u2014 modelo: {working}"
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

        def _migrate_provider(self, new_provider: str):
            """Migra para provedor alternativo que funciona com esta chave."""
            old = self.api_provider
            self.api_provider = new_provider
            self.api_provider_menu.set(new_provider)
            self._save_state()
            self.log.ok(
                f"Provedor migrado automaticamente: {old} \u2192 {new_provider}"
            )

        def _show_auto_validate_result(self, ok: bool, msg: str):
            if ok:
                if "modelo:" not in msg and self.api_provider != "Ollama (local)":
                    self._update_ai_status(
                        "testing",
                        "Provedor sem modelo de chat — testando outros provedores..."
                    )
                    found = self._find_working_provider(self.api_key)
                    if found:
                        self._migrate_provider(found)
                        w = self._auto_selected_models.get(found, "")
                        msg = f"OK \u2014 migrado para {found}, modelo: {w}"
                    else:
                        msg += " (sem modelo de chat — tente outra chave)"
                self.lbl_api_status.configure(
                    text=f"✓ {msg}", text_color="#4CAF50"
                )
                self._update_ai_status("connected", f"{self.api_provider}: {msg}")
            else:
                self._update_ai_status(
                    "testing",
                    "Chave inválida — testando outros provedores..."
                )
                found = self._find_working_provider(self.api_key)
                if found:
                    self._migrate_provider(found)
                    w = self._auto_selected_models.get(found, "")
                    msg = f"OK \u2014 chave funciona com {found}, modelo: {w}"
                    ok = True
                    self._update_ai_status("connected", msg)
                else:
                    msg = f"Chave n\u00e3o funciona com nenhum provedor"
                    self._update_ai_status("error", msg)
                self.lbl_api_status.configure(
                    text=f"{'✓' if ok else '✗'} {msg}",
                    text_color="#4CAF50" if ok else "#FF5722",
                )

        def _save_api_key(self):
            key = self.api_key_entry.get().strip()
            if not key:
                messagebox.showwarning("Aviso", "Digite uma chave primeiro")
                return
            self.api_key = key
            self._save_state()
            self.log.ok(
                f"Chave salva para {self.api_provider} "
                f"(termina em ...{key[-4:]})"
            )
            self._update_ai_status("testing", "Validando chave salva...")
            threading.Thread(
                target=self._do_validate_saved_key,
                args=(key,), daemon=True
            ).start()

        def _do_validate_saved_key(self, key: str):
            provider = self.api_provider
            self._update_ai_status("testing", f"Validando chave {provider}...")
            working = self._auto_select_model(provider, key, force=True)
            if working:
                self._update_ai_status(
                    "connected",
                    f"{provider}/{working} OK"
                )
                self.after(0, lambda: self.log.ok(
                    "Chave validada automaticamente ap\u00f3s salvar"
                ))
            else:
                self._update_ai_status("error", f"{provider}: chave inv\u00e1lida")
                self.after(0, lambda: self.log.err(
                    "Chave n\u00e3o funciona — clique no link 'Obter chave' "
                    "para gerar uma nova"
                ))

        def _open_provider_key_url(self):
            provider = self.api_provider
            url = self.PROVIDER_KEY_URLS.get(provider)
            if not url:
                url = "https://www.google.com/search?q=" + provider.replace(" ", "+") + "+API+key"
            import webbrowser
            webbrowser.open(url)
            self.log.info(f"Link aberto: {url}")

        def _validate_openai_key(self, key: str):
            return self._validate_openai_compatible(key, "OpenAI",
                "https://api.openai.com/v1/models")

        def _list_models_for_provider(self, provider: str,
                                        key: str) -> list:
            """Retorna lista de IDs de modelo dispon\u00edveis para qualquer provedor."""
            try:
                if provider == "Gemini":
                    url = ("https://generativelanguage.googleapis.com/v1beta/"
                           f"models?key={key}")
                    with urllib.request.urlopen(url, timeout=10) as r:
                        data = json.loads(r.read())
                    return [m["name"].replace("models/", "")
                            for m in data.get("models", [])
                            if "generateContent" in m.get("supportedGenerationMethods", [])]
                elif provider == "Anthropic":
                    req = urllib.request.Request(
                        "https://api.anthropic.com/v1/models",
                        headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
                    )
                    with urllib.request.urlopen(req, timeout=10) as r:
                        data = json.loads(r.read())
                    return [m["id"] for m in data.get("data", []) if m.get("id")]
                elif provider == "OpenRouter":
                    req = urllib.request.Request(
                        "https://openrouter.ai/api/v1/models",
                        headers={"Authorization": f"Bearer {key}"},
                    )
                    with urllib.request.urlopen(req, timeout=10) as r:
                        data = json.loads(r.read())
                    raw = data.get("data", [])
                    return [m["id"] for m in raw if m.get("id")]
                elif provider in self.OPENAI_COMPATIBLE:
                    base_url = self.OPENAI_COMPATIBLE[provider][0].rstrip("/")
                    req = urllib.request.Request(
                        f"{base_url}/models",
                        headers={"Authorization": f"Bearer {key}"},
                    )
                    with urllib.request.urlopen(req, timeout=10) as r:
                        data = json.loads(r.read())
                    return [m["id"] for m in data.get("data", []) if m.get("id")]
                elif provider in self._custom_providers:
                    cfg = self._custom_providers[provider]
                    url = cfg["url"].rstrip("/")
                    if not url.endswith("/models"):
                        url += "/models"
                    hdr = {cfg.get("auth_header", "Authorization"):
                           f"{cfg.get('auth_prefix', 'Bearer ')}{key}"}
                    req = urllib.request.Request(url, headers=hdr)
                    with urllib.request.urlopen(req, timeout=10) as r:
                        data = json.loads(r.read())
                    return [m["id"] for m in data.get("data", data.get("models", []))
                            if isinstance(m, dict) and m.get("id")]
                elif provider == "Ollama (local)":
                    req = urllib.request.Request("http://localhost:11434/api/tags")
                    with urllib.request.urlopen(req, timeout=5) as r:
                        data = json.loads(r.read())
                    names = [m.get("name", "") for m in data.get("models", [])
                             if m.get("name")]
                    self._ollama_models_cache = names
                    return names
                return []
            except Exception:
                return []

        def _test_chat_model(self, provider: str, key: str,
                              model_id: str) -> bool:
            """Testa se um modelo responde a chat completions."""
            try:
                if provider == "Gemini":
                    url = ("https://generativelanguage.googleapis.com/v1beta/"
                           f"models/{model_id}:generateContent?key={key}")
                    payload = json.dumps({
                        "contents": [{"parts": [{"text": "hi"}]}],
                        "generationConfig": {"maxOutputTokens": 5},
                    })
                    req = urllib.request.Request(
                        url, data=payload.encode(),
                        headers={"Content-Type": "application/json"},
                    )
                    with urllib.request.urlopen(req, timeout=15) as r:
                        resp = json.loads(r.read())
                    return bool(resp.get("candidates"))
                elif provider == "Anthropic":
                    payload = json.dumps({
                        "model": model_id, "max_tokens": 5,
                        "messages": [{"role": "user", "content": "hi"}],
                    })
                    req = urllib.request.Request(
                        "https://api.anthropic.com/v1/messages",
                        data=payload.encode(),
                        headers={
                            "Content-Type": "application/json",
                            "x-api-key": key,
                            "anthropic-version": "2023-06-01",
                        },
                        method="POST",
                    )
                    with urllib.request.urlopen(req, timeout=15) as r:
                        resp = json.loads(r.read())
                    return bool(resp.get("content"))
                else:
                    if provider in self.OPENAI_COMPATIBLE:
                        base_url = self.OPENAI_COMPATIBLE[provider][0].rstrip("/")
                        auth = f"Bearer {key}"
                    elif provider == "OpenRouter":
                        base_url = "https://openrouter.ai/api/v1"
                        auth = f"Bearer {key}"
                    elif provider in self._custom_providers:
                        cfg = self._custom_providers[provider]
                        base_url = cfg["url"].rstrip("/")
                        auth = f"{cfg.get('auth_prefix', 'Bearer ')}{key}"
                    else:
                        return False
                    payload = json.dumps({
                        "model": model_id,
                        "messages": [{"role": "user", "content": "hi"}],
                        "max_tokens": 5,
                    })
                    req = urllib.request.Request(
                        f"{base_url}/chat/completions",
                        data=payload.encode(),
                        headers={
                            "Content-Type": "application/json",
                            "Authorization": auth,
                        },
                        method="POST",
                    )
                    with urllib.request.urlopen(req, timeout=15) as r:
                        resp = json.loads(r.read())
                    return bool(resp.get("choices"))
            except urllib.error.HTTPError as e:
                if provider in ("NVIDIA",) and e.code == 401:
                    self._bad_models.add(model_id)
                return False
            except Exception:
                return False

        def _try_key_on_all_providers(self, key: str) -> list:
            """Testa a chave contra TODOS os provedores. Retorna [(provider, models_count), ...]."""
            results = []
            providers_to_test = []

            # Provedores OpenAI-compatible
            for prov in self.OPENAI_COMPATIBLE:
                providers_to_test.append((prov, "openai_compatible"))
            providers_to_test.append(("OpenAI", "openai_compatible"))
            providers_to_test.append(("Anthropic", "anthropic"))
            providers_to_test.append(("OpenRouter", "openrouter"))
            # Gemini testado separadamente via GeminiCodeFixer
            providers_to_test.append(("Gemini", "gemini"))

            # Custom providers
            for prov in self._custom_providers:
                providers_to_test.append((prov, "custom"))

            for prov, ptype in providers_to_test:
                try:
                    if ptype == "gemini":
                        from gui.gemini_fixer import GeminiCodeFixer
                        ok, msg = GeminiCodeFixer.validate_key(key)
                        if ok:
                            results.append((prov, "gemini", 0))
                        elif "modelos" in msg:
                            results.append((prov, "gemini", 1))
                    elif ptype == "anthropic":
                        req = urllib.request.Request(
                            "https://api.anthropic.com/v1/models",
                            headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
                        )
                        with urllib.request.urlopen(req, timeout=8) as r:
                            data = json.loads(r.read())
                        models = data.get("data", [])
                        results.append((prov, "anthropic", len(models)))
                    elif ptype == "openrouter":
                        req = urllib.request.Request(
                            "https://openrouter.ai/api/v1/models",
                            headers={"Authorization": f"Bearer {key}"},
                        )
                        with urllib.request.urlopen(req, timeout=8) as r:
                            data = json.loads(r.read())
                        models = data.get("data", [])
                        results.append((prov, "openai", len(models)))
                    elif ptype == "openai_compatible":
                        base_url = self.OPENAI_COMPATIBLE[prov][0].rstrip("/")
                        req = urllib.request.Request(
                            f"{base_url}/models",
                            headers={"Authorization": f"Bearer {key}"},
                        )
                        with urllib.request.urlopen(req, timeout=8) as r:
                            data = json.loads(r.read())
                        models = data.get("data", [])
                        results.append((prov, "openai", len(models)))
                    elif ptype == "custom":
                        cfg = self._custom_providers.get(prov, {})
                        url = cfg.get("url", "").rstrip("/")
                        if not url:
                            continue
                        hdr = {cfg.get("auth_header", "Authorization"):
                               f"{cfg.get('auth_prefix', 'Bearer ')}{key}"}
                        models_url = url + "/models" if not url.endswith("/models") else url
                        req = urllib.request.Request(models_url, headers=hdr)
                        with urllib.request.urlopen(req, timeout=8) as r:
                            data = json.loads(r.read())
                        raw = data.get("data", data.get("models", []))
                        results.append((prov, "openai", len(raw)))
                except Exception:
                    continue
            return results

        def _find_working_provider(self, key: str) -> Optional[str]:
            """Testa chave contra TODOS os provedores at\u00e9 achar um com chat funcional."""
            all_providers = self._try_key_on_all_providers(key)
            # Prioridade: provedores com mais modelos primeiro
            scored = []
            for entry in all_providers:
                prov = entry[0]
                # Tenta auto-select model
                working = self._auto_select_model(prov, key, force=True)
                if working:
                    scored.append((prov, working, 100))
            if scored:
                scored.sort(key=lambda x: -x[2])
                best = scored[0]
                self.log.ok(
                    f"Chave funciona com {best[0]} (modelo: {best[1]})"
                )
                return best[0]
            return None

        def _auto_select_model(self, provider: str, key: str,
                                force: bool = False) -> Optional[str]:
            """Auto-seleciona modelo funcional para QUALQUER provedor."""
            if not key:
                return None

            cached = self._auto_selected_models.get(provider)
            if cached and cached not in self._bad_models and not force:
                return cached

            self._update_ai_status("testing", f"Listando modelos de {provider}...")
            models = self._list_models_for_provider(provider, key)
            if not models:
                self._update_ai_status("error", f"{provider}: 0 modelos disponíveis")
                return None

            self._update_ai_status(
                "testing", f"{provider}: {len(models)} modelos disponíveis"
            )
            self._model_fallback_cache[provider] = models

            skip_keywords = ["embedding", "tts", "whisper", "davinci",
                             "babbage", "curie", "ada", "moderation",
                             "similarity", "edit"]
            chat_keywords = ["gpt", "claude", "gemini", "llama", "mistral",
                             "mixtral", "command", "jamba", "grok", "sonar",
                             "deepseek", "qwen", "phi", "nemotron", "dbrx",
                             "yi", "chat", "flash", "pro", "haiku",
                             "sonnet", "opus"]

            candidates = [m for m in models
                          if not any(s in m.lower() for s in skip_keywords)
                          and m not in self._bad_models]
            chat_first = [m for m in candidates
                          if any(k in m.lower() for k in chat_keywords)]
            other = [m for m in candidates if m not in chat_first]
            ordered = chat_first + other

            tested = 0
            import time as _time
            for mid in ordered[:20]:
                tested += 1
                t0 = _time.time()
                self._update_ai_status(
                    "testing", f"Testando modelo [{tested}/{len(ordered[:20])}]: {mid}..."
                )
                ok = self._test_chat_model(provider, key, mid)
                elapsed = (_time.time() - t0) * 1000
                if ok:
                    self._auto_selected_models[provider] = mid
                    if provider in self.OPENAI_COMPATIBLE:
                        self.OPENAI_COMPATIBLE[provider] = (
                            self.OPENAI_COMPATIBLE[provider][0], mid
                        )
                    elif provider in self._custom_providers:
                        self._custom_providers[provider]["model"] = mid
                    self._update_ai_status(
                        "connected",
                        f"{provider}/{mid} OK ({elapsed:.0f}ms)"
                    )
                    return mid
                self._update_ai_status(
                    "testing",
                    f"Modelo {mid} falhou ({elapsed:.0f}ms) — testando próximo..."
                )

            self._update_ai_status(
                "error",
                f"{provider}: 0/{tested} modelos confirmaram chat — "
                "chave sem permissão de inferência?"
            )
            return None

        def _validate_openai_compatible(self, key: str, provider: str,
                                         base_url: str = None):
            """Valida chave contra API compat\u00edvel com OpenAI + auto-select model."""
            url = base_url or self.OPENAI_COMPATIBLE.get(provider, [None])[0]
            if not url:
                cfg = self.OPENAI_COMPATIBLE.get(provider)
                if cfg:
                    url = cfg[0].rstrip("/") + "/models"
            if not url:
                return False, "URL n\u00e3o configurada"
            import time as _time
            _t0 = _time.time()
            self._update_ai_status("testing", f"Handshake: {url}...")
            try:
                req = urllib.request.Request(
                    url, headers={"Authorization": f"Bearer {key}"},
                )
                resp_status = 0
                with urllib.request.urlopen(req, timeout=10) as r:
                    resp_status = r.status
                _t1 = _time.time()
                self._update_ai_status(
                    "testing",
                    f"Handshake OK (HTTP {resp_status}) | {(_t1-_t0)*1000:.0f}ms | Selecionando modelo..."
                )
                working = self._auto_select_model(provider, key, force=True)
                if working:
                    return True, (f"OK \u2014 modelo: {working}")
                self._update_ai_status(
                    "error",
                    f"API responde (HTTP {resp_status}) mas nenhum modelo aceita a chave"
                )
                return False, "Nenhum modelo respondeu — chave sem permiss\u00e3o de infer\u00eancia?"
            except urllib.error.HTTPError as e:
                _t1 = _time.time()
                self._update_ai_status(
                    "error",
                    f"HTTP {e.code} ({(_t1-_t0)*1000:.0f}ms)"
                )
                if e.code == 401:
                    return False, "Chave inv\u00e1lida"
                return False, f"HTTP {e.code}: {e.reason[:100]}"
            except Exception as e:
                _t1 = _time.time()
                err = str(e)
                self._update_ai_status(
                    "error",
                    f"Falha ({(_t1-_t0)*1000:.0f}ms): {err[:80]}"
                )
                if "401" in err:
                    return False, "Chave inv\u00e1lida"
                return False, f"Erro: {err[:100]}"

        def _validate_anthropic_key(self, key: str):
            try:
                req = urllib.request.Request(
                    "https://api.anthropic.com/v1/messages",
                    data=json.dumps(
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
                with urllib.request.urlopen(req, timeout=15) as r:
                    working = self._auto_select_model("Anthropic", key, force=True)
                    if working:
                        return True, f"Chave v\u00e1lida, modelo: {working}"
                    return True, "Chave v\u00e1lida"
            except urllib.error.HTTPError as e:
                if e.code == 401:
                    return False, "Chave inv\u00e1lida"
                if e.code == 403:
                    return False, "Sem permiss\u00e3o"
                return False, f"HTTP {e.code}: {e.reason[:100]}"
            except Exception as e:
                return False, f"Erro: {str(e)[:100]}"

        def _validate_openrouter_key(self, key: str):
            try:
                req = urllib.request.Request(
                    "https://openrouter.ai/api/v1/auth/key",
                    headers={"Authorization": f"Bearer {key}"},
                )
                with urllib.request.urlopen(req, timeout=10) as r:
                    working = self._auto_select_model("OpenRouter", key, force=True)
                    if working:
                        return True, f"Chave v\u00e1lida, modelo: {working}"
                    return True, "Chave v\u00e1lida"
            except urllib.error.HTTPError as e:
                if e.code == 401:
                    return False, "Chave inv\u00e1lida"
                return False, f"HTTP {e.code}: {e.reason[:100]}"
            except Exception as e:
                return False, f"Erro: {str(e)[:100]}"

        def _validate_ollama(self):
            try:
                working = self._auto_select_model("Ollama (local)", "", force=True)
                if working:
                    models = self._ollama_models_cache or [working]
                    return True, (f"OK \u2014 {len(models)} modelos, "
                                   f"auto: {working}")
                return True, "Ollama rodando (sem modelos)"
            except Exception:
                return False, "Ollama n\u00e3o encontrado em localhost:11434"

        def _validate_custom_provider(self, key: str):
            cfg = self._custom_providers.get(self.api_provider)
            if not cfg:
                return False, "Configura\u00e7\u00e3o do provedor n\u00e3o encontrada"
            url = cfg["url"]
            auth_header = cfg.get("auth_header", "Authorization")
            auth_prefix = cfg.get("auth_prefix", "Bearer ")
            try:
                # Testa conectividade com GET na URL base
                hdr = {auth_header: f"{auth_prefix}{key}"}
                req = urllib.request.Request(url, headers=hdr, method="GET")
                with urllib.request.urlopen(req, timeout=10) as r:
                    pass
                working = self._auto_select_model(self.api_provider, key, force=True)
                if working:
                    cfg["model"] = working
                    return True, f"OK \u2014 modelo: {working}"
                return True, "Conectado"
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

        def _on_progress(self, percent: int, status: str):
            self.progress_bar.set(percent / 100.0)
            self.lbl_progress_status.configure(
                text=f"{percent}% — {status}"
            )
            self.update_idletasks()

        def _run_build(self):
            self._set_build_state(True)
            self._on_progress(0, "Iniciando...")
            self._save_state()
            try:
                release = self._release_var.get()
                skip = self.check_skip_tests.get()
                auto_install = self.check_auto_install.get()

                self.log.info(
                    f"Build em: {self.project_dir} "
                    f"({'Release' if release else 'Debug'})"
                )

                kb_path = str(Path(__file__).resolve().parent.parent / "known_fixes.json")
                selected_model = self._auto_selected_models.get(
                    self.api_provider
                )

                # Lista de fallback de modelos (todos exceto o atual)
                all_models = []
                try:
                    if self.api_provider in self.OPENAI_COMPATIBLE:
                        all_models = self._list_models_for_provider(
                            self.api_provider, self.api_key
                        )
                    elif self.api_provider in self._custom_providers:
                        all_models = self._list_models_for_provider(
                            self.api_provider, self.api_key
                        )
                    elif self.api_provider == "Ollama (local)":
                        all_models = self._ollama_models_cache[:]
                except Exception as exc:
                    self.log.warn(
                        f"N\u00e3o foi poss\u00edvel listar modelos: {exc}"
                    )

                self.orch = FlutterBuildOrchestrator(
                    project_path=str(self.project_dir),
                    auto_install=auto_install,
                    log_callback=self._on_log,
                    progress_callback=self._on_progress,
                    api_provider=self.api_provider if self.api_key else None,
                    api_key=self.api_key or None,
                    api_model=selected_model,
                    model_fallback_list=all_models,
                    kb_path=kb_path,
                )
                success = self.orch.orchestrate(
                    skip_tests=skip,
                    debug=not release,
                )

                if success and self.check_install_adb.get() and self.adb_available:
                    self._install_via_adb()

                self._on_progress(100, "Conclu\u00eddo" if success else "Falhou")
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
            self.btn_save_api.configure(state=est)
            self.btn_select_adb.configure(state=est)
            self.btn_stop.configure(state="normal" if running else "disabled")
            # Pausa/retoma ADB poll para n\u00e3o floodar log durante build
            if running:
                self._stop_adb_poll()
            else:
                self._start_adb_poll()

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
                found = self._find_adb_path()
                if found and found != self._adb_path:
                    self._adb_path = found
                    self.log.ok(f"ADB localizado automaticamente: {Path(found).name}")
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
                    except Exception:
                        result["error"] = "ADB encontrado mas falhou ao listar devices"
                else:
                    result["error"] = "ADB não encontrado — use 'Selecionar ADB manualmente'"
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
