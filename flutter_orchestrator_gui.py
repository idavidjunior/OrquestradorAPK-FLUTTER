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
        candidates = self._flutter_candidates()
        for exe in candidates:
            try:
                proc = subprocess.Popen(
                    [exe, "--version"],
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, encoding="utf-8", errors="replace",
                    env=os.environ.copy(),
                )
                try:
                    out, _ = proc.communicate(timeout=30)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    continue
                if proc.returncode == 0:
                    version_line = out.strip().split("\n")[0]
                    self.log.ok(f"Flutter: {version_line}")
                    self.log.info(f"  Executável: {exe}")
                    self.flutter_exe = exe
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
#  Knowledge Base — cérebro que aprende
# ─────────────────────────────────────────────────────────────
class KnowledgeBase:
    """
    Carrega known_fixes.json, aplica correções conhecidas ao código,
    e aprende novos erros resolvidos pelo Gemini gravando no JSON.

    Fluxo de aprendizado:
    1. Build falha → KnowledgeBase tenta corrigir pelos fixes conhecidos
    2. Se não resolveu → Gemini corrige
    3. Gemini corrigiu → KnowledgeBase salva o novo padrão no JSON
    4. Próxima vez → KnowledgeBase resolve sem chamar Gemini
    """

    DEFAULT_PATH = Path(__file__).parent / "known_fixes.json"

    def __init__(self, log: Logger, path: Path | None = None):
        self.log  = log
        self.path = path or self.DEFAULT_PATH
        self._db: dict = {}
        self._load()

    # ── Carregamento ────────────────────────────
    def _load(self):
        try:
            if self.path.exists():
                self._db = json.loads(self.path.read_text(encoding="utf-8"))
                fixes = len(self._db.get("fixes", []))
                total = self._db.get("_meta", {}).get("total_fixes_applied", 0)
                self.log.ok(f"🧠 KnowledgeBase carregada: {fixes} correções conhecidas "
                            f"({total} aplicações no total)")
            else:
                self.log.warn("🧠 known_fixes.json não encontrado — iniciando vazio")
                self._db = {"_meta": {}, "fixes": [], "package_versions": {},
                            "error_history": []}
        except Exception as e:
            self.log.err(f"🧠 Erro ao carregar KnowledgeBase: {e}")
            self._db = {"_meta": {}, "fixes": [], "package_versions": {},
                        "error_history": []}

    def _save(self):
        try:
            self._db["_meta"]["last_updated"] = datetime.now().strftime("%Y-%m-%d")
            self.path.write_text(
                json.dumps(self._db, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
        except Exception as e:
            self.log.err(f"🧠 Erro ao salvar KnowledgeBase: {e}")

    # ── Aplicar correções conhecidas ─────────────
    def apply(self, code: str, errors: list[str],
              project_dir: Path | None = None) -> tuple[str, list[str]]:
        """
        Tenta corrigir o código usando fixes conhecidos.
        Retorna (código_corrigido, lista_de_correções_aplicadas).
        """
        applied = []
        error_text = "\n".join(errors)

        for fix in self._db.get("fixes", []):
            fix_id = fix.get("id", "?")

            # Verifica se algum erro do compilador bate com os padrões do fix
            error_match = any(
                pat.lower() in error_text.lower()
                for pat in fix.get("error_patterns", [])
            )
            # Verifica se o contexto do código bate
            context_match = all(
                pat in code
                for pat in fix.get("context_patterns", [])
            )

            if not (error_match and context_match):
                continue

            fix_type = fix.get("type", "")
            desc     = fix.get("description", fix_id)
            changed  = False

            if fix_type == "regex_replace":
                for op in fix.get("operations", []):
                    new_code = re.sub(op["find"], op["replace"], code)
                    if new_code != code:
                        code    = new_code
                        changed = True

                # Garante imports necessários
                for imp in fix.get("ensure_imports", []):
                    if imp not in code:
                        code    = imp + "\n" + code
                        changed = True

            elif fix_type == "import_replace":
                for op in fix.get("operations", []):
                    if op["find"] in code:
                        code    = code.replace(op["find"], op["replace"])
                        changed = True
                pubspec_replace = fix.get("pubspec_replace", {})
                if pubspec_replace and changed:
                    if project_dir:
                        ProjectSourceManager._inject_pubspec_packages(
                            project_dir, {}, self.log, replace=pubspec_replace)
                    else:
                        for old_pkg, new_entry in pubspec_replace.items():
                            self.log.warn(
                                f"🧠 pubspec: substituir '{old_pkg}' por '{new_entry}'")

            elif fix_type == "pubspec_inject":
                changed = True
                if project_dir:
                    ProjectSourceManager._detect_and_inject_deps(
                        code, project_dir, self.log, kb=self)

            elif fix_type == "info_only":
                hint = fix.get("fix_hint", "")
                if hint:
                    self.log.warn(f"🧠 [{fix_id}] {desc}")
                    self.log.warn(f"   💡 {hint}")

            elif fix_type == "add_default_case":
                # Adiciona default ao switch de LoopMode se não existir
                def _add_default(m):
                    block = m.group(0)
                    if "default:" not in block:
                        block = block.rstrip("}").rstrip() + \
                                "\n        default:\n          break;\n      }"
                        return block
                    return block
                new_code = re.sub(
                    r'switch\s*\(\w+\)\s*\{[^}]+LoopMode[^}]+\}',
                    _add_default, code, flags=re.DOTALL
                )
                if new_code != code:
                    code    = new_code
                    changed = True

            elif fix_type == "android_gradle_fix":
                # Corrige erro de namespace no build.gradle de plugins Android
                if project_dir:
                    changed = self._fix_android_gradle_namespace(project_dir, errors, self.log)

            elif fix_type == "pubspec_fix":
                # Corrige erros de sintaxe no pubspec.yaml
                if project_dir:
                    changed = self._fix_pubspec_syntax_errors(errors, project_dir, self.log)

            if changed and fix_type != "info_only":
                applied.append(desc)
                fix["times_applied"] = fix.get("times_applied", 0) + 1
                self.log.ok(f"🧠 [{fix_id}] Correção aplicada: {desc}")

        if applied:
            meta = self._db.setdefault("_meta", {})
            meta["total_fixes_applied"] = meta.get("total_fixes_applied", 0) + len(applied)
            self._save()

        return code, applied

    # ── Aprender com o Gemini ────────────────────
    def learn_from_gemini(self, original_code: str, fixed_code: str,
                          errors: list[str], session_id: str):
        """
        Quando o Gemini corrige um erro novo, tenta extrair o padrão
        e gravar como um novo fix para uso futuro sem API.
        """
        try:
            # Extrai comentários de correção do código do Gemini
            corrections = []
            for line in fixed_code.split("\n"):
                line = line.strip()
                if line.startswith("// -") and "CORREÇÕES" not in line:
                    corrections.append(line[4:].strip())
                if line.startswith("// CORREÇÕES"):
                    continue

            if not corrections:
                return

            # Registra no histórico de erros
            entry = {
                "session_id":   session_id,
                "date":         datetime.now().strftime("%Y-%m-%d %H:%M"),
                "errors":       errors[:10],
                "corrections":  corrections,
                "status":       "gemini_resolved"
            }
            self._db.setdefault("error_history", []).append(entry)

            # Tenta criar um fix automático simples por diff de linhas
            orig_lines  = set(original_code.split("\n"))
            fixed_lines = set(fixed_code.split("\n"))
            removed = orig_lines - fixed_lines
            added   = fixed_lines - orig_lines

            if removed and added and len(removed) <= 5:
                new_fix = {
                    "id":               f"gemini_{session_id}",
                    "description":      corrections[0] if corrections else "Fix aprendido do Gemini",
                    "error_patterns":   [e[:80] for e in errors[:3]],
                    "context_patterns": [],
                    "type":             "info_only",
                    "operations":       [],
                    "fix_hint":         f"Gemini corrigiu: {'; '.join(corrections[:2])}",
                    "removed_lines":    list(removed)[:5],
                    "added_lines":      list(added)[:5],
                    "explanation":      f"Aprendido automaticamente do Gemini em {entry['date']}",
                    "times_applied":    0,
                    "source":           "gemini"
                }
                self._db.setdefault("fixes", []).append(new_fix)
                self.log.ok(f"🧠 Novo fix aprendido do Gemini: '{new_fix['description']}'")
                self.log.info(f"   Total de fixes conhecidos: {len(self._db['fixes'])}")

            self._save()

        except Exception as e:
            self.log.warn(f"🧠 Não foi possível aprender deste fix: {e}")

    # ── Pacotes conhecidos ───────────────────────
    def get_package_version(self, pkg: str) -> str | None:
        return self._db.get("package_versions", {}).get(pkg)

    def add_package_version(self, pkg: str, version: str):
        """Aprende uma nova versão de pacote."""
        pv = self._db.setdefault("package_versions", {})
        if pkg not in pv:
            pv[pkg] = version
            self.log.info(f"🧠 Novo pacote aprendido: {pkg}: {version}")
            self._save()

    def _fix_android_gradle_namespace(self, project_dir: Path, errors: list[str], log: Logger) -> bool:
        """
        Corrige erro de namespace no build.gradle de plugins Android.
        Detecta plugins sem namespace e adiciona automaticamente baseado no AndroidManifest.xml.
        """
        try:
            error_text = "\n".join(errors)
            
            # Extrai o caminho do build.gradle problemático do erro
            build_gradle_match = re.search(r'([A-Z]:\\[^:]+\\android\\build\.gradle)', error_text)
            if not build_gradle_match:
                log.warn("🧠 Não foi possível extrair caminho do build.gradle do erro")
                return False
            
            build_gradle_path = Path(build_gradle_match.group(1))
            if not build_gradle_path.exists():
                log.warn(f"🧠 build.gradle não encontrado: {build_gradle_path}")
                return False
            
            # Lê o build.gradle atual
            build_gradle_content = build_gradle_path.read_text(encoding="utf-8")
            
            # Verifica se já tem namespace
            if "namespace" in build_gradle_content:
                log.info(f"🧠 build.gradle já tem namespace: {build_gradle_path}")
                return False
            
            # Tenta encontrar o AndroidManifest.xml do plugin
            android_manifest_path = build_gradle_path.parent / "src" / "main" / "AndroidManifest.xml"
            if not android_manifest_path.exists():
                log.warn(f"🧠 AndroidManifest.xml não encontrado: {android_manifest_path}")
                return False
            
            # Extrai o package do AndroidManifest.xml
            manifest_content = android_manifest_path.read_text(encoding="utf-8")
            package_match = re.search(r'package="([^"]+)"', manifest_content)
            if not package_match:
                log.warn("🧠 Não foi possível extrair package do AndroidManifest.xml")
                return False
            
            package_name = package_match.group(1)
            
            # Adiciona namespace ao build.gradle
            # Procura pelo bloco android { ... }
            android_block_match = re.search(r'android\s*\{', build_gradle_content)
            if not android_block_match:
                log.warn("🧠 Não foi possível encontrar bloco android no build.gradle")
                return False
            
            # Insere namespace após o bloco android {
            insert_pos = android_block_match.end()
            new_build_gradle = (
                build_gradle_content[:insert_pos] + 
                f'\n    namespace \'{package_name}\'' +
                build_gradle_content[insert_pos:]
            )
            
            # Escreve o build.gradle corrigido
            build_gradle_path.write_text(new_build_gradle, encoding="utf-8")
            
            log.ok(f"🧠 Namespace adicionado ao build.gradle: {package_name}")
            log.ok(f"🧠 Arquivo corrigido: {build_gradle_path}")
            return True
            
        except Exception as e:
            log.err(f"🧠 Erro ao corrigir namespace do Android Gradle Plugin: {e}")
            return False

    def stats(self) -> dict:
        meta   = self._db.get("_meta", {})
        fixes  = self._db.get("fixes", [])
        hist   = self._db.get("error_history", [])
        manual = sum(1 for f in fixes if f.get("source") == "manual")
        learned= sum(1 for f in fixes if f.get("source") == "gemini")
        return {
            "total_fixes":    len(fixes),
            "manual_fixes":   manual,
            "learned_fixes":  learned,
            "total_applied":  meta.get("total_fixes_applied", 0),
            "history_count":  len(hist),
        }


# ─────────────────────────────────────────────────────────────
#  Gemini Code Fixer — corrige código Dart com IA
# ─────────────────────────────────────────────────────────────
class GeminiCodeFixer:
    """
    Usa a API Gemini para analisar erros do compilador Dart,
    corrigir o código e retornar o código corrigido com explicações.
    """
    # Tenta modelos em ordem até um funcionar
    MODELS = [
        "gemini-2.0-flash",
        "gemini-1.5-flash",
        "gemini-1.5-flash-latest",
        "gemini-pro",
    ]
    BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

    @classmethod
    def _working_url(cls, api_key: str) -> str | None:
        """Encontra o primeiro modelo disponível para esta chave."""
        for model in cls.MODELS:
            url = cls.BASE_URL.format(model=model)
            try:
                req = Request(
                    f"{url}?key={api_key}",
                    data=json.dumps({"contents": [{"parts": [{"text": "hi"}]}]}).encode(),
                    headers={"Content-Type": "application/json"},
                    method="POST"
                )
                with urlopen(req, timeout=10) as r:
                    if r.status == 200:
                        return url
            except Exception as e:
                if "404" not in str(e):
                    return url  # outro erro (quota, etc) — modelo existe
        return None

    def __init__(self, api_key: str, log: Logger):
        self.api_key = api_key
        self.log = log

    def fix(self, code: str, errors: list[str]) -> str | None:
        """
        Envia código + erros para o Gemini e retorna código corrigido.
        Retorna None se falhar.
        """
        if not self.api_key:
            return None

        error_text = "\n".join(errors[:60])  # máx 60 linhas de erro

        prompt = f"""Você é um especialista em Flutter/Dart.
O código abaixo falhou ao compilar com os erros listados.

ERROS DO COMPILADOR:
{error_text}

CÓDIGO DART (main.dart):
```dart
{code}
```

TAREFA:
1. Analise cada erro e corrija o código
2. Mantenha a lógica e funcionalidade originais intactas
3. Corrija apenas o que é necessário para compilar
4. Retorne APENAS o código Dart corrigido, sem explicações antes ou depois
5. Não inclua marcadores de código (``` ou ```dart) na resposta
6. Logo abaixo do import inicial, adicione um comentário com as correções feitas:
   // CORREÇÕES APLICADAS:
   // - [descrição curta de cada correção]

IMPORTANTE: Retorne SOMENTE o código Dart puro, começando com import ou void main."""

        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.1,
                "maxOutputTokens": 8192,
            }
        }

        try:
            self.log.info("🤖 Enviando código para Gemini analisar e corrigir...")

            # Verifica cache local primeiro
            cache_key = hashlib.md5((code + "\n".join(errors)).encode()).hexdigest()
            cache_file = Path.home() / ".flutter_orchestrator_cache" / f"gemini_fix_{cache_key}.json"
            
            if cache_file.exists():
                try:
                    cache_data = json.loads(cache_file.read_text(encoding="utf-8"))
                    self.log.ok("🤖 Usando correção em cache (evitando rate limit)")
                    return cache_data.get("fixed_code")
                except Exception:
                    pass  # Cache corrompido, ignora e continua

            # Descobre URL funcional
            url = GeminiCodeFixer._working_url(self.api_key)
            if not url:
                self.log.err("🤖 Nenhum modelo Gemini disponível para esta chave")
                return None

            self.log.info(f"🤖 Usando: {url.split('/models/')[1].split(':')[0]}")
            full_url = f"{url}?key={self.api_key}"
            payload_bytes = json.dumps(payload).encode("utf-8")
            headers = {"Content-Type": "application/json"}

            resp = None
            for attempt, wait in enumerate((0, 15, 30, 60)):
                if wait:
                    self.log.warn(f"🤖 Rate limit — aguardando {wait}s (tentativa {attempt + 1}/4)...")
                    time.sleep(wait)
                try:
                    req = Request(full_url, data=payload_bytes, headers=headers, method="POST")
                    with urlopen(req, timeout=90) as r:
                        resp = json.loads(r.read())
                    break
                except Exception as e:
                    if "429" in str(e) and attempt < 3:
                        continue
                    raise

            if resp is None:
                self.log.err("🤖 Gemini: esgotadas tentativas após rate limit")
                return None

            # Extrai o texto da resposta
            fixed_code = (resp.get("candidates", [{}])[0]
                             .get("content", {})
                             .get("parts", [{}])[0]
                             .get("text", "")).strip()

            if not fixed_code:
                self.log.err("Gemini retornou resposta vazia")
                return None

            # Remove marcadores de código se Gemini os incluiu mesmo assim
            if fixed_code.startswith("```"):
                lines = fixed_code.split("\n")
                fixed_code = "\n".join(
                    l for l in lines
                    if not l.strip().startswith("```")
                ).strip()

            # Salva no cache local
            try:
                cache_dir = Path.home() / ".flutter_orchestrator_cache"
                cache_dir.mkdir(exist_ok=True)
                cache_data = {
                    "fixed_code": fixed_code,
                    "timestamp": datetime.now().isoformat(),
                    "errors": errors
                }
                cache_file.write_text(json.dumps(cache_data, indent=2), encoding="utf-8")
                self.log.ok("🤖 Correção salva em cache local")
            except Exception as e:
                self.log.warn(f"🤖 Não foi possível salvar cache: {e}")

            self.log.ok("🤖 Gemini retornou código corrigido")
            return fixed_code

        except Exception as e:
            self.log.err(f"🤖 Gemini API falhou: {e}")
            return None

    @staticmethod
    def validate_key(api_key: str) -> tuple[bool, str]:
        """Valida a chave Gemini com uma chamada mínima."""
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
            req = Request(url, headers={"Content-Type": "application/json"})
            with urlopen(req, timeout=10) as r:
                data = json.loads(r.read())
            models = [m.get("name", "") for m in data.get("models", [])]
            gemini = [m for m in models if "gemini" in m.lower()]
            if gemini:
                return True, f"OK — {len(gemini)} modelos Gemini disponíveis"
            return False, "Chave válida mas sem modelos Gemini"
        except Exception as e:
            err = str(e)
            if "400" in err or "API_KEY_INVALID" in err:
                return False, "Chave inválida"
            if "403" in err:
                return False, "Sem permissão — verifique a chave"
            return False, f"Erro de conexão: {err}"


# ─────────────────────────────────────────────────────────────
#  Project Source Manager
# ─────────────────────────────────────────────────────────────
class ProjectSourceManager:

    # Mapa de package → versão estável conhecida
    KNOWN_PACKAGES = {
        "on_audio_query":       "^2.9.0",
        "device_info_plus":     "^10.1.0",
        "media_store_plus":     "^1.0.3",
        "path_provider":        "^2.1.4",
        "shared_preferences":   "^2.3.2",
        "just_audio":           "^0.9.40",
        "http":                 "^1.2.2",
        "provider":             "^6.1.2",
        "get":                  "^4.6.6",
        "dio":                  "^5.7.0",
        "cached_network_image": "^3.4.1",
        "flutter_bloc":         "^8.1.6",
        "sqflite":              "^2.3.3",
        "hive":                 "^2.2.3",
        "hive_flutter":         "^1.1.0",
        "image_picker":         "^1.1.2",
        "permission_handler":   "^11.3.1",
        "url_launcher":         "^6.3.0",
        "connectivity_plus":    "^6.1.0",
        "intl":                 "^0.19.0",
        "lottie":               "^3.1.2",
        "flutter_svg":          "^2.0.10",
        "google_fonts":         "^6.2.1",
        "audioplayers":         "^6.1.0",
        "camera":               "^0.11.0",
        "geolocator":           "^13.0.1",
        "firebase_core":        "^3.6.0",
        "firebase_auth":        "^5.3.1",
        "cloud_firestore":      "^5.4.3",
        "video_player":         "^2.9.1",
        "animations":           "^2.0.11",
        "flutter_animate":      "^4.5.0",
        "rxdart":               "^0.28.0",
        "equatable":            "^2.0.5",
        "freezed_annotation":   "^2.4.4",
        "json_annotation":      "^4.9.0",
        "path":                 "^1.9.0",
        "uuid":                 "^4.5.1",
        "crypto":               "^3.0.5",
        "collection":           "^1.19.0",
        "flutter_localizations": None,   # SDK package
        "flutter_test":          None,   # SDK dev package
    }

    # Pacotes inexistentes/errados → pacote real no pub.dev
    PACKAGE_ALIASES = {
        "media_store": "on_audio_query",
    }

    _PUBSPEC_LINE = re.compile(
        r'^(name:|description:|version:|publish_to:|environment:|'
        r'sdk:|dependencies:|dev_dependencies:|flutter:|uses-material-design:|'
        r'  [a-zA-Z_][\w-]*:|  sdk:)'
    )
    _MANIFEST_LINE = re.compile(
        r'^<(uses-permission|manifest|application|/manifest)\b'
    )

    @staticmethod
    def _split_pasted_content(raw: str, log: Logger) -> tuple[str, str | None, list[str]]:
        """
        Separa Dart, pubspec.yaml e permissões Android colados no mesmo bloco.
        """
        lines = raw.split("\n")
        dart_lines: list[str] = []
        pubspec_lines: list[str] = []
        manifest_lines: list[str] = []
        i = 0

        while i < len(lines):
            line = lines[i]
            stripped = line.strip()

            if not pubspec_lines and re.match(r'^name:\s*\S', stripped):
                window = "\n".join(lines[i:min(i + 20, len(lines))])
                if re.search(r'^(environment:|dependencies:|version:)', window, re.M):
                    log.info("📂 Detectado pubspec.yaml embutido — separando...")
                    while i < len(lines):
                        cur = lines[i]
                        cur_s = cur.strip()
                        if ProjectSourceManager._MANIFEST_LINE.match(cur_s):
                            break
                        if pubspec_lines and cur_s and not ProjectSourceManager._PUBSPEC_LINE.match(cur_s):
                            break
                        pubspec_lines.append(cur)
                        i += 1
                    continue

            if ProjectSourceManager._MANIFEST_LINE.match(stripped):
                log.info("📂 Detectado AndroidManifest embutido — separando...")
                while i < len(lines):
                    cur = lines[i]
                    cur_s = cur.strip()
                    if (ProjectSourceManager._MANIFEST_LINE.match(cur_s)
                            or cur_s.startswith("</manifest")):
                        manifest_lines.append(cur)
                        i += 1
                    elif not cur_s:
                        i += 1
                        break
                    else:
                        break
                continue

            dart_lines.append(line)
            i += 1

        dart = "\n".join(dart_lines).strip()
        pubspec = "\n".join(pubspec_lines).strip() if pubspec_lines else None
        return dart, pubspec, manifest_lines

    @staticmethod
    def _inject_pubspec_packages(project_dir: Path, packages: dict[str, str],
                                 log: Logger, replace: dict[str, str] | None = None):
        """Injeta ou substitui pacotes no pubspec.yaml do projeto."""
        pubspec_path = project_dir / "pubspec.yaml"
        if not pubspec_path.exists():
            return
        pubspec = pubspec_path.read_text(encoding="utf-8")
        changed = False
        replace = replace or {}

        for old_pkg, new_entry in replace.items():
            if re.search(rf'^\s*{re.escape(old_pkg)}:', pubspec, re.M):
                pubspec = re.sub(
                    rf'^\s*{re.escape(old_pkg)}:.*$',
                    f"  {new_entry}",
                    pubspec,
                    count=1,
                    flags=re.M,
                )
                changed = True
                log.ok(f"pubspec: {old_pkg} → {new_entry}")
            else:
                m = re.match(r'^([\w_-]+):\s*(\S+)$', new_entry)
                if m:
                    packages.setdefault(m.group(1), m.group(2))

        for pkg, version in packages.items():
            if pkg in pubspec:
                continue
            if "\nflutter:\n" in pubspec:
                pubspec = pubspec.replace(
                    "\nflutter:\n", f"\n  {pkg}: {version}\nflutter:\n", 1)
                changed = True
                log.ok(f"pubspec: + {pkg}: {version}")

        if changed:
            pubspec_path.write_text(pubspec, encoding="utf-8")

    @staticmethod
    def _merge_pubspec_fragment(project_dir: Path, fragment: str, log: Logger):
        """Mescla dependências de um pubspec.yaml colado no projeto."""
        deps: dict[str, str] = {}
        in_deps = False
        for line in fragment.split("\n"):
            s = line.strip()
            if s.startswith("dependencies:"):
                in_deps = True
                continue
            if in_deps and s.startswith(("dev_dependencies:", "flutter:")):
                break
            if in_deps:
                m = re.match(r'^(\w[\w_-]*):\s*(\S+)', s)
                if m and m.group(1) not in ("flutter", "sdk"):
                    pkg = ProjectSourceManager.PACKAGE_ALIASES.get(m.group(1), m.group(1))
                    deps[pkg] = m.group(2)

        if deps:
            log.info(f"Mesclando {len(deps)} dependência(s) do pubspec colado...")
            ProjectSourceManager._inject_pubspec_packages(project_dir, deps, log)

    @staticmethod
    def _inject_manifest_permissions(project_dir: Path, perm_lines: list[str], log: Logger):
        """Injeta permissões Android no AndroidManifest.xml."""
        if not perm_lines:
            return
        manifest = project_dir / "android" / "app" / "src" / "main" / "AndroidManifest.xml"
        if not manifest.exists():
            log.warn("AndroidManifest.xml não encontrado — permissões não injetadas")
            return
        content = manifest.read_text(encoding="utf-8")
        added = []
        for line in perm_lines:
            perm = line.strip()
            if not perm.startswith("<uses-permission"):
                continue
            m = re.search(r'android:name="([^"]+)"', perm)
            if not m:
                continue
            name = m.group(1)
            if name in content:
                continue
            content = content.replace(
                "<application",
                f"    {perm}\n    <application",
                1,
            )
            added.append(name)
        if added:
            manifest.write_text(content, encoding="utf-8")
            log.ok(f"Permissões Android injetadas: {', '.join(added)}")

    @staticmethod
    def _resolve_package_aliases(code: str, log: Logger) -> tuple[str, list[str]]:
        """Corrige imports/API de pacotes inexistentes ou renomeados."""
        fixes = []
        for wrong, correct in ProjectSourceManager.PACKAGE_ALIASES.items():
            wrong_imports = [
                f"import 'package:{wrong}/{wrong}.dart';",
                f'import "package:{wrong}/{wrong}.dart";',
            ]
            correct_import = f"import 'package:{correct}/{correct}.dart';"
            for wi in wrong_imports:
                if wi in code:
                    code = code.replace(wi, correct_import)
                    fixes.append(f"{wrong} → {correct} (import)")

            if "MediaStore()" in code or re.search(rf"package:{wrong}/", code):
                code = code.replace("MediaStore()", "OnAudioQuery()")
                oaq = f"import 'package:{correct}/{correct}.dart';"
                if oaq not in code:
                    code = oaq + "\n" + code
                    fixes.append("MediaStore() → OnAudioQuery()")

        if fixes:
            log.ok(f"Aliases de pacotes: {', '.join(fixes)}")
        return code, fixes

    @staticmethod
    def organize_pasted_code(raw: str, log: Logger) -> tuple[str, str | None, list[str]]:
        """
        Pipeline completo de organização antes do flutter create:
        separa arquivos, corrige aliases e aplica fixes estáticos.
        """
        log.info("📂 Organizando código colado...")
        dart, pubspec_frag, manifest = ProjectSourceManager._split_pasted_content(raw, log)
        dart, _ = ProjectSourceManager._resolve_package_aliases(dart, log)
        dart, _ = ProjectSourceManager._apply_static_fixes(dart, log)

        if pubspec_frag:
            log.ok("pubspec.yaml extraído do paste")
        if manifest:
            log.ok(f"AndroidManifest: {len(manifest)} linha(s) extraída(s)")

        non_dart = [l for l in dart.split("\n") if l.strip().startswith(("name:", "<uses-"))]
        if non_dart:
            log.warn("Removendo resíduos não-Dart do main.dart...")
            dart = "\n".join(
                l for l in dart.split("\n")
                if not l.strip().startswith(("name:", "description:", "version:",
                                             "environment:", "dependencies:",
                                             "dev_dependencies:", "<uses-"))
            ).strip()

        return dart, pubspec_frag, manifest

    @staticmethod
    def _detect_and_inject_deps(code: str, project_dir: Path, log: Logger,
                                kb=None):
        """Lê imports do código e injeta dependências no pubspec.yaml."""
        imports = re.findall(r"import\s+'package:([^/]+)/", code)
        imports += re.findall(r'import\s+"package:([^/]+)/', code)
        packages = set(imports) - {"flutter", "flutter_test", "flutter_localizations",
                                    "flutter_app_generated"}

        if not packages:
            log.info("Nenhuma dependência extra detectada no código")
            return

        log.info(f"Dependências detectadas no código: {', '.join(sorted(packages))}")

        pubspec_path = project_dir / "pubspec.yaml"
        pubspec = pubspec_path.read_text(encoding="utf-8")

        added = []
        unknown = []
        for pkg in sorted(packages):
            resolved = ProjectSourceManager.PACKAGE_ALIASES.get(pkg, pkg)
            if resolved != pkg:
                log.info(f"  alias: {pkg} → {resolved}")

            if resolved in pubspec or pkg in pubspec:
                log.info(f"  já presente: {resolved}")
                continue

            # 1. Tenta no KnowledgeBase primeiro
            version = kb.get_package_version(resolved) if kb else None

            # 2. Fallback no dicionário local
            if version is None:
                version = ProjectSourceManager.KNOWN_PACKAGES.get(resolved)

            if version is None and resolved in ProjectSourceManager.KNOWN_PACKAGES:
                continue  # SDK package

            if version:
                pubspec = pubspec.replace(
                    "\nflutter:\n", f"\n  {resolved}: {version}\nflutter:\n", 1)
                added.append(f"{resolved}: {version}")
                if kb:
                    kb.add_package_version(resolved, version)
            else:
                unknown.append(pkg)

        pubspec_path.write_text(pubspec, encoding="utf-8")

        if added:
            log.ok(f"Dependências injetadas no pubspec.yaml: {', '.join(added)}")
        if unknown:
            log.warn(f"Pacotes desconhecidos (versão não mapeada): {', '.join(unknown)}")
            log.warn("  Adicione manualmente ao pubspec.yaml se necessário")

    @staticmethod
    def _analyse_code_issues(code: str, log: Logger) -> list[str]:
        """
        Detecta problemas conhecidos no código antes de compilar.
        Retorna lista de avisos (não bloqueia o build).
        """
        warnings = []

        # just_audio usa LoopMode, não RepeatMode
        if "just_audio" in code and "RepeatMode" in code:
            warnings.append(
                "CONFLITO: 'RepeatMode' encontrado mas just_audio usa 'LoopMode'.\n"
                "  Substitua RepeatMode.off → LoopMode.off\n"
                "            RepeatMode.one → LoopMode.one\n"
                "            RepeatMode.all → LoopMode.all\n"
                "  E importe: import 'package:just_audio/just_audio.dart';\n"
                "  Ref: https://pub.dev/packages/just_audio"
            )

        # AudioPlayer.setUrl foi removido em just_audio >= 0.9
        if "just_audio" in code and ".setUrl(" in code:
            warnings.append(
                "AVISO: 'AudioPlayer.setUrl()' foi removido no just_audio >= 0.9.\n"
                "  Use: await player.setAudioSource(AudioSource.uri(Uri.parse(url)));"
            )

        # shared_preferences: getInt/getString agora são síncronos
        if "shared_preferences" in code and "await prefs.get" in code:
            warnings.append(
                "AVISO: SharedPreferences.getX() é síncrono desde v2.x.\n"
                "  Remova o 'await' de prefs.getInt(), prefs.getString(), etc."
            )

        return warnings

    @staticmethod
    def _apply_static_fixes(code: str, log: Logger) -> tuple[str, list[str]]:
        """
        Aplica correções estáticas conhecidas sem precisar da API Gemini.
        Retorna (código_corrigido, lista_de_correções_aplicadas).
        """
        fixes = []
        original = code

        # just_audio: RepeatMode → LoopMode
        if "just_audio" in code and "RepeatMode" in code:
            code = re.sub(r'\bRepeatMode\.off\b', 'LoopMode.off', code)
            code = re.sub(r'\bRepeatMode\.one\b', 'LoopMode.one', code)
            code = re.sub(r'\bRepeatMode\.all\b', 'LoopMode.all', code)
            # Substitui declaração do tipo
            code = re.sub(r'\bRepeatMode\b(?!\s*\.\s*restart)', 'LoopMode', code)
            # Garante import do just_audio
            if "import 'package:just_audio/just_audio.dart'" not in code:
                code = "import 'package:just_audio/just_audio.dart';\n" + code
            fixes.append("RepeatMode → LoopMode (just_audio)")

        # Corrige switch sem case default para LoopMode (Dart 3 exhaustiveness)
        if "LoopMode" in code and "switch" in code:
            code = ProjectSourceManager._fix_loopmode_switch(code, fixes)

        # Build.VERSION.SDK_INT é Java — substituir por dart:io Platform
        if "Build.VERSION.SDK_INT" in code:
            if "import 'dart:io'" not in code and 'import "dart:io"' not in code:
                code = "import 'dart:io' show Platform;\n" + code
            code = re.sub(
                r'if\s*\(\s*Build\.VERSION\.SDK_INT\s*>=\s*\d+\s*\)\s*\{',
                'if (Platform.isAndroid) {',
                code,
            )
            fixes.append("Build.VERSION.SDK_INT → Platform.isAndroid")

        if code != original:
            log.ok(f"Correções estáticas aplicadas: {', '.join(fixes)}")
        else:
            log.info("Nenhuma correção estática necessária")

        return code, fixes

    @staticmethod
    def _fix_loopmode_switch(code: str, fixes: list) -> str:
        """
        Localiza blocos switch que usam LoopMode e adiciona 'default: break;'
        se não existir. Usa contagem de chaves para capturar o bloco correto.
        """
        lines = code.split("\n")
        result = []
        i = 0
        while i < len(lines):
            line = lines[i]
            # Detecta início de switch
            if re.search(r'\bswitch\s*\(', line):
                # Captura o bloco completo contando chaves
                block_lines = [line]
                depth = line.count("{") - line.count("}")
                j = i + 1
                while j < len(lines) and depth > 0:
                    block_lines.append(lines[j])
                    depth += lines[j].count("{") - lines[j].count("}")
                    j += 1

                block_text = "\n".join(block_lines)

                # Só modifica se o bloco contiver LoopMode e não tiver default
                if "LoopMode" in block_text and "default:" not in block_text:
                    # Insere default antes do último }
                    last_brace = len(block_lines) - 1
                    indent = "        "  # 8 espaços
                    block_lines.insert(last_brace,
                                       f"{indent}default:\n{indent}  break;")
                    fixes.append("Adicionado case default no switch de LoopMode")

                result.extend(block_lines)
                i = j
            else:
                result.append(line)
                i += 1

        return "\n".join(result)

    @staticmethod
    def from_code(code: str, work_dir: Path, flutter_exe: str, log: Logger,
                  kb=None) -> Path:
        dart, pubspec_frag, manifest = ProjectSourceManager.organize_pasted_code(code, log)

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

            deadline = time.time() + 600
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

        if pubspec_frag:
            ProjectSourceManager._merge_pubspec_fragment(project_dir, pubspec_frag, log)
        if manifest:
            ProjectSourceManager._inject_manifest_permissions(project_dir, manifest, log)

        main_dart = project_dir / "lib" / "main.dart"
        content = dart if "void main(" in dart else (
            "import 'package:flutter/material.dart';\n\n" + dart
        )
        main_dart.write_text(content, encoding="utf-8")
        log.ok(f"Projeto criado. main.dart organizado ({len(content)} chars)")

        ProjectSourceManager._detect_and_inject_deps(content, project_dir, log, kb=kb)
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
            raw = r.read()
            if not raw.strip():
                return {}          # 204 No Content — resposta vazia é OK
            return json.loads(raw)

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
                    # CVE-2007-4559: valida path antes de extrair
                    if not name.endswith(".apk"):
                        continue
                    if any(part in ("", "..", ".") or part.startswith("/")
                           for part in Path(name).parts):
                        self.log.warn(f"Path suspeito ignorado no artefato: {name}")
                        continue
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
            # Força UTF-8 na saída do Flutter no Windows
            env["PYTHONIOENCODING"] = "utf-8"
            env["FLUTTER_SUPPRESS_ANALYTICS"] = "true"
            proc = subprocess.Popen(
                cmd, cwd=str(cwd),
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                env=env,
            )
            stdout_lines, stderr_lines = [], []

            def _read(stream, store, level):
                for raw in stream:
                    try:
                        line = raw.decode("utf-8", errors="replace").rstrip()
                    except Exception:
                        line = repr(raw)
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
                self.log.ok("Concluído (exit 0)")
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

    def flutter_cmd_with_errors(self, args: list[str], cwd: Path) -> tuple[bool, list[str]]:
        """Como flutter_cmd mas retorna (sucesso, lista_de_erros)."""
        cmd = [self.flutter] + args
        cmd_str = " ".join(str(c) for c in cmd)
        self.log.info(f"▶ {cmd_str}")
        self.log.info(f"  em: {cwd}")
        all_errors: list[str] = []
        try:
            env = os.environ.copy()
            env["FLUTTER_SUPPRESS_ANALYTICS"] = "true"
            proc = subprocess.Popen(
                cmd, cwd=str(cwd),
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
            stdout_lines, stderr_lines = [], []

            def _read(stream, store, level):
                for raw in stream:
                    try:
                        line = raw.decode("utf-8", errors="replace").rstrip()
                    except Exception:
                        line = repr(raw)
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

            all_errors = [l for l in (stdout_lines + stderr_lines)
                          if "Error:" in l or "error:" in l.lower()
                          or "FAILURE" in l or "failed" in l.lower()]

            if proc.returncode == 0:
                self.log.ok("Concluído (exit 0)")
                return True, []
            else:
                self.log.err(f"Falhou (exit {proc.returncode})")
                return False, all_errors

        except Exception as e:
            self.log.err(f"Exceção: {e}")
            return False, [str(e)]


# ─────────────────────────────────────────────────────────────
#  Main GUI
# ─────────────────────────────────────────────────────────────
class FlutterOrchestratorGUI(ctk.CTk):

    def __init__(self):
        super().__init__()
        self.title("🚀 Flutter Build Orchestrator")
        self.geometry("1200x960")
        self.minsize(1000, 750)
        
        # Configura handler de fechamento para limpeza adequada
        self.protocol("WM_DELETE_WINDOW", self._on_closing)

        self.build_type     = tk.StringVar(value="release")
        self.auto_install   = tk.BooleanVar(value=True)
        self.auto_adb       = tk.BooleanVar(value=True)
        self.github_token   = tk.StringVar()
        self.ci_token       = tk.StringVar()
        self.gemini_key     = tk.StringVar()
        self.folder_path    = tk.StringVar()
        self.github_url     = tk.StringVar()
        self.device_var     = tk.StringVar(value="Nenhum dispositivo")

        self.is_building    = False
        self.last_apk       = None
        self._devices: list[tuple[str,str]] = []
        self._adb_exe: str | None = None
        self.work_dir       = Path(tempfile.mkdtemp(prefix="flutter_orch_"))
        self._checklist: Checklist | None = None
        self.kb: KnowledgeBase | None = None   # iniciado após _build_ui (precisa do Logger)

        self._build_ui()
        self.kb = KnowledgeBase(self.log)      # Logger já existe aqui
        self._poll_adb()
        threading.Thread(target=self._run_checklist, daemon=True).start()

    def _on_closing(self):
        """Handler de fechamento da janela - limpa diretório temporário."""
        try:
            if hasattr(self, 'work_dir') and self.work_dir.exists():
                # Usa print() pois self.log não drena mais após destroy()
                print(f"[shutdown] Limpando diretório temporário: {self.work_dir}")
                shutil.rmtree(self.work_dir, ignore_errors=True)
        except Exception as e:
            print(f"[shutdown] Erro na limpeza: {e}")
        self.destroy()

    # ── UI ──────────────────────────────────────
    def _build_ui(self):
        # ── Painel superior: configurações (fixo, compacto) ──
        top_panel = ctk.CTkFrame(self, fg_color="transparent")
        top_panel.pack(fill="x", padx=6, pady=(6, 0))

        # Header compacto (1 linha)
        hdr = ctk.CTkFrame(top_panel, fg_color="transparent")
        hdr.pack(fill="x")
        ctk.CTkLabel(hdr, text="🚀 Flutter Build Orchestrator",
                     font=ctk.CTkFont(size=18, weight="bold")).pack(side="left")
        ctk.CTkLabel(hdr, text="compile · instale · entregue",
                     font=ctk.CTkFont(size=11), text_color="gray").pack(
                         side="left", padx=8, pady=(2, 0))

        # Status + progresso na mesma linha do header
        self.lbl_status = ctk.CTkLabel(hdr, text="● Pronto", text_color="gray",
                                        font=ctk.CTkFont(size=11))
        self.lbl_status.pack(side="right", padx=8)
        self.progress = ctk.CTkProgressBar(hdr, mode="indeterminate", width=180)
        self.progress.pack(side="right", padx=4)
        self.progress.set(0)

        # Tabs de entrada (altura reduzida)
        self.tabview = ctk.CTkTabview(top_panel, height=170)
        self.tabview.pack(fill="x", pady=(4, 0))
        for tab in ("📋 Colar Código", "📁 Pasta / Diretório", "🔗 Link GitHub"):
            self.tabview.add(tab)
        self._tab_code()
        self._tab_folder()
        self._tab_github()

        # Opções em grid 2x2 compacto
        opts = ctk.CTkFrame(top_panel)
        opts.pack(fill="x", pady=(3, 0))

        # Linha 1: build type + flutter status + botão verificar
        r1 = ctk.CTkFrame(opts, fg_color="transparent")
        r1.pack(fill="x", padx=6, pady=(4, 0))
        ctk.CTkLabel(r1, text="⚙️", width=20).pack(side="left")
        ctk.CTkRadioButton(r1, text="📦 Release", variable=self.build_type,
                           value="release").pack(side="left", padx=6)
        ctk.CTkRadioButton(r1, text="🐛 Debug", variable=self.build_type,
                           value="debug").pack(side="left", padx=6)
        ctk.CTkCheckBox(r1, text="Auto-instalar Flutter",
                        variable=self.auto_install).pack(side="left", padx=10)
        self.lbl_flutter_status = ctk.CTkLabel(
            r1, text="", text_color="gray", font=ctk.CTkFont(size=11))
        self.lbl_flutter_status.pack(side="left", padx=4)
        ctk.CTkButton(r1, text="🔍 Verificar", width=100, height=26,
                      command=lambda: threading.Thread(
                          target=self._run_checklist, daemon=True).start()
                      ).pack(side="right", padx=6)

        # Linha 2: CI + Gemini
        r2 = ctk.CTkFrame(opts, fg_color="transparent")
        r2.pack(fill="x", padx=6, pady=(2, 0))
        ctk.CTkLabel(r2, text="☁️", width=20).pack(side="left")
        self.lbl_ci_mode = ctk.CTkLabel(r2, text="● Aguardando", text_color="gray",
                                         font=ctk.CTkFont(size=11, weight="bold"))
        self.lbl_ci_mode.pack(side="left", padx=(0, 6))
        ctk.CTkLabel(r2, text="CI Token:", text_color="gray",
                     font=ctk.CTkFont(size=11)).pack(side="left")
        ci_entry = ctk.CTkEntry(r2, textvariable=self.ci_token,
                                placeholder_text="ghp_xxx...", show="*", width=200, height=26)
        ci_entry.pack(side="left", padx=4)
        self.lbl_token_status = ctk.CTkLabel(r2, text="⬜", text_color="gray",
                                              font=ctk.CTkFont(size=11))
        self.lbl_token_status.pack(side="left", padx=2)
        ctk.CTkButton(r2, text="✓", width=30, height=26,
                      command=lambda: threading.Thread(
                          target=self._validate_token, daemon=True).start()
                      ).pack(side="left", padx=2)
        ci_entry.bind("<FocusOut>", lambda e: threading.Thread(
            target=self._validate_token, daemon=True).start())

        # Gemini na mesma linha
        ctk.CTkLabel(r2, text="  🤖 Gemini:", text_color="gray",
                     font=ctk.CTkFont(size=11)).pack(side="left", padx=(10, 0))
        gem_entry = ctk.CTkEntry(r2, textvariable=self.gemini_key,
                                  placeholder_text="AIza...", show="*", width=200, height=26)
        gem_entry.pack(side="left", padx=4)
        self.lbl_gemini_status = ctk.CTkLabel(r2, text="⬜", text_color="gray",
                                               font=ctk.CTkFont(size=11))
        self.lbl_gemini_status.pack(side="left", padx=2)
        ctk.CTkButton(r2, text="✓", width=30, height=26,
                      command=lambda: threading.Thread(
                          target=self._validate_gemini_key, daemon=True).start()
                      ).pack(side="left", padx=2)
        gem_entry.bind("<FocusOut>", lambda e: threading.Thread(
            target=self._validate_gemini_key, daemon=True).start())

        # Linha 3: ADB
        r3 = ctk.CTkFrame(opts, fg_color="transparent")
        r3.pack(fill="x", padx=6, pady=(2, 4))
        ctk.CTkLabel(r3, text="📱", width=20).pack(side="left")
        self.lbl_adb_status = ctk.CTkLabel(r3, text="● Sem dispositivo",
                                            text_color="gray",
                                            font=ctk.CTkFont(size=11, weight="bold"))
        self.lbl_adb_status.pack(side="left", padx=(0, 6))
        self.menu_device = ctk.CTkOptionMenu(r3, variable=self.device_var,
                                              values=["Nenhum dispositivo"],
                                              width=200, height=26)
        self.menu_device.pack(side="left", padx=4)
        ctk.CTkButton(r3, text="🔄", width=30, height=26,
                      command=lambda: threading.Thread(
                          target=self._refresh_devices, daemon=True).start()
                      ).pack(side="left", padx=2)
        ctk.CTkCheckBox(r3, text="Instalar auto", variable=self.auto_adb,
                        height=26).pack(side="left", padx=10)
        self.btn_install = ctk.CTkButton(
            r3, text="📲 Instalar", width=110, height=26,
            command=self._manual_install,
            fg_color="#1565C0", hover_color="#0D47A1", state="disabled")
        self.btn_install.pack(side="left", padx=4)

        # Botão build grande
        self.btn_build = ctk.CTkButton(
            top_panel, text="🔨 Iniciar Build", command=self.start_build,
            height=40, font=ctk.CTkFont(size=14, weight="bold"),
            fg_color="#28a745", hover_color="#218838"
        )
        self.btn_build.pack(fill="x", pady=(4, 2))

        # ── Painel inferior: LOG (ocupa todo o resto) ──
        lf = ctk.CTkFrame(self)
        lf.pack(fill="both", expand=True, padx=6, pady=(2, 6))

        log_hdr = ctk.CTkFrame(lf, fg_color="transparent")
        log_hdr.pack(fill="x", padx=6, pady=(4, 2))
        ctk.CTkLabel(log_hdr, text="📋 Log em Tempo Real",
                     font=ctk.CTkFont(size=13, weight="bold")).pack(side="left")
        self.btn_open_output = ctk.CTkButton(
            log_hdr, text="📂 Abrir Pasta do APK", width=170, height=28,
            command=self._open_output_folder, state="disabled",
            fg_color="#1565C0", hover_color="#0D47A1"
        )
        self.btn_open_output.pack(side="right", padx=(4, 0))
        ctk.CTkButton(log_hdr, text="🗑 Limpar", width=80, height=28,
                      command=self._clear_log).pack(side="right")

        self.log_box = ctk.CTkTextbox(
            lf, wrap="word", state="disabled",
            font=ctk.CTkFont(family="Courier New", size=12)
        )
        self.log_box.pack(fill="both", expand=True, padx=4, pady=(0, 4))

        # Inicia o Logger
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

    # ── Helpers UI ──────────────────────────────
    def _validate_gemini_key(self):
        key = self.gemini_key.get().strip()
        if not key:
            self.after(0, lambda: self.lbl_gemini_status.configure(
                text="⬜", text_color="gray"))
            return
        self.after(0, lambda: self.lbl_gemini_status.configure(
            text="🔄", text_color="#ffc107"))
        ok, msg = GeminiCodeFixer.validate_key(key)
        color = "#00cc66" if ok else "#ff4444"
        icon  = "✅" if ok else "❌"
        self.after(0, lambda m=f"{icon} {msg}": self.lbl_gemini_status.configure(
            text=m, text_color=color))
        level = "ok" if ok else "err"
        self.log.put(f"🤖 Gemini: {msg}", level)
    def _open_output_folder(self):
        """Abre a pasta que contém o último APK gerado."""
        if not self.last_apk:
            return
        folder = str(Path(self.last_apk).parent)
        try:
            if platform.system() == "Windows":
                os.startfile(folder)
            elif platform.system() == "Darwin":
                subprocess.Popen(["open", folder])
            else:
                subprocess.Popen(["xdg-open", folder])
        except Exception as e:
            self.log.err(f"Não foi possível abrir a pasta: {e}")

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
        # Mostra estatísticas do cérebro
        if self.kb:
            s = self.kb.stats()
            self.log.info(f"🧠 Cérebro: {s['total_fixes']} fixes conhecidos "
                          f"({s['manual_fixes']} manuais + {s['learned_fixes']} aprendidos) "
                          f"| {s['total_applied']} aplicações | "
                          f"{s['history_count']} erros no histórico")
        cl = Checklist(self.log)
        ok = cl.run()
        self._checklist = cl
        if ok:
            self._set_status("● Ambiente OK — pronto para build", "#00cc66")
            # Atualiza indicador do Flutter
            if cl.flutter_exe:
                self.after(0, lambda: self.lbl_flutter_status.configure(
                    text="✅ Flutter detectado", text_color="#00cc66"))
                # Desativa auto-install visualmente (já tem Flutter)
                self.after(0, lambda: self.auto_install.set(False))
        else:
            self._set_status("● Pré-requisito faltando — veja o log", "#ff4444")
            if not cl.flutter_exe:
                self.after(0, lambda: self.lbl_flutter_status.configure(
                    text="⚠️ não encontrado — auto-install ativo", text_color="#ffc107"))

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

    def _poll_adb(self):
        """Verifica dispositivos a cada 2s em background — detecção automática."""
        threading.Thread(target=self._refresh_devices, daemon=True).start()
        self.after(2000, self._poll_adb)

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

            # Análise prévia do código colado
            if source_type == "code":
                issues = ProjectSourceManager._analyse_code_issues(source_data, self.log)
                if issues:
                    self.log.sep()
                    self.log.warn("⚠️  PROBLEMAS DETECTADOS NO CÓDIGO:")
                    for issue in issues:
                        for line in issue.split("\n"):
                            self.log.warn(f"  {line}")
                    self.log.warn("  O build continuará mas pode falhar por esses motivos.")
                    self.log.sep()

            if source_type == "code":
                project = ProjectSourceManager.from_code(
                    source_data, self.work_dir, cl.flutter_exe, self.log,
                    kb=self.kb)
            elif source_type == "folder":
                project = ProjectSourceManager.from_directory(source_data, self.log)
            else:
                project = ProjectSourceManager.from_github(
                    source_data, self.work_dir,
                    self.github_token.get().strip(), self.log)

            apk = None
            local_ok = False
            build_errors: list[str] = []
            build_flag = "--" + self.build_type.get()  # definido aqui — sempre disponível

            # ── ETAPA 2b: Verificação prévia de compatibilidade de plugins Android ──
            if source_type == "code":
                self.log.sep()
                self.log.info("[2b] 🔍 Verificando compatibilidade de plugins Android...")
                self._set_status("🔍 Verificando compatibilidade de plugins...", "#ff9800")
                
                compatibility_issues = self._check_android_plugin_compatibility(project, self.log)
                if compatibility_issues:
                    self.log.warn(f"🔍 {len(compatibility_issues)} problema(s) de compatibilidade detectado(s):")
                    for issue in compatibility_issues:
                        self.log.warn(f"  - {issue}")
                    self.log.info("🔍 Tentando correções automáticas...")
                    
                    # Tenta corrigir problemas de compatibilidade
                    fixed = self._fix_compatibility_issues(compatibility_issues, project, self.log)
                    if fixed:
                        self.log.ok("🔍 Correções de compatibilidade aplicadas")
                    else:
                        self.log.warn("🔍 Não foi possível corrigir automaticamente — continuando...")

            # ── ETAPA 2c: Verificação de dependências conflitantes ──
            if source_type == "code":
                self.log.sep()
                self.log.info("[2c] 🔍 Verificando dependências conflitantes...")
                self._set_status("🔍 Verificando dependências conflitantes...", "#ff9800")
                
                conflicts = self._check_dependency_conflicts(project, self.log)
                if conflicts:
                    self.log.warn(f"🔍 {len(conflicts)} conflito(s) de dependência detectado(s):")
                    for conflict in conflicts:
                        self.log.warn(f"  - {conflict}")
                    self.log.info("🔍 Tentando resolver conflitos automaticamente...")
                    
                    # Tenta resolver conflitos
                    resolved = self._resolve_dependency_conflicts(conflicts, project, self.log)
                    if resolved:
                        self.log.ok("🔍 Conflitos de dependência resolvidos")
                    else:
                        self.log.warn("🔍 Não foi possível resolver automaticamente — continuando...")

            # ── ETAPA 2d: Verificação de sintaxe do pubspec.yaml ──
            if source_type == "code":
                self.log.sep()
                self.log.info("[2d] 🔍 Verificando sintaxe do pubspec.yaml...")
                self._set_status("🔍 Verificando sintaxe do pubspec.yaml...", "#ff9800")
                
                syntax_errors = self._check_pubspec_syntax(project, self.log)
                if syntax_errors:
                    self.log.warn(f"🔍 {len(syntax_errors)} erro(s) de sintaxe detectado(s):")
                    for error in syntax_errors:
                        self.log.warn(f"  - {error}")
                    self.log.info("🔍 Tentando corrigir erros de sintaxe automaticamente...")
                    
                    # Tenta corrigir erros de sintaxe
                    fixed = self._fix_pubspec_syntax_errors(syntax_errors, project, self.log)
                    if fixed:
                        self.log.ok("🔍 Erros de sintaxe corrigidos")
                    else:
                        self.log.warn("🔍 Não foi possível corrigir automaticamente — continuando...")

            # ── ETAPA 3: Build local ─────────────
            self.log.sep()
            self.log.info("[3/5] Build local...")
            self._set_ci_mode("local")

            try:
                self._set_status("Limpando projeto...", "#ffc107")
                runner.flutter_cmd(["clean"], project, fail_on_error=False)

                self._set_status("Baixando dependências...", "#ffc107")
                # Retry inteligente para pub get com backoff exponencial
                pub_ok = False
                for attempt, wait in enumerate((0, 5, 10, 15)):
                    if wait:
                        self.log.warn(f"📦 pub get falhou — aguardando {wait}s (tentativa {attempt + 1}/4)...")
                        time.sleep(wait)
                    pub_ok = runner.flutter_cmd(["pub", "get"], project)
                    if pub_ok:
                        break
                
                if not pub_ok:
                    self.log.warn("📦 pub get falhou após 4 tentativas — tentando build mesmo assim...")

                self._set_status(f"Compilando APK {self.build_type.get()}...", "#ffc107")
                build_ok, build_errors = runner.flutter_cmd_with_errors(
                    ["build", "apk", build_flag], project)

                if build_ok:
                    apk = self._find_apk(project)
                    if apk:
                        local_ok = True
                        self.log.ok("Build local concluído!")
                    else:
                        self.log.warn("Build terminou mas APK não foi encontrado")
                else:
                    self.log.warn("flutter build apk falhou")

            except Exception as local_err:
                self.log.warn(f"Exceção no build local: {local_err}")

            # ── ETAPA 3a: Correção automática de namespace do Android Gradle Plugin ──
            if not local_ok and build_errors:
                error_text = "\n".join(build_errors)
                if "Namespace not specified" in error_text and "build.gradle" in error_text:
                    self.log.sep()
                    self.log.info("[3a] 🔧 Detectado erro de namespace do Android Gradle Plugin...")
                    self._set_status("🔧 Corrigindo namespace do Android Gradle Plugin...", "#ff9800")
                    
                    if self._fix_android_gradle_namespace_errors(build_errors, project):
                        self.log.ok("🔧 Namespace corrigido — recompilando...")
                        runner.flutter_cmd(["clean"], project, fail_on_error=False)
                        runner.flutter_cmd(["pub", "get"], project)
                        build_ok, build_errors = runner.flutter_cmd_with_errors(
                            ["build", "apk", build_flag], project)
                        if build_ok:
                            apk = self._find_apk(project)
                            if apk:
                                local_ok = True
                                self.log.ok("Build local concluído após correção de namespace!")
                            else:
                                self.log.warn("Build terminou mas APK não foi encontrado")
                        else:
                            self.log.warn("Build ainda falha após correção de namespace")

            # ── ETAPA 3b: KnowledgeBase (grátis, sem API) ──
            if not local_ok and build_errors:
                self.log.sep()
                self.log.info("[3b] 🧠 Consultando KnowledgeBase...")
                self._set_status("🧠 Aplicando fixes conhecidos...", "#9c27b0")
                main_dart = project / "lib" / "main.dart"
                current_code = main_dart.read_text(encoding="utf-8", errors="replace")

                kb_fixed, kb_applied = self.kb.apply(
                    current_code, build_errors, project_dir=project) \
                    if self.kb else (current_code, [])

                if kb_applied:
                    kb_fixed, _ = ProjectSourceManager._resolve_package_aliases(
                        kb_fixed, self.log)
                    main_dart.write_text(kb_fixed, encoding="utf-8")
                    ProjectSourceManager._detect_and_inject_deps(
                        kb_fixed, project, self.log, kb=self.kb)
                    self.log.ok(f"🧠 {len(kb_applied)} fix(es) do cérebro aplicados — recompilando...")
                    runner.flutter_cmd(["clean"], project, fail_on_error=False)
                    runner.flutter_cmd(["pub", "get"], project)
                    build_ok_kb, build_errors = runner.flutter_cmd_with_errors(
                        ["build", "apk", build_flag], project)
                    if build_ok_kb:
                        apk = self._find_apk(project)
                        if apk:
                            local_ok = True
                            self.log.ok("🧠 Build concluído com fixes do cérebro! (sem API)")
                    if not local_ok:
                        self.log.warn("🧠 Fixes do cérebro não resolveram completamente")
                else:
                    self.log.info("🧠 Nenhum fix conhecido para estes erros")

            # ── ETAPA 3c: Gemini (API — só se KB não resolveu) ──
            if not local_ok and source_type == "code" and build_errors:
                gemini_key = self.gemini_key.get().strip()
                if gemini_key:
                    self.log.sep()
                    self.log.info("[3c] 🤖 Consultando Gemini...")
                    self._set_status("🤖 Gemini corrigindo código...", "#9c27b0")

                    main_dart = project / "lib" / "main.dart"
                    current_code = main_dart.read_text(encoding="utf-8", errors="replace")
                    original_code = current_code  # guarda para aprendizado

                    fixer = GeminiCodeFixer(gemini_key, self.log)
                    fixed_code = fixer.fix(current_code, build_errors)

                    if fixed_code:
                        fixed_code, _, _ = ProjectSourceManager.organize_pasted_code(
                            fixed_code, self.log)
                        main_dart.write_text(fixed_code, encoding="utf-8")
                        ProjectSourceManager._detect_and_inject_deps(
                            fixed_code, project, self.log, kb=self.kb)
                        self.log.ok("🤖 Código corrigido pelo Gemini — recompilando...")

                        for line in fixed_code.split("\n"):
                            if "CORREÇÕES" in line or line.strip().startswith("// -"):
                                self.log.info(f"  {line.strip()}")

                        runner.flutter_cmd(["clean"], project, fail_on_error=False)
                        runner.flutter_cmd(["pub", "get"], project)
                        build_ok_gem, _ = runner.flutter_cmd_with_errors(
                            ["build", "apk", build_flag], project)

                        if build_ok_gem:
                            apk = self._find_apk(project)
                            if apk:
                                local_ok = True
                                self.log.ok("🤖 Build concluído após correção do Gemini!")
                                # ── Aprende com o Gemini ──
                                if self.kb:
                                    session_id = datetime.now().strftime("%Y%m%d%H%M%S")
                                    self.kb.learn_from_gemini(
                                        original_code, fixed_code,
                                        build_errors, session_id)
                        if not local_ok:
                            self.log.warn("🤖 Correção do Gemini não resolveu — indo para CI...")
                    else:
                        self.log.warn("🤖 Gemini não retornou correção válida")
                else:
                    # Sem Gemini: mostra erros detalhados
                    self.log.sep()
                    self.log.warn("━━━ ERROS QUE IMPEDEM A COMPILAÇÃO ━━━")
                    self.log.warn("Configure a API Key do Gemini para correção automática")
                    self.log.warn("Ou corrija manualmente os erros abaixo:")
                    self.log.sep()
                    dart_errors = [e for e in build_errors
                                   if "Error:" in e or "error:" in e.lower()]
                    for err in dart_errors[:40]:
                        self.log.err(err)
                    self.log.sep()

            # ── ETAPA 3d: Fallback local agressivo antes do CI ──
            if not local_ok and build_errors:
                self.log.sep()
                self.log.info("[3d] 🔧 Tentando correções locais agressivas antes do CI...")
                self._set_status("🔧 Tentando correções locais agressivas...", "#ff5722")
                
                # Tenta downgrade de Flutter SDK se for problema de versão
                if "Flutter SDK" in "\n".join(build_errors) or "requires Flutter SDK" in "\n".join(build_errors):
                    self.log.info("🔧 Detectado problema de versão do Flutter SDK")
                    # Tenta usar versão estável do Flutter
                    runner.flutter_cmd(["downgrade", "stable"], project, fail_on_error=False)
                    runner.flutter_cmd(["clean"], project, fail_on_error=False)
                    runner.flutter_cmd(["pub", "get"], project)
                    build_ok, build_errors = runner.flutter_cmd_with_errors(
                        ["build", "apk", build_flag], project)
                    if build_ok:
                        apk = self._find_apk(project)
                        if apk:
                            local_ok = True
                            self.log.ok("🔧 Build concluído após downgrade do Flutter SDK!")
                
                # Tenta limpar cache do Flutter se for problema de cache corrompido
                if not local_ok and "cache" in "\n".join(build_errors).lower():
                    self.log.info("🔧 Detectado problema de cache do Flutter")
                    runner.flutter_cmd(["clean"], project, fail_on_error=False)
                    # Limpa cache do pub
                    pub_cache = Path.home() / ".pub-cache"
                    if pub_cache.exists():
                        try:
                            import shutil
                            shutil.rmtree(pub_cache / "hosted" / "pub.dev" / ".cache", ignore_errors=True)
                            self.log.ok("🔧 Cache do pub limpo")
                        except Exception:
                            pass
                    runner.flutter_cmd(["pub", "get"], project)
                    build_ok, build_errors = runner.flutter_cmd_with_errors(
                        ["build", "apk", build_flag], project)
                    if build_ok:
                        apk = self._find_apk(project)
                        if apk:
                            local_ok = True
                            self.log.ok("🔧 Build concluído após limpeza de cache!")

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

                # Garante que o CI recebe código organizado (sem pubspec/manifest no main.dart)
                if source_type == "code":
                    main_dart = project / "lib" / "main.dart"
                    if main_dart.exists():
                        current = main_dart.read_text(encoding="utf-8", errors="replace")
                        organized, pub_frag, man = ProjectSourceManager.organize_pasted_code(
                            current, self.log)
                        main_dart.write_text(organized, encoding="utf-8")
                        if pub_frag:
                            ProjectSourceManager._merge_pubspec_fragment(
                                project, pub_frag, self.log)
                        if man:
                            ProjectSourceManager._inject_manifest_permissions(
                                project, man, self.log)
                        ProjectSourceManager._detect_and_inject_deps(
                            organized, project, self.log, kb=self.kb)
                        self.log.ok("Código reorganizado antes do envio ao CI")

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
            self.after(0, lambda: self.btn_open_output.configure(state="normal"))

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
    def _fix_android_gradle_namespace_errors(build_errors: list[str], project_dir: Path) -> bool:
        """
        Corrige erros de namespace do Android Gradle Plugin em plugins.
        Detecta plugins sem namespace e adiciona automaticamente baseado no AndroidManifest.xml.
        """
        try:
            error_text = "\n".join(build_errors)
            
            # Extrai o caminho do build.gradle problemático do erro
            build_gradle_match = re.search(r'([A-Z]:\\[^:]+\\android\\build\.gradle)', error_text)
            if not build_gradle_match:
                return False
            
            build_gradle_path = Path(build_gradle_match.group(1))
            if not build_gradle_path.exists():
                return False
            
            # Lê o build.gradle atual
            build_gradle_content = build_gradle_path.read_text(encoding="utf-8")
            
            # Verifica se já tem namespace
            if "namespace" in build_gradle_content:
                return False
            
            # Tenta encontrar o AndroidManifest.xml do plugin
            android_manifest_path = build_gradle_path.parent / "src" / "main" / "AndroidManifest.xml"
            if not android_manifest_path.exists():
                return False
            
            # Extrai o package do AndroidManifest.xml
            manifest_content = android_manifest_path.read_text(encoding="utf-8")
            package_match = re.search(r'package="([^"]+)"', manifest_content)
            if not package_match:
                return False
            
            package_name = package_match.group(1)
            
            # Adiciona namespace ao build.gradle
            # Procura pelo bloco android { ... }
            android_block_match = re.search(r'android\s*\{', build_gradle_content)
            if not android_block_match:
                return False
            
            # Insere namespace após o bloco android {
            insert_pos = android_block_match.end()
            new_build_gradle = (
                build_gradle_content[:insert_pos] + 
                f'\n    namespace \'{package_name}\'' +
                build_gradle_content[insert_pos:]
            )
            
            # Escreve o build.gradle corrigido
            build_gradle_path.write_text(new_build_gradle, encoding="utf-8")
            
            return True
            
        except Exception:
            return False

    @staticmethod
    def _check_android_plugin_compatibility(project: Path, log: Logger) -> list[str]:
        """
        Verifica compatibilidade de plugins Android antes do build.
        Detecta plugins conhecidos por terem problemas com versões do Android Gradle Plugin.
        """
        issues = []
        
        try:
            pubspec_path = project / "pubspec.yaml"
            if not pubspec_path.exists():
                return issues
            
            pubspec_content = pubspec_path.read_text(encoding="utf-8")
            
            # Lista de plugins conhecidos com problemas de compatibilidade
            problematic_plugins = {
                "on_audio_query": {
                    "bad_versions": ["^2.9.0", "2.9.0"],
                    "good_version": "^3.0.0",
                    "issue": "Versão 2.9.0 não tem namespace no build.gradle (incompatível com AGP 8.0+)"
                },
                "permission_handler": {
                    "bad_versions": ["^11.3.1", "11.3.1"],
                    "good_version": "^12.0.0",
                    "issue": "Versão 11.3.1 pode ter problemas de compatibilidade com Android 14+"
                },
            }
            
            for plugin, info in problematic_plugins.items():
                # Verifica se o plugin está no pubspec.yaml
                if plugin in pubspec_content:
                    # Extrai a versão atual
                    version_match = re.search(rf'{re.escape(plugin)}:\s*([^\s\n]+)', pubspec_content)
                    if version_match:
                        current_version = version_match.group(1).strip()
                        if current_version in info["bad_versions"]:
                            issues.append(
                                f"{plugin}: {current_version} - {info['issue']}. "
                                f"Recomendado: {info['good_version']}"
                            )
            
            # Verifica se há plugins Android sem namespace no cache local
            pub_cache = Path.home() / ".pub-cache" / "hosted" / "pub.dev"
            if pub_cache.exists():
                for plugin_dir in pub_cache.glob("*_android-*"):
                    build_gradle = plugin_dir / "android" / "build.gradle"
                    if build_gradle.exists():
                        build_gradle_content = build_gradle.read_text(encoding="utf-8")
                        if "namespace" not in build_gradle_content.lower():
                            plugin_name = plugin_dir.name.split("-")[0]
                            issues.append(
                                f"{plugin_name}: Plugin Android não tem namespace no build.gradle. "
                                f"Será corrigido automaticamente durante o build se ocorrer erro."
                            )
        
        except Exception as e:
            log.warn(f"Erro ao verificar compatibilidade de plugins: {e}")
        
        return issues

    @staticmethod
    def _fix_compatibility_issues(issues: list[str], project: Path, log: Logger) -> bool:
        """
        Tenta corrigir problemas de compatibilidade de plugins automaticamente.
        """
        try:
            pubspec_path = project / "pubspec.yaml"
            if not pubspec_path.exists():
                return False
            
            pubspec_content = pubspec_path.read_text(encoding="utf-8")
            modified = False
            
            # Correções conhecidas
            fixes = {
                "on_audio_query: ^2.9.0": "on_audio_query: ^3.0.0",
                "on_audio_query: 2.9.0": "on_audio_query: ^3.0.0",
                "permission_handler: ^11.3.1": "permission_handler: ^12.0.0",
                "permission_handler: 11.3.1": "permission_handler: ^12.0.0",
            }
            
            for issue in issues:
                for old, new in fixes.items():
                    if old in issue and old in pubspec_content:
                        pubspec_content = pubspec_content.replace(old, new)
                        log.ok(f"🔍 Corrigido: {old} → {new}")
                        modified = True
            
            if modified:
                pubspec_path.write_text(pubspec_content, encoding="utf-8")
                return True
        
        except Exception as e:
            log.warn(f"Erro ao corrigir problemas de compatibilidade: {e}")
        
        return False

    @staticmethod
    def _check_dependency_conflicts(project: Path, log: Logger) -> list[str]:
        """
        Verifica conflitos de dependências no pubspec.yaml.
        Detecta pacotes que podem ter conflitos de versão ou incompatibilidades.
        """
        conflicts = []
        
        try:
            pubspec_path = project / "pubspec.yaml"
            if not pubspec_path.exists():
                return conflicts
            
            pubspec_content = pubspec_path.read_text(encoding="utf-8")
            
            # Lista de pacotes conhecidos por terem conflitos
            known_conflicts = {
                "http": ["dio", "get"],  # http e dio/get podem conflitar
                "dio": ["http", "get"],  # dio e http/get podem conflitar
                "get": ["http", "dio"],  # get e http/dio podem conflitar
                "path_provider": ["path"],  # path_provider e path podem conflitar
                "shared_preferences": ["hive", "sqflite"],  # diferentes soluções de persistência
            }
            
            for package, conflicting_packages in known_conflicts.items():
                if package in pubspec_content:
                    for conflicting in conflicting_packages:
                        if conflicting in pubspec_content:
                            conflicts.append(
                                f"Conflito potencial: {package} e {conflicting} podem ter incompatibilidades. "
                                f"Considere usar apenas um deles."
                            )
            
            # Verifica versões muito antigas de pacotes populares
            old_versions = {
                "flutter": "2.0.0",
                "dio": "4.0.0",
                "http": "0.13.0",
                "provider": "5.0.0",
            }
            
            for package, min_version in old_versions.items():
                if package in pubspec_content:
                    version_match = re.search(rf'{re.escape(package)}:\s*([^\s\n]+)', pubspec_content)
                    if version_match:
                        current_version = version_match.group(1).strip().replace("^", "").replace(">=", "")
                        try:
                            # Comparação simples de versões
                            if current_version < min_version:
                                conflicts.append(
                                    f"{package}: versão {current_version} é muito antiga. "
                                    f"Recomendado: >= {min_version}"
                                )
                        except Exception:
                            pass  # Falha na comparação de versão, ignora
        
        except Exception as e:
            log.warn(f"Erro ao verificar conflitos de dependências: {e}")
        
        return conflicts

    @staticmethod
    def _resolve_dependency_conflicts(conflicts: list[str], project: Path, log: Logger) -> bool:
        """
        Tenta resolver conflitos de dependências automaticamente.
        """
        try:
            pubspec_path = project / "pubspec.yaml"
            if not pubspec_path.exists():
                return False
            
            pubspec_content = pubspec_path.read_text(encoding="utf-8")
            modified = False
            
            # Resoluções conhecidas
            resolutions = {
                # Remove http se dio estiver presente (dio é mais moderno)
                ("http", "dio"): lambda content: re.sub(r'http:\s*[^\n]+\n', '', content),
                # Remove dio se http estiver presente (http é mais simples)
                ("dio", "http"): lambda content: re.sub(r'dio:\s*[^\n]+\n', '', content),
            }
            
            for conflict in conflicts:
                for (pkg1, pkg2), resolver in resolutions.items():
                    if pkg1 in conflict and pkg2 in conflict:
                        if pkg1 in pubspec_content and pkg2 in pubspec_content:
                            pubspec_content = resolver(pubspec_content)
                            log.ok(f"🔍 Removido {pkg1} para resolver conflito com {pkg2}")
                            modified = True
            
            if modified:
                pubspec_path.write_text(pubspec_content, encoding="utf-8")
                return True
        
        except Exception as e:
            log.warn(f"Erro ao resolver conflitos de dependências: {e}")
        
        return False

    @staticmethod
    def _check_pubspec_syntax(project: Path, log: Logger) -> list[str]:
        """
        Verifica erros de sintaxe no pubspec.yaml.
        Detecta nomes de pacotes inválidos, espaços extras, etc.
        """
        errors = []
        
        try:
            pubspec_path = project / "pubspec.yaml"
            if not pubspec_path.exists():
                return errors
            
            pubspec_content = pubspec_path.read_text(encoding="utf-8")
            lines = pubspec_content.split("\n")
            
            for i, line in enumerate(lines, 1):
                # Detecta espaços extras em nomes de pacotes
                if ":" in line and not line.strip().startswith("#"):
                    # Verifica se há espaços extras antes dos dois pontos
                    package_part = line.split(":")[0].strip()
                    if "  " in package_part:
                        errors.append(f"Linha {i}: Espaços extras no nome do pacote: '{package_part}'")
                    
                    # Detecta nomes de pacotes com caracteres inválidos
                    if package_part and not package_part.replace("_", "").replace("-", "").isalnum():
                        errors.append(f"Linha {i}: Nome de pacote inválido: '{package_part}'")
                
                # Detecta linhas com espaços extras no início (indentação incorreta)
                if line.startswith("  ") and not line.startswith("    "):
                    # Verifica se não está dentro de um bloco
                    if "dependencies:" not in lines[max(0, i-2):i]:
                        errors.append(f"Linha {i}: Indentação incorreta: '{line[:20]}...'")
            
            # Verifica se há linhas com nomes de pacotes corrompidos (como "just_au  on_audio_query")
            for i, line in enumerate(lines, 1):
                if re.search(r'\w+\s{2,}\w+:', line):
                    errors.append(f"Linha {i}: Nome de pacote corrompido com espaços extras: '{line.strip()}'")
        
        except Exception as e:
            log.warn(f"Erro ao verificar sintaxe do pubspec.yaml: {e}")
        
        return errors

    @staticmethod
    def _fix_pubspec_syntax_errors(errors: list[str], project: Path, log: Logger) -> bool:
        """
        Tenta corrigir erros de sintaxe no pubspec.yaml automaticamente.
        """
        try:
            pubspec_path = project / "pubspec.yaml"
            if not pubspec_path.exists():
                return False
            
            pubspec_content = pubspec_path.read_text(encoding="utf-8")
            modified = False
            
            # Corrige nomes de pacotes com espaços extras (ex: "just_au  on_audio_query" -> "on_audio_query")
            # O padrão detecta algo como "palavra1  palavra2:" e mantém apenas a segunda parte
            def fix_corrupted_package(match):
                full_match = match.group(0)
                # Se houver espaços extras, mantém apenas a última parte antes dos dois pontos
                if "  " in full_match:
                    parts = full_match.split(":")[0].split()
                    if len(parts) > 1:
                        # Mantém apenas a última parte que parece ser o nome real do pacote
                        return f"  {parts[-1]}: {match.group(1)}"
                return full_match
            
            # Aplica correção para padrões como "just_au  on_audio_query: ^3.0.0"
            pubspec_content = re.sub(r'(\w+\s{2,}\w+):\s*([^\n]+)', fix_corrupted_package, pubspec_content)
            if pubspec_content != pubspec_path.read_text(encoding="utf-8"):
                modified = True
                log.ok("🔍 Corrigidos nomes de pacotes com espaços extras")
            
            # Remove espaços extras no início de linhas
            lines = pubspec_content.split("\n")
            fixed_lines = []
            for line in lines:
                if line.startswith("  ") and not line.startswith("    ") and ":" in line:
                    # Remove espaços extras, mantendo apenas 2 espaços
                    fixed_lines.append("  " + line.lstrip())
                    modified = True
                else:
                    fixed_lines.append(line)
            
            if modified:
                pubspec_path.write_text("\n".join(fixed_lines), encoding="utf-8")
                return True
        
        except Exception as e:
            log.warn(f"Erro ao corrigir sintaxe do pubspec.yaml: {e}")
        
        return False

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
