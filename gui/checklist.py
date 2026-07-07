#!/usr/bin/env python3
"""Checklist de pr\u00e9-requisitos — verifica ambiente antes do build."""

import os
import platform
import subprocess
from pathlib import Path


class Checklist:
    """
    Verifica todos os pr\u00e9-requisitos antes de qualquer build.
    Retorna (ok: bool, flutter_exe: str | None).
    """

    def __init__(self, log):
        self.log = log
        self.flutter_exe = None

    def run(self):
        self.log.sep()
        self.log.info("PR\u00c9-REQUISITOS \u2014 verificando ambiente...")
        self.log.sep()

        results = [
            self._check_python(),
            self._check_git(),
            self._check_java(),
            self._check_flutter(),
        ]

        self.log.sep()
        if all(results):
            self.log.ok("Todos os pr\u00e9-requisitos OK \u2014 iniciando build")
        else:
            self.log.err("Um ou mais pr\u00e9-requisitos falharam \u2014 build cancelado")
        self.log.sep()
        return all(results)

    def _check_python(self):
        v = platform.python_version()
        self.log.ok(f"Python {v}")
        return True

    def _check_git(self):
        try:
            r = subprocess.run(
                ["git", "--version"], capture_output=True, text=True, timeout=10
            )
            if r.returncode == 0:
                self.log.ok(f"Git: {r.stdout.strip()}")
                return True
        except Exception:
            pass
        self.log.err("Git N\u00c3O encontrado")
        return False

    def _check_java(self):
        try:
            r = subprocess.run(
                ["java", "-version"], capture_output=True, text=True, timeout=10
            )
            out = (r.stdout + r.stderr).strip().split("\n")[0]
            self.log.ok(f"Java: {out}")
            return True
        except Exception:
            pass
        jh = os.environ.get("JAVA_HOME", "")
        if jh:
            java_bin = Path(jh) / "bin" / ("java.exe" if os.name == "nt" else "java")
            if java_bin.exists():
                self.log.ok(f"Java via JAVA_HOME: {java_bin}")
                return True
        self.log.warn("Java n\u00e3o encontrado \u2014 pode ser necess\u00e1rio para build Android")
        return True

    def _check_flutter(self):
        candidates = self._flutter_candidates()
        for exe in candidates:
            try:
                proc = subprocess.Popen(
                    [exe, "--version"],
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, encoding="utf-8", errors="replace",
                )
                try:
                    out, _ = proc.communicate(timeout=30)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    continue
                if proc.returncode == 0:
                    version_line = out.strip().split("\n")[0]
                    self.log.ok(f"Flutter: {version_line}")
                    self.log.info(f"  Execut\u00e1vel: {exe}")
                    self.flutter_exe = exe
                    bin_dir = str(Path(exe).parent)
                    if bin_dir not in os.environ.get("PATH", ""):
                        os.environ["PATH"] = (
                            bin_dir + os.pathsep + os.environ.get("PATH", "")
                        )
                    return True
            except Exception:
                continue

        self.log.err("Flutter N\u00c3O encontrado nos locais verificados")
        for c in candidates:
            self.log.info(f"    \u2022 {c}")
        self.log.info("Solu\u00e7\u00e3o: instale o Flutter e adicione flutter/bin ao PATH")
        return False

    def _flutter_candidates(self):
        is_win = os.name == "nt"
        suffix = ".bat" if is_win else ""
        candidates = []
        candidates.append(f"flutter{suffix}")
        for var in ("Flutter", "Flutterbin", "FLUTTER_ROOT", "FLUTTER_HOME", "FLUTTER_SDK"):
            val = os.environ.get(var, "").strip()
            if val:
                candidates.append(str(Path(val) / f"flutter{suffix}"))
                candidates.append(str(Path(val) / "bin" / f"flutter{suffix}"))
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
        seen = set()
        result = []
        for c in candidates:
            if c not in seen:
                seen.add(c)
                result.append(c)
        return result
