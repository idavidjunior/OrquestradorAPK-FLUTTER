#!/usr/bin/env python3
"""ProjectSourceManager — gerencia c\u00f3digo fonte, pubspec e permiss\u00f5es."""

import re
from pathlib import Path


class ProjectSourceManager:
    """Gerencia c\u00f3digo fonte colado, separa\u00e7\u00e3o de arquivos e inje\u00e7\u00e3o de depend\u00eancias."""

    PACKAGE_ALIASES = {
        "media_store": "on_audio_query",
    }

    @staticmethod
    def validate_and_fix_pubspec(project_dir, log):
        """
        Valida e corrige erros de sintaxe no pubspec.yaml.
        Returns True if valid, False if corrections were needed.
        """
        pubspec_path = project_dir / "pubspec.yaml"
        if not pubspec_path.exists():
            log.err("pubspec.yaml n\u00e3o encontrado")
            return False

        try:
            content = pubspec_path.read_text(encoding="utf-8")
        except Exception as e:
            log.err(f"N\u00e3o foi poss\u00edvel ler pubspec.yaml: {e}")
            return False

        fixed = False
        lines = content.split("\n")
        new_lines = []

        # Corre\u00e7\u00e3o 1: quebrar linhas mescladas
        merged_pattern = r"^(\s*)(\w+):\s*([^\n]+?)\s+(\w+):\s*(.*)$"
        for i, line in enumerate(lines):
            match = re.match(merged_pattern, line)
            if match and not line.strip().startswith("#"):
                indent, key1, val1, key2, val2 = match.groups()
                if key1 in ["version", "sdk", "environment", "dependencies", "flutter"] or \
                   key2 in ["version", "sdk", "environment", "dependencies", "flutter"]:
                    log.warn(f"Linha {i+1} mesclada: separando '{key1}' e '{key2}'")
                    new_lines.append(f"{indent}{key1}: {val1.strip()}")
                    new_lines.append(f"{indent}{key2}: {val2.strip()}")
                    fixed = True
                else:
                    new_lines.append(line)
            else:
                new_lines.append(line)

        content = "\n".join(new_lines)

        # Corre\u00e7\u00e3o 2: espa\u00e7os extras em nomes de pacotes
        pkg_pattern = r"^(\s+)([\w_]+)\s+([\w_]+):\s*(.*)$"
        new_lines = []
        for line in content.split("\n"):
            match = re.match(pkg_pattern, line)
            if match and not line.strip().startswith("#"):
                indent, pkg1, pkg2, version = match.groups()
                log.warn(f"Pacote com espa\u00e7o extra: '{pkg1}  {pkg2}' -> '{pkg2}'")
                new_lines.append(f"{indent}{pkg2}: {version}")
                fixed = True
            else:
                new_lines.append(line)

        content = "\n".join(new_lines)

        # Corre\u00e7\u00e3o 3: tabs para espa\u00e7os
        if "\t" in content:
            content = content.replace("\t", "  ")
            fixed = True

        if fixed:
            log.ok("Corre\u00e7\u00f5es aplicadas ao pubspec.yaml")
            try:
                pubspec_path.write_text(content, encoding="utf-8")
            except Exception as e:
                log.err(f"N\u00e3o foi poss\u00edvel salvar pubspec.yaml corrigido: {e}")
                return False

        # Valida\u00e7\u00e3o final com PyYAML se dispon\u00edvel
        try:
            import yaml
            yaml.safe_load(content)
            log.ok("pubspec.yaml \u00e9 sintaticamente v\u00e1lido")
            return True
        except ImportError:
            return True
        except yaml.YAMLError as e:
            log.err(f"Erro de sintaxe YAML persistente: {e}")
            return False

    @staticmethod
    def organize_pasted_code(raw, log):
        """Organiza c\u00f3digo colado, separando Dart, YAML e XML."""
        log.info("Organizando c\u00f3digo colado...")
        dart, pubspec_frag, manifest = ProjectSourceManager._split_pasted_content(
            raw, log
        )
        dart, _ = ProjectSourceManager._resolve_package_aliases(dart, log)
        dart, _ = ProjectSourceManager._apply_static_fixes(dart, log)

        non_dart = [
            l for l in dart.split("\n")
            if l.strip().startswith(("name:", "<uses-"))
        ]
        if non_dart:
            dart = "\n".join(
                l for l in dart.split("\n")
                if not l.strip().startswith((
                    "name:", "description:", "version:",
                    "environment:", "dependencies:", "dev_dependencies:", "<uses-"
                ))
            ).strip()

        return dart, pubspec_frag, manifest

    @staticmethod
    def _split_pasted_content(raw, log):
        """Separa c\u00f3digo colado em Dart, YAML e XML."""
        lines = raw.split("\n")
        dart_lines = []
        pubspec_lines = []
        manifest_lines = []
        i = 0

        while i < len(lines):
            line = lines[i]
            stripped = line.strip()

            if not pubspec_lines and re.match(r"^name:\s*\S", stripped):
                window = "\n".join(lines[i:min(i + 20, len(lines))])
                if re.search(
                    r"^(environment:|dependencies:|version:)", window, re.M
                ):
                    log.info("Detectado pubspec.yaml embutido \u2014 separando...")
                    while i < len(lines):
                        cur = lines[i]
                        if re.match(
                            r"^<(uses-permission|manifest|application|/manifest)\b",
                            cur.strip()
                        ):
                            break
                        pubspec_lines.append(cur)
                        i += 1
                    continue

            if re.match(r"^<(uses-permission|manifest|application|/manifest)\b", stripped):
                log.info("Detectado AndroidManifest embutido \u2014 separando...")
                while i < len(lines):
                    cur = lines[i]
                    cur_s = cur.strip()
                    if re.match(
                        r"^<(uses-permission|manifest|application|/manifest)\b", cur_s
                    ) or cur_s.startswith("</manifest"):
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
    def _resolve_package_aliases(code, log):
        """Corrige imports de pacotes inexistentes ou renomeados."""
        fixes = []
        for wrong, correct in ProjectSourceManager.PACKAGE_ALIASES.items():
            for q in ["'", '"']:
                wrong_import = f"import {q}package:{wrong}/{wrong}.dart{q};"
                correct_import = f"import {q}package:{correct}/{correct}.dart{q};"
                if wrong_import in code:
                    code = code.replace(wrong_import, correct_import)
                    fixes.append(f"{wrong} \u2192 {correct} (import)")

            if "MediaStore()" in code:
                code = code.replace("MediaStore()", "OnAudioQuery()")
                oaq = f"import 'package:{correct}/{correct}.dart';"
                if oaq not in code:
                    code = oaq + "\n" + code
                    fixes.append("MediaStore() \u2192 OnAudioQuery()")

        if fixes:
            log.ok(f"Aliases: {', '.join(fixes)}")
        return code, fixes

    @staticmethod
    def _apply_static_fixes(code, log):
        """Aplica corre\u00e7\u00f5es est\u00e1ticas adicionais ao c\u00f3digo Dart."""
        fixes = []

        # Case 1: RepeatMode -> LoopMode (just_audio)
        if "RepeatMode" in code and "just_audio" in code:
            code = code.replace("RepeatMode.off", "LoopMode.off")
            code = code.replace("RepeatMode.one", "LoopMode.one")
            code = code.replace("RepeatMode.all", "LoopMode.all")
            code = code.replace("RepeatMode.restart", "LoopMode.restart")
            code = code.replace("RepeatMode", "LoopMode")
            imp = "import 'package:just_audio/just_audio.dart';"
            if imp not in code:
                code = imp + "\n" + code
            fixes.append("RepeatMode \u2192 LoopMode")

        # Case 2: Build.VERSION.SDK_INT
        if "Build.VERSION.SDK_INT" in code:
            code = code.replace(
                "Build.VERSION.SDK_INT",
                "// Build.VERSION.SDK_INT substitu\u00eddo"
            )
            fixes.append("Build.VERSION.SDK_INT \u2192 alternativa Dart")

        if fixes:
            log.ok(f"Fixes est\u00e1ticos: {'; '.join(fixes)}")
        return code, fixes

    @staticmethod
    def code_fragments(raw_code, log):
        """
        Algoritmo inteligente para separar Dart, YAML e XML colados juntos.
        """
        result = {
            "dart": "",
            "pubspec_yaml": None,
            "android_manifest": None,
            "other_files": [],
        }
        lines = raw_code.split("\n")
        current_fragment = []
        current_type = "dart"

        i = 0
        while i < len(lines):
            line = lines[i]
            stripped = line.strip()

            if stripped.startswith("name:") and ":" in stripped:
                if ";" not in line and "=" not in line:
                    if current_fragment and current_type == "dart":
                        result["dart"] = "\n".join(current_fragment)
                        current_fragment = []
                    current_type = "pubspec"
                    current_fragment = [line]
                    log.info("Detectado bloco pubspec.yaml")
                    i += 1
                    continue

            if "<manifest" in stripped or '<?xml' in stripped:
                if current_fragment and current_type == "dart":
                    result["dart"] = "\n".join(current_fragment)
                elif current_fragment and current_type == "pubspec":
                    result["pubspec_yaml"] = "\n".join(current_fragment)
                current_fragment = [line]
                current_type = "android_manifest"
                log.info("Detectado bloco AndroidManifest.xml")
                i += 1
                continue

            if current_type == "pubspec":
                if stripped.startswith(("import ", "class ", "void main")):
                    result["pubspec_yaml"] = "\n".join(current_fragment)
                    current_fragment = [line]
                    current_type = "dart"
                    i += 1
                    continue

            if current_type == "android_manifest":
                if "</manifest>" in line:
                    current_fragment.append(line)
                    result["android_manifest"] = "\n".join(current_fragment)
                    current_fragment = []
                    current_type = "dart"
                    i += 1
                    continue

            current_fragment.append(line)
            i += 1

        if current_fragment:
            if current_type == "dart":
                result["dart"] = "\n".join(current_fragment)
            elif current_type == "pubspec":
                result["pubspec_yaml"] = "\n".join(current_fragment)
            elif current_type == "android_manifest":
                result["android_manifest"] = "\n".join(current_fragment)

        dart_len = len(result["dart"].split("\n")) if result["dart"] else 0
        yaml_len = len(result["pubspec_yaml"].split("\n")) if result["pubspec_yaml"] else 0
        xml_len = len(result["android_manifest"].split("\n")) if result["android_manifest"] else 0
        log.info(
            f"An\u00e1lise: {dart_len} linhas Dart, "
            f"{yaml_len} YAML, {xml_len} XML"
        )
        return result

    @staticmethod
    def inject_deps(code, project_dir, log, kb=None):
        """Detecta imports no c\u00f3digo e injeta depend\u00eancias no pubspec.yaml."""
        imports = re.findall(r"import\s+'package:([^/]+)/", code)
        imports += re.findall(r'import\s+"package:([^/]+)/', code)
        packages = set(imports) - {
            "flutter", "flutter_test", "flutter_localizations", "flutter_app_generated"
        }
        if not packages:
            log.info("Nenhuma depend\u00eancia extra detectada no c\u00f3digo")
            return

        log.info(f"Depend\u00eancias detectadas: {', '.join(sorted(packages))}")
        pubspec_path = project_dir / "pubspec.yaml"
        pubspec = pubspec_path.read_text(encoding="utf-8")
        added = []

        for pkg in sorted(packages):
            resolved = ProjectSourceManager.PACKAGE_ALIASES.get(pkg, pkg)
            if resolved in pubspec or pkg in pubspec:
                log.info(f"  j\u00e1 presente: {resolved}")
                continue

            version = None
            if kb:
                version = kb.get_package_version(resolved)
            if not version:
                version = "^1.0.0"

            if "\nflutter:\n" in pubspec:
                pubspec = pubspec.replace(
                    "\nflutter:\n", f"\n  {resolved}: {version}\nflutter:\n", 1
                )
            else:
                pubspec += f"\n  {resolved}: {version}\n"
            added.append(f"{resolved}: {version}")

        if added:
            pubspec_path.write_text(pubspec, encoding="utf-8")
            log.ok(f"Depend\u00eancias injetadas: {', '.join(added)}")

    @staticmethod
    def inject_permissions(project_dir, perm_lines, log):
        """Injeta permiss\u00f5es Android no AndroidManifest.xml."""
        if not perm_lines:
            return
        manifest = (
            project_dir / "android" / "app" / "src" / "main" / "AndroidManifest.xml"
        )
        if not manifest.exists():
            log.warn("AndroidManifest.xml n\u00e3o encontrado")
            return
        content = manifest.read_text(encoding="utf-8")
        added = []
        for line in perm_lines:
            perm = line.strip()
            if not perm.startswith("<uses-permission"):
                continue
            match = re.search(r'android:name="([^"]+)"', perm)
            if not match:
                continue
            name = match.group(1)
            if name in content:
                continue
            content = content.replace("<application", f"    {perm}\n    <application", 1)
            added.append(name)
        if added:
            manifest.write_text(content, encoding="utf-8")
            log.ok(f"Permiss\u00f5es injetadas: {', '.join(added)}")
