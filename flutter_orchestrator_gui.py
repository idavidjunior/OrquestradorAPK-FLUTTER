#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Flutter Build Orchestrator — Interface Gráfica
Fontes: código colado | pasta local | link GitHub
Motor: build local com fallback automático para GitHub Actions
"""

import sys
import os
import queue
import threading
import subprocess
import platform
import shutil
import tempfile
import re
import json
import time
import zipfile
import io
import traceback
from datetime import datetime
from pathlib import Path
from urllib.request import urlopen, Request

# ─────────────────────────────────────────────────────────────
#  Verifica suporte a GUI
# ─────────────────────────────────────────────────────────────
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
    print("GUI indisponível. Use flutter_orchestrator.py no terminal.")
    sys.exit(1)

import customtkinter as ctk
import tkinter as tk
from tkinter import filedialog, messagebox

ctk.set_appearance_mode("System")
ctk.set_default_color_theme("blue")

# ─────────────────────────────────────────────────────────────
#  Logger — fila thread-safe, drenada por timer independente
# ─────────────────────────────────────────────────────────────
class Logger:
    """
    Qualquer thread chama .put(). O widget tkinter só é tocado
    pelo timer _drain() que roda no mainloop — nunca de outra thread.
    """
    ICONS = {"ok": "✅", "err": "❌", "warn": "⚠️", "info": "ℹ️", "sep": "─"}

    def __init__(self, textbox: ctk.CTkTextbox):
        self._box = textbox
        self._q: queue.Queue = queue.Queue()
        self._drain()

    def _drain(self):
        try:
            count = 0
            while count < 30:          # máx 30 linhas por ciclo
                level, msg = self._q.get_nowait()
                ts = datetime.now().strftime("%H:%M:%S")
                icon = self.ICONS.get(level, "•")
                line = f"[{ts}] {icon}  {msg}\n" if level != "sep" else f"{'─'*60}\n"
                self._box.configure(state="normal")
                self._box.insert("end", line)
                self._box.see("end")
                self._box.configure(state="disabled")
                count += 1
        except queue.Empty:
            pass
        except Exception:
            pass
        self._box.after(40, self._drain)   # agenda próximo ciclo

    def put(self, msg: str, level: str = "info"):
        self._q.put((level, msg))

    def sep(self):
        self._q.put(("sep", ""))

    def ok(self, msg):  self.put(msg, "ok")
    def err(self, msg): self.put(msg, "err")
    def warn(self, msg):self.put(msg, "warn")
    def info(self, msg):self.put(msg, "info")


# ─────────────────────────────────────────────────────────────
#  Checklist de pré-requisitos
# ─────────────────────────────────────────────────────────────
class Checklist:
    """
    Verifica todos os pré-requisitos antes de qualquer build.
    Retorna (ok: bool, flutter_exe: str | None).
    """

    def __init__(self, log: Logger):
        self.log = log
        self.flutter_exe: str | None = None

    def run(self) -> bool:
        self.log.sep()
        self.log.info("PRÉ-REQUISITOS — verificando ambiente...")
        self.log.sep()

        results = [
            self._check_python(),
            self._check_git(),
            self._check_java(),
            self._check_flutter(),
        ]

        self.log.sep()
        if all(results):
            self.log.ok("Todos os pré-requisitos OK — iniciando build")
        else:
            self.log.err("Um ou mais pré-requisitos falharam — build cancelado")
        self.log.sep()
        return all(results)

    # ── checks individuais ────────────────────────
    def _check_python(self) -> bool:
        v = platform.python_version()
        self.log.ok(f"Python {v}")
        return True

    def _check_git(self) -> bool:
        try:
            r = subprocess.run(["git", "--version"], capture_output=True, text=True, timeout=10)
            if r.returncode == 0:
                self.log.ok(f"Git: {r.stdout.strip()}")
                return True
        except Exception:
            pass
        self.log.err("Git NÃO encontrado — necessário para clonagem de repositórios")
        return False

    def _check_java(self) -> bool:
        try:
            r = subprocess.run(
                ["java", "-version"], capture_output=True, text=True, timeout=10)
            out = (r.stdout + r.stderr).strip().split("\n")[0]
            self.log.ok(f"Java: {out}")
            return True
        except Exception:
            pass
        # Tenta JAVA_HOME
        jh = os.environ.get("JAVA_HOME", "")
        if jh:
            java_bin = Path(jh) / "bin" / ("java.exe" if os.name == "nt" else "java")
            if java_bin.exists():
                self.log.ok(f"Java via JAVA_HOME: {java_bin}")
                return True
        self.log.warn("Java não encontrado — pode ser necessário para o build Android")
        return True   # warning, não bloqueia

    def _check_flutter(self) -> bool:
        # Candidatos em ordem de prioridade
        candidates = self._flutter_candidates()
        for exe in candidates:
            try:
                r = subprocess.run(
                    [exe, "--version"],
                    capture_output=True, text=True, timeout=30,
                    env=os.environ.copy()
                )
                if r.returncode == 0:
                    version_line = (r.stdout + r.stderr).strip().split("\n")[0]
                    self.log.ok(f"Flutter: {version_line}")
                    self.log.info(f"  Executável: {exe}")
                    self.flutter_exe = exe
                    # Garante que o bin/ está no PATH para subprocessos filhos
                    bin_dir = str(Path(exe).parent)
                    if bin_dir not in os.environ.get("PATH", ""):
                        os.environ["PATH"] = bin_dir + os.pathsep + os.environ.get("PATH", "")
                    return True
            except Exception:
                continue

        self.log.err("Flutter NÃO encontrado")
        self.log.info("  Locais verificados:")
        for c in candidates:
            self.log.info(f"    • {c}")
        self.log.info("  Solução: instale o Flutter e adicione flutter/bin ao PATH")
        self.log.info("  https://docs.flutter.dev/get-started/install")
        return False

    def _flutter_candidates(self) -> list[str]:
        is_win = os.name == "nt"
        suffix = ".bat" if is_win else ""
        candidates = []

        # 1. PATH direto
        candidates.append(f"flutter{suffix}")

        # 2. Variáveis de ambiente
        for var in ("Flutter", "Flutterbin", "FLUTTER_ROOT", "FLUTTER_HOME", "FLUTTER_SDK"):
            val = os.environ.get(var, "").strip()
            if val:
                for sub in [f"flutter{suffix}", f"bin/flutter{suffix}"]:
                    candidates.append(str(Path(val) / sub))

        # 3. Caminhos comuns
        home = Path.home()
        roots = [
            home / "flutter",
            home / "development" / "flutter",
            home / ".flutter_orchestrator" / "flutter",
            Path("C:/flutter"),
            Path("C:/src/flutter"),
            Path("C:/tools/flutter"),
            Path("/usr/local/flutter"),
            Path("/opt/flutter"),
        ]
        for root in roots:
            candidates.append(str(root / "bin" / f"flutter{suffix}"))

        # Remove duplicatas mantendo ordem
        seen = set()
        result = []
        for c in candidates:
            if c not in seen:
                seen.add(c)
                result.append(c)
        return result


# ─────────────────────────────────────────────────────────────
#  Project Source Manager
# ─────────────────────────────────────────────────────────────
class ProjectSourceManager:

    @staticmethod
    def from_code(code: str, work_dir: Path, flutter_exe: str, log: Logger) -> Path:
        project_dir = work_dir / "pasted_project"
        if project_dir.exists():
            shutil.rmtree(project_dir)

        log.info("Criando projeto Flutter para código colado...")
        log.info(f"  Destino: {project_dir}")
        log.info("  (Primeira execução pode levar alguns minutos — aguarde)")

        cmd = [flutter_exe, "create",
               "--project-name", "flutter_app_generated",
               "--org", "com.orchestrator",
               str(project_dir)]
        log.info(f"  ▶ {' '.join(cmd)}")

        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=os.environ.copy(),
            )

            # Lê saída em tempo real — evita bloqueio de buffer no Windows
            deadline = time.time() + 600  # 10 min
            for line in proc.stdout:
                line = line.rstrip()
                if line:
                    log.info(line)
                if time.time() > deadline:
                    proc.kill()
                    raise Exception("flutter create excedeu 10 minutos")

            proc.wait()
            if proc.returncode != 0:
                raise Exception(f"flutter create falhou (exit {proc.returncode})")

        except Exception as e:
            raise Exception(f"flutter create: {e}")

        if not (project_dir / "pubspec.yaml").exists():
            raise Exception(f"Projeto não foi criado corretamente em {project_dir}")

        main_dart = project_dir / "lib" / "main.dart"
        content = code if "void main(" in code else (
            "import 'package:flutter/material.dart';\n\n" + code
        )
        main_dart.write_text(content, encoding="utf-8")
        log.ok(f"Projeto criado com sucesso. main.dart substituído ({len(content)} chars)")
        return project_dir

    @staticmethod
    def from_directory(path: str, log: Logger) -> Path:
        p = Path(path).resolve()
        if not (p / "pubspec.yaml").exists():
            raise Exception(f"pubspec.yaml não encontrado em: {p}")
        log.ok(f"Projeto local: {p}")
        return p

    @staticmethod
    def from_github(url: str, work_dir: Path, token: str, log: Logger) -> Path:
        url = url.strip().rstrip("/")
        if not url.startswith("http"):
            url = "https://github.com/" + url
        clone_url = re.sub(r"https://", f"https://{token}@", url) if token else url
        repo_name = url.split("/")[-1].replace(".git", "")
        dest = work_dir / repo_name
        if dest.exists():
            shutil.rmtree(dest)
        log.info(f"Clonando: {url}")

        proc = subprocess.Popen(
            ["git", "clone", "--depth", "1", clone_url, str(dest)],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace",
        )
        for line in proc.stdout:
            line = line.rstrip()
            if line:
                log.info(line)
        proc.wait()
        if proc.returncode != 0:
            raise Exception(f"git clone falhou (exit {proc.returncode})")
        if not (dest / "pubspec.yaml").exists():
            raise Exception("Repositório não contém pubspec.yaml")
        log.ok(f"Clonado em: {dest}")
        return dest


# ─────────────────────────────────────────────────────────────
#  ADB Helper
# ─────────────────────────────────────────────────────────────
class ADBHelper:

    @staticmethod
    def find_adb() -> str | None:
        if shutil.which("adb"):
            return "adb"
        for p in [
            Path.home() / "Android/Sdk/platform-tools/adb",
            Path(os.environ.get("ANDROID_HOME", "")) / "platform-tools/adb",
            Path("C:/Android/platform-tools/adb.exe"),
            Path.home() / "AppData/Local/Android/Sdk/platform-tools/adb.exe",
        ]:
            if p.exists():
                return str(p)
        return None

    @staticmethod
    def list_devices(adb: str) -> list[tuple[str, str]]:
        try:
            r = subprocess.run([adb, "devices", "-l"],
                               capture_output=True, text=True, timeout=10)
            devices = []
            for line in r.stdout.splitlines()[1:]:
                if "device" in line and "offline" not in line:
                    parts = line.split()
                    serial = parts[0]
                    model = next((p.split(":")[1] for p in parts
                                  if p.startswith("model:")), serial)
                    devices.append((serial, model))
            return devices
        except Exception:
            return []

    @staticmethod
    def install(adb: str, serial: str, apk: str, log: Logger):
        log.info(f"Instalando via ADB → {serial}")
        try:
            proc = subprocess.Popen(
                [adb, "-s", serial, "install", "-r", apk],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
            )
            for line in proc.stdout:
                line = line.strip()
                if line:
                    log.info(line)
            proc.wait()
            if proc.returncode == 0:
                log.ok("APK instalado no dispositivo!")
            else:
                log.err(f"adb install falhou (exit {proc.returncode})")
        except Exception as e:
            log.err(f"Erro ADB: {e}")


# ─────────────────────────────────────────────────────────────
#  CI Engine
# ─────────────────────────────────────────────────────────────
class CIEngine:
    CI_REPO  = "idavidjunior/flutter-ci"
    WORKFLOW = "build.yml"
    API      = "https://api.github.com"

    def __init__(self, token: str, log: Logger):
        self.token = token
        self.log   = log
        self._hdrs = {
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        self._tmp_release_id: int | None = None

    def _api(self, method, path, body=None):
        data = json.dumps(body).encode() if body else None
        req  = Request(f"{self.API}{path}", data=data,
                       headers={**self._hdrs, "Content-Type": "application/json"},
                       method=method)
        with urlopen(req, timeout=30) as r:
            return json.loads(r.read())

    def _upload_project(self, project_path: Path, session_id: str) -> str:
        self.log.info("Empacotando projeto para CI...")
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for f in project_path.rglob("*"):
                if any(p in ("build", ".dart_tool", ".git", ".idea")
                       for p in f.parts):
                    continue
                if f.is_file():
                    zf.write(f, f.relative_to(project_path))
        size = len(buf.getvalue()) // 1024
        self.log.info(f"Zip: {size} KB")
        buf.seek(0)

        tag = f"ci-tmp-{session_id}"
        release = self._api("POST", f"/repos/{self.CI_REPO}/releases", {
            "tag_name": tag, "name": f"CI {session_id}",
            "draft": False, "prerelease": True,
        })
        self._tmp_release_id = release["id"]
        upload_url = release["upload_url"].split("{")[0]

        zip_bytes = buf.read()
        asset_name = f"project_{session_id}.zip"
        req = Request(
            f"{upload_url}?name={asset_name}",
            data=zip_bytes,
            headers={**self._hdrs, "Content-Type": "application/zip",
                     "Content-Length": str(len(zip_bytes))},
            method="POST"
        )
        with urlopen(req, timeout=120) as r:
            asset = json.loads(r.read())

        url = asset["browser_download_url"]
        self.log.ok(f"Upload concluído: {asset_name}")
        return url

    def _cleanup(self):
        if self._tmp_release_id:
            try:
                self._api("DELETE",
                          f"/repos/{self.CI_REPO}/releases/{self._tmp_release_id}")
                self.log.info("Release temporária removida")
            except Exception:
                pass

    def dispatch(self, zip_url: str, build_type: str, session_id: str) -> float:
        self.log.info("Disparando workflow no GitHub Actions...")
        t = time.time()
        self._api("POST",
            f"/repos/{self.CI_REPO}/actions/workflows/{self.WORKFLOW}/dispatches",
            {"ref": "main", "inputs": {
                "project_zip_url": zip_url, "project_zip_b64": "",
                "build_type": build_type, "session_id": session_id,
            }}
        )
        self.log.ok("Workflow disparado")
        return t

    def monitor(self, dispatch_time: float, timeout=1200) -> dict | None:
        self.log.info("Aguardando run do workflow...")
        deadline = time.time() + 90
        run = None
        while time.time() < deadline and not run:
            try:
                data = self._api("GET",
                    f"/repos/{self.CI_REPO}/actions/workflows/{self.WORKFLOW}/runs?per_page=5")
                for r in data.get("workflow_runs", []):
                    try:
                        import datetime as _dt
                        ts = _dt.datetime.fromisoformat(
                            r["created_at"].replace("Z", "+00:00")).timestamp()
                        if ts >= dispatch_time - 30:
                            run = r
                            break
                    except Exception:
                        pass
            except Exception:
                pass
            if not run:
                time.sleep(5)

        if not run:
            self.log.err("Run não encontrado após dispatch")
            return None

        run_id = run["id"]
        self.log.info(f"Run #{run_id}: {run['html_url']}")
        deadline = time.time() + timeout
        dots = 0
        while time.time() < deadline:
            try:
                run = self._api("GET", f"/repos/{self.CI_REPO}/actions/runs/{run_id}")
                status = run.get("status", "")
                conclusion = run.get("conclusion", "")
                dots = (dots + 1) % 4
                self.log.info(f"Status: {status}{'.' * dots}")
                if status == "completed":
                    if conclusion == "success":
                        self.log.ok("Build remoto concluído!")
                        return run
                    else:
                        self.log.err(f"Build remoto falhou: {conclusion}")
                        self.log.info(f"Detalhes: {run['html_url']}")
                        return None
            except Exception as e:
                self.log.warn(f"Erro ao monitorar: {e}")
            time.sleep(8)

        self.log.err("Timeout aguardando GitHub Actions")
        return None

    def download_apk(self, run: dict, session_id: str, dest: Path) -> Path | None:
        self.log.info("Baixando APK do artefato...")
        try:
            data = self._api("GET",
                f"/repos/{self.CI_REPO}/actions/runs/{run['id']}/artifacts")
            artifacts = data.get("artifacts", [])
            if not artifacts:
                self.log.err("Nenhum artefato encontrado")
                return None

            art = artifacts[0]
            self.log.info(f"Artefato: {art['name']} ({art['size_in_bytes']//1024} KB)")
            dl_url = f"{self.API}/repos/{self.CI_REPO}/actions/artifacts/{art['id']}/zip"
            req = Request(dl_url, headers=self._hdrs)
            with urlopen(req, timeout=120) as r:
                buf = io.BytesIO(r.read())

            dest.mkdir(parents=True, exist_ok=True)
            apk_path = dest / f"app_{session_id}.apk"
            with zipfile.ZipFile(buf) as z:
                for name in z.namelist():
                    if name.endswith(".apk"):
                        with z.open(name) as src, open(apk_path, "wb") as dst:
                            dst.write(src.read())
                        break

            if apk_path.exists():
                self.log.ok(f"APK baixado: {apk_path}")
                return apk_path
            self.log.err("APK não encontrado no artefato")
            return None
        except Exception as e:
            self.log.err(f"Falha ao baixar APK: {e}")
            return None

    def run_pipeline(self, project_path: Path, build_type: str) -> Path | None:
        session_id = datetime.now().strftime("%Y%m%d%H%M%S")
        try:
            zip_url = self._upload_project(project_path, session_id)
            dt = self.dispatch(zip_url, build_type, session_id)
            run = self.monitor(dt)
            if not run:
                return None
            return self.download_apk(run, session_id,
                                     project_path.parent / "ci_outputs")
        finally:
            self._cleanup()


# ─────────────────────────────────────────────────────────────
#  Build Runner — executa comandos com log em tempo real
# ─────────────────────────────────────────────────────────────
class BuildRunner:

    def __init__(self, flutter_exe: str, log: Logger):
        self.flutter = flutter_exe
        self.log = log

    def run(self, cmd: list[str], cwd: Path, fail_on_error=True) -> bool:
        cmd_str = " ".join(str(c) for c in cmd)
        self.log.info(f"▶ {cmd_str}")
        self.log.info(f"  em: {cwd}")
        try:
            env = os.environ.copy()
            proc = subprocess.Popen(
                cmd, cwd=str(cwd),
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, bufsize=1, env=env,
                encoding="utf-8", errors="replace",
            )
            stdout_lines, stderr_lines = [], []

            def _read(stream, store, level):
                for line in stream:
                    line = line.rstrip()
                    if line:
                        store.append(line)
                        self.log.put(line, level)

            t1 = threading.Thread(target=_read,
                                  args=(proc.stdout, stdout_lines, "info"), daemon=True)
            t2 = threading.Thread(target=_read,
                                  args=(proc.stderr, stderr_lines, "warn"), daemon=True)
            t1.start(); t2.start()
            t1.join();  t2.join()
            proc.wait()

            rc = proc.returncode
            if rc == 0:
                self.log.ok(f"Concluído (exit 0)")
                return True
            else:
                self.log.err(f"Falhou (exit {rc})")
                if stderr_lines:
                    self.log.err("── Últimas linhas de erro ──")
                    for l in stderr_lines[-20:]:
                        self.log.err(l)
                return not fail_on_error

        except FileNotFoundError:
            self.log.err(f"Executável não encontrado: {cmd[0]}")
            self.log.err(f"PATH: {os.environ.get('PATH','')}")
            return False
        except Exception as e:
            self.log.err(f"Exceção: {e}")
            self.log.err(traceback.format_exc())
            return False

    def flutter_cmd(self, args: list[str], cwd: Path, fail_on_error=True) -> bool:
        return self.run([self.flutter] + args, cwd, fail_on_error)


# ─────────────────────────────────────────────────────────────
#  Main GUI
# ─────────────────────────────────────────────────────────────
class FlutterOrchestratorGUI(ctk.CTk):

    def __init__(self):
        super().__init__()
        self.title("🚀 Flutter Build Orchestrator")
        self.geometry("1020x800")
        self.minsize(900, 680)

        self.build_type     = tk.StringVar(value="release")
        self.auto_install   = tk.BooleanVar(value=True)
        self.auto_adb       = tk.BooleanVar(value=True)
        self.github_token   = tk.StringVar()
        self.ci_token       = tk.StringVar()
        self.folder_path    = tk.StringVar()
        self.github_url     = tk.StringVar()
        self.device_var     = tk.StringVar(value="Nenhum dispositivo")

        self.is_building    = False
        self.last_apk       = None
        self._devices: list[tuple[str,str]] = []
        self._adb_exe: str | None = None
        self.work_dir       = Path(tempfile.mkdtemp(prefix="flutter_orch_"))
        self._checklist: Checklist | None = None   # resultado do último checklist

        self._build_ui()
        self._poll_adb()   # detecção automática a cada 2s
        # Roda checklist automaticamente ao abrir
        threading.Thread(target=self._run_checklist, daemon=True).start()

    # ── UI ──────────────────────────────────────
    def _build_ui(self):
        # Header
        hdr = ctk.CTkFrame(self, fg_color="transparent")
        hdr.pack(fill="x", padx=20, pady=(14, 4))
        ctk.CTkLabel(hdr, text="🚀 Flutter Build Orchestrator",
                     font=ctk.CTkFont(size=22, weight="bold")).pack(side="left")
        ctk.CTkLabel(hdr, text="compile · instale · entregue",
                     font=ctk.CTkFont(size=12), text_color="gray").pack(
                         side="left", padx=10, pady=(4, 0))

        # Tabs de entrada
        self.tabview = ctk.CTkTabview(self, height=230)
        self.tabview.pack(fill="x", padx=20, pady=(4, 0))
        for tab in ("📋 Colar Código", "📁 Pasta / Diretório", "🔗 Link GitHub"):
            self.tabview.add(tab)
        self._tab_code()
        self._tab_folder()
        self._tab_github()

        # Opções
        self._row_options()
        # CI
        self._row_ci()
        # ADB
        self._row_adb()

        # Botão build
        self.btn_build = ctk.CTkButton(
            self, text="🔨 Iniciar Build", command=self.start_build,
            height=46, font=ctk.CTkFont(size=15, weight="bold"),
            fg_color="#28a745", hover_color="#218838"
        )
        self.btn_build.pack(fill="x", padx=20, pady=(8, 2))

        # Progress + status
        self.progress = ctk.CTkProgressBar(self, mode="indeterminate")
        self.progress.pack(fill="x", padx=20, pady=(0, 2))
        self.progress.set(0)
        self.lbl_status = ctk.CTkLabel(self, text="● Pronto", text_color="gray",
                                        font=ctk.CTkFont(size=12))
        self.lbl_status.pack(anchor="w", padx=22)

        # Log
        lf = ctk.CTkFrame(self)
        lf.pack(fill="both", expand=True, padx=20, pady=(4, 12))
        top = ctk.CTkFrame(lf, fg_color="transparent")
        top.pack(fill="x", padx=8, pady=(6, 2))
        ctk.CTkLabel(top, text="📋 Log em Tempo Real",
                     font=ctk.CTkFont(weight="bold")).pack(side="left")
        ctk.CTkButton(top, text="Limpar", width=60, height=24,
                      command=self._clear_log).pack(side="right")
        self.log_box = ctk.CTkTextbox(
            lf, wrap="word", state="disabled",
            font=ctk.CTkFont(family="Courier New", size=11)
        )
        self.log_box.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        # Inicia o Logger (drena a fila via timer interno)
        self.log = Logger(self.log_box)

    def _tab_code(self):
        tab = self.tabview.tab("📋 Colar Código")
        ctk.CTkLabel(tab,
            text="Cole o código Dart abaixo. Um projeto Flutter completo será gerado automaticamente.",
            text_color="gray", font=ctk.CTkFont(size=11)
        ).pack(anchor="w", padx=4, pady=(4, 2))
        self.code_box = ctk.CTkTextbox(
            tab, font=ctk.CTkFont(family="Courier New", size=12), height=155)
        self.code_box.pack(fill="both", expand=True, padx=4, pady=(0, 4))
        self.code_box.insert("end", "// Cole seu código Dart aqui\n")

    def _tab_folder(self):
        tab = self.tabview.tab("📁 Pasta / Diretório")
        row = ctk.CTkFrame(tab, fg_color="transparent")
        row.pack(fill="x", padx=4, pady=30)
        ctk.CTkLabel(row, text="Pasta do projeto:", width=130).pack(side="left")
        ctk.CTkEntry(row, textvariable=self.folder_path, width=520,
                     placeholder_text="Selecione ou digite o caminho...").pack(
                         side="left", padx=8)
        ctk.CTkButton(row, text="📂 Procurar", width=100,
                      command=self._browse).pack(side="left")

    def _tab_github(self):
        tab = self.tabview.tab("🔗 Link GitHub")
        r1 = ctk.CTkFrame(tab, fg_color="transparent")
        r1.pack(fill="x", padx=4, pady=(18, 6))
        ctk.CTkLabel(r1, text="URL do repositório:", width=150).pack(side="left")
        ctk.CTkEntry(r1, textvariable=self.github_url, width=560,
                     placeholder_text="https://github.com/usuario/repo").pack(
                         side="left", padx=8)
        r2 = ctk.CTkFrame(tab, fg_color="transparent")
        r2.pack(fill="x", padx=4)
        ctk.CTkLabel(r2, text="Token (privado):", width=150,
                     text_color="gray").pack(side="left")
        ctk.CTkEntry(r2, textvariable=self.github_token, width=400,
                     placeholder_text="ghp_xxx... (opcional)",
                     show="*").pack(side="left", padx=8)

    def _row_options(self):
        f = ctk.CTkFrame(self)
        f.pack(fill="x", padx=20, pady=(6, 0))
        ctk.CTkLabel(f, text="⚙️ Build:",
                     font=ctk.CTkFont(weight="bold")).pack(side="left", padx=12)
        ctk.CTkRadioButton(f, text="📦 Release",
                           variable=self.build_type, value="release").pack(
                               side="left", padx=10, pady=8)
        ctk.CTkRadioButton(f, text="🐛 Debug",
                           variable=self.build_type, value="debug").pack(
                               side="left", padx=10)
        ctk.CTkCheckBox(f, text="Instalar Flutter automaticamente",
                        variable=self.auto_install).pack(side="left", padx=20)
        ctk.CTkButton(f, text="🔍 Verificar Ambiente", width=160,
                      command=lambda: threading.Thread(
                          target=self._run_checklist, daemon=True).start()
                      ).pack(side="right", padx=12)

    def _row_ci(self):
        f = ctk.CTkFrame(self)
        f.pack(fill="x", padx=20, pady=(4, 0))
        ctk.CTkLabel(f, text="☁️ CI:",
                     font=ctk.CTkFont(weight="bold")).pack(side="left", padx=12, pady=8)
        self.lbl_ci_mode = ctk.CTkLabel(
            f, text="● Aguardando", text_color="gray",
            font=ctk.CTkFont(size=12, weight="bold"))
        self.lbl_ci_mode.pack(side="left", padx=(0, 10))
        ctk.CTkLabel(f, text="Token:", text_color="gray").pack(side="left")
        token_entry = ctk.CTkEntry(
            f, textvariable=self.ci_token,
            placeholder_text="ghp_xxx...", show="*", width=260)
        token_entry.pack(side="left", padx=6)
        self.lbl_token_status = ctk.CTkLabel(
            f, text="⬜ não validado", text_color="gray",
            font=ctk.CTkFont(size=11))
        self.lbl_token_status.pack(side="left", padx=4)
        ctk.CTkButton(f, text="Validar", width=70,
                      command=lambda: threading.Thread(
                          target=self._validate_token, daemon=True).start()
                      ).pack(side="left", padx=4)
        token_entry.bind("<FocusOut>", lambda e: threading.Thread(
            target=self._validate_token, daemon=True).start())
        token_entry.bind("<Return>", lambda e: threading.Thread(
            target=self._validate_token, daemon=True).start())

    def _row_adb(self):
        f = ctk.CTkFrame(self)
        f.pack(fill="x", padx=20, pady=(4, 0))
        ctk.CTkLabel(f, text="📱 ADB:",
                     font=ctk.CTkFont(weight="bold")).pack(side="left", padx=12, pady=8)

        # Indicador de status do dispositivo
        self.lbl_adb_status = ctk.CTkLabel(
            f, text="● Sem dispositivo", text_color="gray",
            font=ctk.CTkFont(size=12, weight="bold"))
        self.lbl_adb_status.pack(side="left", padx=(0, 10))

        self.menu_device = ctk.CTkOptionMenu(
            f, variable=self.device_var,
            values=["Nenhum dispositivo"], width=220)
        self.menu_device.pack(side="left", padx=4)

        ctk.CTkButton(f, text="🔄", width=36,
                      command=lambda: threading.Thread(
                          target=self._refresh_devices, daemon=True).start()
                      ).pack(side="left", padx=2)

        ctk.CTkCheckBox(f, text="Instalar auto após build",
                        variable=self.auto_adb).pack(side="left", padx=14)

        self.btn_install = ctk.CTkButton(
            f, text="📲 Instalar no Dispositivo", width=200,
            command=self._manual_install,
            fg_color="#1565C0", hover_color="#0D47A1", state="disabled")
        self.btn_install.pack(side="left", padx=8)

    # ── Helpers UI ──────────────────────────────
    def _clear_log(self):
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.configure(state="disabled")

    def _browse(self):
        d = filedialog.askdirectory(title="Selecione a pasta do projeto Flutter")
        if d:
            self.folder_path.set(d)

    def _set_status(self, text: str, color: str = "gray"):
        self.after(0, lambda: self.lbl_status.configure(text=text, text_color=color))

    def _set_ci_mode(self, mode: str):
        m = {"local": ("● Local", "#00cc66"),
             "ci":    ("● GitHub Actions", "#ffc107"),
             "idle":  ("● Aguardando", "gray")}
        text, color = m.get(mode, ("●", "gray"))
        self.after(0, lambda: self.lbl_ci_mode.configure(text=text, text_color=color))

    # ── Checklist ───────────────────────────────
    def _run_checklist(self):
        self.log.sep()
        self.log.info("🔍 VERIFICANDO AMBIENTE...")
        cl = Checklist(self.log)
        ok = cl.run()
        self._checklist = cl
        if ok:
            self._set_status("● Ambiente OK — pronto para build", "#00cc66")
        else:
            self._set_status("● Pré-requisito faltando — veja o log", "#ff4444")

    # ── Token validation ────────────────────────
    def _validate_token(self):
        token = self.ci_token.get().strip()
        if not token:
            self.after(0, lambda: self.lbl_token_status.configure(
                text="⬜ não validado", text_color="gray"))
            return
        self.after(0, lambda: self.lbl_token_status.configure(
            text="🔄 validando...", text_color="#ffc107"))
        try:
            def _get(url):
                req = Request(url, headers={**{
                    "Authorization": f"token {token}",
                    "Accept": "application/vnd.github+json"}})
                with urlopen(req, timeout=10) as r:
                    return json.loads(r.read())

            user = _get("https://api.github.com/user")
            _get(f"https://api.github.com/repos/{CIEngine.CI_REPO}")
            login = user.get("login", "?")
            self.after(0, lambda: self.lbl_token_status.configure(
                text=f"✅ válido ({login})", text_color="#00cc66"))
            self.log.ok(f"Token CI válido — usuário: {login}")
        except Exception as e:
            err = str(e)
            msg = ("❌ token inválido" if "401" in err else
                   "❌ sem acesso ao flutter-ci" if "404" in err else
                   "❌ erro de conexão")
            self.after(0, lambda m=msg: self.lbl_token_status.configure(
                text=m, text_color="#ff4444"))
            self.log.err(f"Token inválido: {err}")

    # ── ADB ─────────────────────────────────────
    def _refresh_devices(self):
        """Escaneia dispositivos ADB e atualiza UI. Pode ser chamado de qualquer thread."""
        adb = ADBHelper.find_adb()
        if not adb:
            self._adb_exe = None
            self.after(0, self._adb_ui_no_adb)
            return

        self._adb_exe = adb
        devices = ADBHelper.list_devices(adb)
        prev_count = len(self._devices)
        self._devices = devices

        if devices:
            labels = [f"{m}  ({s})" for s, m in devices]
            def _update_connected():
                self.menu_device.configure(values=labels)
                self.device_var.set(labels[0])
                self.lbl_adb_status.configure(
                    text=f"● {len(devices)} dispositivo(s)",
                    text_color="#00cc66")
            self.after(0, _update_connected)
            # Loga apenas quando novo dispositivo conectar
            if len(devices) > prev_count:
                for serial, model in devices:
                    self.log.ok(f"Dispositivo conectado: {model} ({serial})")
        else:
            self.after(0, self._adb_ui_no_device)
            # Loga apenas quando desconectar
            if prev_count > 0:
                self.log.warn("Dispositivo desconectado")

    def _adb_ui_no_adb(self):
        self.menu_device.configure(values=["ADB não encontrado"])
        self.device_var.set("ADB não encontrado")
        self.lbl_adb_status.configure(text="● ADB ausente", text_color="#ff4444")

    def _adb_ui_no_device(self):
        self.menu_device.configure(values=["Nenhum dispositivo conectado"])
        self.device_var.set("Nenhum dispositivo conectado")
        self.lbl_adb_status.configure(text="● Sem dispositivo", text_color="gray")

    def _poll_adb(self):
        """Verifica dispositivos a cada 2s em background — detecção automática."""
        threading.Thread(target=self._refresh_devices, daemon=True).start()
        self.after(2000, self._poll_adb)

    def _selected_serial(self) -> str | None:
        label = self.device_var.get()
        for serial, model in self._devices:
            if serial in label or model in label:
                return serial
        return self._devices[0][0] if self._devices else None

    def _manual_install(self):
        if not self.last_apk:
            messagebox.showwarning("Sem APK", "Faça um build primeiro.")
            return
        serial = self._selected_serial()
        if not serial or not self._adb_exe:
            messagebox.showerror("ADB", "Nenhum dispositivo selecionado.")
            return
        threading.Thread(
            target=ADBHelper.install,
            args=(self._adb_exe, serial, self.last_apk, self.log),
            daemon=True).start()

    # ── Build ────────────────────────────────────
    def start_build(self):
        if self.is_building:
            return

        tab = self.tabview.get()
        if tab == "📋 Colar Código":
            code = self.code_box.get("1.0", "end").strip()
            if not code or code.startswith("// Cole"):
                messagebox.showerror("Erro", "Cole algum código Dart.")
                return
            source = ("code", code)
        elif tab == "📁 Pasta / Diretório":
            path = self.folder_path.get().strip()
            if not path:
                messagebox.showerror("Erro", "Selecione uma pasta.")
                return
            source = ("folder", path)
        else:
            url = self.github_url.get().strip()
            if not url:
                messagebox.showerror("Erro", "Informe a URL do repositório.")
                return
            source = ("github", url)

        self.is_building = True
        self.last_apk = None
        self.btn_install.configure(state="disabled")
        self.btn_build.configure(text="⏳ Compilando...", state="disabled",
                                 fg_color="#ffc107")
        self.progress.start()
        self._set_status("🔄 Build em andamento...", "#ffc107")
        self._clear_log()
        threading.Thread(target=self._worker, args=(source,), daemon=True).start()

    def _worker(self, source):
        try:
            start = datetime.now()
            source_type, source_data = source

            self.log.sep()
            self.log.info("PIPELINE DE BUILD INICIADO")
            self.log.info(f"  Fonte  : {source_type}")
            self.log.info(f"  Tipo   : {self.build_type.get()}")
            self.log.info(f"  Sistema: {platform.system()} {platform.release()}")
            self.log.sep()

            # ── ETAPA 1: Checklist ───────────────
            self.log.info("[1/5] Verificando pré-requisitos...")
            self._set_status("Verificando ambiente...", "#ffc107")
            cl = Checklist(self.log)
            if not cl.run():
                raise Exception("Pré-requisitos não atendidos — build cancelado")

            runner = BuildRunner(cl.flutter_exe, self.log)

            # ── ETAPA 2: Resolver projeto ────────
            self.log.info("[2/5] Preparando projeto...")
            self._set_status("Preparando projeto...", "#ffc107")
            if source_type == "code":
                project = ProjectSourceManager.from_code(
                    source_data, self.work_dir, cl.flutter_exe, self.log)
            elif source_type == "folder":
                project = ProjectSourceManager.from_directory(source_data, self.log)
            else:
                project = ProjectSourceManager.from_github(
                    source_data, self.work_dir,
                    self.github_token.get().strip(), self.log)

            apk = None
            local_ok = False

            # ── ETAPA 3: Build local ─────────────
            self.log.sep()
            self.log.info("[3/5] Build local...")
            self._set_ci_mode("local")
            self._set_status("Limpando projeto...", "#ffc107")
            runner.flutter_cmd(["clean"], project, fail_on_error=False)

            self._set_status("Baixando dependências...", "#ffc107")
            self.log.info("flutter pub get")
            if not runner.flutter_cmd(["pub", "get"], project):
                self.log.warn("pub get falhou — tentando continuar...")
            else:
                build_flag = "--" + self.build_type.get()
                self._set_status(f"Compilando APK {self.build_type.get()}...", "#ffc107")
                self.log.info(f"flutter build apk {build_flag}")
                if runner.flutter_cmd(["build", "apk", build_flag], project):
                    apk = self._find_apk(project)
                    if apk:
                        local_ok = True
                        self.log.ok("Build local concluído!")

            # ── ETAPA 4: Fallback CI ─────────────
            if not local_ok:
                self.log.sep()
                self.log.warn("[4/5] Build local falhou — ativando GitHub Actions...")
                token = self.ci_token.get().strip()
                if not token:
                    raise Exception(
                        "Build local falhou. Configure o token CI para usar o fallback.")
                self._set_ci_mode("ci")
                self._set_status("GitHub Actions — aguardando...", "#ffc107")
                ci = CIEngine(token, self.log)
                apk_path = ci.run_pipeline(project, self.build_type.get())
                if not apk_path:
                    raise Exception("Build remoto também falhou.")
                apk = str(apk_path)
            else:
                self.log.info("[4/5] Fallback CI não necessário")

            # ── ETAPA 5: Entrega ─────────────────
            self.log.sep()
            self.log.info("[5/5] Entregando APK...")
            self.last_apk = apk
            elapsed = datetime.now() - start
            self.log.ok(f"APK: {apk}")
            self.log.ok(f"Tempo total: {elapsed}")
            self.log.sep()
            self._set_status("✅ Build concluído!", "#00cc66")
            self.after(0, lambda: self.btn_install.configure(state="normal"))

            if self.auto_adb.get():
                serial = self._selected_serial()
                if serial and self._adb_exe:
                    ADBHelper.install(self._adb_exe, serial, apk, self.log)
                else:
                    self.log.warn("Sem dispositivo ADB — instale manualmente")

        except Exception as e:
            self.log.sep()
            self.log.err(f"PIPELINE FALHOU: {e}")
            self.log.err(traceback.format_exc())
            self.log.sep()
            self._set_status("❌ Build falhou — veja o log", "#ff4444")
        finally:
            self._set_ci_mode("idle")
            self.is_building = False
            self.after(0, lambda: (
                self.btn_build.configure(
                    text="🔨 Iniciar Build", state="normal", fg_color="#28a745"),
                self.progress.stop(),
                self.progress.set(0),
            ))

    @staticmethod
    def _find_apk(project: Path) -> str | None:
        d = project / "build" / "app" / "outputs" / "flutter-apk"
        if not d.exists():
            return None
        apks = sorted(d.glob("*.apk"), key=os.path.getmtime, reverse=True)
        return str(apks[0]) if apks else None


# ─────────────────────────────────────────────────────────────
#  Entry point
# ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app = FlutterOrchestratorGUI()
    app.mainloop()
