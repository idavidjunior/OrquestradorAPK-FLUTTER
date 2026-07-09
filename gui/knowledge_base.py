#!/usr/bin/env python3
"""
KnowledgeBase — cérebro que aprende com erros anteriores.
Carrega known_fixes.json, aplica correções conhecidas ao código,
e aprende novos erros resolvidos salvando padrões no JSON.
"""

import json
import re
from datetime import datetime
from pathlib import Path


class KnowledgeBase:
    """
    Gerencia correções conhecidas para erros comuns de compilação Flutter.
    """

    DEFAULT_PATH = Path(__file__).parent.parent / "known_fixes.json"

    # Templates de boilerplate para injeção estrutural
    TEMPLATES = {
        "minimal_main": (
            "import 'package:flutter/material.dart';\n"
            "\n"
            "void main() => runApp(const MyApp());\n"
            "\n"
            "class MyApp extends StatelessWidget {\n"
            "  const MyApp({super.key});\n"
            "\n"
            "  @override\n"
            "  Widget build(BuildContext context) {\n"
            "    return MaterialApp(\n"
            "      title: 'Flutter App',\n"
            "      theme: ThemeData(\n"
            "        colorSchemeSeed: Colors.blue,\n"
            "        useMaterial3: true,\n"
            "      ),\n"
            "      home: const MyHomePage(),\n"
            "    );\n"
            "  }\n"
            "}\n"
            "\n"
            "class MyHomePage extends StatelessWidget {\n"
            "  const MyHomePage({super.key});\n"
            "\n"
            "  @override\n"
            "  Widget build(BuildContext context) {\n"
            "    return Scaffold(\n"
            "      appBar: AppBar(title: const Text('Home')),\n"
            "      body: const Center(child: Text('Hello World')),\n"
            "    );\n"
            "  }\n"
            "}\n"
        ),
        "stateful_widget_skeleton": (
            "class MyWidget extends StatefulWidget {\n"
            "  const MyWidget({super.key});\n"
            "\n"
            "  @override\n"
            "  State<MyWidget> createState() => _MyWidgetState();\n"
            "}\n"
            "\n"
            "class _MyWidgetState extends State<MyWidget> {\n"
            "  @override\n"
            "  Widget build(BuildContext context) {\n"
            "    return Container();\n"
            "  }\n"
            "}\n"
        ),
        "material_app_scaffold": (
            "    return MaterialApp(\n"
            "      title: 'Flutter App',\n"
            "      theme: ThemeData(\n"
            "        colorSchemeSeed: Colors.blue,\n"
            "        useMaterial3: true,\n"
            "      ),\n"
            "      home: Scaffold(\n"
            "        appBar: AppBar(title: const Text('Home')),\n"
            "        body: const Center(child: Text('Hello')),\n"
            "      ),\n"
            "    );\n"
        ),
    }

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
                    f"KnowledgeBase: {fixes} correções conhecidas "
                    f"({total} aplicações)"
                )
            else:
                self.log.warn("known_fixes.json não encontrado — iniciando vazio")
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
            ctx_pats = fix.get("context_patterns", [])
            context_match = (
                all(pat in code for pat in ctx_pats) or
                all(pat in error_text for pat in ctx_pats)
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

            elif fix_type == "structural_fix":
                for op in fix.get("operations", []):
                    action = op.get("action", "")
                    code, ch = self._apply_structural_action(code, action, op)
                    if ch:
                        changed = True

            elif fix_type == "template_inject":
                strategy = fix.get("insert_strategy", "replace_all")
                templates = fix.get("templates", {})
                for tkey, tval in templates.items():
                    new_code, ch = self._inject_template(
                        code, tkey, tval, strategy
                    )
                    if ch:
                        code = new_code
                        changed = True

            elif fix_type == "restructure":
                code, applied_fixes = self._restructure_code(
                    code, fix.get("operations", [])
                )
                if applied_fixes:
                    changed = True
                    for ap in applied_fixes:
                        self.log.ok(f"[{fix_id}] {ap}")

            if changed and fix_type not in ("info_only",):
                applied.append(desc)
                fix["times_applied"] = fix.get("times_applied", 0) + 1
                self.log.ok(f"[{fix_id}] Correção aplicada: {desc}")

        if applied:
            meta = self._db.setdefault("_meta", {})
            meta["total_fixes_applied"] = (
                meta.get("total_fixes_applied", 0) + len(applied)
            )
            self._save()

        return code, applied

    def _apply_structural_action(self, code, action, op):
        """Aplica uma ação estrutural individual."""
        if action == "ensure_imports_top":
            return self._ensure_imports_top(code)
        elif action == "ensure_material_import":
            return self._ensure_material_import(code)
        elif action == "remove_duplicate_imports":
            return self._remove_duplicate_imports(code)
        elif action == "ensure_main_function":
            class_name = op.get("class_name", "MyApp")
            return self._ensure_main_function(code, class_name)
        elif action == "ensure_run_app":
            class_name = op.get("class_name", "MyApp")
            return self._ensure_run_app(code, class_name)
        elif action == "ensure_const_constructor":
            return self._ensure_const_constructor(code)
        elif action == "ensure_override_annotation":
            return self._ensure_override_annotation(code)
        elif action == "ensure_build_method":
            return self._ensure_build_method(code)
        elif action == "ensure_material_app_structure":
            return self._ensure_material_app_structure(code)
        elif action == "fix_unmatched_brackets":
            return self._fix_unmatched_brackets(code)
        elif action == "ensure_semicolons":
            return self._ensure_semicolons(code)
        elif action == "reorder_sections":
            return self._reorder_code_sections(code)
        elif action == "remove_duplicate_classes":
            return self._remove_duplicate_classes(code)
        elif action == "ensure_scaffold_in_home":
            return self._ensure_scaffold_in_home(code)
        elif action == "inline_code_outside_class":
            return self._inline_code_outside_class(code)
        elif action == "ensure_widget_structure":
            return self._ensure_widget_structure(code)
        elif action == "ensure_common_imports":
            return self._ensure_common_imports(code)
        return code, False

    def _restructure_code(self, code, operations):
        """Orquestra múltiplas transformações estruturais em sequência."""
        applied = []
        for op in operations:
            action = op.get("action", "")
            code, ch = self._apply_structural_action(code, action, op)
            if ch:
                applied.append(action)
        return code, applied

    def _ensure_imports_top(self, code):
        """Move todas as linhas de import para o topo do arquivo."""
        lines = code.split("\n")
        imports = []
        non_imports = []
        in_import_block = False
        for line in lines:
            if line.strip().startswith("import ") or line.strip().startswith("export "):
                imports.append(line)
                in_import_block = True
            elif in_import_block and not line.strip():
                imports.append(line)
            else:
                if in_import_block:
                    in_import_block = False
                non_imports.append(line)
        if not imports:
            return code, False
        first_import_pos = None
        for i, line in enumerate(lines):
            if line.strip().startswith("import ") or line.strip().startswith("export "):
                first_import_pos = i
                break
        if first_import_pos is None:
            return code, False
        has_code_before = any(
            l.strip() and not l.strip().startswith("import ")
            and not l.strip().startswith("export ")
            for l in lines[:first_import_pos]
        )
        if not has_code_before:
            return code, False
        imports_str = "\n".join(imports)
        non_imports_str = "\n".join(non_imports)
        new_code = imports_str.rstrip() + "\n" + non_imports_str
        return new_code, True

    def _ensure_material_import(self, code):
        """Adiciona import de material.dart se widgets Material forem usados."""
        material_widgets = [
            "MaterialApp", "Scaffold", "AppBar", "FloatingActionButton",
            "ThemeData", "Colors", "Text", "Container", "Row", "Column",
            "Center", "Padding", "EdgeInsets", "SizedBox", "Stack",
            "Positioned", "Expanded", "Flexible", "ListView", "GridView",
            "Icon", "IconButton", "ElevatedButton", "TextButton",
            "OutlinedButton", "SnackBar", "Drawer", "BottomNavigationBar",
            "TabBar", "TabController", "TextField", "Form", "DropdownButton",
        ]
        uses_material = any(w in code for w in material_widgets)
        has_import = "import 'package:flutter/material.dart';" in code
        if uses_material and not has_import:
            code = "import 'package:flutter/material.dart';\n" + code
            return code, True
        return code, False

    def _remove_duplicate_imports(self, code):
        """Remove linhas de import duplicadas."""
        lines = code.split("\n")
        seen = set()
        new_lines = []
        changed = False
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("import ") or stripped.startswith("export "):
                if stripped in seen:
                    changed = True
                    continue
                seen.add(stripped)
            new_lines.append(line)
        if changed:
            return "\n".join(new_lines), True
        return code, False

    def _ensure_main_function(self, code, class_name="MyApp"):
        """Adiciona função main() se ausente."""
        if re.search(r'\bvoid\s+main\b', code) or re.search(r'\bmain\s*\(', code):
            return code, False
        lines = code.split("\n")
        last_import_idx = -1
        for i, line in enumerate(lines):
            if line.strip().startswith("import "):
                last_import_idx = i
        insert_pos = last_import_idx + 1 if last_import_idx >= 0 else 0
        main_line = f"void main() => runApp(const {class_name}());"
        insert_lines = ["", main_line, ""]
        for j, ml in enumerate(insert_lines):
            lines.insert(insert_pos + j, ml)
        return "\n".join(lines), True

    def _ensure_run_app(self, code, class_name="MyApp"):
        """Adiciona chamada runApp se main existe mas runApp não."""
        has_main = re.search(r'\bvoid\s+main\b', code) or re.search(r'\bmain\s*\(', code)
        if not has_main:
            return code, False
        if "runApp" in code:
            return code, False
        code = re.sub(
            r'(void\s+main\s*\(\s*\)\s*\{)',
            r'\1  runApp(const ' + class_name + r'());',
            code
        )
        code = re.sub(
            r"(void\s+main\s*\(\s*\)\s*=>)",
            r"\1 runApp(const " + class_name + r"());",
            code
        )
        if "runApp" in code:
            return code, True
        code = re.sub(
            r'(void\s+main\b.*?)(?:\n|\Z)',
            r'\1 => runApp(const ' + class_name + r'());\n',
            code
        )
        if "runApp" in code:
            return code, True
        lines = code.split("\n")
        for i, line in enumerate(lines):
            if 'void main' in line:
                lines[i] = line.rstrip() + f"  runApp(const {class_name}());"
                return "\n".join(lines), True
        return code, False

    def _ensure_const_constructor(self, code):
        """Adiciona const constructor a classes widget que não têm um."""
        changed = False
        class_pattern = re.compile(
            r'class\s+(\w+)\s+extends\s+(StatelessWidget|StatefulWidget)\s*\{'
        )
        for match in class_pattern.finditer(code):
            class_name = match.group(1)
            class_start = match.start()
            class_end = self._find_class_end(code, class_start)
            class_body = code[class_start:class_end]
            if f"const {class_name}" in class_body:
                continue
            if "{super.key}" in class_body:
                continue
            brace_pos = class_body.index("{")
            insert_pos = class_start + brace_pos + 1
            const_line = f"\n  const {class_name}({{super.key}});\n"
            if "const " + class_name + "(" not in class_body:
                code = code[:insert_pos] + const_line + code[insert_pos:]
                changed = True
        return code, changed

    def _ensure_override_annotation(self, code):
        """Adiciona @override a métodos build() que não têm."""
        changed = False
        pattern = re.compile(
            r'(\s+)(Widget\s+build\s*\([^)]*\)\s*(?:=>|\{))'
        )
        for match in pattern.finditer(code):
            before = code[max(0, match.start() - 12):match.start()]
            if "@override" not in before:
                indent = match.group(1)
                code = (
                    code[:match.start()]
                    + f"{indent}@override\n{match.group(1)}{match.group(2)}"
                    + code[match.end():]
                )
                changed = True
        return code, changed

    def _ensure_build_method(self, code):
        """Adiciona método build() a classes widget que não têm."""
        changed = False
        class_pattern = re.compile(
            r'class\s+(\w+)\s+extends\s+(StatelessWidget|StatefulWidget)\s*\{'
        )
        for match in class_pattern.finditer(code):
            class_start = match.start()
            class_end = self._find_class_end(code, class_start)
            class_body = code[class_start:class_end]
            if "Widget build" in class_body or "build(" in class_body:
                continue
            if "StatelessWidget" in match.group(0):
                build_method = (
                    "\n\n  @override\n"
                    "  Widget build(BuildContext context) {\n"
                    "    return Container();\n"
                    "  }"
                )
                insert_pos = class_end - 1
                code = code[:insert_pos] + build_method + code[insert_pos:]
                changed = True
            elif "StatefulWidget" in match.group(0):
                build_method = (
                    "\n\n  @override\n"
                    "  Widget build(BuildContext context) {\n"
                    "    return Container();\n"
                    "  }"
                )
                insert_pos = class_end - 1
                code = code[:insert_pos] + build_method + code[insert_pos:]
                changed = True
        return code, changed

    def _ensure_material_app_structure(self, code):
        """Corrige estrutura do MaterialApp se presente mas incompleto."""
        changed = False
        if "MaterialApp(" not in code:
            return code, changed
        if "home:" not in code and "Scaffold" not in code:
            code = code.replace(
                "MaterialApp(",
                "MaterialApp(\n        home: const Scaffold(\n"
                "          body: Center(child: Text('Hello')),\n"
                "        ),",
            )
            changed = True
        if "title:" not in code:
            code = code.replace(
                "MaterialApp(",
                "MaterialApp(\n      title: 'Flutter App',",
            )
            changed = True
        return code, changed

    def _fix_unmatched_brackets(self, code):
        """Corrige chaves/colchetes desbalanceados."""
        open_count = code.count("{")
        close_count = code.count("}")
        if open_count == close_count:
            return code, False
        if open_count > close_count:
            code += "\n" + "}" * (open_count - close_count)
            return code, True
        return code, False

    def _ensure_semicolons(self, code):
        """Adiciona ponto-e-vírgula ausente em statements que precisam."""
        changed = False
        lines = code.split("\n")
        new_lines = []
        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.endswith(";") or stripped.endswith("{"):
                new_lines.append(line)
                continue
            if stripped.endswith("}") or stripped.endswith("},"):
                new_lines.append(line)
                continue
            if stripped.startswith("//") or stripped.startswith("/*"):
                new_lines.append(line)
                continue
            if stripped.startswith(("import ", "export ", "class ", "abstract ")):
                new_lines.append(line)
                continue
            if stripped.startswith(("@override", "@deprecated", "@protected")):
                new_lines.append(line)
                continue
            if re.match(r'^\s*(//|/\*|\*|\*/)', stripped):
                new_lines.append(line)
                continue
            if re.match(r'^\s*\)\s*(;\s*)?$', stripped):
                new_lines.append(line)
                continue
            if re.match(r'^\s*,\s*$', stripped):
                new_lines.append(line)
                continue
            if re.match(r'^\s*:\s*$', stripped):
                new_lines.append(line)
                continue
            if re.match(
                r'^\s*(return|if|for|while|switch|case |default:|try|catch|finally)\b',
                stripped
            ):
                if stripped.endswith(")") and not stripped.endswith(");"):
                    pass
                elif stripped.endswith("=>") and not stripped.endswith("=>"):
                    pass
                else:
                    new_lines.append(line)
                    continue
            if any(kw in stripped for kw in ["=>", "//", "/*"]):
                if "=>" in stripped and not stripped.rstrip().endswith(";"):
                    new_lines.append(line.rstrip() + ";")
                    changed = True
                    continue
                new_lines.append(line)
                continue
            if re.match(r'^\s*\w+[.\w]*\s*=', stripped):
                if not stripped.rstrip().endswith(";"):
                    new_lines.append(line.rstrip() + ";")
                    changed = True
                    continue
            if re.match(r'^\s*\w+\s*\(', stripped):
                if not stripped.rstrip().endswith(";"):
                    new_lines.append(line.rstrip() + ";")
                    changed = True
                    continue
            new_lines.append(line)
        if changed:
            return "\n".join(new_lines), True
        return code, False

    def _reorder_code_sections(self, code):
        """Reordena: imports no topo, main antes das classes."""
        lines = code.split("\n")
        imports = []
        main_block = []
        class_block = []
        other = []
        state = "scan"
        brace_depth = 0
        for line in lines:
            if state == "scan":
                if line.strip().startswith("import ") or line.strip().startswith("export "):
                    imports.append(line)
                elif re.search(r'\bvoid\s+main\b', line) or re.search(r'\bmain\s*\(', line):
                    main_block.append(line)
                    brace_depth = line.count("{") - line.count("}")
                    state = "in_main" if brace_depth > 0 else "scan"
                elif re.match(r'^\s*(class|abstract class|mixin|enum)\s', line):
                    class_block.append(line)
                    brace_depth = line.count("{") - line.count("}")
                    state = "in_class" if brace_depth > 0 else "scan"
                else:
                    other.append(line)
            elif state == "in_main":
                main_block.append(line)
                brace_depth += line.count("{") - line.count("}")
                if brace_depth <= 0:
                    state = "scan"
            elif state == "in_class":
                class_block.append(line)
                brace_depth += line.count("{") - line.count("}")
                if brace_depth <= 0:
                    state = "scan"
        if not imports and not main_block and not class_block:
            return code, False
        has_preamble = any(
            l.strip() and not l.strip().startswith("import ")
            and not l.strip().startswith("export ")
            for l in other
        )
        new_lines = list(imports)
        if main_block:
            if new_lines:
                new_lines.append("")
            new_lines.extend(main_block)
        if class_block:
            if new_lines:
                new_lines.append("")
            new_lines.extend(class_block)
        if other and has_preamble:
            pre = [l for l in other if l.strip()]
            if pre:
                if new_lines:
                    new_lines.append("")
                new_lines.extend(pre)
        new_code = "\n".join(new_lines)
        if new_code.strip() == code.strip():
            return code, False
        return new_code, True

    def _remove_duplicate_classes(self, code):
        """Remove definições de classe duplicadas."""
        changed = False
        class_pattern = re.compile(r'^\s*(class|abstract class|mixin)\s+(\w+)', re.M)
        seen = {}
        for match in class_pattern.finditer(code):
            name = match.group(2)
            if name in seen:
                start = seen[name]
                end = self._find_class_end(code, match.start())
                block = code[start:end]
                code = code.replace(block, "", 1)
                changed = True
            else:
                seen[name] = match.start()
        if changed:
            code = re.sub(r'\n{3,}', '\n\n', code)
        return code, changed

    def _ensure_scaffold_in_home(self, code):
        """Adiciona Scaffold se home do MaterialApp não usa Scaffold."""
        changed = False
        if "MaterialApp(" not in code:
            return code, False
        if "Scaffold(" in code:
            return code, False
        match = re.search(r'home:\s*(const\s+)?(\w+)\(', code)
        if match:
            widget_name = match.group(2)
            if widget_name != "Scaffold":
                code = code.replace(
                    f"home: const {widget_name}(",
                    "home: const Scaffold(\n          body: " + widget_name + "(",
                )
                code = self._fix_unmatched_brackets(code)
                changed = True
        return code, changed

    def _inline_code_outside_class(self, code):
        """Move código Dart solto (fora de classe) para dentro de main()."""
        lines = code.split("\n")
        inside_main = False
        inside_class = False
        brace_depth = 0
        loose_code = []
        new_lines = []
        for line in lines:
            stripped = line.strip()
            if not stripped:
                new_lines.append(line)
                continue
            if stripped.startswith("import ") or stripped.startswith("export "):
                new_lines.append(line)
                continue
            if re.search(r'\bvoid\s+main\b', stripped) or re.search(r'\bmain\s*\(', stripped):
                inside_main = True
                brace_depth = line.count("{") - line.count("}")
                new_lines.append(line)
                continue
            if re.match(r'^\s*(class|abstract class|mixin|enum)\s', stripped):
                inside_class = True
                brace_depth = line.count("{") - line.count("}")
                new_lines.append(line)
                continue
            if inside_class or inside_main:
                brace_depth += line.count("{") - line.count("}")
                if brace_depth <= 0:
                    inside_class = False
                    inside_main = False
                new_lines.append(line)
            else:
                if stripped.startswith(("@", "//", "/*", "*", "*/")):
                    new_lines.append(line)
                elif re.match(r'^\s*[\w]+\s*\(', stripped):
                    loose_code.append(line)
                elif re.match(r'^\s*[\w]+\s*=', stripped):
                    loose_code.append(line)
                elif re.match(r'^\s*return\b', stripped):
                    loose_code.append(line)
                else:
                    new_lines.append(line)
        if loose_code:
            has_main = any("void main" in l for l in new_lines)
            if has_main:
                for i, line in enumerate(new_lines):
                    if "void main" in line:
                        if "{" in line:
                            for j, lc in enumerate(loose_code):
                                new_lines.insert(i + 1 + j, "  " + lc)
                        else:
                            new_lines[i] = line.rstrip() + " {\n" + "\n".join(
                                "  " + lc for lc in loose_code
                            ) + "\n}"
                        break
            else:
                main_lines = ["", "void main() {"]
                for lc in loose_code:
                    main_lines.append("  " + lc)
                main_lines.append("}")
                insert_pos = 0
                for i, line in enumerate(new_lines):
                    if line.strip().startswith("import ") or line.strip().startswith("export "):
                        insert_pos = i + 1
                for j, ml in enumerate(main_lines):
                    new_lines.insert(insert_pos + j, ml)
            return "\n".join(new_lines), True
        return code, False

    def _ensure_widget_structure(self, code):
        """Corrige problemas comuns de aninhamento de widgets."""
        changed = False
        if "Scaffold(" in code and "MaterialApp(" not in code:
            code = (
                "import 'package:flutter/material.dart';\n\n"
                "void main() => runApp(const MyApp());\n\n"
                "class MyApp extends StatelessWidget {\n"
                "  const MyApp({super.key});\n"
                "  @override\n"
                "  Widget build(BuildContext context) {\n"
                "    return MaterialApp(\n"
                "      home: " + code.strip() + ",\n"
                "    );\n"
                "  }\n"
                "}\n"
            )
            changed = True
        if "Text(" in code and "MaterialApp(" not in code and "Scaffold(" not in code:
            code = self.TEMPLATES["material_app_scaffold"] + "\n" + code
            changed = True
        return code, changed

    def _ensure_common_imports(self, code):
        """Adiciona imports comuns baseado em widgets usados."""
        changed = False
        import_map = [
            (["MaterialApp", "Scaffold", "ThemeData", "Colors"],
             "import 'package:flutter/material.dart';"),
            (["CupertinoApp", "CupertinoButton"],
             "import 'package:flutter/cupertino.dart';"),
            (["http.get", "http.post", "http.put", "http.delete"],
             "import 'package:http/http.dart' as http;"),
            (["SharedPreferences", "getInstance"],
             "import 'package:shared_preferences/shared_preferences.dart';"),
            (["ChangeNotifier", "Provider.of", "Consumer<"],
             "import 'package:provider/provider.dart';"),
            (["AudioPlayer", "LoopMode"],
             "import 'package:just_audio/just_audio.dart';"),
            (["DeviceInfoPlugin"],
             "import 'package:device_info_plus/device_info_plus.dart';"),
            (["OnAudioQuery"],
             "import 'package:on_audio_query/on_audio_query.dart';"),
            (["Dio"],
             "import 'package:dio/dio.dart';"),
            (["FirebaseApp", "Firebase.initializeApp"],
             "import 'package:firebase_core/firebase_core.dart';"),
            (["Get.", "GetxController", "Obx"],
             "import 'package:get/get.dart';"),
            (["BlocProvider", "BlocBuilder", "Cubit"],
             "import 'package:flutter_bloc/flutter_bloc.dart';"),
        ]
        for widgets, imp in import_map:
            if any(w in code for w in widgets):
                if imp not in code:
                    code = imp + "\n" + code
                    changed = True
        return code, changed

    def _inject_template(self, code, template_key, template, strategy="replace_all"):
        """Injeta um template de código baseado na estratégia."""
        if strategy == "replace_all":
            if template.strip() != code.strip():
                return template, True
            return code, False
        elif strategy == "append":
            if template not in code:
                return code.rstrip() + "\n\n" + template, True
            return code, False
        elif strategy == "inject_after_main":
            match = re.search(r'(void\s+main\b[^;{]*[;{])', code)
            if match and template not in code:
                pos = match.end()
                code = code[:pos] + "\n\n" + template + code[pos:]
                return code, True
            return code, False
        elif strategy == "replace_if_empty":
            code_stripped = code.strip()
            if not code_stripped or len(code_stripped) < 30:
                return template, True
            return code, False
        return code, False

    def _find_class_end(self, code, start):
        """Encontra o final de uma classe contando chaves."""
        brace_depth = 0
        in_string = False
        string_char = None
        for i in range(start, len(code)):
            ch = code[i]
            if in_string:
                if ch == "\\":
                    i += 1
                elif ch == string_char:
                    in_string = False
                continue
            if ch in ('"', "'"):
                in_string = True
                string_char = ch
                continue
            if ch == "{":
                brace_depth += 1
            elif ch == "}":
                brace_depth -= 1
                if brace_depth == 0:
                    return i + 1
        return len(code)

    def learn_from_gemini(self, original_code, fixed_code, errors, session_id):
        try:
            corrections = []
            for line in fixed_code.split("\n"):
                line = line.strip()
                if line.startswith("// -") and "CORREÇÕES" not in line:
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
            self.log.warn(f"Não foi possível aprender deste fix: {e}")

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
            build_gradle_path = None

            # 1. Try to extract path from error text (project build.gradle)
            match = re.search(
                r'([A-Z]:\\[^:]+\\android\\build\.gradle)', error_text
            )
            if match:
                build_gradle_path = Path(match.group(1))

            # 2. If path not found, check if it's a plugin error (e.g. :on_audio_query_android)
            if not build_gradle_path or not build_gradle_path.exists():
                plugin_match = re.search(
                    r"Project\s+':(\S+)'.*Namespace not specified", error_text
                )
                if not plugin_match:
                    plugin_match = re.search(
                        r"configure project\s+':(\S+)'", error_text
                    )
                if not plugin_match:
                    # Try to find any build.gradle that lacks namespace in project
                    for bg in Path(project_dir).rglob("**/android/build.gradle"):
                        if "namespace" not in bg.read_text(encoding="utf-8", errors="ignore"):
                            build_gradle_path = bg
                            break
                else:
                    plugin_name = plugin_match.group(1)
                    pub_cache = Path.home() / ".pub-cache" / "hosted"
                    for bg in pub_cache.rglob(f"**/{plugin_name}/android/build.gradle"):
                        if bg.exists():
                            build_gradle_path = bg
                            break

            if not build_gradle_path or not build_gradle_path.exists():
                log.warn("N\u00e3o foi poss\u00edvel localizar o build.gradle sem namespace")
                return False

            content = build_gradle_path.read_text(encoding="utf-8")
            if "namespace" in content:
                return False

            # Find AndroidManifest.xml to extract package name
            manifest_path = (
                build_gradle_path.parent / "src" / "main" / "AndroidManifest.xml"
            )
            if not manifest_path.exists():
                manifest_path = (
                    build_gradle_path.parent.parent / "src" / "main" / "AndroidManifest.xml"
                )
            if not manifest_path.exists():
                log.warn(f"AndroidManifest.xml n\u00e3o encontrado junto a {build_gradle_path}")
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
        """Injeta substituições de pacotes no pubspec.yaml."""
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
                self.log.ok(f"pubspec: {old_pkg} → {new_entry}")
        if changed:
            pubspec_path.write_text(pubspec, encoding="utf-8")

    def _detect_and_inject_deps(self, code, project_dir):
        """Detecta imports e injeta dependências no pubspec.yaml."""
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
            self.log.ok(f"Dependências injetadas: {', '.join(added)}")

    def proactive_restructure(self, code):
        """Aplica correções estruturais proativamente, sem depender de erros."""
        return self._restructure_code(code, [
            {"action": "ensure_imports_top"},
            {"action": "ensure_material_import"},
            {"action": "remove_duplicate_imports"},
            {"action": "ensure_main_function", "class_name": "MyApp"},
            {"action": "ensure_run_app", "class_name": "MyApp"},
            {"action": "ensure_const_constructor"},
            {"action": "ensure_override_annotation"},
            {"action": "ensure_build_method"},
            {"action": "ensure_material_app_structure"},
            {"action": "fix_unmatched_brackets"},
            {"action": "ensure_semicolons"},
            {"action": "reorder_sections"},
            {"action": "remove_duplicate_classes"},
            {"action": "inline_code_outside_class"},
            {"action": "ensure_scaffold_in_home"},
            {"action": "ensure_common_imports"},
        ])

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
