#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import sys
import subprocess

# FORCA UTF-8
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except:
        pass
os.environ['PYTHONIOENCODING'] = 'utf-8'
os.environ['PYTHONUTF8'] = '1'

if __name__ == "__main__":
    # Executa o orquestrador com codificacao forcada
    cmd = [sys.executable, "-c", "from orchestrator.main_orchestrator import FlutterOrchestrator; import asyncio; asyncio.run(FlutterOrchestrator('.').build_app())"]
    subprocess.run(cmd, env=os.environ)
