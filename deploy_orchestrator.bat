@echo off
echo Deploying Flutter Orchestrator v2.0...

REM 1. Create directory structure
if not exist orchestrator mkdir orchestrator
if not exist orchestrator\models mkdir orchestrator\models
if not exist orchestrator\fixes mkdir orchestrator\fixes

REM 2. Install Python dependencies
pip install -r requirements.txt

REM 3. Create initial config
if not exist orchestrator_config.yaml copy orchestrator_config.yaml config.yaml >nul 2>&1

REM 4. Initialize KnowledgeBase via import (will create on first use)
echo KnowledgeBase sera criada na primeira execucao.

REM 5. Verify Flutter
where flutter >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo Flutter nao encontrado. Certifique-se de que esta instalado.
)

echo.
echo Deploy concluido!
echo Estrutura criada:
echo    - orchestrator\          # Codigo fonte
echo    - orchestrator\models\   # Modelos IA
echo    - orchestrator\fixes\    # Correcoes automaticas
echo    - orchestrator_config.yaml # Configuracao
