#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Flutter Build Orchestrator - Interface Gráfica
Suporta três fontes de entrada: código colado, pasta local e link GitHub.
Inclui integração ADB para instalação direta no dispositivo.
"""

import sys
import os

def check_gui_support():
    if os.name == 'posix' and not os.environ.get('DISPLAY'):
        return False
    try:
        import tkinter
        root = tkinter.Tk()
        root.withdraw()
        root.destroy()
        return True
    except Exception:
        return False

HAS_GUI_SUPPORT = check_gui_support()

if HAS_GUI_SUPPORT:
    import customtkinter as ctk
    import tkinter as tk
    from tkinter import filedialog, messagebox
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
    import queue
    from urllib.request import urlopen, Request
    from urllib.error import URLError
    from datetime import datetime
    from pathlib import Path

    ctk.set_appearance_mode("System")
    ctk.set_default_color_theme("blue")

    # ─────────────────────────────────────────────
    #  ADB Helper
    # ─────────────────────────────────────────────
    class ADBHelper:
        @staticmethod
        def find_adb():
            """Retorna o caminho do adb ou None."""
            if shutil.which("adb"):
                return "adb"
            candidates = [
                os.path.expanduser("~/Android/Sdk/platform-tools/adb"),
                os.path.expanduser("~\\AppData\\Local\\Android\\Sdk\\platform-tools\\adb.exe"),
                "/usr/local/bin/adb",
            ]
            for c in candidates:
                if os.path.exists(c):
                    return c
            return None

        @staticmethod
        def list_devices(adb_path):
            """Retorna lista de (serial, descrição) dos dispositivos conectados."""
            try:
                result = subprocess.run(
                    [adb_path, "devices", "-l"],
                    capture_output=True, text=True, timeout=10
                )
                devices = []
                for line in result.stdout.splitlines()[1:]:
                    line = line.strip()
                    if not line or "offline" in line:
                        continue
                    parts = line.split()
                    if len(parts) >= 2 and parts[1] == "device":
                        serial = parts[0]
                        model = next((p.split(":")[1] for p in parts if p.startswith("model:")), serial)
                        devices.append((serial, model))
                return devices
            except Exception:
                return []

        @staticmethod
        def install_apk(adb_path, serial, apk_path, log_cb):
            """Instala APK no dispositivo. Retorna True se sucesso."""
            try:
                cmd = [adb_path, "-s", serial, "install", "-r", str(apk_path)]
                log_cb(f"📲 Instalando via ADB: {apk_path}", "info")
                process = subprocess.Popen(
                    cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True
                )
                for line in process.stdout:
                    line = line.strip()
                    if line:
                        log_cb(line, "info")
                process.wait()
                if process.returncode == 0:
                    log_cb("✅ APK instalado com sucesso no dispositivo!", "success")
                    return True
                else:
                    log_cb("❌ Falha na instalação via ADB.", "error")
                    return False
            except Exception as e:
                log_cb(f"❌ Erro ADB: {e}", "error")
                return False

    # ─────────────────────────────────────────────
    #  Project Source Manager
    # ─────────────────────────────────────────────
    class ProjectSourceManager:
        """Prepara o projeto Flutter a partir de qualquer fonte de entrada."""

        PUBSPEC_TEMPLATE = """\
name: flutter_app_generated
description: App gerado pelo Flutter Build Orchestrator
publish_to: 'none'
version: 1.0.0+1

environment:
  sdk: '>=3.0.0 <4.0.0'

dependencies:
  flutter:
    sdk: flutter
  cupertino_icons: ^1.0.2

dev_dependencies:
  flutter_test:
    sdk: flutter
  flutter_lints: ^2.0.0

flutter:
  uses-material-design: true
"""

        MAIN_WRAPPER = """\
import 'package:flutter/material.dart';

// ── código colado pelo usuário ──
{user_code}
"""

        @staticmethod
        def from_code(code: str, work_dir: Path, log_cb) -> Path:
            """Cria projeto Flutter completo a partir de código colado."""
            project_dir = work_dir / "pasted_project"
            if project_dir.exists():
                shutil.rmtree(project_dir)

            log_cb("🔧 Criando estrutura Flutter para código colado...", "info")
            try:
                result = subprocess.run(
                    ["flutter", "create", "--project-name", "flutter_app_generated",
                     "--org", "com.orchestrator", str(project_dir)],
                    capture_output=True, text=True, timeout=120
                )
                if result.returncode != 0:
                    raise Exception(result.stderr or result.stdout)
            except FileNotFoundError:
                raise Exception("Flutter não encontrado no PATH.")

            # Substitui main.dart pelo código do usuário
            main_dart = project_dir / "lib" / "main.dart"
            # Se o código já tem 'void main()', usa direto; senão envolve
            if "void main(" in code:
                main_dart.write_text(code, encoding="utf-8")
            else:
                main_dart.write_text(
                    ProjectSourceManager.MAIN_WRAPPER.format(user_code=code),
                    encoding="utf-8"
                )
            log_cb(f"📝 main.dart substituído pelo código colado.", "success")
            return project_dir

        @staticmethod
        def from_directory(path: str, log_cb) -> Path:
            """Valida e retorna o caminho de um projeto Flutter existente."""
            p = Path(path).resolve()
            if not (p / "pubspec.yaml").exists():
                raise Exception(f"pubspec.yaml não encontrado em: {p}")
            log_cb(f"📁 Usando projeto existente: {p}", "info")
            return p

        @staticmethod
        def from_github(url: str, work_dir: Path, token: str, log_cb) -> Path:
            """Clona repositório GitHub e retorna o caminho."""
            # Limpa URL
            url = url.strip().rstrip("/")
            if not url.startswith("http"):
                url = "https://github.com/" + url

            # Injeta token se fornecido
            clone_url = url
            if token:
                clone_url = re.sub(r"https://", f"https://{token}@", url)

            repo_name = url.rstrip("/").split("/")[-1].replace(".git", "")
            dest = work_dir / repo_name
            if dest.exists():
                shutil.rmtree(dest)

            log_cb(f"⬇️ Clonando repositório: {url}", "info")
            result = subprocess.run(
                ["git", "clone", "--depth", "1", clone_url, str(dest)],
                capture_output=True, text=True, timeout=300
            )
            if result.returncode != 0:
                raise Exception(result.stderr or result.stdout)

            # Verifica se é projeto Flutter
            if not (dest / "pubspec.yaml").exists():
                raise Exception("Repositório clonado não contém pubspec.yaml. Não é um projeto Flutter.")

            log_cb(f"✅ Repositório clonado em: {dest}", "success")
            return dest

    # ─────────────────────────────────────────────
    #  CI Engine  (GitHub Actions fallback)
    # ─────────────────────────────────────────────
    class CIEngine:
        """
        Cérebro remoto: empacota o projeto, dispara o workflow
        flutter-ci no GitHub Actions, monitora e devolve o APK.
        """
        CI_REPO  = "idavidjunior/flutter-ci"
        WORKFLOW = "build.yml"
        API      = "https://api.github.com"

        def __init__(self, token: str, log_cb, status_cb):
            self.token     = token
            self.log       = log_cb
            self.status    = status_cb
            self._headers  = {
                "Authorization": f"token {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            }

        def _api(self, method, path, body=None):
            url  = f"{self.API}{path}"
            data = json.dumps(body).encode() if body else None
            req  = Request(url, data=data, headers={
                **self._headers, "Content-Type": "application/json"
            }, method=method)
            with urlopen(req, timeout=30) as r:
                return json.loads(r.read())

        # ── Faz upload do zip como Release Asset ─────
        def _upload_project(self, project_path: Path, session_id: str) -> str:
            """Cria uma release temporária e sobe o zip. Retorna a URL de download."""
            self.log("☁️ Fazendo upload do projeto para GitHub...", "info")

            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
                for f in project_path.rglob("*"):
                    parts = f.parts
                    if any(p in ("build", ".dart_tool", ".git", ".idea") for p in parts):
                        continue
                    if f.is_file():
                        zf.write(f, f.relative_to(project_path))
            zip_bytes = buf.getvalue()
            size_kb = len(zip_bytes) // 1024
            self.log(f"📦 Zip gerado: {size_kb} KB", "info")

            # Cria release temporária
            tag = f"ci-tmp-{session_id}"
            try:
                release = self._api("POST", f"/repos/{self.CI_REPO}/releases", {
                    "tag_name": tag,
                    "name": f"CI Build {session_id}",
                    "body": "Release temporária para build CI. Será deletada automaticamente.",
                    "draft": False,
                    "prerelease": True,
                })
                upload_url = release["upload_url"].split("{")[0]
                release_id = release["id"]
            except Exception as e:
                raise Exception(f"Falha ao criar release temporária: {e}")

            # Faz upload do zip
            asset_name = f"project_{session_id}.zip"
            upload_req = Request(
                f"{upload_url}?name={asset_name}",
                data=zip_bytes,
                headers={
                    **self._headers,
                    "Content-Type": "application/zip",
                    "Content-Length": str(len(zip_bytes)),
                },
                method="POST"
            )
            with urlopen(upload_req, timeout=120) as r:
                asset = json.loads(r.read())

            download_url = asset["browser_download_url"]
            self.log(f"✅ Upload concluído: {asset_name}", "success")
            self._tmp_release_id = release_id  # guarda para limpeza
            return download_url

        # ── Limpa release temporária ─────────────────
        def _cleanup_release(self):
            if hasattr(self, "_tmp_release_id"):
                try:
                    self._api("DELETE", f"/repos/{self.CI_REPO}/releases/{self._tmp_release_id}")
                    self.log("🗑️ Release temporária removida.", "info")
                except Exception:
                    pass

        # ── Dispara workflow ─────────────────────────
        def dispatch(self, project_path: Path, build_type: str, session_id: str) -> float:
            """Faz upload do projeto, dispara o workflow. Retorna o timestamp do dispatch ou 0."""
            try:
                zip_url = self._upload_project(project_path, session_id)
                self.log("🚀 Despachando build para GitHub Actions...", "info")
                self.status("Enviando para GitHub Actions...")
                dispatch_time = time.time()
                self._api("POST",
                    f"/repos/{self.CI_REPO}/actions/workflows/{self.WORKFLOW}/dispatches",
                    {
                        "ref": "main",
                        "inputs": {
                            "project_zip_url": zip_url,
                            "project_zip_b64": "",
                            "build_type": build_type,
                            "session_id": session_id,
                        }
                    }
                )
                self.log("✅ Workflow disparado.", "success")
                return dispatch_time
            except Exception as e:
                self.log(f"❌ Falha ao disparar workflow: {e}", "error")
                return 0

        # ── Encontra o run recém-criado ──────────────
        def _find_run(self, dispatch_time: float, max_wait=90) -> dict | None:
            self.log("🔍 Aguardando run do workflow...", "info")
            deadline = time.time() + max_wait
            while time.time() < deadline:
                try:
                    data = self._api("GET",
                        f"/repos/{self.CI_REPO}/actions/workflows/{self.WORKFLOW}/runs?per_page=5")
                    for run in data.get("workflow_runs", []):
                        # Aceita runs criados após o dispatch (margem de 30s)
                        created = run.get("created_at", "")
                        import datetime as _dt
                        try:
                            created_ts = _dt.datetime.fromisoformat(
                                created.replace("Z", "+00:00")).timestamp()
                        except Exception:
                            created_ts = 0
                        if created_ts >= dispatch_time - 30:
                            return run
                except Exception:
                    pass
                time.sleep(5)
            return None

        # ── Monitora até concluir ────────────────────
        def monitor(self, dispatch_time: float, timeout=1200) -> dict | None:
            """Monitora o workflow e retorna o run quando terminar."""
            run = self._find_run(dispatch_time)
            if not run:
                self.log("❌ Run não encontrado após dispatch.", "error")
                return None

            run_id = run["id"]
            self.log(f"🔗 Run #{run_id}: {run['html_url']}", "info")
            deadline = time.time() + timeout
            dots = 0

            while time.time() < deadline:
                try:
                    run = self._api("GET",
                        f"/repos/{self.CI_REPO}/actions/runs/{run_id}")
                    status     = run.get("status", "")
                    conclusion = run.get("conclusion", "")
                    dots = (dots + 1) % 4
                    self.status(f"GitHub Actions: {status}{'.' * dots}")

                    if status == "completed":
                        if conclusion == "success":
                            self.log("✅ Build remoto concluído com sucesso!", "success")
                        else:
                            self.log(f"❌ Build remoto falhou: {conclusion}", "error")
                            self.log(f"🔗 Detalhes: {run['html_url']}", "info")
                        return run if conclusion == "success" else None
                except Exception as e:
                    self.log(f"⚠️ Erro ao monitorar: {e}", "warning")
                time.sleep(8)

            self.log("❌ Timeout ao aguardar GitHub Actions.", "error")
            return None

        # ── Baixa o APK do artefato ──────────────────
        def download_apk(self, run: dict, session_id: str, dest_dir: Path) -> Path | None:
            self.log("⬇️ Baixando APK do artefato...", "info")
            self.status("Baixando APK...")
            try:
                data = self._api("GET",
                    f"/repos/{self.CI_REPO}/actions/runs/{run['id']}/artifacts")
                artifacts = data.get("artifacts", [])
                if not artifacts:
                    self.log("❌ Nenhum artefato encontrado.", "error")
                    return None

                artifact = artifacts[0]
                self.log(f"📦 Artefato: {artifact['name']} ({artifact['size_in_bytes']//1024} KB)", "info")

                # Download via URL de redirect
                dl_url = f"{self.API}/repos/{self.CI_REPO}/actions/artifacts/{artifact['id']}/zip"
                req = Request(dl_url, headers=self._headers)
                dest_dir.mkdir(parents=True, exist_ok=True)
                apk_path = dest_dir / f"app_{session_id}.apk"

                with urlopen(req, timeout=120) as r:
                    buf = io.BytesIO(r.read())

                with zipfile.ZipFile(buf) as z:
                    for name in z.namelist():
                        if name.endswith(".apk"):
                            with z.open(name) as src, open(apk_path, "wb") as dst:
                                dst.write(src.read())
                            break

                if apk_path.exists():
                    self.log(f"✅ APK baixado: {apk_path}", "success")
                    return apk_path

                self.log("❌ APK não encontrado no artefato.", "error")
                return None

            except Exception as e:
                self.log(f"❌ Falha ao baixar APK: {e}", "error")
                return None

        # ── Pipeline completo ────────────────────────
        def run_pipeline(self, project_path: Path, build_type: str) -> Path | None:
            session_id = datetime.now().strftime("%Y%m%d%H%M%S")
            dispatch_time = self.dispatch(project_path, build_type, session_id)
            if not dispatch_time:
                return None
            try:
                run = self.monitor(dispatch_time)
                if not run:
                    return None
                dest = project_path.parent / "ci_outputs"
                return self.download_apk(run, session_id, dest)
            finally:
                self._cleanup_release()

    # ─────────────────────────────────────────────
    #  Main GUI
    # ─────────────────────────────────────────────
    class FlutterOrchestratorGUI(ctk.CTk):
        def __init__(self):
            super().__init__()
            self.title("🚀 Flutter Build Orchestrator")
            self.geometry("1000x780")
            self.minsize(900, 650)

            self.build_type = tk.StringVar(value="release")
            self.auto_install = tk.BooleanVar(value=True)
            self.auto_adb_install = tk.BooleanVar(value=True)
            self.github_token = tk.StringVar()
            self.ci_token = tk.StringVar()
            self.is_building = False
            self.last_apk_path = None
            self.work_dir = Path(tempfile.mkdtemp(prefix="flutter_orch_"))
            self._log_queue = queue.Queue()   # fila thread-safe para logs

            self._build_ui()
            self._refresh_devices()
            self._poll_log()   # inicia loop de drenagem da fila

        # ── UI ───────────────────────────────────
        def _build_ui(self):
            # Cabeçalho
            header = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")
            header.pack(fill="x", padx=20, pady=(15, 5))
            ctk.CTkLabel(
                header, text="🚀 Flutter Build Orchestrator",
                font=ctk.CTkFont(size=22, weight="bold")
            ).pack(side="left")
            ctk.CTkLabel(
                header, text="compile · instale · entregue",
                font=ctk.CTkFont(size=12), text_color="gray"
            ).pack(side="left", padx=12, pady=(4, 0))

            # Notebook (tabs)
            self.tabview = ctk.CTkTabview(self, height=280)
            self.tabview.pack(fill="x", padx=20, pady=(5, 0))
            self.tabview.add("📋 Colar Código")
            self.tabview.add("📁 Pasta / Diretório")
            self.tabview.add("🔗 Link GitHub")

            self._build_tab_code()
            self._build_tab_folder()
            self._build_tab_github()

            # Opções de build
            self._build_options()

            # CI remoto
            self._build_ci_section()

            # ADB
            self._build_adb_section()

            # Botão principal
            self.build_button = ctk.CTkButton(
                self, text="🔨 Iniciar Build",
                command=self.start_build,
                height=48,
                font=ctk.CTkFont(size=15, weight="bold"),
                fg_color="#28a745", hover_color="#218838"
            )
            self.build_button.pack(fill="x", padx=20, pady=(8, 4))

            # Progress + status
            self.progress_bar = ctk.CTkProgressBar(self, mode="indeterminate")
            self.progress_bar.pack(fill="x", padx=20, pady=(0, 2))
            self.progress_bar.set(0)
            self.status_label = ctk.CTkLabel(self, text="✅ Pronto", text_color="gray")
            self.status_label.pack(anchor="w", padx=22)

            # Log
            log_frame = ctk.CTkFrame(self)
            log_frame.pack(fill="both", expand=True, padx=20, pady=(4, 12))
            ctk.CTkLabel(log_frame, text="📋 Logs em Tempo Real",
                         font=ctk.CTkFont(weight="bold")).pack(anchor="w", padx=10, pady=(8, 2))
            self.log_text = ctk.CTkTextbox(log_frame, wrap="word", state="disabled",
                                           font=ctk.CTkFont(family="Courier", size=12))
            self.log_text.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        def _build_tab_code(self):
            tab = self.tabview.tab("📋 Colar Código")
            ctk.CTkLabel(tab, text="Cole seu código Dart/Flutter abaixo. Um projeto completo será gerado automaticamente.",
                         text_color="gray").pack(anchor="w", padx=5, pady=(6, 4))
            self.code_text = ctk.CTkTextbox(tab, wrap="word",
                                            font=ctk.CTkFont(family="Courier", size=12),
                                            height=180)
            self.code_text.pack(fill="both", expand=True, padx=5, pady=(0, 6))
            self.code_text.insert("end", "// Cole seu código Dart aqui\n// Ex: void main() => runApp(MyApp());\n")

        def _build_tab_folder(self):
            tab = self.tabview.tab("📁 Pasta / Diretório")
            self.folder_path = tk.StringVar()
            row = ctk.CTkFrame(tab, fg_color="transparent")
            row.pack(fill="x", padx=5, pady=20)
            ctk.CTkLabel(row, text="Pasta do projeto:", width=130).pack(side="left")
            ctk.CTkEntry(row, textvariable=self.folder_path,
                         placeholder_text="Selecione ou digite o caminho...",
                         width=500).pack(side="left", padx=8)
            ctk.CTkButton(row, text="📂 Procurar", width=100,
                          command=self._browse_folder).pack(side="left")

        def _build_tab_github(self):
            tab = self.tabview.tab("🔗 Link GitHub")
            self.github_url = tk.StringVar()

            row1 = ctk.CTkFrame(tab, fg_color="transparent")
            row1.pack(fill="x", padx=5, pady=(16, 6))
            ctk.CTkLabel(row1, text="URL do repositório:", width=150).pack(side="left")
            ctk.CTkEntry(row1, textvariable=self.github_url,
                         placeholder_text="https://github.com/usuario/repo  ou  usuario/repo",
                         width=550).pack(side="left", padx=8)

            row2 = ctk.CTkFrame(tab, fg_color="transparent")
            row2.pack(fill="x", padx=5, pady=(0, 16))
            ctk.CTkLabel(row2, text="Token (privado):", width=150,
                         text_color="gray").pack(side="left")
            ctk.CTkEntry(row2, textvariable=self.github_token,
                         placeholder_text="ghp_xxx... (opcional, para repos privados)",
                         show="*", width=400).pack(side="left", padx=8)

        def _build_options(self):
            frame = ctk.CTkFrame(self)
            frame.pack(fill="x", padx=20, pady=(8, 0))
            ctk.CTkLabel(frame, text="⚙️ Opções:",
                         font=ctk.CTkFont(weight="bold")).pack(side="left", padx=12)
            ctk.CTkRadioButton(frame, text="📦 Release", variable=self.build_type,
                               value="release").pack(side="left", padx=10, pady=8)
            ctk.CTkRadioButton(frame, text="🐛 Debug", variable=self.build_type,
                               value="debug").pack(side="left", padx=10)
            ctk.CTkCheckBox(frame, text="Instalar Flutter auto",
                            variable=self.auto_install).pack(side="left", padx=20)

        def _build_ci_section(self):
            frame = ctk.CTkFrame(self)
            frame.pack(fill="x", padx=20, pady=(6, 0))

            ctk.CTkLabel(frame, text="☁️ CI Remoto:",
                         font=ctk.CTkFont(weight="bold")).pack(side="left", padx=12, pady=8)

            # Indicador de modo ativo
            self.ci_mode_label = ctk.CTkLabel(
                frame, text="● Aguardando", text_color="gray",
                font=ctk.CTkFont(size=12, weight="bold")
            )
            self.ci_mode_label.pack(side="left", padx=(0, 10))

            ctk.CTkLabel(frame, text="Token GitHub:", text_color="gray").pack(side="left")
            token_entry = ctk.CTkEntry(
                frame, textvariable=self.ci_token,
                placeholder_text="ghp_xxx...",
                show="*", width=280
            )
            token_entry.pack(side="left", padx=8)

            # Indicador de validade do token
            self.token_status_label = ctk.CTkLabel(
                frame, text="⬜ não validado",
                text_color="gray", font=ctk.CTkFont(size=11)
            )
            self.token_status_label.pack(side="left", padx=4)

            # Botão validar
            ctk.CTkButton(
                frame, text="Validar", width=70,
                command=self._validate_ci_token
            ).pack(side="left", padx=4)

            # Valida automaticamente quando sai do campo
            token_entry.bind("<FocusOut>", lambda e: threading.Thread(
                target=self._validate_ci_token, daemon=True).start())
            token_entry.bind("<Return>", lambda e: threading.Thread(
                target=self._validate_ci_token, daemon=True).start())

        def _validate_ci_token(self):
            """Valida o token GitHub contra a API e verifica acesso ao repo flutter-ci."""
            token = self.ci_token.get().strip()
            if not token:
                self.after(0, lambda: self.token_status_label.configure(
                    text="⬜ não validado", text_color="gray"))
                return

            self.after(0, lambda: self.token_status_label.configure(
                text="🔄 validando...", text_color="#ffc107"))
            try:
                req = Request(
                    "https://api.github.com/user",
                    headers={
                        "Authorization": f"token {token}",
                        "Accept": "application/vnd.github+json",
                    }
                )
                with urlopen(req, timeout=10) as r:
                    user = json.loads(r.read())
                login = user.get("login", "?")

                # Verifica acesso ao repo flutter-ci
                req2 = Request(
                    "https://api.github.com/repos/idavidjunior/flutter-ci",
                    headers={
                        "Authorization": f"token {token}",
                        "Accept": "application/vnd.github+json",
                    }
                )
                with urlopen(req2, timeout=10) as r2:
                    json.loads(r2.read())

                self.after(0, lambda: self.token_status_label.configure(
                    text=f"✅ válido ({login})", text_color="#00cc66"))
                self.log_message(f"✅ Token GitHub válido — usuário: {login}", "success")

            except Exception as e:
                err = str(e)
                if "401" in err:
                    msg = "❌ token inválido"
                elif "404" in err:
                    msg = "❌ sem acesso ao flutter-ci"
                else:
                    msg = "❌ erro de conexão"
                self.after(0, lambda m=msg: self.token_status_label.configure(
                    text=m, text_color="#ff4444"))
                self.log_message(f"❌ Validação do token falhou: {err}", "error")

        def _build_adb_section(self):
            frame = ctk.CTkFrame(self)
            frame.pack(fill="x", padx=20, pady=(6, 0))

            ctk.CTkLabel(frame, text="📱 ADB:",
                         font=ctk.CTkFont(weight="bold")).pack(side="left", padx=12, pady=8)

            self.device_var = tk.StringVar(value="Nenhum dispositivo")
            self.device_menu = ctk.CTkOptionMenu(frame, variable=self.device_var,
                                                  values=["Nenhum dispositivo"],
                                                  width=240)
            self.device_menu.pack(side="left", padx=8)

            ctk.CTkButton(frame, text="🔄 Atualizar", width=90,
                          command=self._refresh_devices).pack(side="left", padx=4)

            ctk.CTkCheckBox(frame, text="Instalar automaticamente após build",
                            variable=self.auto_adb_install).pack(side="left", padx=14)

            self.install_btn = ctk.CTkButton(
                frame, text="📲 Instalar no Dispositivo", width=200,
                command=self._manual_install,
                fg_color="#1565C0", hover_color="#0D47A1",
                state="disabled"
            )
            self.install_btn.pack(side="left", padx=8)

        # ── Device helpers ────────────────────────
        def _refresh_devices(self):
            adb = ADBHelper.find_adb()
            if not adb:
                self.device_menu.configure(values=["ADB não encontrado"])
                self.device_var.set("ADB não encontrado")
                self._devices = []
                return
            devices = ADBHelper.list_devices(adb)
            self._adb_path = adb
            self._devices = devices
            if devices:
                labels = [f"{m} ({s})" for s, m in devices]
                self.device_menu.configure(values=labels)
                self.device_var.set(labels[0])
            else:
                self.device_menu.configure(values=["Nenhum dispositivo conectado"])
                self.device_var.set("Nenhum dispositivo conectado")

        def _get_selected_serial(self):
            if not hasattr(self, "_devices") or not self._devices:
                return None
            label = self.device_var.get()
            for serial, model in self._devices:
                if serial in label or model in label:
                    return serial
            return self._devices[0][0] if self._devices else None

        def _manual_install(self):
            if not self.last_apk_path:
                messagebox.showwarning("Sem APK", "Faça um build primeiro.")
                return
            serial = self._get_selected_serial()
            if not serial:
                messagebox.showerror("Dispositivo", "Nenhum dispositivo ADB selecionado.")
                return
            threading.Thread(
                target=ADBHelper.install_apk,
                args=(self._adb_path, serial, self.last_apk_path, self.log_message),
                daemon=True
            ).start()

        # ── Browse ───────────────────────────────
        def _browse_folder(self):
            folder = filedialog.askdirectory(title="Selecione a pasta do projeto Flutter")
            if folder:
                self.folder_path.set(folder)

        # ── Logging ──────────────────────────────
        # ── Logging (thread-safe via queue) ──────
        def log_message(self, message, level="info"):
            """Pode ser chamado de qualquer thread — enfileira para o loop principal."""
            self._log_queue.put((level, message))

        def _poll_log(self):
            """Drena a fila de log no loop principal do tkinter a cada 50ms."""
            prefix_map = {"error": "❌", "success": "✅", "warning": "⚠️", "info": "ℹ️"}
            try:
                while True:
                    level, message = self._log_queue.get_nowait()
                    prefix = prefix_map.get(level, "•")
                    ts = datetime.now().strftime("%H:%M:%S")
                    self.log_text.configure(state="normal")
                    self.log_text.insert("end", f"[{ts}] {prefix} {message}\n")
                    self.log_text.see("end")
                    self.log_text.configure(state="disabled")
            except queue.Empty:
                pass
            except Exception:
                pass
            self.after(50, self._poll_log)

        def update_status(self, text, color="#4488ff"):
            """Thread-safe via after()."""
            self.after(0, lambda: self.status_label.configure(text=text, text_color=color))

        # ── Build entry point ─────────────────────
        def start_build(self):
            if self.is_building:
                messagebox.showwarning("Atenção", "Build em andamento.")
                return

            active_tab = self.tabview.get()

            # Validações por aba
            if active_tab == "📋 Colar Código":
                code = self.code_text.get("1.0", "end").strip()
                if not code or code.startswith("// Cole seu"):
                    messagebox.showerror("Erro", "Cole algum código Dart antes de iniciar.")
                    return
                source = ("code", code)

            elif active_tab == "📁 Pasta / Diretório":
                path = self.folder_path.get().strip()
                if not path:
                    messagebox.showerror("Erro", "Selecione uma pasta de projeto.")
                    return
                source = ("folder", path)

            else:  # GitHub
                url = self.github_url.get().strip()
                if not url:
                    messagebox.showerror("Erro", "Informe a URL do repositório.")
                    return
                source = ("github", url)

            self.is_building = True
            self.last_apk_path = None
            self.install_btn.configure(state="disabled")
            self.build_button.configure(text="⏳ Compilando...", state="disabled",
                                        fg_color="#ffc107")
            self.progress_bar.start()
            self.update_status("🔄 Iniciando...", "#ffc107")
            self.log_text.configure(state="normal")
            self.log_text.delete("1.0", "end")
            self.log_text.configure(state="disabled")

            threading.Thread(target=self._build_worker, args=(source,), daemon=True).start()

        # ── Build worker ──────────────────────────
        def _build_worker(self, source):
            import traceback as _tb
            try:
                start = datetime.now()
                source_type, source_data = source
                apk = None

                self.log_message("━" * 55, "info")
                self.log_message("🚀 INICIANDO PIPELINE DE BUILD", "info")
                self.log_message(f"   Fonte : {source_type}", "info")
                self.log_message(f"   Tipo  : {self.build_type.get()}", "info")
                self.log_message(f"   Sistema: {platform.system()} {platform.release()}", "info")
                self.log_message("━" * 55, "info")

                # ── Tentativa LOCAL ───────────────────
                self.log_message("🖥️ [ETAPA 1/5] Verificando Flutter local...", "info")
                flutter_ok = self._check_flutter()
                self.log_message(f"   Flutter no PATH: {'SIM' if flutter_ok else 'NÃO'}", "info")

                if flutter_ok or self.auto_install.get():
                    self._set_ci_indicator("local")
                    try:
                        if not flutter_ok:
                            self.log_message("🖥️ [ETAPA 1/5] Instalando Flutter...", "info")
                            if not self._ensure_flutter():
                                raise Exception("Flutter indisponível localmente.")

                        self.log_message("📁 [ETAPA 2/5] Preparando projeto...", "info")
                        self.update_status("Preparando projeto...")
                        project_path = self._resolve_project(source_type, source_data)
                        self.log_message(f"   Projeto: {project_path}", "info")

                        self.log_message("🧹 [ETAPA 3/5] Limpando projeto...", "info")
                        self.update_status("Limpando projeto...")
                        self._run_cmd(["flutter", "clean"], project_path, fail_on_error=False)

                        self.log_message("📥 [ETAPA 4/5] Baixando dependências...", "info")
                        self.update_status("Baixando dependências...")
                        if not self._run_cmd(["flutter", "pub", "get"], project_path):
                            raise Exception("flutter pub get falhou — veja erros acima")

                        build_flag = "--" + self.build_type.get()
                        self.log_message(f"🔨 [ETAPA 5/5] Compilando APK {self.build_type.get().upper()}...", "info")
                        self.update_status(f"Compilando APK ({self.build_type.get()})...")
                        if not self._run_cmd(["flutter", "build", "apk", build_flag], project_path):
                            raise Exception("flutter build apk falhou — veja erros acima")

                        apk = self._find_apk(project_path, self.build_type.get())
                        if not apk:
                            raise Exception("APK não encontrado após build — verifique build/app/outputs/flutter-apk/")

                        self.log_message("✅ Build local concluído com sucesso.", "success")

                    except Exception as local_err:
                        self.log_message("━" * 55, "warning")
                        self.log_message(f"⚠️ Build local falhou: {local_err}", "warning")
                        self.log_message(_tb.format_exc(), "warning")
                        self.log_message("━" * 55, "warning")
                        apk = None

                # ── Fallback CI ───────────────────────
                if not apk:
                    token = self.ci_token.get().strip()
                    if not token:
                        raise Exception(
                            "Build local falhou e nenhum token GitHub configurado.\n"
                            "Preencha o campo ☁️ CI Remoto com seu token ghp_xxx para usar GitHub Actions."
                        )

                    self.log_message("━" * 55, "info")
                    self.log_message("☁️ ATIVANDO FALLBACK: GitHub Actions", "warning")
                    self.log_message("━" * 55, "info")
                    self._set_ci_indicator("ci")

                    self.update_status("Preparando projeto para CI...")
                    project_path = self._resolve_project(source_type, source_data)

                    ci = CIEngine(token, self.log_message, self.update_status)
                    apk_path = ci.run_pipeline(project_path, self.build_type.get())
                    if not apk_path:
                        raise Exception("Build via GitHub Actions também falhou. Veja os logs acima.")
                    apk = str(apk_path)

                # ── Entrega ───────────────────────────
                self.last_apk_path = apk
                elapsed = datetime.now() - start
                self.log_message("━" * 55, "success")
                self.log_message(f"📦 APK gerado : {apk}", "success")
                self.log_message(f"⏱️ Tempo total: {elapsed}", "info")
                self.log_message("━" * 55, "success")
                self.update_status("✅ Build concluído!", "#00cc66")
                self.install_btn.configure(state="normal")

                if self.auto_adb_install.get():
                    serial = self._get_selected_serial()
                    if serial and hasattr(self, "_adb_path"):
                        ADBHelper.install_apk(self._adb_path, serial, apk, self.log_message)
                    else:
                        self.log_message("⚠️ Sem dispositivo ADB para instalação automática.", "warning")

            except Exception as e:
                self.log_message("━" * 55, "error")
                self.log_message(f"❌ PIPELINE FALHOU: {e}", "error")
                self.log_message(_tb.format_exc(), "error")
                self.log_message("━" * 55, "error")
                self.update_status("❌ Build falhou.", "#ff4444")
            finally:
                self._set_ci_indicator("idle")
                self.is_building = False
                self.build_button.configure(text="🔨 Iniciar Build", state="normal",
                                            fg_color="#28a745")
                self.progress_bar.stop()
                self.progress_bar.set(0)

        def _resolve_project(self, source_type, source_data) -> Path:
            """Resolve qualquer fonte para um Path de projeto Flutter em disco."""
            if source_type == "code":
                return ProjectSourceManager.from_code(
                    source_data, self.work_dir, self.log_message)
            elif source_type == "folder":
                return ProjectSourceManager.from_directory(
                    source_data, self.log_message)
            else:
                return ProjectSourceManager.from_github(
                    source_data, self.work_dir,
                    self.github_token.get().strip(), self.log_message)

        def _set_ci_indicator(self, mode: str):
            colors = {"local": "#00cc66", "ci": "#ffc107", "idle": "gray"}
            labels = {"local": "● Local", "ci": "● GitHub Actions", "idle": "● Aguardando"}
            try:
                self.ci_mode_label.configure(
                    text=labels.get(mode, "●"),
                    text_color=colors.get(mode, "gray")
                )
            except Exception:
                pass

        # ── Helpers ───────────────────────────────
        def _check_flutter(self):
            """Verifica se flutter está acessível — PATH, variáveis de ambiente e caminhos comuns."""
            # 1. Tenta direto no PATH
            try:
                r = subprocess.run(
                    ["flutter", "--version"],
                    capture_output=True, text=True, timeout=30,
                    env=os.environ.copy()
                )
                if r.returncode == 0:
                    return True
            except Exception:
                pass

            # 2. Procura em variáveis de ambiente conhecidas (Flutter, Flutterbin, FLUTTER_ROOT)
            for var in ("Flutter", "Flutterbin", "FLUTTER_ROOT", "FLUTTER_HOME"):
                val = os.environ.get(var, "")
                if not val:
                    continue
                for candidate in [
                    Path(val) / "flutter.bat",
                    Path(val) / "flutter",
                    Path(val) / "bin" / "flutter.bat",
                    Path(val) / "bin" / "flutter",
                ]:
                    if candidate.exists():
                        try:
                            r = subprocess.run(
                                [str(candidate), "--version"],
                                capture_output=True, text=True, timeout=30
                            )
                            if r.returncode == 0:
                                # Injeta o bin no PATH para os próximos comandos
                                flutter_bin = str(candidate.parent)
                                os.environ["PATH"] = flutter_bin + os.pathsep + os.environ.get("PATH", "")
                                self.log_message(f"✅ Flutter encontrado via variável {var}: {candidate}", "success")
                                return True
                        except Exception:
                            pass

            # 3. Caminhos comuns Windows / Linux / Mac
            home = Path.home()
            common = [
                home / "flutter" / "bin" / "flutter.bat",
                home / "flutter" / "bin" / "flutter",
                Path("C:/flutter/bin/flutter.bat"),
                Path("C:/src/flutter/bin/flutter.bat"),
                home / ".flutter_orchestrator" / "flutter" / "bin" / "flutter.bat",
                home / ".flutter_orchestrator" / "flutter" / "bin" / "flutter",
                Path("/usr/local/flutter/bin/flutter"),
                Path("/opt/flutter/bin/flutter"),
            ]
            for candidate in common:
                if candidate.exists():
                    try:
                        r = subprocess.run(
                            [str(candidate), "--version"],
                            capture_output=True, text=True, timeout=30
                        )
                        if r.returncode == 0:
                            flutter_bin = str(candidate.parent)
                            os.environ["PATH"] = flutter_bin + os.pathsep + os.environ.get("PATH", "")
                            self.log_message(f"✅ Flutter encontrado em: {candidate}", "success")
                            return True
                    except Exception:
                        pass

            return False

        def _ensure_flutter(self):
            """Garante que o Flutter está disponível. Instala se necessário e auto_install=True."""
            if self._check_flutter():
                self.log_message("✅ Flutter encontrado no PATH.", "success")
                return True

            self.log_message("⚠️ Flutter não encontrado no PATH.", "warning")

            if not self.auto_install.get():
                self.log_message("❌ Auto-instalação desativada. Instale o Flutter manualmente.", "error")
                return False

            self.log_message("📥 Iniciando download automático do Flutter SDK...", "info")
            self.update_status("Baixando Flutter SDK...")

            system = platform.system()
            install_dir = Path.home() / ".flutter_orchestrator"
            install_dir.mkdir(parents=True, exist_ok=True)

            urls = {
                "Linux":  "https://storage.googleapis.com/flutter_infra_release/releases/stable/linux/flutter_linux_3.24.0-stable.tar.xz",
                "Darwin": "https://storage.googleapis.com/flutter_infra_release/releases/stable/macos/flutter_macos_3.24.0-stable.zip",
                "Windows": "https://storage.googleapis.com/flutter_infra_release/releases/stable/windows/flutter_windows_3.24.0-stable.zip",
            }
            url = urls.get(system)
            if not url:
                self.log_message(f"❌ Sistema '{system}' não suportado para auto-instalação.", "error")
                return False

            filename = url.split("/")[-1]
            archive_path = install_dir / filename

            # Download com progresso
            try:
                from urllib.request import urlopen
                import zipfile, tarfile as tf

                self.log_message(f"⬇️ Baixando: {filename}", "info")
                with urlopen(url) as resp:
                    total = int(resp.getheader("Content-Length", 0))
                    downloaded = 0
                    block = 65536
                    with open(archive_path, "wb") as f:
                        while True:
                            buf = resp.read(block)
                            if not buf:
                                break
                            f.write(buf)
                            downloaded += len(buf)
                            if total:
                                pct = downloaded / total * 100
                                self.update_status(f"Baixando Flutter... {pct:.0f}%")

                self.log_message("✅ Download concluído. Extraindo...", "success")
                self.update_status("Extraindo Flutter SDK...")

                # Extração
                if filename.endswith(".zip"):
                    with zipfile.ZipFile(archive_path, "r") as z:
                        z.extractall(install_dir)
                else:  # .tar.xz
                    with tf.open(archive_path, "r:xz") as t:
                        t.extractall(install_dir)

                archive_path.unlink(missing_ok=True)

                # Adiciona ao PATH desta sessão
                flutter_bin = install_dir / "flutter" / "bin"
                os.environ["PATH"] = str(flutter_bin) + os.pathsep + os.environ.get("PATH", "")
                self.log_message(f"✅ Flutter instalado em: {flutter_bin}", "success")
                self.log_message(f"💡 Para uso permanente: export PATH=\"$PATH:{flutter_bin}\"", "warning")

                # Aceitar licenças Android
                try:
                    flutter_exe = str(flutter_bin / "flutter")
                    subprocess.run([flutter_exe, "--version"],
                                   capture_output=True, timeout=60)
                    subprocess.run(
                        [flutter_exe, "doctor", "--android-licenses"],
                        input="y\ny\ny\ny\ny\n", text=True,
                        capture_output=True, timeout=120
                    )
                    self.log_message("✅ Licenças Android aceitas.", "success")
                except Exception as e:
                    self.log_message(f"⚠️ Licenças: {e} — aceite manualmente depois.", "warning")

                return self._check_flutter()

            except Exception as e:
                self.log_message(f"❌ Falha na instalação do Flutter: {e}", "error")
                return False

        def _run_cmd(self, cmd, cwd, fail_on_error=True):
            """Executa comando com saída detalhada em tempo real (stdout + stderr separados)."""
            import traceback as _tb
            cmd_str = " ".join(str(c) for c in cmd)
            self.log_message(f"▶ {cmd_str}", "info")
            self.log_message(f"  📂 cwd: {cwd}", "info")
            try:
                env = os.environ.copy()
                proc = subprocess.Popen(
                    cmd,
                    cwd=str(cwd),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    bufsize=1,
                    env=env,
                    encoding="utf-8",
                    errors="replace",
                )

                # Lê stdout e stderr em threads para não bloquear
                stdout_lines = []
                stderr_lines = []

                def _read(stream, store, level):
                    for line in stream:
                        line = line.rstrip()
                        if line:
                            store.append(line)
                            self.log_message(line, level)

                t_out = threading.Thread(target=_read, args=(proc.stdout, stdout_lines, "info"), daemon=True)
                t_err = threading.Thread(target=_read, args=(proc.stderr, stderr_lines, "warning"), daemon=True)
                t_out.start()
                t_err.start()
                t_out.join()
                t_err.join()
                proc.wait()

                rc = proc.returncode
                if rc == 0:
                    self.log_message(f"✅ Comando concluído (exit 0)", "success")
                    return True
                else:
                    self.log_message(f"❌ Comando falhou (exit {rc})", "error")
                    if stderr_lines:
                        self.log_message("── stderr completo ──", "error")
                        for l in stderr_lines[-30:]:  # últimas 30 linhas de erro
                            self.log_message(l, "error")
                    return not fail_on_error

            except FileNotFoundError:
                self.log_message(f"❌ Executável não encontrado: {cmd[0]}", "error")
                self.log_message(f"   PATH atual: {os.environ.get('PATH', 'N/A')}", "error")
                return False
            except Exception as e:
                self.log_message(f"❌ Exceção ao executar comando: {e}", "error")
                self.log_message(_tb.format_exc(), "error")
                return False

        @staticmethod
        def _find_apk(project_path, build_type):
            build_dir = Path(project_path) / "build" / "app" / "outputs" / "flutter-apk"
            if not build_dir.exists():
                return None
            apks = sorted(build_dir.glob("*.apk"), key=os.path.getmtime, reverse=True)
            return str(apks[0]) if apks else None


# ─────────────────────────────────────────────
#  Entry point
# ─────────────────────────────────────────────
if __name__ == "__main__":
    if HAS_GUI_SUPPORT:
        app = FlutterOrchestratorGUI()
        app.mainloop()
    else:
        print("\n" + "="*60)
        print("🚀 FLUTTER BUILD ORCHESTRATOR - MODO TERMINAL")
        print("="*60)
        print("GUI indisponível (sem DISPLAY). Use flutter_orchestrator.py diretamente.")
        sys.exit(1)
