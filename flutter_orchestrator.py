#!/usr/bin/env python3
"""
Flutter Build Orchestrator
Automatiza todo o processo de build de aplicativos Flutter, gerando APK pronto para instala\u00e7\u00e3o.
Unifica as funcionalidades dos dois scripts anteriores com auto-install e corre\u00e7\u00f5es autom\u00e1ticas.
"""

import os
import sys
import subprocess
import shutil
import argparse
import json
import platform
import re
import zipfile
import tarfile
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict
from urllib.request import urlopen, Request
from urllib.error import URLError


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
    Retorna None se falhar (fallback para vers\u00e3o fixa conhecida).
    """
    try:
        url = ("https://storage.googleapis.com/"
               "flutter_infra_release/releases/releases_linux.json")
        req = Request(url, headers={"User-Agent": "FlutterOrchestrator/1.0"})
        with urlopen(req, timeout=15) as r:
            data = json.loads(r.read())
        stable = [r for r in data.get("releases", [])
                  if r.get("channel") == "stable"]
        if stable:
            return stable[0]["version"]
    except Exception:
        pass
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

    def __init__(self, project_path: str,
                 output_dir: str = "build_output",
                 auto_install: bool = False):
        self.project_path = Path(project_path).resolve()
        self.output_dir = Path(output_dir).resolve()
        self.auto_install = auto_install
        self.build_log: List[Dict] = []
        self.start_time = datetime.now()
        self.flutter_cmd = "flutter"
        self.install_dir = Path.home() / ".flutter_auto"

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

    # ── Prerequisites ──────────────────────────────────────────────────

    def check_prerequisites(self) -> bool:
        self.log("Verificando pr\u00e9-requisitos...", "STEP")
        all_ok = True

        # Flutter
        try:
            result = subprocess.run(
                [self.flutter_cmd, "--version"],
                capture_output=True, text=True, timeout=30
            )
            if result.returncode == 0:
                v = result.stdout.split("\n")[0]
                self.log(f"Flutter: {v}", "SUCCESS")
            else:
                raise Exception("Flutter --version falhou")
        except (FileNotFoundError, Exception):
            self.log("Flutter n\u00e3o encontrado", "ERROR")
            if self.auto_install:
                self.log("Auto-instala\u00e7\u00e3o ativada...", "INFO")
                if self._install_flutter():
                    return self.check_prerequisites()
            all_ok = False

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

        try:
            subprocess.run(
                [self.flutter_cmd, "doctor", "--android-licenses"],
                input="y\n" * 5, text=True,
                capture_output=True, timeout=120,
            )
        except Exception:
            pass

        return True

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
            if result.returncode == 0:
                self.log("An\u00e1lise sem erros", "SUCCESS")
            else:
                if "error:" in (result.stdout + result.stderr).lower():
                    self.log("Erros de an\u00e1lise encontrados", "WARNING")
                    self.log(result.stdout[:500], "INFO")
                else:
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
                  build_number: Optional[str] = None) -> bool:
        mode = "release" if release else "debug"
        self.log(f"Compilando APK ({mode})...", "STEP")
        try:
            cmd = [self.flutter_cmd, "build", "apk"]
            if release:
                cmd.append("--release")
            if build_number:
                cmd.extend(["--build-number", build_number])
            result = subprocess.run(
                cmd, cwd=self.project_path,
                capture_output=True, text=True, timeout=1800
            )
            if result.returncode == 0:
                self.log("APK compilado com sucesso", "SUCCESS")
                return True
            self.log(f"Erro: {result.stderr[:500]}", "ERROR")
            return False
        except subprocess.TimeoutExpired:
            self.log("Timeout na compila\u00e7\u00e3o", "ERROR")
            return False
        except Exception as e:
            self.log(f"Erro: {e}", "ERROR")
            return False

    # ── Artifacts ──────────────────────────────────────────────────────

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
        self.log(f"Copiado: {output_path}", "SUCCESS")
        return output_path

    # ── Report ─────────────────────────────────────────────────────────

    def generate_build_report(self, apk_path: Optional[Path], success: bool):
        self.log("Gerando relat\u00f3rio...", "STEP")
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

    # ── Pipeline ───────────────────────────────────────────────────────

    def orchestrate(self, skip_tests: bool = False, debug: bool = False,
                    build_number: Optional[str] = None) -> bool:
        print(f"\n{Color.BOLD}{Color.CYAN}{'='*60}{Color.RESET}")
        print(f"{Color.BOLD}{Color.CYAN}FLUTTER BUILD ORCHESTRATOR{Color.RESET}")
        print(f"{Color.BOLD}{Color.CYAN}{'='*60}{Color.RESET}\n")

        self.log(f"Projeto: {self.project_path}", "INFO")
        self.log(f"Output: {self.output_dir}", "INFO")

        steps = [
            ("Pr\u00e9-requisitos", lambda: self.check_prerequisites()),
            ("Valida\u00e7\u00e3o", lambda: self.validate_flutter_project()),
            ("Depend\u00eancias", lambda: self.get_dependencies()),
            ("An\u00e1lise", lambda: self.analyze_code()),
            ("Testes", lambda: self.run_tests(skip=skip_tests)),
            ("Build APK",
             lambda: self.build_apk(release=not debug, build_number=build_number)),
            ("Artifacts", lambda: self.copy_artifacts()),
        ]

        apk_path = None
        for name, fn in steps:
            self.log(f"\n>>> {name}", "STEP")
            try:
                result = fn()
                if result is False and name != "Testes":
                    self.log(f"Falhou em: {name}", "ERROR")
                    self.generate_build_report(apk_path, False)
                    return False
                if name == "Artifacts" and result:
                    apk_path = result
            except Exception as e:
                self.log(f"Erro em '{name}': {e}", "ERROR")
                self.generate_build_report(apk_path, False)
                return False

        ok = apk_path is not None
        self.generate_build_report(apk_path, ok)
        if ok:
            self.log("BUILD CONCLU\u00cdDO COM SUCESSO!", "SUCCESS")
        else:
            self.log("BUILD FALHOU", "ERROR")
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
