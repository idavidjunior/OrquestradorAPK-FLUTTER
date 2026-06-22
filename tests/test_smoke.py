#!/usr/bin/env python3
"""
Teste de fumaça: garante que todos os módulos Python do projeto compilam.

Foi exatamente um SyntaxError não detectado que deixou o componente principal
(flutter_orchestrator_gui.py) quebrado no repositório. Este teste impede que
isso volte a acontecer.

Roda de duas formas:
    pytest                       # como suíte de testes
    python tests/test_smoke.py   # standalone, sem dependências
"""

import py_compile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def iter_python_files():
    """Todos os .py do projeto, exceto caches e ambientes virtuais."""
    skip_dirs = {"__pycache__", ".venv", "venv", "build", "dist"}
    for path in sorted(PROJECT_ROOT.rglob("*.py")):
        if any(part in skip_dirs for part in path.parts):
            continue
        yield path


class TestModulesCompile(unittest.TestCase):
    """Cada arquivo .py deve compilar sem erros de sintaxe."""

    def test_all_modules_compile(self):
        files = list(iter_python_files())
        self.assertTrue(files, "Nenhum arquivo Python encontrado para validar")

        failures = []
        for path in files:
            try:
                py_compile.compile(str(path), doraise=True)
            except py_compile.PyCompileError as exc:
                failures.append(f"{path.relative_to(PROJECT_ROOT)}: {exc.msg}")

        self.assertFalse(
            failures,
            "Arquivos com erro de compilação:\n" + "\n".join(failures),
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
