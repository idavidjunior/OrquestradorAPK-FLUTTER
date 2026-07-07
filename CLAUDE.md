# Projeto: Flutter Build Orchestrator

## Miss\u00e3o

Automatizar o processo de build de aplicativos Flutter, gerando APK pronto para
instala\u00e7\u00e3o com m\u00ednima interven\u00e7\u00e3o manual. Suporta CLI e GUI.

## Arquitetura

```
flutter_orchestrator.py          # CLI unificada (entry point principal)
flutter_build_orchestrator.py     # Wrapper thin que redireciona para a CLI
flutter_orchestrator_gui.py       # Entry point thin para a GUI
gui/
  __init__.py                     # Package marker
  app.py                          # GUI principal (BuildOrchestratorGUI)
  logger.py                       # Logger thread-safe com fila
  checklist.py                    # Verifica\u00e7\u00e3o de pr\u00e9-requisitos
  knowledge_base.py               # Base de corre\u00e7\u00f5es conhecidas (known_fixes.json)
  gemini_fixer.py                 # Corre\u00e7\u00e3o via API Gemini
  project_source.py               # Gerencia c\u00f3digo fonte, pubspec, permiss\u00f5es
known_fixes.json                  # Knowledge base de erros e corre\u00e7\u00f5es
examples/
  mp3_player_fixed.dart           # Exemplo de app corrigido automaticamente
tests/
  test_orchestrator.py            # Testes unit\u00e1rios do orchestrator
  test_smoke.py                   # Testes de fuma\u00e7a (imports)
```

## CLI Usage

```bash
# Build release (padr\u00e3o)
python flutter_orchestrator.py /caminho/do/projeto

# Build debug pulando testes com auto-install
python flutter_orchestrator.py /caminho/do/projeto --debug --skip-tests

# Com n\u00famero de build personalizado
python flutter_orchestrator.py /caminho/do/projeto --build-number 42

# Com auto-instala\u00e7\u00e3o do Flutter se ausente
python flutter_orchestrator.py /caminho/do/projeto --auto-install
```

## GUI Usage

```bash
python flutter_orchestrator_gui.py
```

## Padr\u00f5es de C\u00f3digo

- Python 3.7+, tipagem com type hints
- Respeitar single-responsibility: cada classe/arquivo um prop\u00f3sito
- Evitar hardcoding de URLs (usar lookup din\u00e2mico via API)
- Tratar PyYAML como opcional com fallback gracioso
- Prote\u00e7\u00e3o contra path traversal na extra\u00e7\u00e3o de archives
- Testes em tests/ com pytest

## Git / Commits

- Commitar sempre na branch `main`
- Mensagens em portugu\u00eas (idioma do projeto)
- Usar conventional commits: `fix:`, `feat:`, `refactor:`, `docs:`, `test:`

## CI/CD

Workflow em `.github/workflows/compile.yml`:
- Lint com ruff
- Testes com pytest
- Verifica\u00e7\u00e3o de imports dos m\u00f3dulos
- Smoke tests
