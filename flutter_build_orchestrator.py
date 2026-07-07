#!/usr/bin/env python3
"""
Flutter Build Orchestrator — thin wrapper.
Redireciona para o orchestrator unificado em flutter_orchestrator.py.
"""
import sys
from flutter_orchestrator import FlutterBuildOrchestrator, main

if __name__ == "__main__":
    sys.exit(main())
