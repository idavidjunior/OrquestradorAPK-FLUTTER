"""
Smoke tests — verifica importa\u00e7\u00e3o dos m\u00f3dulos principais.
"""

import sys
from pathlib import Path


def test_import_cli():
    from flutter_orchestrator import FlutterBuildOrchestrator, Color


def test_import_gui_modules():
    from gui.logger import Logger
    from gui.checklist import Checklist
    from gui.knowledge_base import KnowledgeBase
    from gui.gemini_fixer import GeminiCodeFixer
    from gui.project_source import ProjectSourceManager


def test_knowledge_base_init():
    from gui.knowledge_base import KnowledgeBase

    class FakeLog:
        def ok(self, msg): pass
        def warn(self, msg): pass
        def err(self, msg): pass
        def info(self, msg): pass

    kb = KnowledgeBase(FakeLog())
    stats = kb.stats()
    assert "total_fixes" in stats
    assert "total_applied" in stats


def test_flutter_version_url():
    from flutter_orchestrator import _flutter_download_url
    url = _flutter_download_url()
    assert url.startswith("https://")
    assert "flutter" in url
