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
            self.is_building = False
            self.last_apk_path = None
            self.work_dir = Path(tempfile.mkdtemp(prefix="flutter_orch_"))

            self._build_ui()
            self._refresh_devices()

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
        def log_message(self, message, level="info"):
            prefix_map = {"error": "❌", "success": "✅", "warning": "⚠️", "info": "ℹ️"}
            prefix = prefix_map.get(level, "•")
            ts = datetime.now().strftime("%H:%M:%S")
            self.log_text.configure(state="normal")
            self.log_text.insert("end", f"[{ts}] {prefix} {message}\n")
            self.log_text.see("end")
            self.log_text.configure(state="disabled")

        def update_status(self, text, color="#4488ff"):
            self.status_label.configure(text=text, text_color=color)

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
            try:
                start = datetime.now()

                # 1. Resolver projeto
                source_type, source_data = source
                self.update_status("Preparando projeto...")

                if source_type == "code":
                    project_path = ProjectSourceManager.from_code(
                        source_data, self.work_dir, self.log_message)
                elif source_type == "folder":
                    project_path = ProjectSourceManager.from_directory(
                        source_data, self.log_message)
                else:  # github
                    project_path = ProjectSourceManager.from_github(
                        source_data, self.work_dir,
                        self.github_token.get().strip(), self.log_message)

                # 2. Verificar Flutter
                self.update_status("Verificando Flutter...")
                if not self._check_flutter():
                    raise Exception("Flutter não encontrado no PATH. Instale manualmente ou ative auto-instalar.")

                # 3. flutter clean
                self.update_status("Limpando projeto...")
                self.log_message("🧹 flutter clean", "info")
                self._run_cmd(["flutter", "clean"], project_path)

                # 4. pub get
                self.update_status("Baixando dependências...")
                self.log_message("📥 flutter pub get", "info")
                if not self._run_cmd(["flutter", "pub", "get"], project_path):
                    raise Exception("Falha em flutter pub get")

                # 5. build apk
                build_flag = "--release" if self.build_type.get() == "release" else "--debug"
                self.update_status(f"Compilando APK ({self.build_type.get()})...")
                self.log_message(f"🔨 flutter build apk {build_flag}", "info")
                if not self._run_cmd(["flutter", "build", "apk", build_flag], project_path):
                    raise Exception("Falha na compilação do APK")

                # 6. Localizar APK
                apk = self._find_apk(project_path, self.build_type.get())
                if not apk:
                    raise Exception("APK não encontrado após build")

                self.last_apk_path = apk
                elapsed = datetime.now() - start
                self.log_message(f"✅ APK: {apk}", "success")
                self.log_message(f"⏱️ Tempo: {elapsed}", "info")
                self.update_status("✅ Build concluído!", "#00cc66")

                # Habilitar botão de instalação manual
                self.install_btn.configure(state="normal")

                # 7. ADB auto-install
                if self.auto_adb_install.get():
                    serial = self._get_selected_serial()
                    if serial and hasattr(self, "_adb_path"):
                        ADBHelper.install_apk(self._adb_path, serial, apk, self.log_message)
                    else:
                        self.log_message("⚠️ Nenhum dispositivo ADB disponível para instalação automática.", "warning")

            except Exception as e:
                self.log_message(f"❌ {e}", "error")
                self.update_status("❌ Build falhou.", "#ff4444")
            finally:
                self.is_building = False
                self.build_button.configure(text="🔨 Iniciar Build", state="normal",
                                            fg_color="#28a745")
                self.progress_bar.stop()
                self.progress_bar.set(0)

        # ── Helpers ───────────────────────────────
        def _check_flutter(self):
            try:
                r = subprocess.run(["flutter", "--version"],
                                   capture_output=True, text=True, timeout=30)
                return r.returncode == 0
            except Exception:
                return False

        def _run_cmd(self, cmd, cwd, fail_on_error=True):
            try:
                proc = subprocess.Popen(
                    cmd, cwd=str(cwd),
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, bufsize=1
                )
                for line in proc.stdout:
                    line = line.strip()
                    if line:
                        self.log_message(line, "info")
                proc.wait()
                return proc.returncode == 0 or not fail_on_error
            except Exception as e:
                self.log_message(f"Erro ao executar {cmd[0]}: {e}", "error")
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
