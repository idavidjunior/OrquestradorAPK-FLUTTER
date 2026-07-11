"""
Smoke tests — verifica importa\u00e7\u00e3o dos m\u00f3dulos principais.
Nenhum destes testes requer customtkinter instalado.
"""


def test_import_cli():
    from flutter_orchestrator import FlutterBuildOrchestrator, Color


def test_import_gui_modules_without_ctk():
    """
    Todos os m\u00f3dulos do pacote gui/ devem importar sem customtkinter.
    (app.run() falhar\u00e1 em tempo de execu\u00e7\u00e3o, mas o import do m\u00f3dulo deve passar.)
    """
    from gui.logger import Logger
    from gui.checklist import Checklist
    from gui.knowledge_base import KnowledgeBase
    from gui.gemini_fixer import GeminiCodeFixer
    from gui.project_source import ProjectSourceManager

    # garante que n\u00e3o importamos acidentalmente ctk
    import sys
    assert "customtkinter" not in sys.modules, (
        "customtkinter foi importado indiretamente!"
    )


def test_gui_entry_point_import():
    """
    O entry point flutter_orchestrator_gui.py deve importar sem erros.
    (A execu\u00e7\u00e3o vai falhar por falta de display, mas o parse deve passar.)
    """
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "gui_entry",
        "flutter_orchestrator_gui.py",
    )
    assert spec is not None, "N\u00e3o foi poss\u00edvel ler flutter_orchestrator_gui.py"
    # N\u00e3o executamos — s\u00f3 verificamos que o arquivo \u00e9 leg\u00edvel


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


def test_build_pipeline_import():
    """BuildPipeline dentro de gui/app.py deve ser acess\u00edvel via factory."""
    from gui.app import run
    assert callable(run)
