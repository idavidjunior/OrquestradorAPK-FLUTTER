"""
Flutter Build Orchestrator — GUI Package

M\u00f3dulos dispon\u00edveis (todos import\u00e1veis sem customtkinter):
  logger          Logger thread-safe (usa queue, gen\u00e9rico)
  checklist       Verifica\u00e7\u00e3o de pr\u00e9-requisitos
  knowledge_base  Base de corre\u00e7\u00f5es conhecidas (known_fixes.json)
  gemini_fixer    Corre\u00e7\u00e3o via API Gemini
  project_source  Gerencia c\u00f3digo fonte, pubspec e permiss\u00f5es
  app             Interface gr\u00e1fica (requer customtkinter em tempo de execu\u00e7\u00e3o)

Uso:
  from gui.app import run   # s\u00f3 executa se customtkinter estiver instalado
  run()                     # inicia a janela principal
"""

from gui.logger import Logger
from gui.checklist import Checklist
from gui.knowledge_base import KnowledgeBase
from gui.gemini_fixer import GeminiCodeFixer
from gui.project_source import ProjectSourceManager

__all__ = [
    "Logger",
    "Checklist",
    "KnowledgeBase",
    "GeminiCodeFixer",
    "ProjectSourceManager",
]
