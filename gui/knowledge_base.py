#!/usr/bin/env python3
"""
KnowledgeBase — c\u00e9rebro que aprende com erros anteriores.
Carrega known_fixes.json, aplica corre\u00e7\u00f5es conhecidas ao c\u00f3digo,
e aprende novos erros resolvidos salvando padr\u00f5es no JSON.
"""

import json
import re
from datetime import datetime
from pathlib import Path


class KnowledgeBase:
    """
    Gerencia corre\u00e7\u00f5es conhecidas para erros comuns de compila\u00e7\u00e3o Flutter.
    """

    DEFAULT_PATH = Path(__file__).parent.parent / "known_fixes.json"

    def __init__(self, log, path=None):
        self.log = log
        self.path = path or self.DEFAULT_PATH
        self._db = {}
        self._load()

    def _load(self):
        try:
            if self.path.exists():
                self._db = json.loads(self.path.read_text(encoding="utf-8"))
                fixes = len(self._db.get("fixes", []))
                total = self._db.get("_meta", {}).get("total_fixes_applied", 0)
                self.log.ok(
                    f"KnowledgeBase: {fixes} corre\u00e7\u00f5es conhecidas "
                    f"({total} aplica\u00e7\u00f5es)"
                )
            else:
                self.log.warn("known_fixes.json n\u00e3o encontrado \u2014 iniciando vazio")
                self._db = {
                    "_meta": {}, "fixes": [], "package_versions": {}, "error_history": []
                }
        except Exception as e:
            self.log.err(f"Erro ao carregar KnowledgeBase: {e}")
            self._db = {
                "_meta": {}, "fixes": [], "package_versions": {}, "error_history": []
            }

    def _save(self):
        try:
            self._db["_meta"]["last_updated"] = datetime.now().strftime("%Y-%m-%d")
            self.path.write_text(
                json.dumps(self._db, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
        except Exception as e:
            self.log.err(f"Erro ao salvar KnowledgeBase: {e}")

    def apply(self, code, errors, project_dir=None):
        applied = []
        error_text = "\n".join(errors)

        for fix in self._db.get("fixes", []):
            fix_id = fix.get("id", "?")
            error_match = any(
                pat.lower() in error_text.lower()
                for pat in fix.get("error_patterns", [])
            )
            context_match = all(
                pat in code for pat in fix.get("context_patterns", [])
            )
            if not (error_match and context_match):
                continue

            fix_type = fix.get("type", "")
            desc = fix.get("description", fix_id)
            changed = False

            if fix_type == "regex_replace":
                for op in fix.get("operations", []):
                    new_code = re.sub(op["find"], op["replace"], code)
                    if new_code != code:
                        code = new_code
                        changed = True
                for imp in fix.get("ensure_imports", []):
                    if imp not in code:
                        code = imp + "\n" + code
                        changed = True

            elif fix_type == "import_replace":
                for op in fix.get("operations", []):
                    if op["find"] in code:
                        code = code.replace(op["find"], op["replace"])
                        changed = True
                pubspec_replace = fix.get("pubspec_replace", {})
                if pubspec_replace and changed and project_dir:
                    self._inject_pubspec(project_dir, pubspec_replace)

            elif fix_type == "pubspec_inject":
                changed = True
                if project_dir:
                    self._detect_and_inject_deps(code, project_dir)

            elif fix_type == "info_only":
                hint = fix.get("fix_hint", "")
                if hint:
                    self.log.warn(f"[{fix_id}] {desc}")
                    self.log.warn(f"   {hint}")

            elif fix_type == "add_default_case":
                def _add_default(m):
                    block = m.group(0)
                    if "default:" not in block:
                        block = block.rstrip("}").rstrip() + (
                            "\n        default:\n          break;\n      }"
                        )
                    return block
                new_code = re.sub(
                    r"switch\s*\(\w+\)\s*\{[^}]+LoopMode[^}]+\}",
                    _add_default, code, flags=re.DOTALL
                )
                if new_code != code:
                    code = new_code
                    changed = True

            elif fix_type == "android_gradle_fix":
                if project_dir:
                    changed = self._fix_android_gradle_namespace(
                        project_dir, errors, self.log
                    )

            elif fix_type == "pubspec_fix":
                if project_dir:
                    from .project_source import ProjectSourceManager
                    try:
                        result = ProjectSourceManager.validate_and_fix_pubspec(
                            project_dir, self.log
                        )
                        changed = not result
                    except Exception as e:
                        self.log.warn(f"pubspec_fix falhou: {e}")

            if changed and fix_type != "info_only":
                applied.append(desc)
                fix["times_applied"] = fix.get("times_applied", 0) + 1
                self.log.ok(f"[{fix_id}] Corre\u00e7\u00e3o aplicada: {desc}")

        if applied:
            meta = self._db.setdefault("_meta", {})
            meta["total_fixes_applied"] = (
                meta.get("total_fixes_applied", 0) + len(applied)
            )
            self._save()

        return code, applied

    def learn_from_gemini(self, original_code, fixed_code, errors, session_id):
        try:
            corrections = []
            for line in fixed_code.split("\n"):
                line = line.strip()
                if line.startswith("// -") and "CORRE\u00c7\u00d5ES" not in line:
                    corrections.append(line[4:].strip())

            if not corrections:
                return

            entry = {
                "session_id": session_id,
                "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "errors": errors[:10],
                "corrections": corrections,
                "status": "gemini_resolved"
            }
            self._db.setdefault("error_history", []).append(entry)

            orig_lines = set(original_code.split("\n"))
            fixed_lines = set(fixed_code.split("\n"))
            removed = orig_lines - fixed_lines
            added = fixed_lines - orig_lines

            if removed and added and len(removed) <= 5:
                new_fix = {
                    "id": f"gemini_{session_id}",
                    "description": (
                        corrections[0] if corrections else "Fix aprendido do Gemini"
                    ),
                    "error_patterns": [e[:80] for e in errors[:3]],
                    "context_patterns": [],
                    "type": "info_only",
                    "operations": [],
                    "fix_hint": (
                        f"Gemini corrigiu: {'; '.join(corrections[:2])}"
                    ),
                    "removed_lines": list(removed)[:5],
                    "added_lines": list(added)[:5],
                    "explanation": (
                        f"Aprendido do Gemini em {entry['date']}"
                    ),
                    "times_applied": 0,
                    "source": "gemini"
                }
                self._db.setdefault("fixes", []).append(new_fix)
                self.log.ok(
                    f"Novo fix aprendido do Gemini: '{new_fix['description']}'"
                )

            self._save()
        except Exception as e:
            self.log.warn(f"N\u00e3o foi poss\u00edvel aprender deste fix: {e}")

    def get_package_version(self, pkg):
        return self._db.get("package_versions", {}).get(pkg)

    def add_package_version(self, pkg, version):
        pv = self._db.setdefault("package_versions", {})
        if pkg not in pv:
            pv[pkg] = version
            self.log.info(f"Novo pacote aprendido: {pkg}: {version}")
            self._save()

    def _fix_android_gradle_namespace(self, project_dir, errors, log):
        try:
            error_text = "\n".join(errors)
            match = re.search(
                r'([A-Z]:\\[^:]+\\android\\build\.gradle)', error_text
            )
            if not match:
                log.warn("N\u00e3o foi poss\u00edvel extrair caminho do build.gradle")
                return False

            build_gradle_path = Path(match.group(1))
            if not build_gradle_path.exists():
                return False

            content = build_gradle_path.read_text(encoding="utf-8")
            if "namespace" in content:
                return False

            manifest_path = (
                build_gradle_path.parent / "src" / "main" / "AndroidManifest.xml"
            )
            if not manifest_path.exists():
                return False

            manifest = manifest_path.read_text(encoding="utf-8")
            package_match = re.search(r'package="([^"]+)"', manifest)
            if not package_match:
                return False

            package_name = package_match.group(1)
            android_match = re.search(r"android\s*\{", content)
            if not android_match:
                return False

            insert_pos = android_match.end()
            new_content = (
                content[:insert_pos]
                + f"\n    namespace '{package_name}'"
                + content[insert_pos:]
            )
            build_gradle_path.write_text(new_content, encoding="utf-8")
            log.ok(f"Namespace adicionado ao build.gradle: {package_name}")
            return True

        except Exception as e:
            log.err(f"Erro ao corrigir namespace: {e}")
            return False

    def _inject_pubspec(self, project_dir, replace_map):
        """Injeta substitui\u00e7\u00f5es de pacotes no pubspec.yaml."""
        pubspec_path = project_dir / "pubspec.yaml"
        if not pubspec_path.exists():
            return
        pubspec = pubspec_path.read_text(encoding="utf-8")
        changed = False
        for old_pkg, new_entry in replace_map.items():
            if re.search(rf"^\s*{re.escape(old_pkg)}:", pubspec, re.M):
                pubspec = re.sub(
                    rf"^\s*{re.escape(old_pkg)}:.*$",
                    f"  {new_entry}",
                    pubspec, count=1, flags=re.M,
                )
                changed = True
                self.log.ok(f"pubspec: {old_pkg} \u2192 {new_entry}")
        if changed:
            pubspec_path.write_text(pubspec, encoding="utf-8")

    def _detect_and_inject_deps(self, code, project_dir):
        """Detecta imports e injeta depend\u00eancias no pubspec.yaml."""
        imports = re.findall(r"import\s+'package:([^/]+)/", code)
        imports += re.findall(r'import\s+"package:([^/]+)/', code)
        packages = set(imports) - {
            "flutter", "flutter_test", "flutter_localizations",
            "flutter_app_generated"
        }
        if not packages:
            return

        pubspec_path = project_dir / "pubspec.yaml"
        pubspec = pubspec_path.read_text(encoding="utf-8")
        added = []
        for pkg in sorted(packages):
            if pkg in pubspec:
                continue
            version = self.get_package_version(pkg) or "^1.0.0"
            if "\nflutter:\n" in pubspec:
                pubspec = pubspec.replace(
                    "\nflutter:\n", f"\n  {pkg}: {version}\nflutter:\n", 1
                )
            else:
                pubspec += f"\n  {pkg}: {version}\n"
            added.append(pkg)

        if added:
            pubspec_path.write_text(pubspec, encoding="utf-8")
            self.log.ok(f"Depend\u00eancias injetadas: {', '.join(added)}")

    def stats(self):
        meta = self._db.get("_meta", {})
        fixes = self._db.get("fixes", [])
        hist = self._db.get("error_history", [])
        manual = sum(1 for f in fixes if f.get("source") == "manual")
        learned = sum(1 for f in fixes if f.get("source") == "gemini")
        return {
            "total_fixes": len(fixes),
            "manual_fixes": manual,
            "learned_fixes": learned,
            "total_applied": meta.get("total_fixes_applied", 0),
            "history_count": len(hist),
        }
