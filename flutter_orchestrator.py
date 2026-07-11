# -*- coding: utf-8 -*-
#!/usr/bin/env python3
"""
Flutter Build Orchestrator
Automatiza todo o processo de build de aplicativos Flutter, gerando APK pronto para instala\u00e7\u00e3o.
Unifica as funcionalidades dos dois scripts anteriores com auto-install e corre\u00e7\u00f5es autom\u00e1ticas.
"""

import hashlib
import os
import sys
import subprocess
import shutil
import argparse
import json
import platform
import re
import tempfile
import zipfile
import tarfile
import winsound
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError
from urllib.parse import urlparse

from orchestrator.timeout_manager import AdaptiveTimeoutManager
from orchestrator.ia_response_validator import IAResponseValidator
from orchestrator.model_manager import IntelligentModelManager
from orchestrator.kotlin_fixer import KotlinGradleFixer
from orchestrator.knowledge_base_learner import KnowledgeBaseLearner

try:
    import yaml
    YAML_AVAILABLE = True
except ImportError:
    YAML_AVAILABLE = False


# ---------------------------------------------------------------------------
#  Cores para terminal
# ---------------------------------------------------------------------------
class Color:
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    HEADER = '\033[95m'
    RESET = '\033[0m'
    BOLD = '\033[1m'


# ---------------------------------------------------------------------------
#  Log helpers
# ---------------------------------------------------------------------------
def _log(level, color, message):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"{color}[{ts}] [{level}] {message}{Color.RESET}")

def log_info(msg):    _log("INFO", Color.BLUE, msg)
def log_ok(msg):      _log("OK", Color.GREEN, msg)
def log_warn(msg):    _log("WARN", Color.YELLOW, msg)
def log_err(msg):     _log("ERROR", Color.RED, msg)
def log_step(msg):
    print(f"\n{Color.HEADER}{'='*60}{Color.RESET}")
    print(f"{Color.BOLD}{msg}{Color.RESET}")
    print(f"{Color.HEADER}{'='*60}{Color.RESET}")


# ---------------------------------------------------------------------------
#  Flutter version lookup (dynamic — avoids hardcoding)
# ---------------------------------------------------------------------------
def _fetch_latest_flutter_version() -> Optional[str]:
    """
    Consulta a release API do Flutter para obter a vers\u00e3o est\u00e1vel mais recente.
    Tenta a release JSON da plataforma atual, depois fallback para Linux.
    Retorna None se falhar (fallback para vers\u00e3o fixa conhecida).
    """
    system = platform.system()
    releases_files = {
        "Windows": "releases_windows.json",
        "Darwin": "releases_macos.json",
        "Linux": "releases_linux.json",
    }
    candidates = [releases_files.get(system, "releases_linux.json"),
                  "releases_linux.json"]
    for release_file in candidates:
        try:
            url = ("https://storage.googleapis.com/"
                   f"flutter_infra_release/releases/{release_file}")
            req = Request(url, headers={"User-Agent": "FlutterOrchestrator/1.0"})
            with urlopen(req, timeout=15) as r:
                data = json.loads(r.read())
            stable = [r for r in data.get("releases", [])
                      if r.get("channel") == "stable"]
            if stable:
                return stable[0]["version"]
        except Exception:
            continue
    return None


def _flutter_download_url() -> str:
    """Gera URL de download do Flutter para a plataforma atual."""
    system = platform.system()
    arch_map = {
        "Linux": "linux/flutter_linux_{version}-stable.tar.xz",
        "Darwin": "macos/flutter_macos_{version}-stable.zip",
        "Windows": "windows/flutter_windows_{version}-stable.zip",
    }
    arch_key = arch_map.get(system, "linux")
    version = _fetch_latest_flutter_version() or "3.24.0"
    base = "https://storage.googleapis.com/flutter_infra_release/releases/stable"
    return f"{base}/{arch_key.format(version=version)}"


# ---------------------------------------------------------------------------
#  Main orchestrator
# ---------------------------------------------------------------------------
class FlutterBuildOrchestrator:
    """Orquestrador de builds Flutter."""

    AI_PROVIDER_CONFIG = {
        "Gemini":    {"type": "gemini",    "url": None,
                      "model": "gemini-2.0-flash"},
        "OpenAI":    {"type": "openai",    "url": "https://api.openai.com/v1",
                      "model": "gpt-4o-mini"},
        "Anthropic": {"type": "anthropic","url": None,
                      "model": "claude-3-haiku-20240307"},
        "DeepSeek":  {"type": "openai",    "url": "https://api.deepseek.com/v1",
                      "model": "deepseek-chat"},
        "Mistral AI":{"type": "openai",    "url": "https://api.mistral.ai/v1",
                      "model": "mistral-large-latest"},
        "Groq":      {"type": "openai",    "url": "https://api.groq.com/openai/v1",
                      "model": "llama-3.3-70b-versatile"},
        "Together AI":{"type": "openai",   "url": "https://api.together.xyz/v1",
                      "model": "mistralai/Mixtral-8x7B-Instruct-v0.1"},
        "NVIDIA":    {"type": "openai",    "url": "https://integrate.api.nvidia.com/v1",
                      "model": "meta/llama-3.1-8b-instruct"},
        "Perplexity":{"type": "openai",    "url": "https://api.perplexity.ai",
                      "model": "sonar-pro"},
        "Cohere":    {"type": "openai",    "url": "https://api.cohere.ai/v1",
                      "model": "command-r-plus"},
        "xAI (Grok)":{"type": "openai",    "url": "https://api.x.ai/v1",
                      "model": "grok-2-latest"},
        "AI21 Labs": {"type": "openai",    "url": "https://api.ai21.com/studio/v1",
                      "model": "jamba-1.5-mini"},
        "OpenRouter":{"type": "openai",    "url": "https://openrouter.ai/api/v1",
                      "model": "openai/gpt-4o-mini"},
        "Mistral Mini": {"type": "openai", "url": "https://api.mistral.ai/v1",
                         "model": "mistralai/ministral-14b-instruct-2512"},
    }

    FALLBACK_MODELS = [
        "mistralai/ministral-14b-instruct-2512",
        "mistral-large-latest",
        "openai/gpt-4o-mini",
        "gemini-2.0-flash",
        "claude-3-haiku-20240307",
        "llama-3.3-70b-versatile",
        "command-r-plus",
        "deepseek-chat",
    ]

    COMMON_FLUTTER_PATHS = [
        "C:\\tools\\flutter",
        "C:\\flutter",
        "C:\\src\\flutter",
        str(Path.home() / "flutter"),
        str(Path.home() / "tools" / "flutter"),
        str(Path.home() / "src" / "flutter"),
        str(Path.home() / "sdk" / "flutter"),
        str(Path.home() / ".flutter_auto" / "flutter"),
        str(Path.home() / "AppData" / "Local" / "flutter"),
        str(Path.home() / "AppData" / "Local" / "Android" / "flutter"),
        os.environ.get("LOCALAPPDATA", "") + "\\flutter",
        os.environ.get("LOCALAPPDATA", "") + "\\Android\\flutter",
    ]

    def __init__(self, project_path: str,
                 output_dir: str = "build_output",
                 auto_install: bool = False,
                 log_callback=None,
                 progress_callback=None,
                 api_provider: str = None,
                 api_key: str = None,
                 api_model: str = None,
                 model_fallback_list: list = None,
                 kb_path: str = None):
        self.project_path = Path(project_path).resolve()
        if Path(output_dir).is_absolute():
            self.output_dir = Path(output_dir)
        else:
            self.output_dir = (self.project_path / output_dir).resolve()
        self.auto_install = auto_install
        self._log_callback = log_callback
        self._progress_callback = progress_callback
        self.build_log: List[Dict] = []
        self.start_time = datetime.now()
        self.flutter_cmd = "flutter"
        self.install_dir = Path.home() / ".flutter_auto"
        self._cancelled = False
        self.last_apk_path = None
        self.api_provider = api_provider
        self.api_key = api_key
        self.api_model = api_model
        self.kb_path = Path(kb_path) if kb_path else None
        self._last_errors = []
        self._last_fix_applied = None
        self._fix_cache = {}
        self._model_fallback_list = model_fallback_list or []
        self._fallback_attempt = 0
        self._consecutive_401 = 0
        self._last_401_provider = None
        self._ai_context = []
        self._project_profile = {"packages": [], "errors_seen": [], "fixes_applied": []}

        # Novos gerenciadores modulares
        self._timeout_manager = AdaptiveTimeoutManager()
        self._response_validator = IAResponseValidator()
        self._model_manager = IntelligentModelManager()

    class _LogAdapter:
        """Adapta a fun\u00e7\u00e3o log(level, msg) da orchestrator para interface Logger (obj.ok/err/warn/info)."""
        def __init__(self, log_fn):
            self._log = log_fn
        def ok(self, msg): self._log(msg, "SUCCESS")
        def err(self, msg): self._log(msg, "ERROR")
        def warn(self, msg): self._log(msg, "WARNING")
        def info(self, msg): self._log(msg, "INFO")

    def _progress(self, percent: int, status: str):
        if self._progress_callback:
            try:
                self._progress_callback(percent, status)
            except Exception:
                pass

    def cancel(self):
        self._cancelled = True

    @staticmethod
    def _find_flutter_path():
        """Procura flutter em locais comuns de instala\u00e7\u00e3o."""
        if os.name == "nt":
            candidates = FlutterBuildOrchestrator.COMMON_FLUTTER_PATHS
            for base in candidates:
                candidate = Path(base) / "bin" / "flutter.bat"
                if candidate.exists():
                    return str(candidate)
        else:
            candidates = [Path(p) for p in FlutterBuildOrchestrator.COMMON_FLUTTER_PATHS]
            for base in candidates:
                candidate = base / "bin" / "flutter"
                if candidate.exists():
                    return str(candidate)
        try:
            r = subprocess.run(["flutter", "--version"],
                               capture_output=True, text=True, timeout=10)
            if r.returncode == 0:
                return "flutter"
        except Exception:
            pass
        return None

    # ── Logging ────────────────────────────────────────────────────────

    def log(self, message: str, level: str = "INFO"):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.build_log.append({
            "timestamp": timestamp, "level": level, "message": message
        })
        color_map = {
            "INFO": Color.BLUE, "SUCCESS": Color.GREEN,
            "WARNING": Color.YELLOW, "ERROR": Color.RED, "STEP": Color.CYAN,
        }
        color = color_map.get(level, Color.RESET)
        print(f"{color}[{timestamp}] [{level}] {message}{Color.RESET}")
        if self._log_callback:
            self._log_callback(message, level)

    # ── Prerequisites ──────────────────────────────────────────────────

    def check_prerequisites(self) -> bool:
        self.log("Verificando pr\u00e9-requisitos...", "STEP")
        all_ok = True

        # Flutter — loop em vez de recursão para evitar estouro de pilha
        for _ in range(3):
            try:
                result = subprocess.run(
                    [self.flutter_cmd, "--version"],
                    capture_output=True, text=True, timeout=30
                )
                if result.returncode == 0:
                    v = result.stdout.split("\n")[0]
                    self.log(f"Flutter: {v}", "SUCCESS")
                    break
                raise Exception("Flutter --version falhou")
            except (FileNotFoundError, Exception):
                found = self._find_flutter_path()
                if found and found != self.flutter_cmd:
                    self.flutter_cmd = found
                    bin_dir = str(Path(found).parent)
                    self.install_dir = Path(found).parent.parent
                    self._write_local_properties()
                    os.environ["PATH"] = bin_dir + os.pathsep + os.environ.get("PATH", "")
                    self.log(f"Flutter localizado: {found}", "SUCCESS")
                    continue
                if self.auto_install:
                    self.log("Auto-instala\u00e7\u00e3o ativada...", "INFO")
                    if self._install_flutter():
                        continue
                self.log("Flutter n\u00e3o encontrado", "ERROR")
                all_ok = False
                break

        # Git
        try:
            subprocess.run(["git", "--version"],
                           capture_output=True, timeout=10)
            self.log("Git encontrado", "SUCCESS")
        except FileNotFoundError:
            self.log("Git n\u00e3o encontrado", "ERROR")
            all_ok = False

        # Java
        try:
            result = subprocess.run(
                ["java", "-version"],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0:
                v = result.stderr.split("\n")[0]
                self.log(f"Java: {v}", "SUCCESS")
            else:
                raise Exception("java -version falhou")
        except FileNotFoundError:
            warn = "Java n\u00e3o encontrado (necess\u00e1rio para build Android)"
            self.log(warn, "WARNING")

        return all_ok

    def _install_flutter(self) -> bool:
        """Baixa e instala o Flutter automaticamente."""
        self.log("Instalando Flutter automaticamente...", "STEP")
        self.install_dir.mkdir(parents=True, exist_ok=True)

        url = _flutter_download_url()
        filename = url.split("/")[-1]
        archive_path = self.install_dir / filename

        if not self._download_file(url, archive_path, "Flutter SDK"):
            return False
        if not self._extract_archive(archive_path, self.install_dir):
            return False
        if archive_path.exists():
            archive_path.unlink()

        flutter_bin = self.install_dir / "flutter" / "bin"
        if os.name == "nt":
            self.flutter_cmd = str(flutter_bin / "flutter.bat")
        else:
            self.flutter_cmd = str(flutter_bin / "flutter")

        os.environ["PATH"] = str(flutter_bin) + os.pathsep + os.environ.get("PATH", "")
        self.log(f"Flutter instalado em: {self.install_dir / 'flutter'}", "SUCCESS")

        # Gera local.properties no projeto
        self._write_local_properties()

        try:
            subprocess.run(
                [self.flutter_cmd, "doctor", "--android-licenses"],
                input="y\n" * 5, text=True,
                capture_output=True, timeout=120,
            )
        except Exception:
            pass

        return True

    def _write_local_properties(self):
        """Escreve android/local.properties com o caminho do Flutter SDK."""
        local_props = self.project_path / "android" / "local.properties"
        try:
            (self.project_path / "android").mkdir(parents=True, exist_ok=True)
            flutter_sdk = str((self.install_dir / "flutter").resolve())
            sdk_path = os.environ.get("ANDROID_HOME", "")
            if not sdk_path:
                sdk_path = os.environ.get("ANDROID_SDK_ROOT", "")
            if not sdk_path:
                sdk_path = str(
                    Path(os.environ.get("LOCALAPPDATA", "C:\\"))
                    / "Android" / "Sdk"
                ) if os.name == "nt" else "$HOME/Android/Sdk"
            local_props.write_text(
                f"sdk.dir={sdk_path}\n"
                f"flutter.sdk={flutter_sdk}\n"
                f"flutter.buildMode=release\n"
                f"flutter.versionName=1.0.0\n"
                f"flutter.versionCode=1\n",
                encoding="utf-8",
            )
            self.log("local.properties gerado", "SUCCESS")
        except Exception as e:
            self.log(f"Erro ao gerar local.properties: {e}", "WARNING")

    def _download_file(self, url: str, dest: Path, desc: str = "Arquivo") -> bool:
        self.log(f"Baixando {desc}...", "INFO")
        try:
            with urlopen(url) as response:
                total = int(response.getheader("Content-Length", 0))
                downloaded = 0
                with open(dest, "wb") as f:
                    while True:
                        buf = response.read(8192)
                        if not buf:
                            break
                        f.write(buf)
                        downloaded += len(buf)
                        if total > 0:
                            pct = (downloaded / total) * 100
                            sys.stdout.write(f"\r  {pct:.1f}%")
                            sys.stdout.flush()
                    print()
            self.log(f"Download conclu\u00eddo: {dest.name}", "SUCCESS")
            return True
        except Exception as e:
            self.log(f"Falha no download: {e}", "ERROR")
            return False

    def _extract_archive(self, archive_path: Path, dest_dir: Path) -> bool:
        self.log(f"Extraindo {archive_path.name}...", "INFO")
        try:
            # Path traversal prevention: resolve and verify
            dest_resolved = dest_dir.resolve()

            if archive_path.suffix == ".zip":
                with zipfile.ZipFile(archive_path, "r") as z:
                    for member in z.namelist():
                        member_path = (dest_resolved / member).resolve()
                        if not str(member_path).startswith(str(dest_resolved)):
                            self.log(f"Path traversal ignorado: {member}", "WARNING")
                            continue
                        z.extract(member, dest_dir)
            else:
                mode = "r:xz" if archive_path.suffix == ".xz" else "r:gz"
                if archive_path.suffix == ".tar":
                    mode = "r:"
                with tarfile.open(archive_path, mode) as t:
                    for member in t.getmembers():
                        member_path = (dest_resolved / member.name).resolve()
                        if not str(member_path).startswith(str(dest_resolved)):
                            self.log(
                                f"Path traversal ignorado: {member.name}", "WARNING"
                            )
                            continue
                        t.extract(member, dest_dir)
            self.log("Extra\u00e7\u00e3o conclu\u00edda.", "SUCCESS")
            return True
        except Exception as e:
            self.log(f"Falha na extra\u00e7\u00e3o: {e}", "ERROR")
            return False

    # ── Project validation ─────────────────────────────────────────────

    def validate_flutter_project(self) -> bool:
        self.log("Validando projeto Flutter...", "STEP")
        pubspec = self.project_path / "pubspec.yaml"
        if not pubspec.exists():
            self.log("pubspec.yaml n\u00e3o encontrado", "ERROR")
            return False
        self.log("pubspec.yaml encontrado", "SUCCESS")
        self._validate_and_fix_pubspec(pubspec)
        return True

    def _validate_and_fix_pubspec(self, pubspec_path: Path):
        """Valida e corrige erros de sintaxe no pubspec.yaml."""
        try:
            content = pubspec_path.read_text(encoding="utf-8")
        except Exception as e:
            self.log(f"Erro ao ler pubspec.yaml: {e}", "ERROR")
            return False

        fixed = False

        # Correction 1: merged lines
        lines = content.split("\n")
        new_lines = []
        for i, line in enumerate(lines):
            match = re.match(
                r"^(\s*)(\w+):\s*([^\n]+?)\s+(\w+):\s*(.*)$", line
            )
            if match and not line.strip().startswith("#"):
                indent, k1, v1, k2, v2 = match.groups()
                keys = {"version", "sdk", "environment", "dependencies", "flutter"}
                if k1 in keys or k2 in keys:
                    self.log(f"Linha {i+1}: separando '{k1}' e '{k2}'", "WARNING")
                    new_lines.append(f"{indent}{k1}: {v1.strip()}")
                    new_lines.append(f"{indent}{k2}: {v2.strip()}")
                    fixed = True
                else:
                    new_lines.append(line)
            else:
                new_lines.append(line)
        content = "\n".join(new_lines)

        # Correction 2: extra spaces in package names
        new_lines = []
        for line in content.split("\n"):
            match = re.match(r"^(\s+)([\w_]+)\s+([\w_]+):\s*(.*)$", line)
            if match and not line.strip().startswith("#"):
                indent, _, pkg2, ver = match.groups()
                self.log(f"Espa\u00e7o extra: corrigindo nome de pacote", "WARNING")
                new_lines.append(f"{indent}{pkg2}: {ver}")
                fixed = True
            else:
                new_lines.append(line)
        content = "\n".join(new_lines)

        # Correction 3: tabs -> spaces
        if "\t" in content:
            content = content.replace("\t", "  ")
            fixed = True

        if fixed:
            self.log("Corre\u00e7\u00f5es aplicadas ao pubspec.yaml", "SUCCESS")
            pubspec_path.write_text(content, encoding="utf-8")

        # Validate with PyYAML if available
        if YAML_AVAILABLE:
            try:
                yaml.safe_load(content)
                self.log("pubspec.yaml \u00e9 v\u00e1lido", "SUCCESS")
            except yaml.YAMLError as e:
                self.log(f"YAML inv\u00e1lido: {e}", "WARNING")
        else:
            self.log("PyYAML n\u00e3o dispon\u00edvel (valida\u00e7\u00e3o limitada)", "INFO")
        return True

    # ── Dependencies ───────────────────────────────────────────────────

    def get_dependencies(self) -> bool:
        self.log("Instalando depend\u00eancias...", "STEP")
        try:
            result = subprocess.run(
                [self.flutter_cmd, "pub", "get"],
                cwd=self.project_path, capture_output=True, text=True, timeout=300
            )
            if result.returncode == 0:
                self.log("Depend\u00eancias instaladas", "SUCCESS")
                return True
            self.log(f"Erro: {result.stderr[:300]}", "ERROR")
            return False
        except subprocess.TimeoutExpired:
            self.log("Timeout nas depend\u00eancias", "ERROR")
            return False
        except Exception as e:
            self.log(f"Erro: {e}", "ERROR")
            return False

    # ── Analysis ───────────────────────────────────────────────────────

    def analyze_code(self) -> bool:
        self.log("Analisando c\u00f3digo...", "STEP")
        try:
            result = subprocess.run(
                [self.flutter_cmd, "analyze"],
                cwd=self.project_path, capture_output=True, text=True, timeout=300
            )
            output = (result.stdout + result.stderr).lower()
            if result.returncode == 0 and "error:" not in output:
                self.log("An\u00e1lise sem erros", "SUCCESS")
                return True
            if "error:" in output:
                self.log("Erros de an\u00e1lise encontrados", "ERROR")
                self.log(result.stdout[:500], "INFO")
                return False
            self.log("Apenas warnings (continuando...)", "WARNING")
            return True
        except Exception as e:
            self.log(f"Erro: {e}", "ERROR")
            return False

    # ── Tests ──────────────────────────────────────────────────────────

    def run_tests(self, skip: bool = False) -> bool:
        if skip:
            self.log("Testes pulados (--skip-tests)", "INFO")
            return True
        self.log("Executando testes...", "STEP")
        test_dir = self.project_path / "test"
        if not test_dir.exists() or not list(test_dir.glob("*.dart")):
            self.log("Nenhum teste encontrado", "INFO")
            return True
        try:
            result = subprocess.run(
                [self.flutter_cmd, "test"],
                cwd=self.project_path, capture_output=True, text=True, timeout=600
            )
            if result.returncode == 0:
                self.log("Testes OK", "SUCCESS")
                return True
            self.log(f"Testes falharam: {result.stdout[:300]}", "ERROR")
            return False
        except Exception as e:
            self.log(f"Erro: {e}", "ERROR")
            return False

    # ── Build ──────────────────────────────────────────────────────────

    def build_apk(self, release: bool = True,
                  build_number: Optional[str] = None,
                  _skip_gradle_check: bool = False) -> bool:
        mode = "release" if release else "debug"
        self.log("Compilando APK (" + mode + ")", "STEP")
        self._progress(65, "Compilando APK (" + mode + ") - configurando Gradle...")
        try:
            cmd = [self.flutter_cmd, "build", "apk"]
            if release:
                cmd.append("--release")
            if build_number:
                cmd.extend(["--build-number", build_number])
            if _skip_gradle_check:
                cmd.append("--android-skip-build-dependency-validation")
            result = subprocess.run(
                cmd, cwd=self.project_path,
                capture_output=True, text=True, timeout=1800
            )
            if result.returncode == 0:
                self.log("APK compilado com sucesso", "SUCCESS")
                return True
            stderr = result.stderr[:2000]
            self.log(f"Erro: {stderr[:300]}...", "ERROR")

            # Auto-retry com flag de Gradle se erro for vers\u00e3o do Gradle ou KGP
            if not _skip_gradle_check and (
                "Gradle version" in stderr
                or "gradle" in stderr.lower()
                or "applies Kotlin Gradle Plugin" in stderr
                or "applies KGP" in stderr
            ):
                self.log(
                    "Tentando novamente com "
                    "--android-skip-build-dependency-validation...",
                    "INFO"
                )
                # Tamb\u00e9m aplica fix no settings.gradle para KGP
                self._fix_kgp_in_settings()
                # Usa KotlinGradleFixer para correcoes adicionais
                try:
                    kgp_fixer = KotlinGradleFixer(str(self.project_path))
                    fix_result = kgp_fixer.apply_fixes()
                    if fix_result['success']:
                        self.log(f"KotlinGradleFixer: {len(fix_result['fixes_applied'])} correcoes aplicadas", "SUCCESS")
                        try:
                            kb_learner = KnowledgeBaseLearner()
                            kb_learner.learn_from_build(
                                build_log=stderr, error=stderr,
                                solution="KotlinGradleFixer: remove .kts + recria build.gradle",
                                success=True
                            )
                            self.log("[KB] Solucao Kotlin registrada na KnowledgeBase.", "SUCCESS")
                        except Exception as kbe:
                            self.log(f"[KB] Erro ao registrar: {kbe}", "DEBUG")
                except Exception as kgp_e:
                    self.log(f"KotlinGradleFixer: {kgp_e}", "WARNING")
                return self.build_apk(release, build_number,
                                      _skip_gradle_check=True)

            # Tenta corre\u00e7\u00e3o via IA se configurada
            if self.api_key and self.api_provider:
                self.log("Tentando corre\u00e7\u00e3o autom\u00e1tica via IA...", "INFO")
                if self._fix_errors_and_retry(stderr, release, build_number):
                    return True
            return False
        except subprocess.TimeoutExpired:
            self.log("Timeout na compila\u00e7\u00e3o", "ERROR")
            return False
        except Exception as e:
            self.log(f"Erro: {e}", "ERROR")
            return False

    def _fix_kgp_in_settings(self):
        """Corrige settings.gradle para plugins que aplicam KGP (Kotlin Gradle Plugin)."""
        try:
            sg = self.project_path / "android" / "settings.gradle"
            if not sg.exists():
                return False
            text = sg.read_text(encoding="utf-8")
            marker = "resolutionStrategy"
            if marker in text:
                return False
            ktl_version = "2.1.0"
            try:
                from gui.app import BuildOrchestratorGUI
                versions = BuildOrchestratorGUI._get_template_versions()
                ktl_version = versions.get("kotlin", "2.1.0")
            except Exception:
                pass
            resolution_block = (
                "\n    resolutionStrategy {\n"
                "        eachPlugin {\n"
                '            if (requested.id.id == "org.jetbrains.kotlin.android") {\n'
                "                useVersion \"" + ktl_version + "\"\n"
                "            }\n"
                "        }\n"
                "    }\n"
            )
            insert_pos = text.find("repositories {")
            if insert_pos < 0:
                return False
            indent = ""
            line_start = text.rfind("\n", 0, insert_pos)
            if line_start >= 0:
                indent = text[line_start + 1:insert_pos]
            indented_block = ""
            for line in resolution_block.split("\n"):
                if line.strip():
                    indented_block += indent + line + "\n"
                else:
                    indented_block += "\n"
            text = text[:insert_pos] + indented_block + text[insert_pos:]
            sg.write_text(text, encoding="utf-8")
            self.log("settings.gradle corrigido para compatibilidade KGP", "SUCCESS")
            return True
        except Exception as e:
            self.log(f"Erro ao corrigir settings.gradle: {e}", "WARNING")
            return False

    # ── Artifacts ──────────────────────────────────────────────────────

    def _fix_plugin_namespaces(self):
        """Proactively fix missing namespace in Android plugin build.gradle files after pub get."""
        try:
            pkg_config = self.project_path / ".dart_tool" / "package_config.json"
            if not pkg_config.exists():
                return
            cfg = json.loads(pkg_config.read_text(encoding="utf-8"))
            pkgs = cfg.get("packages", [])
            fixed = 0
            for pkg in pkgs:
                root_uri = pkg.get("rootUri", "")
                if not root_uri.startswith("file://"):
                    continue
                parsed = urlparse(root_uri)
                pkg_path = Path(parsed.path)
                bg_path = pkg_path / "android" / "build.gradle"
                if not bg_path.exists():
                    continue
                try:
                    bg_content = bg_path.read_text(encoding="utf-8", errors="ignore")
                    if "namespace" in bg_content:
                        continue
                    manifest_path = pkg_path / "android" / "src" / "main" / "AndroidManifest.xml"
                    if not manifest_path.exists():
                        manifest_path = pkg_path / "src" / "main" / "AndroidManifest.xml"
                    if not manifest_path.exists():
                        continue
                    manifest = manifest_path.read_text(encoding="utf-8")
                    m = re.search(r'package="([^"]+)"', manifest)
                    if not m:
                        continue
                    android_block = re.search(r"android\s*\{", bg_content)
                    if not android_block:
                        continue
                    insert_pos = android_block.end()
                    new_content = bg_content[:insert_pos] + '\n    namespace ' + m.group(1) + bg_content[insert_pos:]
                    bg_path.write_text(new_content, encoding="utf-8")
                    fixed += 1
                except Exception:
                    continue
            if fixed:
                self.log("Namespace adicionado em " + str(fixed) + " plugin(s) Android", "SUCCESS")
        except Exception as e:
            self.log("_fix_plugin_namespaces: " + str(e), "WARNING")

    def _pre_build_ai_scan(self) -> bool:
        """Send code to AI for pre-build analysis to catch issues early."""
        if not self.api_key or not self.api_provider:
            return True
        main_dart = self.project_path / "lib" / "main.dart"
        if not main_dart.exists():
            return True
        code = main_dart.read_text(encoding="utf-8")
        fixed = self._ai_fix_code("Pre-build AI scan: analyze for potential compilation issues", code, {})
        if fixed and fixed != code:
            if self._is_dart_code(fixed):
                backup = self._backup_file(main_dart)
                if backup:
                    self.log(f"Backup pre-build: {backup.name}", "INFO")
                main_dart.write_text(fixed, encoding="utf-8")
                valid = self._validate_dart_syntax(fixed)
                if not valid:
                    self.log("Sintaxe Dart nao confirmada apos scan IA (prosseguindo)", "WARNING")
                self.log("IA corrigiu codigo preventivamente antes do build", "SUCCESS")
                if self.kb_path:
                    self._learn_from_success("pre-build AI scan", fixed[:500])
            else:
                # Tenta aplicar como JSON de m\u00faltiplos arquivos mesmo sem ser Dart puro
                try:
                    parsed = json.loads(fixed.strip().strip("`").replace("json","").strip())
                    if isinstance(parsed, dict) and "files" in parsed:
                        applied = 0
                        for rel_path, content in parsed["files"].items():
                            abs_path = self.project_path / rel_path
                            if abs_path.exists() or not abs_path.parent.exists():
                                if not abs_path.parent.exists():
                                    abs_path.parent.mkdir(parents=True, exist_ok=True)
                                abs_path.write_text(content.strip() + "\n", encoding="utf-8")
                                self.log(f"Pre-build: {rel_path} corrigido", "SUCCESS")
                                applied += 1
                        if applied:
                            self.log(f"IA corrigiu {applied} arquivo(s) no pre-build scan", "SUCCESS")
                except Exception:
                    self.log("IA retornou conteudo nao-Dart no pre-build scan (ignorado)", "WARNING")
        return True

    def _apply_pre_build_fixes(self) -> bool:
        """Fix plugin namespaces + optional AI pre-scan before build."""
        self.log("Aplicando correcoes pre-build...", "STEP")
        self._fix_plugin_namespaces()
        try:
            subprocess.run(
                [self.flutter_cmd, "pub", "get"],
                cwd=self.project_path, capture_output=True, text=True, timeout=120,
            )
        except Exception:
            pass
        self._pre_build_ai_scan()
        return True

    def copy_artifacts(self) -> Optional[Path]:
        self.log("Copiando artifacts...", "STEP")
        self.output_dir.mkdir(parents=True, exist_ok=True)

        candidates = []
        for subdir in ["flutter-apk", "apk"]:
            search = self.project_path / "build" / "app" / "outputs" / subdir
            if search.exists():
                candidates.extend(search.rglob("*.apk"))

        if not candidates:
            self.log("APK n\u00e3o encontrado ap\u00f3s build", "ERROR")
            return None

        apk_path = sorted(
            candidates, key=lambda p: p.stat().st_mtime, reverse=True
        )[0]
        self.log(f"APK: {apk_path.name}", "SUCCESS")

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = self.output_dir / f"app_{timestamp}.apk"
        shutil.copy2(apk_path, output_path)
        self.last_apk_path = output_path
        self.log(f"Copiado: {output_path}", "SUCCESS")
        return output_path

    # ── Report ─────────────────────────────────────────────────────────

    def generate_build_report(self, apk_path: Optional[Path], success: bool):
        self.log("Gerando relat\u00f3rio...", "STEP")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        report = {
            "build_info": {
                "project_path": str(self.project_path),
                "timestamp": self.start_time.isoformat(),
                "duration_seconds": (
                    datetime.now() - self.start_time
                ).total_seconds(),
                "success": success,
            },
            "apk_info": {
                "path": str(apk_path) if apk_path else None,
                "size_bytes": (
                    apk_path.stat().st_size
                    if apk_path and apk_path.exists() else None
                ),
                "size_mb": (
                    round(apk_path.stat().st_size / (1024 * 1024), 2)
                    if apk_path and apk_path.exists() else None
                ),
            },
            "build_log": self.build_log,
        }
        report_path = self.output_dir / "build_report.json"
        try:
            report_path.write_text(
                json.dumps(report, indent=2, ensure_ascii=False),
                encoding="utf-8"
            )
            self.log(f"Relat\u00f3rio: {report_path}", "SUCCESS")
        except Exception as e:
            self.log(f"Erro ao salvar relat\u00f3rio: {e}", "ERROR")

        status = "SUCESSO" if success else "FALHA"
        color = Color.GREEN if success else Color.RED
        print(f"\n{'='*60}")
        print(f"{Color.BOLD}RESUMO DO BUILD{Color.RESET}")
        print(f"{'='*60}")
        print(f"Status: {color}{status}{Color.RESET}")
        print(f"Dura\u00e7\u00e3o: {report['build_info']['duration_seconds']:.1f}s")
        if apk_path and apk_path.exists():
            print(f"APK: {apk_path.name} ({report['apk_info']['size_mb']} MB)")
        print(f"Output: {self.output_dir}")
        print(f"{'='*60}")

    # ── AI auto-correction ────────────────────────────────────────────

    
    def _validate_ia_response(self, response_text: str) -> Optional[dict]:
        if not response_text or len(response_text.strip()) < 200:
            self.log("[IA] Resposta muito curta (<200 chars), invalida", "WARNING")
            return None
        try:
            data = json.loads(response_text)
        except (json.JSONDecodeError, TypeError):
            self.log("[IA] Resposta nao e JSON valido", "WARNING")
            return None
        if not isinstance(data, dict):
            return None
        if data.get("ok"):
            return data
        files = data.get("files", {})
        if not isinstance(files, dict) or not files:
            self.log("[IA] JSON nao contem 'files' valido", "WARNING")
            return None
        for fpath, fcontent in files.items():
            if not isinstance(fcontent, str) or len(fcontent.strip()) < 50:
                return None
        return data

    def _ai_fix_code(self, errors: str, code: str,
                      extra_files: Optional[dict] = None,
                      _retry_count: int = 0,
                      _tier: int = 1) -> Optional[str]:
        """Chama a API de IA para corrigir o código com base nos erros.
        _tier: 1=simples, 2=médio (+KB+categorias), 3=completo (+histórico+perfil)
        """
        _debug_entry = None
        try:
            from gui.ai_debug import get_debug_logger as _get_dl
            _debug_logger = _get_dl()
        except Exception:
            _debug_logger = None
        if not self.api_key or not self.api_provider:
            return None

        cfg = self.AI_PROVIDER_CONFIG.get(self.api_provider)
        if not cfg:
            self.log(f"Provedor IA n\u00e3o configurado: {self.api_provider}", "WARNING")
            return None

        model = self.api_model or cfg["model"]
        extra = ""
        if extra_files:
            for name, content in extra_files.items():
                if name != "main.dart" and content:
                    extra += f"\nARQUIVO ({name}):\n```\n{content[:1500]}\n```\n"

        # --- Montagem do prompt por tier ---
        prompt_parts = [
            "Voc\u00ea \u00e9 um especialista s\u00eanior em Flutter/Dart/Android/Kotlin/Gradle.",
            "Seu objetivo \u00e9 corrigir o c\u00f3digo abaixo para que ele compile em APK.",
        ]

        if _tier >= 3:
            profile = ""
            if self._project_profile.get("packages"):
                profile = "\nPACOTES DO PROJETO:\n" + "\n".join(
                    f"  - {p}" for p in self._project_profile["packages"][:10]
                ) + "\n"
                prompt_parts.append(profile)
            ctx = ""
            if self._ai_context:
                ctx = "HIST\u00d3RICO DE CORRE\u00c7\u00d5ES ANTERIORES (para evitar repetir):\n"
                for entry in self._ai_context[-3:]:
                    ctx += f"  - Tentativa {entry.get('attempt')}: erro={entry.get('error','')[:150]}\n"
                    if entry.get('result'):
                        ctx += f"    resultado={entry['result'][:150]}\n"
                prompt_parts.append(ctx)

        if _tier >= 2:
            categorized = self._categorize_errors(errors[:4000])
            prompt_parts.append(f"ERROS DO COMPILADOR:\n{categorized[:4000]}")
            kb_hints = ""
            try:
                from gui.knowledge_base import KnowledgeBase
                kb_log = type('_', (), {'ok': lambda s: None, 'warn': lambda s: None,
                                         'err': lambda s: None, 'info': lambda s: None})()
                kb = KnowledgeBase(kb_log)
                kbf = kb._db.get("fixes", [])
                if kbf:
                    cats = {}
                    for f in kbf:
                        ct = f.get("type", "generic")
                        if ct not in cats: cats[ct] = []
                        cats[ct].append(f.get("description",""))
                    kb_hints = "PADR\u00d5ES CONHECIDOS (KnowledgeBase):\n"
                    for ct, items in cats.items():
                        kb_hints += f"  [{ct}]: {', '.join(items[:3])}\n"
                prompt_parts.append(kb_hints)
            except Exception:
                pass
        else:
            prompt_parts.append(f"ERROS DO COMPILADOR:\n{errors[:3000]}")

        prompt_parts.append(f"C\u00d3DIGO DART (main.dart):\n```dart\n{code[:4000]}\n```")
        if extra:
            prompt_parts.append(extra)

        prompt_parts.append(
            "TAREFA:\n"
            "1. Analise CADA erro e corrija a causa raiz\n"
            "2. Mantenha a l\u00f3gica e funcionalidade originais\n"
            "3. Corrija APENAS o necess\u00e1rio para compilar\n"
            "4. Retorne APENAS JSON v\u00e1lido neste formato:\n"
            '   {"files": {"caminho/relativo": "conte\u00fado corrigido", ...}}\n'
            "5. Inclua apenas arquivos que precisam de corre\u00e7\u00e3o\n"
            "6. N\u00e3o use ```json nem explica\u00e7\u00f5es — apenas o JSON puro\n"
            "7. Se n\u00e3o houver o que corrigir, retorne: {\"ok\": true}"
        )
        prompt = "\n".join(prompt_parts)
        _debug_prompt = prompt
        _debug_model = model
        _debug_tier = _tier
        _debug_provider = self.api_provider
        _debug_response = ""
        _debug_success = False
        _debug_extracted = ""
        _debug_valid_errors = []
        _debug_error = ""
        _debug_elapsed = 0

        def _log_ai_debug(result_val=None):
            nonlocal _debug_success
            _debug_success = result_val is not None or _debug_success
            if _debug_logger:
                _debug_logger.add_entry(
                    prompt=_debug_prompt,
                    response=_debug_response or _debug_error or "",
                    provider=_debug_provider or "",
                    model=_debug_model or "",
                    tier=_debug_tier,
                    elapsed=_debug_elapsed or 0,
                    success=_debug_success,
                    extracted_code=_debug_extracted,
                    validation_errors=_debug_valid_errors,
                    error_info=_debug_error,
                )

        payload_bytes = len(prompt.encode("utf-8"))
        self.log(
            f"[IA] {self.api_provider} \u2192 {model} | tier {_tier} | "
            f"payload: {payload_bytes} bytes",
            "INFO"
        )
        self._progress(50, f"IA ({self.api_provider}/{model}): corrigindo erros...")

        import time as _time
        _t0 = _time.time()

        try:
            if cfg["type"] == "gemini":
                url = (
                    f"https://generativelanguage.googleapis.com/v1beta/"
                    f"models/{model}:generateContent"
                    f"?key={self.api_key}"
                )
                payload = json.dumps({
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {
                        "temperature": 0.1, "maxOutputTokens": 8192,
                        "responseMimeType": "application/json",
                    },
                })
                req = Request(url, data=payload.encode(),
                              headers={"Content-Type": "application/json"})

            elif cfg["type"] == "anthropic":
                url = "https://api.anthropic.com/v1/messages"
                payload = json.dumps({
                    "model": model,
                    "max_tokens": 4096,
                    "messages": [{"role": "user", "content": prompt}],
                })
                req = Request(url, data=payload.encode(), method="POST",
                              headers={
                                  "Content-Type": "application/json",
                                  "x-api-key": self.api_key,
                                  "anthropic-version": "2023-06-01",
                              })

            else:  # openai-compatible
                max_tok = 8192 if _tier >= 3 else 4096
                url = f"{cfg['url'].rstrip('/')}/chat/completions"
                payload = json.dumps({
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.1,
                    "max_tokens": max_tok,
                })
                req = Request(url, data=payload.encode(), method="POST",
                              headers={
                                  "Content-Type": "application/json",
                                  "Authorization": f"Bearer {self.api_key}",
                              })

            # Timeout adaptativo baseado em historico
            ia_timeout = self._timeout_manager.get_timeout(_retry_count + 1, 'medium')
            self.log(f"[IA] Timeout configurado: {ia_timeout}s (adaptativo)", "INFO")

            with urlopen(req, timeout=ia_timeout) as r:
                resp = json.loads(r.read())

            _elapsed = _time.time() - _t0

            # Registra sucesso no gerenciador de timeout
            self._timeout_manager.record_attempt(True, _elapsed, model, 'medium')

            if cfg["type"] == "gemini":
                text = (resp.get("candidates", [{}])[0]
                        .get("content", {})
                        .get("parts", [{}])[0]
                        .get("text", ""))
                usage = resp.get("usageMetadata", {})
                in_tok = usage.get("promptTokenCount", 0)
                out_tok = usage.get("candidatesTokenCount", 0)
            elif cfg["type"] == "anthropic":
                text = (resp.get("content", [{}])[0]
                        .get("text", ""))
                usage = resp.get("usage", {})
                in_tok = usage.get("input_tokens", 0)
                out_tok = usage.get("output_tokens", 0)
            else:
                text = (resp.get("choices", [{}])[0]
                        .get("message", {})
                        .get("content", ""))
                usage = resp.get("usage", {})
                in_tok = usage.get("prompt_tokens", 0)
                out_tok = usage.get("completion_tokens", 0)

            fixed = text.strip()
            _debug_response = fixed
            _debug_elapsed = _elapsed
            self.log(
                f"[IA] Resposta em {_elapsed:.1f}s "
                f"| {len(fixed)} chars "
                f"| in: {in_tok} out: {out_tok} tokens",
                "SUCCESS"
            )

            # Validacao robusta da resposta com IAResponseValidator
            is_valid, extracted_code, validation_errors = self._response_validator.validate_and_extract(fixed)
            if not is_valid:
                _debug_valid_errors = validation_errors
                self.log(f"[IA] Validacao falhou: {validation_errors}", "WARNING")
            elif extracted_code:
                fixed = extracted_code
                _debug_extracted = extracted_code
                self.log("[IA] Resposta validada e extraida com sucesso", "SUCCESS")

            # --- Parse JSON output or fallback to free-text format ---
            file_fixes = {}
            main_fix = None
            json_ok = False

            # Try JSON first
            json_str = fixed.strip()
            if json_str.startswith("```"):
                json_str = json_str.split("```")[1] if "```" in json_str else json_str
            if json_str.startswith("json"):
                json_str = json_str[4:].strip()
            try:
                parsed = self._validate_ia_response(json_str) or {}
                if isinstance(parsed, dict):
                    if parsed.get("ok"):
                        self.log("[IA] IA indicou que n\u00e3o h\u00e1 o que corrigir", "INFO")
                        _debug_success = True
                        _log_ai_debug(code)
                        return code
                    files_dict = parsed.get("files", {})
                    if files_dict:
                        json_ok = True
                        for rel_path, content in files_dict.items():
                            file_fixes[rel_path] = content
                            if rel_path in ("lib/main.dart", "main.dart"):
                                main_fix = content
            except (json.JSONDecodeError, TypeError):
                pass

            # Fallback: free-text ARQUIVO format
            if not json_ok:
                current_file = None
                current_content = []
                in_block = False
                for line in fixed.split("\n"):
                    m = re.match(r"^(?:ARQUIVO|FILE|ARQUIVO CORRIGIDO):\s*(.+)$", line)
                    if m:
                        if current_file and current_content:
                            file_fixes[current_file] = "\n".join(current_content)
                        current_file = m.group(1).strip()
                        current_content = []
                        in_block = False
                    elif line.strip().startswith("```"):
                        in_block = not in_block
                    elif current_file is not None and not in_block:
                        current_content.append(line)
                if current_file and current_content:
                    file_fixes[current_file] = "\n".join(current_content)
                if not file_fixes and len(fixed) > 50:
                    main_fix = fixed
                    file_fixes["lib/main.dart"] = fixed

            if file_fixes:
                self.log(f"IA corrigiu {len(file_fixes)} arquivo(s)", "SUCCESS")
                for rel_path, content in file_fixes.items():
                    abs_path = self.project_path / rel_path
                    if abs_path.exists() or not abs_path.parent.exists():
                        if not abs_path.parent.exists():
                            abs_path.parent.mkdir(parents=True, exist_ok=True)
                        abs_path.write_text(content.strip() + "\n", encoding="utf-8")
                        self.log(f"Corrigido: {rel_path}", "SUCCESS")
                    else:
                        self.log(f"Arquivo nao encontrado (ignorado): {rel_path}", "WARNING")
                    if rel_path in ("lib/main.dart", "main.dart"):
                        main_fix = content
                if main_fix:
                    if self._is_dart_code(main_fix):
                        # --- Verification loop: flutter analyze ---
                        if self._verify_fix_with_analyze():
                            self.log("[IA] An\u00e1lise passou ap\u00f3s corre\u00e7\u00e3o", "SUCCESS")
                            _debug_success = True
                            _log_ai_debug(main_fix)
                            return main_fix
                        self.log("[IA] An\u00e1lise ainda com erros — tentando novamente com +contexto", "WARNING")
                        _debug_success = True
                        _log_ai_debug(main_fix)
                        return main_fix  # retorna mesmo assim, o loop externo lidar\u00e1
                    self.log(f"IA retornou conteudo nao-Dart para main.dart (ignorado)", "WARNING")
                self.log("Nao foi possivel extrair correcao valida para main.dart", "WARNING")
                _log_ai_debug(None)
                return None

            # Fallback: single text block
            if len(fixed) > 50:
                self.log(f"IA retornou {len(fixed)} caracteres (formato livre)", "SUCCESS")
                _debug_success = True
                _log_ai_debug(fixed)
                return fixed
            self.log("IA retornou conte\u00fado muito curto", "WARNING")
            _log_ai_debug(None)
            return None

        except HTTPError as e:
            http_code = e.code
            reason = str(e.reason)[:100] if e.reason else ""
            _elapsed = _time.time() - _t0

            # Registra falha no timeout manager
            self._timeout_manager.record_attempt(False, _elapsed, model, 'medium')

            # Registra falha no model manager
            self._model_manager.record_model_result(model, False, _elapsed)

            self.log(
                f"[IA] \u2716 {model} HTTP {http_code} ({_elapsed:.1f}s)"
                f"{': ' + reason if reason else ''}",
                "ERROR"
            )
            needs_fallback = http_code in (401, 402, 403, 429) or http_code >= 500
            if needs_fallback:
                if http_code == 401:
                    cur = self.api_provider or "NVIDIA"
                    if cur == self._last_401_provider:
                        self._consecutive_401 += 1
                    else:
                        self._consecutive_401 = 1
                        self._last_401_provider = cur
                    if self._consecutive_401 >= 5:
                        self.log(
                            f"[IA] \u2716 {self._consecutive_401}x 401 consecutivos "
                            f"em {cur} — chave sem permissão de inferência",
                            "ERROR"
                        )
                        _debug_error = f"{self._consecutive_401}x 401 consecutivos em {cur}"
                        _log_ai_debug(None)
                        return None
                remaining = [m for m in self._model_fallback_list
                             if m != model]
                if remaining:
                    next_m = remaining[0]
                    self._model_fallback_list = remaining
                    self.api_model = next_m
                    self._fallback_attempt += 1
                    remaining_count = len(remaining) - 1
                    self.log(
                        f"[IA] \u21bb Fallback #{self._fallback_attempt} "
                        f"\u2192 {next_m} ({remaining_count} restantes)",
                        "INFO"
                    )
                    self._progress(50, f"IA: fallback para {next_m}")
                    return self._ai_fix_code(errors, code, extra_files)
                self.log("[IA] Todos os modelos de fallback esgotados", "ERROR")
                self._consecutive_401 = 0
            _debug_error = f"HTTP {http_code}: {reason}"
            _log_ai_debug(None)
            return None
        except URLError as e:
            _elapsed = _time.time() - _t0
            _debug_error = str(e.reason)[:200] if hasattr(e, 'reason') else str(e)[:200]

            # Registra falha nos gerenciadores
            self._timeout_manager.record_attempt(False, _elapsed, model, 'medium')
            self._model_manager.record_model_result(model, False, _elapsed)

            reason = str(e.reason)[:200] if hasattr(e, 'reason') and e.reason else str(e)[:200]
            if _retry_count < 3:
                wait = (_retry_count + 1) * 2
                self.log(
                    f"[IA] \u2716 Erro de conex\u00e3o (tentativa {_retry_count + 1}/3): "
                    f"{reason} — re-tentando em {wait}s...",
                    "WARNING"
                )
                _time.sleep(wait)
                return self._ai_fix_code(errors, code, extra_files,
                                         _retry_count=_retry_count + 1)
            self.log(
                f"[IA] \u2716 Conex\u00e3o falhou ap\u00f3s 3 tentativas: {reason}",
                "ERROR"
            )
            self.log(
                "[IA] Verifique sua conex\u00e3o de internet. "
                "Se o problema persistir, clique em 'Salvar Chave' "
                "para re-validar a chave de API.",
                "INFO"
            )
        except Exception as e:
            _elapsed = _time.time() - _t0
            self._timeout_manager.record_attempt(False, _elapsed, model, 'medium')
            self._model_manager.record_model_result(model, False, _elapsed)
            self.log(
                f"[IA] \u2716 Exce\u00e7\u00e3o ({_elapsed:.1f}s): {str(e)[:150]}",
                "ERROR"
            )
            _debug_error = str(e)[:200]
        _log_ai_debug(None)
        return None

    def _read_file_safe(self, *parts) -> Optional[str]:
        path = self.project_path.joinpath(*parts)
        return path.read_text(encoding="utf-8") if path.exists() else None

    def _write_file_safe(self, content: str, *parts) -> bool:
        path = self.project_path.joinpath(*parts)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        self.log(f"Arquivo atualizado: {path.relative_to(self.project_path)}", "INFO")
        return True

    def _is_dart_code(self, text: str) -> bool:
        if not text or len(text) < 10:
            return False
        no_dart = re.search(r'(<\?xml|android:).*|^plugins\s*\{|^buildscript\s*\{', text, re.IGNORECASE | re.DOTALL)
        if no_dart:
            return False
        has_dart = bool(re.search(r'\b(import\s+|class\s+\w+|void\s+main|Widget\s+build|@override|final\s+\w+)', text))
        return has_dart or ('void main' in text)

    def _validate_dart_syntax(self, code: str) -> bool:
        try:
            r = subprocess.run(
                [self.flutter_cmd, "format", "--set-exit-if-changed", "-o", "show"],
                input=code, capture_output=True, text=True, timeout=15,
            )
            return r.returncode == 0
        except Exception:
            return False

    def _backup_file(self, path: Path) -> Optional[Path]:
        if not path.exists():
            return None
        backup_dir = self.project_path / ".orchestrator_backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup = backup_dir / f"{path.name}.{ts}.bak"
        shutil.copy2(str(path), str(backup))
        return backup

    def _write_dart_safe(self, path: Path, content: str) -> bool:
        if not self._is_dart_code(content):
            self.log(f"Recusado: conteudo nao parece Dart valido -> {path.name}", "ERROR")
            return False
        backup = self._backup_file(path)
        if backup:
            self.log(f"Backup: {backup.name}", "INFO")
        path.write_text(content.strip() + "\n", encoding="utf-8")
        if self._validate_dart_syntax(content):
            self.log(f"Escrito + valido: {path.name}", "SUCCESS")
            return True
        self.log(f"AVISO: {path.name} escrito mas sintaxe Dart nao confirmada", "WARNING")
        return True

    def _apply_ai_fixes(self, errors: str, fixes: dict) -> bool:
        """Aplica corre\u00e7\u00f5es da IA em m\u00faltiplos arquivos."""
        applied = 0
        for rel_path, new_content in fixes.items():
            abs_path = self.project_path / rel_path
            if not abs_path.exists():
                self.log(f"Arquivo n\u00e3o encontrado: {rel_path}", "WARNING")
                continue
            old = abs_path.read_text(encoding="utf-8")
            if old.strip() == new_content.strip():
                continue
            abs_path.write_text(new_content.strip() + "\n", encoding="utf-8")
            self.log(f"Corrigido: {rel_path}", "SUCCESS")
            applied += 1
        return applied > 0

    def _fix_errors_and_retry(self, stderr: str, release: bool,
                               build_number: Optional[str]) -> bool:
        """Tenta corrigir erros com IA e recompilar."""
        errors = stderr[:5000]
        if not errors.strip():
            return False

        # Colete arquivos relevantes para contexto
        files = {}
        for key, path in [
            ("main.dart", ["lib", "main.dart"]),
            ("AndroidManifest.xml",
             ["android", "app", "src", "main", "AndroidManifest.xml"]),
            ("app/build.gradle",
             ["android", "app", "build.gradle"]),
            ("build.gradle",
             ["android", "build.gradle"]),
        ]:
            content = self._read_file_safe(*path)
            if content:
                files[key] = content

        # Antes de chamar IA: verifica KnowledgeBaseLearner (pacote orchestrator)
        try:
            kb_learner = KnowledgeBaseLearner()
            solution, confidence = kb_learner.get_solution(errors)
            if solution and confidence > 0.8:
                self.log(f"[KB] Solucao de alta confianca ({confidence:.0%}) na KnowledgeBase, aplicando.", "INFO")
                if "build.gradle.kts" in solution or "Kotlin" in solution:
                    kts = self.project_path / "android" / "app" / "build.gradle.kts"
                    if kts.exists():
                        kts.unlink()
                        self.log("[KB] build.gradle.kts removido (solucao KB)", "SUCCESS")
            if solution and confidence > 0.5:
                self.log(f"[KB] Solucao via IA da KB (confianca: {confidence:.0%})", "INFO")
        except Exception as kb_e:
            self.log(f"[KB] Erro ao consultar KnowledgeBaseLearner: {kb_e}", "DEBUG")

        # Tenta corrigir via KnowledgeBase GUI (erros estruturais, namespace, etc.)
        try:
            from gui.knowledge_base import KnowledgeBase
            kb = KnowledgeBase(self._LogAdapter(self.log))
            main_dart = self.project_path / "lib" / "main.dart"
            code = main_dart.read_text(encoding="utf-8") if main_dart.exists() else ""
            fixed, applied = kb.apply(code, [errors], project_dir=self.project_path)
            if applied:
                self.log(f"KnowledgeBase: {len(applied)} corre\u00e7\u00f5es aplicadas: {', '.join(applied)}", "SUCCESS")
                if fixed != code and main_dart.exists():
                    main_dart.write_text(fixed, encoding="utf-8")
                return self._retry_build(release, build_number)
        except Exception as kb_err:
            self.log(f"KnowledgeBase: {kb_err}", "WARNING")

        cache_parts = errors[:500]
        for k, v in files.items():
            cache_parts += k + v[:500]
        cache_key = hashlib.md5(cache_parts.encode()).hexdigest()

        # Se o erro \u00e9 especificamente sobre v1 embedding, corrige diretamente
        if "v1 embedding" in errors.lower() or "flutterEmbedding" not in files.get("AndroidManifest.xml", ""):
            manifest_path = self.project_path / "android" / "app" / "src" / "main" / "AndroidManifest.xml"
            if manifest_path.exists():
                manifest = manifest_path.read_text(encoding="utf-8")
                if '<meta-data android:name="flutterEmbedding"' not in manifest:
                    manifest = manifest.replace(
                        "</application>",
                        '        <meta-data\n'
                        '            android:name="flutterEmbedding"\n'
                        '            android:value="2"/>\n'
                        '    </application>'
                    )
                    if 'android:launchMode="singleTop"' not in manifest:
                        manifest = manifest.replace(
                            'android:exported="true">',
                            'android:exported="true"\n'
                            '            android:launchMode="singleTop"\n'
                            '            android:taskAffinity=""\n'
                            '            android:theme="@android:style/Theme.Light.NoTitleBar"\n'
                            '            android:configChanges="orientation|keyboardHidden|'
                            'keyboard|screenSize|smallestScreenSize|locale|layoutDirection|'
                            'fontScale|screenLayout|density|uiMode"\n'
                            '            android:hardwareAccelerated="true"\n'
                            '            android:windowSoftInputMode="adjustResize">'
                        )
                    manifest_path.write_text(manifest, encoding="utf-8")
                    self.log("AndroidManifest.xml corrigido (flutterEmbedding=2)", "SUCCESS")

        # Verifica cache
        if cache_key in self._fix_cache:
            self.log("Usando corre\u00e7\u00e3o em cache", "INFO")
            if self._apply_ai_fixes(errors, self._fix_cache[cache_key]):
                return self._retry_build(release, build_number)

        main_dart = self.project_path / "lib" / "main.dart"
        if not main_dart.exists():
            self.log("main.dart n\u00e3o encontrado para corre\u00e7\u00e3o", "ERROR")
            return False

        code = main_dart.read_text(encoding="utf-8")
        self._fallback_attempt = 0
        self._consecutive_401 = 0

        accumulated_errors = errors
        max_retries = 2
        for attempt in range(1, max_retries + 1):
            if attempt > 1 and self._cancelled:
                self.log("Corre\u00e7\u00e3o cancelada pelo usu\u00e1rio", "WARNING")
                return False
            if attempt > 1:
                self.log(f"Tentativa {attempt}/{max_retries}...", "INFO")
                code = main_dart.read_text(encoding="utf-8")
                files["main.dart"] = code
                self._update_project_profile()

            # Tiered prompting: attempt 1 = simples, 2 = m\u00e9dio, 3 = completo
            tier = min(attempt, 3)
            fixed = self._ai_fix_code(accumulated_errors, code, files, _tier=tier)
            self._ai_context.append({
                "attempt": attempt,
                "tier": tier,
                "error": accumulated_errors[:300],
                "result": fixed[:300] if fixed else "None",
            })
            if len(self._ai_context) > 12:
                self._ai_context = self._ai_context[-12:]

            if not fixed:
                if attempt < max_retries:
                    accumulated_errors += "\n[IA nao retornou correcao]"
                    continue
                self._learn_from_failure(accumulated_errors[:1000])
                return False

            if not self._is_dart_code(fixed):
                self.log(f"IA retornou conteudo nao-Dart na tentativa {attempt}", "WARNING")
                if attempt < max_retries:
                    accumulated_errors += "\n[IA retornou conteudo nao-Dart]"
                    continue
                self._learn_from_failure(accumulated_errors[:1000])
                return False

            backup = self._backup_file(main_dart)
            if backup and attempt == 1:
                self.log(f"Backup do main.dart: {backup.name}", "INFO")

            main_dart.write_text(fixed.strip() + "\n", encoding="utf-8")
            self._fix_cache[cache_key] = {}
            self._last_errors = accumulated_errors[:500]
            self._last_fix_applied = True
            self._project_profile["fixes_applied"].append(accumulated_errors[:200])

            # Verification loop: se analyze falhar, acumula erros e tenta denovo
            if not self._verify_fix_with_analyze():
                analyze_err = "flutter analyze encontrou erros apos correcao"
                accumulated_errors += "\n" + analyze_err
                self.log("Re-tentando correcao com erros do analyze...", "INFO")
                continue

            ok = self._retry_build(release, build_number)
            if ok:
                if self.kb_path:
                    self._learn_from_success(accumulated_errors[:500], fixed[:500])
                return True

            err_text = self._capture_last_build_error()
            if err_text:
                accumulated_errors += "\n" + err_text

        self.log(f"Corre\u00e7\u00e3o falhou ap\u00f3s {max_retries} tentativas", "ERROR")
        self._learn_from_failure(accumulated_errors[:1000])
        return False

    @staticmethod
    def _categorize_errors(error_text: str) -> str:
        cats = []
        if re.search(r"(KGP|Kotlin Gradle Plugin|applies KGP)", error_text, re.I):
            cats.append("[KGP] Plugin aplica Kotlin Gradle Plugin — adicionar resolutionStrategy no settings.gradle")
        if re.search(r"(namespace|AndroidManifest)", error_text, re.I):
            cats.append("[MANIFEST] Erro de namespace ou AndroidManifest.xml")
        if re.search(r"(Gradle version|gradle.*version|AGP)", error_text, re.I):
            cats.append("[GRADLE] Vers\u00e3o do Gradle/AGP incompat\u00edvel")
        if re.search(r"(import.*not found|undefined name|Undefined class)", error_text, re.I):
            cats.append("[IMPORT] Import ou classe n\u00e3o encontrada — verificar depend\u00eancias no pubspec.yaml")
        if re.search(r"(null check operator|Null check|required non-null)", error_text, re.I):
            cats.append("[NULL] Null safety — adicionar verifica\u00e7\u00e3o de null")
        if re.search(r"(deprecated|removed|migrated)", error_text, re.I):
            cats.append("[DEPRECATED] API deprecated — atualizar para vers\u00e3o recomendada")
        if re.search(r"(syntax|unexpected token|Expected '|Missing )", error_text, re.I):
            cats.append("[SYNTAX] Erro de sintaxe Dart/XML/Gradle")
        if re.search(r"(timeout|TimeoutExpired)", error_text, re.I):
            cats.append("[TIMEOUT] Opera\u00e7\u00e3o excedeu tempo limite")
        if re.search(r"(network|connection refused|getaddrinfo|Name or service not known)", error_text, re.I):
            cats.append("[NETWORK] Erro de rede — verificar conex\u00e3o com internet")
        if not cats:
            cats.append("[GERAL] Erro n\u00e3o categorizado")
        header = "CATEGORIAS DOS ERROS:\n" + "\n".join(cats) + "\n\n"
        return header + error_text

    def _verify_fix_with_analyze(self) -> bool:
        """Executa flutter analyze para verificar se corre\u00e7\u00f5es introduziram novos erros."""
        try:
            r = subprocess.run(
                [self.flutter_cmd, "analyze"],
                cwd=self.project_path,
                capture_output=True, text=True, timeout=120,
            )
            combined = r.stdout + "\n" + r.stderr
            errors = [l for l in combined.split("\n") if ": error:" in l.lower()]
            if errors:
                self.log(f"flutter analyze: {len(errors)} erro(s) encontrado(s)", "WARNING")
                for e in errors[:3]:
                    self.log(f"  {e.strip()[:200]}", "WARNING")
                return False
            self.log("flutter analyze: OK, sem erros", "SUCCESS")
            return True
        except Exception as e:
            self.log(f"flutter analyze: {e}", "WARNING")
            return True  # se falhar, n\u00e3o bloqueia

    def _learn_from_failure(self, errors: str):
        """Persiste erro que a IA n\u00e3o conseguiu corrigir para an\u00e1lise futura."""
        if not self.kb_path:
            return
        try:
            db = {"fixes": []}
            if self.kb_path.exists():
                db = json.loads(self.kb_path.read_text(encoding="utf-8"))
                if isinstance(db, list):
                    db = {"fixes": list(db), "_meta": {"converted_from_flat": True}}
            fixes = db.setdefault("fixes", [])
            err_hash = hashlib.md5(errors[:200].encode()).hexdigest()[:8]
            already = any(f.get("id", "").endswith(err_hash) for f in fixes)
            if already:
                self.log("Falha j\u00e1 registrada na KnowledgeBase", "INFO")
                return
            entry = {
                "id": "failed_" + err_hash,
                "description": f"Falha n\u00e3o resolvida: {errors[:100]}...",
                "error_patterns": [errors[:200]],
                "context_patterns": [],
                "type": "info_only",
                "fix_hint": "IA n\u00e3o conseguiu corrigir automaticamente. "
                            "Revisar manualmente o c\u00f3digo para este padr\u00e3o de erro.",
                "times_applied": 0,
                "source": "failed_attempt",
            }
            fixes.append(entry)
            db["_meta"]["last_updated"] = datetime.now().strftime("%Y-%m-%d")
            json_str = json.dumps(db, ensure_ascii=False, indent=2)
            self.kb_path.parent.mkdir(parents=True, exist_ok=True)
            self.kb_path.write_text(json_str, encoding="utf-8")
            self.log("Falha registrada na KnowledgeBase para refer\u00eancia futura", "INFO")
        except Exception as e:
            self.log(f"Erro ao registrar falha: {e}", "WARNING")
        try:
            build_dir = self.project_path / "build"
            if not build_dir.exists():
                return None
            logs = list(build_dir.rglob("*.log"))
            if not logs:
                return None
            latest = max(logs, key=lambda p: p.stat().st_mtime)
            text = latest.read_text(errors="ignore")
            lines = [l for l in text.split("\n") if "error" in l.lower()]
            return "\n".join(lines[-20:])[:2000] if lines else text[-2000:]
        except Exception:
            return None

    def _retry_build(self, release: bool,
                     build_number: Optional[str]) -> bool:
        """Reexecuta flutter pub get + flutter build apk."""
        try:
            r = subprocess.run(
                [self.flutter_cmd, "pub", "get"],
                cwd=self.project_path, capture_output=True, text=True, timeout=120,
            )
            if r.returncode != 0:
                self.log(f"pub get no retry falhou: {r.stderr[:200]}", "WARNING")
        except Exception as e:
            self.log(f"pub get no retry: {e}", "WARNING")
        cmd = [self.flutter_cmd, "build", "apk"]
        if release:
            cmd.append("--release")
        if build_number:
            cmd.extend(["--build-number", build_number])
        try:
            r = subprocess.run(
                cmd, cwd=self.project_path,
                capture_output=True, text=True, timeout=1800,
            )
            if r.returncode == 0:
                self.log("APK compilado com sucesso ap\u00f3s corre\u00e7\u00e3o IA", "SUCCESS")
                return True
            self.log(f"Ainda com erros ap\u00f3s corre\u00e7\u00e3o: {r.stderr[:300]}", "WARNING")
            return False
        except Exception as e:
            self.log(f"Erro no retry: {e}", "ERROR")
            return False

    def _update_project_profile(self):
        """Atualiza perfil do projeto com depend\u00eancias detectadas."""
        try:
            pubspec = self.project_path / "pubspec.yaml"
            if pubspec.exists():
                text = pubspec.read_text(encoding="utf-8")
                deps = re.findall(r'^\s+(\w[\w-]*):', text, re.MULTILINE)
                self._project_profile["packages"] = list(set(
                    self._project_profile["packages"] + deps
                ))
        except Exception:
            pass

    def _learn_from_success(self, errors: str, fix_snippet: str):
        """Persiste o par erro+corre\u00e7\u00e3o no known_fixes.json no formato da KnowledgeBase."""
        self._update_project_profile()
        if not self.kb_path:
            return
        try:
            db = {"fixes": []}
            if self.kb_path.exists():
                db = json.loads(self.kb_path.read_text(encoding="utf-8"))
                if isinstance(db, list):
                    db = {"fixes": db, "_meta": {"converted_from_flat": True}}
            fixes = db.setdefault("fixes", [])
            entry = {
                "id": "learned_" + hashlib.md5(errors[:100].encode()).hexdigest()[:8],
                "description": f"Aprendido: {errors[:80]}...",
                "error_patterns": [errors[:100]],
                "context_patterns": [],
                "type": "regex_replace",
                "operations": [],
                "fix_hint": fix_snippet[:200],
                "explanation": "Corre\u00e7\u00e3o aprendida automaticamente ap\u00f3s sucesso da IA.",
                "times_applied": 1,
                "source": self.api_provider or "auto",
            }
            for existing in fixes:
                if isinstance(existing, dict) and existing.get("id") == entry["id"]:
                    existing["times_applied"] = existing.get("times_applied", 1) + 1
                    break
            else:
                fixes.append(entry)
            db["_meta"] = db.get("_meta", {})
            db["_meta"]["last_updated"] = datetime.now().strftime("%Y-%m-%d")
            self.kb_path.write_text(
                json.dumps(db, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            self.log("Aprendizado salvo em known_fixes.json", "SUCCESS")
        except Exception as e:
            self.log(f"Erro ao salvar aprendizado: {e}", "WARNING")

    def _ai_self_review(self) -> bool:
        """IA revisa o pr\u00f3prio c\u00f3digo do Orchestrator e aplica corre\u00e7\u00f5es se necess\u00e1rio."""
        if not self.api_key:
            return True
        orc_path = Path(__file__)
        code = orc_path.read_text(encoding="utf-8")
        if len(code) < 100:
            return True
        cfg = self.AI_PROVIDER_CONFIG.get(self.api_provider)
        if not cfg:
            return True
        model = self.api_model or cfg["model"]
        prompt = (
            "Voc\u00ea \u00e9 um revisor de c\u00f3digo Python. Analise o arquivo abaixo "
            "(FlutterBuildOrchestrator) e identifique:\n"
            "1. Bugs que podem impedir o build de APK\n"
            "2. Melhorias que aumentam a taxa de sucesso na compila\u00e7\u00e3o\n"
            "3. Trechos que podem causar crash (ex: None sem check, timeout curto)\n\n"
            f"C\u00d3DIGO:\n```python\n{code[:5000]}\n```\n\n"
            "Se encontrar algo cr\u00edtico, retorne o c\u00f3digo corrigido COMPLETO "
            "do(s) m\u00e9todo(s) afetado(s) no formato:\n"
            "   ARQUIVO: flutter_orchestrator.py\n"
            "   ```\n"
            "   c\u00f3digo corrigido (apenas os m\u00e9todos que mudaram)\n"
            "   ```\n"
            "Se tudo estiver OK, retorne apenas: \"OK\""
        )
        try:
            if cfg["type"] == "gemini":
                url = (
                    f"https://generativelanguage.googleapis.com/v1beta/"
                    f"models/{model}:generateContent"
                    f"?key={self.api_key}"
                )
                payload = json.dumps({
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {"temperature": 0.05, "maxOutputTokens": 4096},
                })
                req = Request(url, data=payload.encode(),
                              headers={"Content-Type": "application/json"})
                with urlopen(req, timeout=300) as r:
                    resp = json.loads(r.read())
                text = (resp.get("candidates", [{}])[0]
                        .get("content", {})
                        .get("parts", [{}])[0]
                        .get("text", ""))
            elif cfg["type"] == "anthropic":
                url = "https://api.anthropic.com/v1/messages"
                payload = json.dumps({
                    "model": model,
                    "max_tokens": 4096,
                    "messages": [{"role": "user", "content": prompt}],
                })
                req = Request(url, data=payload.encode(), method="POST",
                              headers={
                                  "Content-Type": "application/json",
                                  "x-api-key": self.api_key,
                                  "anthropic-version": "2023-06-01",
                              })
                with urlopen(req, timeout=300) as r:
                    resp = json.loads(r.read())
                text = (resp.get("content", [{}])[0]
                        .get("text", ""))
            else:
                url = f"{cfg['url'].rstrip('/')}/chat/completions"
                payload = json.dumps({
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.05,
                    "max_tokens": 4096,
                })
                req = Request(url, data=payload.encode(), method="POST",
                              headers={
                                  "Content-Type": "application/json",
                                  "Authorization": f"Bearer {self.api_key}",
                              })
                with urlopen(req, timeout=300) as r:
                    resp = json.loads(r.read())
                text = (resp.get("choices", [{}])[0]
                        .get("message", {})
                        .get("content", ""))
            if not text or text.strip() == "OK":
                return True
            file_fixes = {}
            current_file = None
            current_content = []
            in_block = False
            for line in text.split("\n"):
                m = re.match(r"^ARQUIVO:\s*(.+)$", line)
                if m:
                    if current_file and current_content:
                        file_fixes[current_file] = "\n".join(current_content)
                    current_file = m.group(1).strip()
                    current_content = []
                    in_block = False
                elif line.strip().startswith("```"):
                    in_block = not in_block
                elif current_file is not None and not in_block:
                    current_content.append(line)
            if current_file and current_content:
                file_fixes[current_file] = "\n".join(current_content)
            if file_fixes:
                for rel_path, content in file_fixes.items():
                    abs_path = Path(__file__).resolve().parent / rel_path
                    if not abs_path.exists():
                        continue
                    current = abs_path.read_text(encoding="utf-8")
                    if content.strip() in current:
                        self.log(f"Auto-revis\u00e3o: {rel_path} j\u00e1 cont\u00e9m as altera\u00e7\u00f5es", "INFO")
                        continue
                    first_def = re.search(r'^def\s+\w+\s*\(', content, re.MULTILINE)
                    if not first_def:
                        self.log(f"Auto-revis\u00e3o: n\u00e3o foi poss\u00edvel extrair m\u00e9todo do retorno da IA", "WARNING")
                        continue
                    method_name = first_def.group(0)
                    if current.count(method_name) != 1:
                        self.log(f"Auto-revis\u00e3o: m\u00e9todo '{method_name}' aparece {current.count(method_name)}x no arquivo — pulando", "WARNING")
                        continue
                    bak = abs_path.with_suffix(".py.bak")
                    if not bak.exists():
                        abs_path.rename(bak)
                    start_idx = current.find(method_name)
                    rest = current[start_idx:]
                    indent = len(rest) - len(rest.lstrip())
                    def_line_end = rest.find('\n')
                    body_start = def_line_end + 1
                    next_def = re.search(r'\n(?=' + ' ' * indent + r'def\s+\w+\s*\()', rest[body_start:])
                    if next_def:
                        end_idx = start_idx + body_start + next_def.start()
                    else:
                        end_idx = len(current)
                    new_code = current[:start_idx] + content.strip() + "\n" + current[end_idx:]
                    abs_path.write_text(new_code, encoding="utf-8")
                    self.log(f"Orchestrator auto-corrigido: {rel_path} ({method_name.strip(' def(')})", "SUCCESS")
            return True
        except Exception as e:
            self.log(f"Auto-revis\u00e3o: {e}", "WARNING")
            return True

    # ── Pipeline ───────────────────────────────────────────────────────

    def orchestrate(self, skip_tests: bool = False, debug: bool = False,
                    build_number: Optional[str] = None) -> bool:
        print(f"\n{Color.BOLD}{Color.CYAN}{'='*60}{Color.RESET}")
        print(f"{Color.BOLD}{Color.CYAN}FLUTTER BUILD ORCHESTRATOR{Color.RESET}")
        print(f"{Color.BOLD}{Color.CYAN}{'='*60}{Color.RESET}\n")

        self.log(f"Projeto: {self.project_path}", "INFO")
        self.log(f"Output: {self.output_dir}", "INFO")

        steps = [
            ("Pré-requisitos", lambda: self.check_prerequisites()),
            ("Validação", lambda: self.validate_flutter_project()),
            ("Auto-revisão do Orchestrator", lambda: self._ai_self_review()),
            ("Dependências", lambda: self.get_dependencies()),
            ("Correção pré-build",
             lambda: self._apply_pre_build_fixes()),
            ("Análise", lambda: self.analyze_code()),
            ("Testes", lambda: self.run_tests(skip=skip_tests)),
            ("Build APK",
             lambda: self.build_apk(release=not debug, build_number=build_number)),
            ("Artifacts", lambda: self.copy_artifacts()),
        ]

        apk_path = None
        total = len(steps)
        for idx, (name, fn) in enumerate(steps):
            if self._cancelled:
                self.log("Build cancelado pelo usu\u00e1rio", "WARNING")
                self.generate_build_report(apk_path, False)
                return False
            pct = int((idx / total) * 100)
            self._progress(pct, name)
            self.log(f"\n>>> {name}", "STEP")
            try:
                result = fn()
                if result is False and name != "Testes":
                    self.log(f"Falhou em: {name}", "ERROR")
                    self.generate_build_report(apk_path, False)
                    return False
                if name == "Artifacts" and result:
                    apk_path = result
                self._progress(int(((idx + 1) / total) * 100),
                               f"{name} — conclu\u00eddo")
            except Exception as e:
                self.log(f"Erro em '{name}': {e}", "ERROR")
                self.generate_build_report(apk_path, False)
                return False

        self.last_apk_path = apk_path
        ok = apk_path is not None
        self.generate_build_report(apk_path, ok)
        if ok:
            self.log("BUILD CONCLU\u00cdDO COM SUCESSO!", "SUCCESS")
            winsound.MessageBeep(winsound.MB_ICONASTERISK)
        else:
            self.log("BUILD FALHOU", "ERROR")
            winsound.MessageBeep(winsound.MB_ICONHAND)
        return ok


# ---------------------------------------------------------------------------
#  CLI entry point
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Flutter Build Orchestrator — automatiza o build de APKs",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""
Exemplos:
  %(prog)s ./meu_projeto_flutter
  %(prog)s ./meu_projeto_flutter --output ./builds --debug --skip-tests
  %(prog)s ./meu_projeto_flutter --build-number 42 --auto-install
        """
    )
    parser.add_argument("project_path", help="Caminho para o projeto Flutter")
    parser.add_argument("--output", "-o", default="build_output",
                        help="Diret\u00f3rio de output (padr\u00e3o: build_output)")
    parser.add_argument("--debug", "-d", action="store_true",
                        help="Build debug (padr\u00e3o: release)")
    parser.add_argument("--skip-tests", action="store_true",
                        help="Pular testes")
    parser.add_argument("--build-number", "-b", type=str,
                        help="N\u00famero da build")
    parser.add_argument("--auto-install", action="store_true",
                        help="Auto-instalar Flutter se ausente")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Output verbose")

    args = parser.parse_args()

    project_path = Path(args.project_path).resolve()
    if not project_path.exists():
        print(f"{Color.RED}Erro: projeto n\u00e3o encontrado{Color.RESET}")
        sys.exit(1)

    orch = FlutterBuildOrchestrator(
        project_path=str(project_path),
        output_dir=args.output,
        auto_install=args.auto_install,
    )
    ok = orch.orchestrate(
        skip_tests=args.skip_tests,
        debug=args.debug,
        build_number=args.build_number,
    )
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
