#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Android Pure SDK Builder
========================
Pipeline de build para projetos Android sem Gradle, sem AndroidX, sem Kotlin.
Usa apenas as ferramentas do Android SDK e JDK:

  aapt -> javac -> jar -> d8 -> aapt package -> aapt add -> zipalign -> apksigner

Baseado no pipeline puro documentado no SKILL.md do Android Pure SDK.
"""

import os
import re
import shutil
import subprocess
import zipfile
import io
import platform
from pathlib import Path
from typing import Optional, List
from datetime import datetime


class PureSdkBuilder:
    """Build Android APK usando apenas ferramentas SDK (aapt, d8, apksigner) + JDK (javac, jar)."""

    # Compile SDK alvo (android-X no platforms/)
    DEFAULT_COMPILE_SDK = 36
    DEFAULT_MIN_SDK = 21
    DEFAULT_TARGET_SDK = 36

    def __init__(self, project_path: str, build_dir: str = "build_pure",
                 compile_sdk: int = DEFAULT_COMPILE_SDK,
                 min_sdk: int = DEFAULT_MIN_SDK,
                 target_sdk: int = DEFAULT_TARGET_SDK,
                 log_callback=None, progress_callback=None):
        self.project_path = Path(project_path).resolve()
        self.build_dir = self.project_path / build_dir
        self.compile_sdk = compile_sdk
        self.min_sdk = min_sdk
        self.target_sdk = target_sdk
        self.log_callback = log_callback
        self.progress_callback = progress_callback
        self.last_apk_path: Optional[Path] = None

        self._aapt: Optional[str] = None
        self._d8: Optional[str] = None
        self._zipalign: Optional[str] = None
        self._apksigner: Optional[str] = None
        self._javac: Optional[str] = None
        self._jar_tool: Optional[str] = None
        self._platform_jar: Optional[str] = None
        self._java: Optional[str] = None

    def _log(self, msg: str, level: str = "INFO"):
        if self.log_callback:
            self.log_callback(msg, level)
        else:
            ts = datetime.now().strftime("%H:%M:%S")
            print(f"[{ts}] [{level}] {msg}")

    def _progress(self, pct: int, status: str):
        if self.progress_callback:
            try:
                self.progress_callback(pct, status)
            except Exception:
                pass

    def _find_sdk_path(self) -> Optional[Path]:
        """Localiza ANDROID_HOME."""
        sdk = os.environ.get("ANDROID_HOME") or os.environ.get("ANDROID_SDK_ROOT") or ""
        if sdk and Path(sdk).exists():
            return Path(sdk)
        if platform.system() == "Windows":
            candidates = [
                Path(os.environ.get("LOCALAPPDATA", "C:\\")) / "Android" / "Sdk",
                Path("C:\\Android\\Sdk"),
                Path("C:\\Program Files\\Android\\Sdk"),
            ]
        elif platform.system() == "Darwin":
            candidates = [
                Path.home() / "Library" / "Android" / "sdk",
            ]
        else:
            candidates = [
                Path.home() / "Android" / "Sdk",
            ]
        for c in candidates:
            if c.exists():
                return c
        return None

    def _find_sdk_tool(self, name: str) -> Optional[str]:
        """Localiza ferramenta do Android SDK build-tools."""
        sdk = self._find_sdk_path()
        if not sdk:
            return None
        bt_dir = sdk / "build-tools"
        if not bt_dir.exists():
            return None
        versions = sorted(bt_dir.iterdir(), reverse=True)
        for v in versions:
            for ext in ["", ".exe", ".bat"]:
                tool = v / f"{name}{ext}"
                if tool.exists():
                    return str(tool.resolve())
        return None

    def _find_platform_jar(self) -> Optional[str]:
        """Localiza android.jar no SDK platforms/."""
        sdk = self._find_sdk_path()
        if not sdk:
            return None
        # Tenta compile_sdk primeiro, depois fallbacks
        for api in [self.compile_sdk, 35, 34, 33, 30]:
            p = sdk / "platforms" / f"android-{api}" / "android.jar"
            if p.exists():
                self.compile_sdk = api
                return str(p.resolve())
        # Fallback: qualquer android.jar
        platforms_dir = sdk / "platforms"
        if platforms_dir.exists():
            for d in sorted(platforms_dir.iterdir(), reverse=True):
                p = d / "android.jar"
                if p.exists():
                    m = re.search(r"android-(\d+)", d.name)
                    if m:
                        self.compile_sdk = int(m.group(1))
                    return str(p.resolve())
        return None

    def _find_java(self) -> Optional[str]:
        """Localiza java.exe e deriva javac, jar."""
        java_home = os.environ.get("JAVA_HOME", "")
        if java_home:
            j = Path(java_home) / "bin" / "java.exe"
            if j.exists():
                self._java = str(j)
                self._javac = str(Path(java_home) / "bin" / "javac.exe")
                self._jar_tool = str(Path(java_home) / "bin" / "jar.exe")
                return self._java
        try:
            r = subprocess.run(["where", "java"], capture_output=True, text=True, timeout=5)
            if r.returncode == 0 and r.stdout.strip():
                java_path = r.stdout.strip().splitlines()[0]
                self._java = java_path
                jdir = str(Path(java_path).parent)
                self._javac = jdir + "\\javac.exe" if platform.system() == "Windows" else jdir + "/javac"
                self._jar_tool = jdir + "\\jar.exe" if platform.system() == "Windows" else jdir + "/jar"
                return java_path
        except Exception:
            pass
        # Fallback: tentar no PATH
        for cmd, attr in [("javac", "_javac"), ("jar", "_jar_tool"), ("java", "_java")]:
            try:
                r = subprocess.run(["where" if platform.system() == "Windows" else "which", cmd],
                                   capture_output=True, text=True, timeout=5)
                if r.returncode == 0 and r.stdout.strip():
                    setattr(self, attr, r.stdout.strip().splitlines()[0])
            except Exception:
                pass
        return self._java

    def check_tools(self) -> bool:
        """Verifica se todas as ferramentas necessarias estao disponiveis. Retorna True se OK."""
        all_ok = True

        # Android SDK tools
        self._aapt = self._find_sdk_tool("aapt") or self._find_sdk_tool("aapt.exe")
        if not self._aapt:
            self._log("aapt nao encontrado no build-tools/", "ERROR")
            all_ok = False
        else:
            self._log(f"aapt: {self._aapt}", "SUCCESS")

        self._d8 = self._find_sdk_tool("d8") or self._find_sdk_tool("d8.bat")
        if not self._d8:
            self._log("d8 nao encontrado no build-tools/", "ERROR")
            all_ok = False
        else:
            self._log(f"d8: {self._d8}", "SUCCESS")

        self._zipalign = self._find_sdk_tool("zipalign") or self._find_sdk_tool("zipalign.exe")
        if not self._zipalign:
            self._log("zipalign nao encontrado (APK nao sera alinhado)", "WARNING")

        self._apksigner = self._find_sdk_tool("apksigner") or self._find_sdk_tool("apksigner.bat")
        if not self._apksigner:
            self._log("apksigner nao encontrado (APK nao sera assinado)", "WARNING")

        # Platform JAR
        self._platform_jar = self._find_platform_jar()
        if not self._platform_jar:
            self._log(f"android.jar (platforms/android-{self.compile_sdk}) nao encontrado", "ERROR")
            all_ok = False
        else:
            self._log(f"android.jar (API {self.compile_sdk}): {self._platform_jar}", "SUCCESS")

        # JDK
        java = self._find_java()
        if not java or not self._javac or not self._jar_tool:
            self._log("JDK nao encontrado (javac + jar obrigatorios)", "ERROR")
            all_ok = False
        else:
            self._log(f"javac: {self._javac}", "SUCCESS")
            self._log(f"jar: {self._jar_tool}", "SUCCESS")

        if all_ok:
            self._log("Todas as ferramentas Pure SDK estao disponiveis", "SUCCESS")
        return all_ok

    def find_java_files(self) -> List[str]:
        """Retorna lista de arquivos .java no diretorio src/."""
        src_dir = self.project_path / "src"
        if not src_dir.exists():
            return []
        return [str(p.resolve()) for p in sorted(src_dir.rglob("*.java"))]

    def validate_project(self) -> bool:
        """Valida estrutura do projeto Pure SDK."""
        checks = {
            "AndroidManifest.xml": (self.project_path / "AndroidManifest.xml").exists(),
            "res/": (self.project_path / "res").is_dir(),
            "res/values/": (self.project_path / "res" / "values").is_dir(),
            "src/": (self.project_path / "src").is_dir(),
            "*.java em src/": len(self.find_java_files()) > 0,
        }
        passed = all(checks.values())
        for name, ok in checks.items():
            self._log(f"  {name}: {'OK' if ok else 'FALTANDO'}", "SUCCESS" if ok else "ERROR")
        if passed:
            self._log("Projeto Pure SDK valido", "SUCCESS")
        else:
            self._log("Projeto Pure SDK INVALIDO", "ERROR")
        return passed

    def cleanup(self):
        """Limpa diretorio de build."""
        if self.build_dir.exists():
            shutil.rmtree(self.build_dir, ignore_errors=True)
        self.build_dir.mkdir(parents=True, exist_ok=True)

    def _run_cmd(self, cmd: List[str], cwd: Optional[Path] = None,
                 timeout: int = 120, desc: str = "") -> subprocess.CompletedProcess:
        """Executa comando com logging e tratamento de erro."""
        self._log(f"  {desc}: {' '.join(cmd)}", "INFO")
        try:
            r = subprocess.run(
                cmd, cwd=cwd or self.project_path,
                capture_output=True, text=True, timeout=timeout
            )
            if r.returncode != 0:
                err = r.stderr[:500] if r.stderr else r.stdout[:500]
                self._log(f"  Falha: {err[:200]}", "ERROR")
            return r
        except subprocess.TimeoutExpired:
            self._log(f"  Timeout ({timeout}s)", "ERROR")
            return subprocess.CompletedProcess(cmd, -1, "", "Timeout")

    def step1_rjava(self) -> bool:
        """aapt package -f -m -M AndroidManifest.xml -S res -I android.jar -J src"""
        self._log("Passo 1/8: Gerando R.java via aapt...", "STEP")
        if not self._aapt or not self._platform_jar:
            return False
        r = self._run_cmd([
            self._aapt, "package", "-f", "-m",
            "-M", str(self.project_path / "AndroidManifest.xml"),
            "-S", str(self.project_path / "res"),
            "-I", self._platform_jar,
            "-J", str(self.project_path / "src"),
        ], timeout=60, desc="aapt package (R.java)")
        if r.returncode == 0:
            # Verifica se R.java foi gerado
            rjava_files = list((self.project_path / "src").rglob("R.java"))
            if rjava_files:
                self._log(f"  R.java gerado: {rjava_files[0]}", "SUCCESS")
                return True
            self._log("  R.java nao encontrado apos aapt", "WARNING")
            return True
        return False

    def step2_javac(self) -> bool:
        """javac -cp android.jar -d build/classes src/**/*.java"""
        self._log("Passo 2/8: Compilando Java...", "STEP")
        classes_dir = self.build_dir / "classes"
        classes_dir.mkdir(parents=True, exist_ok=True)
        java_files = self.find_java_files()
        if not java_files:
            self._log("  Nenhum arquivo .java encontrado em src/", "ERROR")
            return False
        self._log(f"  {len(java_files)} arquivo(s) .java encontrados", "INFO")
        cmd = [self._javac, "-cp", self._platform_jar,
               "-d", str(classes_dir)] + java_files
        r = self._run_cmd(cmd, timeout=120, desc="javac")
        if r.returncode == 0:
            class_count = len(list(classes_dir.rglob("*.class")))
            self._log(f"  {class_count} arquivo(s) .class compilados", "SUCCESS")
            return True
        return False

    def step3_jar(self) -> bool:
        """jar cf build/classes.jar -C build/classes ."""
        self._log("Passo 3/8: Empacotando JAR...", "STEP")
        classes_dir = self.build_dir / "classes"
        if not classes_dir.exists() or not any(classes_dir.iterdir()):
            self._log("  Nenhum .class para empacotar", "ERROR")
            return False
        r = self._run_cmd([
            self._jar_tool, "cf", str(self.build_dir / "classes.jar"),
            "-C", str(classes_dir), ".",
        ], timeout=30, desc="jar")
        if r.returncode == 0:
            size = (self.build_dir / "classes.jar").stat().st_size
            self._log(f"  classes.jar ({size} bytes)", "SUCCESS")
            return True
        return False

    def step4_d8(self) -> bool:
        """d8 --lib android.jar --release --output build/dex build/classes.jar"""
        self._log("Passo 4/8: Convertendo para DEX...", "STEP")
        dex_dir = self.build_dir / "dex"
        dex_dir.mkdir(parents=True, exist_ok=True)
        classes_jar = self.build_dir / "classes.jar"
        if not classes_jar.exists():
            self._log("  classes.jar nao encontrado", "ERROR")
            return False
        r = self._run_cmd([
            self._d8, "--lib", self._platform_jar, "--release",
            "--output", str(dex_dir), str(classes_jar),
        ], timeout=120, desc="d8")
        dex_file = dex_dir / "classes.dex"
        if r.returncode == 0 and dex_file.exists():
            self._log(f"  DEX gerado: {dex_file} ({dex_file.stat().st_size} bytes)", "SUCCESS")
            return True
        self._log("  classes.dex nao encontrado apos d8", "ERROR")
        return False

    def step5_package_apk(self) -> bool:
        """aapt package -f -M AndroidManifest.xml -S res -I android.jar -F build/unsigned.apk"""
        self._log("Passo 5/8: Criando APK esqueleto...", "STEP")
        unsigned_apk = self.build_dir / "unsigned.apk"
        r = self._run_cmd([
            self._aapt, "package", "-f",
            "-M", str(self.project_path / "AndroidManifest.xml"),
            "-S", str(self.project_path / "res"),
            "-I", self._platform_jar,
            "-F", str(unsigned_apk),
        ], timeout=60, desc="aapt package (APK)")
        if r.returncode == 0 and unsigned_apk.exists():
            self._log(f"  APK esqueleto: {unsigned_apk.name} ({unsigned_apk.stat().st_size} bytes)", "SUCCESS")
            return True
        return False

    def step6_add_dex(self) -> bool:
        """aapt add unsigned.apk classes.dex"""
        self._log("Passo 6/8: Injetando DEX no APK...", "STEP")
        unsigned_apk = self.build_dir / "unsigned.apk"
        dex_file = self.build_dir / "dex" / "classes.dex"
        if not unsigned_apk.exists():
            self._log("  APK esqueleto nao encontrado", "ERROR")
            return False
        if not dex_file.exists():
            self._log("  classes.dex nao encontrado", "ERROR")
            return False
        # aapt add requer que o arquivo esteja no CWD
        r = self._run_cmd([
            self._aapt, "add", str(unsigned_apk), str(dex_file),
        ], cwd=self.build_dir, timeout=30, desc="aapt add")
        if r.returncode == 0:
            self._log(f"  DEX injetado em {unsigned_apk.name}", "SUCCESS")
            return True
        return False

    def step7_zipalign(self) -> bool:
        """zipalign -f -v 4 unsigned.apk aligned.apk"""
        self._log("Passo 7/8: Alinhando APK...", "STEP")
        if not self._zipalign:
            self._log("  zipalign nao disponivel, copiando APK sem alinhamento", "WARNING")
            src = self.build_dir / "unsigned.apk"
            dst = self.build_dir / "aligned.apk"
            if src.exists():
                shutil.copy2(str(src), str(dst))
                return True
            return False
        unsigned_apk = self.build_dir / "unsigned.apk"
        aligned_apk = self.build_dir / "aligned.apk"
        if not unsigned_apk.exists():
            self._log("  APK unsigned nao encontrado", "ERROR")
            return False
        r = self._run_cmd([
            self._zipalign, "-f", "-v", "4",
            str(unsigned_apk), str(aligned_apk),
        ], timeout=30, desc="zipalign")
        if r.returncode == 0 and aligned_apk.exists():
            self._log(f"  APK alinhado: {aligned_apk.name}", "SUCCESS")
            return True
        self._log("  zipalign falhou, copiando sem alinhamento", "WARNING")
        shutil.copy2(str(unsigned_apk), str(aligned_apk))
        return True

    def step8_sign(self) -> bool:
        """Assina o APK com debug keystore via apksigner."""
        self._log("Passo 8/8: Assinando APK...", "STEP")
        aligned_apk = self.build_dir / "aligned.apk"
        if not aligned_apk.exists():
            self._log("  APK alinhado nao encontrado", "ERROR")
            return False

        env = os.environ.copy()
        if self._java:
            env["JAVA_HOME"] = str(Path(self._java).parent.parent)

        # Debug keystore
        keystore = Path.home() / ".android" / "debug.keystore"
        if not keystore.exists():
            self._log("  Debug keystore nao encontrado, criando...", "INFO")
            try:
                subprocess.run(
                    ["keytool", "-genkey", "-v", "-keystore", str(keystore),
                     "-alias", "androiddebugkey", "-storepass", "android",
                     "-keypass", "android", "-keyalg", "RSA", "-validity", "365",
                     "-dname", "CN=Android Debug, OU=Android, O=Android, L=Unknown, ST=Unknown, C=US"],
                    capture_output=True, text=True, timeout=30, env=env
                )
            except Exception as e:
                self._log(f"  Falha ao criar keystore: {e}", "WARNING")

        if not keystore.exists():
            self._log("  Nao foi possivel criar keystore, APK nao assinado", "ERROR")
            return False

        if self._apksigner:
            try:
                r = subprocess.run(
                    [self._apksigner, "sign", "--ks", str(keystore),
                     "--ks-pass", "pass:android", "--ks-key-alias", "androiddebugkey",
                     str(aligned_apk)],
                    capture_output=True, text=True, timeout=120,
                )
                if r.returncode == 0:
                    self._log("  APK assinado com sucesso via apksigner", "SUCCESS")
                    return True
                self._log(f"  apksigner falhou: {r.stderr[:200]}", "WARNING")
            except Exception as e:
                self._log(f"  apksigner erro: {e}", "WARNING")

        # Fallback: jarsigner
        try:
            r = subprocess.run(
                ["jarsigner", "-keystore", str(keystore),
                 "-storepass", "android", "-keypass", "android",
                 "-sigalg", "SHA256withRSA", "-digestalg", "SHA-256",
                 str(aligned_apk), "androiddebugkey"],
                capture_output=True, text=True, timeout=30, env=env
            )
            if r.returncode == 0:
                self._log("  APK assinado via jarsigner (fallback)", "SUCCESS")
                return True
            self._log(f"  jarsigner falhou: {r.stderr[:200]}", "WARNING")
        except Exception as e:
            self._log(f"  jarsigner erro: {e}", "WARNING")

        return False

    def build(self) -> bool:
        """Executa pipeline completo de 8 etapas."""
        self._log("=" * 60, "STEP")
        self._log("INICIANDO BUILD ANDROID PURE SDK", "STEP")
        self._log("=" * 60, "STEP")

        # Cleanup
        self.cleanup()

        # Verifica ferramentas
        self._log("Verificando ferramentas...", "STEP")
        if not self.check_tools():
            self._log("Ferramentas insuficientes para build Pure SDK", "ERROR")
            return False

        # Pipeline
        steps = [
            ("Gerar R.java", self.step1_rjava),
            ("Compilar Java", self.step2_javac),
            ("Empacotar JAR", self.step3_jar),
            ("Converter para DEX", self.step4_d8),
            ("Criar APK esqueleto", self.step5_package_apk),
            ("Injetar DEX", self.step6_add_dex),
            ("Alinhar APK", self.step7_zipalign),
            ("Assinar APK", self.step8_sign),
        ]

        total = len(steps)
        for idx, (name, fn) in enumerate(steps):
            self._progress(int((idx / total) * 100), name)
            ok = fn()
            if not ok:
                self._log(f"FALHOU: {name}", "ERROR")
                return False
            self._progress(int(((idx + 1) / total) * 100), f"{name} OK")

        # Verifica resultado final
        final_apk = self.build_dir / "aligned.apk"
        if final_apk.exists():
            self.last_apk_path = final_apk
            self._log("=" * 60, "SUCCESS")
            self._log(f"APK GERADO: {final_apk} ({final_apk.stat().st_size / 1024:.1f} KB)", "SUCCESS")
            self._log("=" * 60, "SUCCESS")
            return True

        self._log("APK final nao encontrado apos pipeline", "ERROR")
        return False
