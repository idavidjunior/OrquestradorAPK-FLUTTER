#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import sys
import re
import json
import shutil
from pathlib import Path
from datetime import datetime

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
os.environ['PYTHONIOENCODING'] = 'utf-8'
os.environ['PYTHONUTF8'] = '1'

PROJECT_ROOT = Path.cwd()
ORCHESTRATOR_DIR = PROJECT_ROOT / "orchestrator"

def log(msg):
    safe = msg.encode('ascii', errors='replace').decode('ascii')
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {safe}")

def patch_flutter_orchestrator():
    log("[PATCH] Adicionando validacao de tamanho minimo e estrutura JSON em flutter_orchestrator.py...")
    target = PROJECT_ROOT / "flutter_orchestrator.py"
    if not target.exists():
        log("[AVISO] flutter_orchestrator.py nao encontrado")
        return False

    content = target.read_text(encoding='utf-8', errors='ignore')

    # Adiciona _validate_ia_response method apos _ai_fix_code
    new_method = """
    def _validate_ia_response(self, response_text: str) -> Optional[dict]:
        if not response_text or len(response_text.strip()) < 200:
            self.log("[IA] Resposta muito curta (<200 chars), invalida", "WARNING")
            return None
        try:
            data = json.loads(response_text)
        except (json.JSONDecodeError, TypeError):
            self.log("[IA] Resposta nao e JSON valido", "WARNING")
            return None
        if not isinstance(data, dict):
            return None
        if data.get("ok"):
            return data
        files = data.get("files", {})
        if not isinstance(files, dict) or not files:
            self.log("[IA] JSON nao contem 'files' valido", "WARNING")
            return None
        for fpath, fcontent in files.items():
            if not isinstance(fcontent, str) or len(fcontent.strip()) < 50:
                return None
        return data
"""
    if "_validate_ia_response" not in content:
        content = content.replace(
            "def _ai_fix_code(self, errors: str, code: str,",
            new_method + "\n    def _ai_fix_code(self, errors: str, code: str,"
        )

    # Replace json.loads call with validate call
    content = content.replace(
        "json.loads(json_str)",
        "self._validate_ia_response(json_str) or {}"
    )

    target.write_text(content, encoding='utf-8')
    log("[OK] flutter_orchestrator.py patched")
    return True

def patch_main_orchestrator():
    log("[PATCH] Ativando _call_ia_model como fallback e adicionando extracao Dart puro...")
    target = ORCHESTRATOR_DIR / "main_orchestrator.py"
    if not target.exists():
        log("[AVISO] main_orchestrator.py nao encontrado")
        return False

    content = target.read_text(encoding='utf-8', errors='ignore')

    # Replace _call_ia_model stub with one that actually calls IA
    old_stub = "async def _call_ia_model(self, model: str, prompt: str) -> Optional[str]:\n        return None"
    new_stub = """async def _call_ia_model(self, model: str, prompt: str) -> Optional[str]:
        self._log("[IA-FALLBACK] Chamando modelo IA...")
        try:
            import aiohttp
            api_key = os.environ.get("NVIDIA_API_KEY") or os.environ.get("API_KEY") or ""
            url = f"https://integrate.api.nvidia.com/v1/chat/completions"
            headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
            payload = {"model": model, "messages": [{"role": "user", "content": prompt}], "temperature": 0.1, "max_tokens": 4096}
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, headers=headers, timeout=120) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        text = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                        if text and len(text.strip()) >= 200:
                            return text
                    self._log(f"[IA-FALLBACK] HTTP {resp.status} ou resposta curta")
                    return None
        except Exception as e:
            self._log(f"[IA-FALLBACK] Erro: {e}")
            return None
"""
    content = content.replace(old_stub, new_stub)

    # Add Dart puro fallback before return {'success': False} in _attempt_fix
    fallback = """
        # FALLBACK: extrai codigo Dart puro da resposta
        if ia_solution:
            extracted = self.response_validator.force_code_extraction(ia_solution)
            if extracted:
                self._log("[FALLBACK] Codigo Dart extraido com sucesso")
                await self._apply_fix(extracted)
                return {'success': True}
"""
    content = content.replace(
        "return {'success': False}",
        fallback + "        return {'success': False}"
    )

    target.write_text(content, encoding='utf-8')
    log("[OK] main_orchestrator.py patched")
    return True

def add_force_code_extraction_if_missing():
    log("[PATCH] Verificando force_code_extraction no validador...")
    target = ORCHESTRATOR_DIR / "ia_response_validator.py"
    if not target.exists():
        log("[AVISO] ia_response_validator.py nao encontrado")
        return False
    content = target.read_text(encoding='utf-8', errors='ignore')
    if "def force_code_extraction" in content:
        log("[OK] force_code_extraction ja existe")
        return True
    new_method = """
    def force_code_extraction(self, response: str) -> Optional[str]:
        if not response or len(response.strip()) < 10:
            return None
        import re
        match = re.search(r'```(?:dart)?\\s*\\n(.*?)\\n```', response, re.DOTALL)
        if match:
            return match.group(1)
        if response.strip().startswith(('import', 'class', 'void', 'Widget')):
            return response
        match = re.search(r'```\\s*\\n(.*?)\\n```', response, re.DOTALL)
        if match:
            return match.group(1)
        return None
"""
    content += new_method
    target.write_text(content, encoding='utf-8')
    log("[OK] force_code_extraction adicionado ao validador")
    return True

def create_fallback_script():
    log("[SCRIPT] Criando fallback_build.bat...")
    script = PROJECT_ROOT / "fallback_build.bat"
    script.write_text('@echo off\necho [FALLBACK] Executando build manual...\nflutter clean\nflutter pub get\nflutter build apk --release --android-skip-build-dependency-validation\nif errorlevel 1 (\n    echo [FALLBACK] Build falhou. Tentando remover .kts...\n    cd android\\app\n    del build.gradle.kts 2>nul\n    cd ..\\..\n    flutter build apk --release --android-skip-build-dependency-validation\n)\npause\n', encoding='utf-8')
    log("[OK] fallback_build.bat criado")
    return True

def main():
    log("="*60)
    log("IMPLEMENTANDO PIPELINE HIBRIDO (JSON + DART PURO)")
    log("="*60)
    patch_flutter_orchestrator()
    patch_main_orchestrator()
    add_force_code_extraction_if_missing()
    create_fallback_script()
    log("="*60)
    log("[DONE] IMPLEMENTACAO CONCLUIDA!")
    log("")
    log("PIPELINE:")
    log("  1. IA com JSON (exige >=200 chars e {files:{...}})")
    log("  2. Se falhar, extrai codigo Dart puro")
    log("  3. Se ainda falhar, correcoes locais (.kts)")
    log("  4. Ultimo recurso: fallback_build.bat")
    log("")
    log("EXECUTE: python run_orchestrator.py")

if __name__ == "__main__":
    main()
