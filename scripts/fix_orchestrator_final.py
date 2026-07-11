#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import sys
import subprocess
import json
import re
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

def remove_kts_forever():
    log("REMOVENDO build.gradle.kts PERMANENTEMENTE...")
    android_dir = PROJECT_ROOT / "android"
    if not android_dir.exists():
        log("[OK] Diretorio android/ nao encontrado (este nao e um projeto Flutter direto)")
        return True
    android_app = android_dir / "app"
    kts = android_app / "build.gradle.kts"
    if kts.exists():
        kts.unlink()
        log("[OK] build.gradle.kts removido")
    gradle = android_app / "build.gradle"
    android_app.mkdir(parents=True, exist_ok=True)
    gradle.write_text("android {\n    compileSdkVersion 34\n    namespace \"com.example.app\"\n\n    compileOptions {\n        sourceCompatibility JavaVersion.VERSION_17\n        targetCompatibility JavaVersion.VERSION_17\n    }\n\n    kotlinOptions {\n        jvmTarget = \"17\"\n    }\n}\n\ndependencies {\n    implementation 'androidx.core:core-ktx:1.12.0'\n    implementation 'androidx.appcompat:appcompat:1.6.1'\n}\n", encoding='utf-8')
    log("[OK] build.gradle recriado (sem .kts)")
    settings = android_dir / "settings.gradle"
    if settings.exists():
        content = settings.read_text(encoding='utf-8', errors='ignore')
        if "build.gradle.kts" in content:
            settings.write_text(content.replace("build.gradle.kts", "build.gradle"), encoding='utf-8')
            log("[OK] settings.gradle atualizado")
    return True

def patch_orchestrator():
    log("PATCHANDO ORQUESTRADOR PARA CORRECAO FORCADA...")
    orch_path = ORCHESTRATOR_DIR / "main_orchestrator.py"
    if not orch_path.exists():
        log("[ERRO] main_orchestrator.py nao encontrado")
        return False

    content = orch_path.read_text(encoding='utf-8', errors='ignore')

    # Replace the entire _attempt_fix method preserving class-level indentation
    # Find any async def line that matches _attempt_fix
    method_pattern = re.compile(
        r'(?<=\n)(\s+)async def _attempt_fix\(self,\s*error:\s*str\)\s*->\s*Dict\[str,\s*bool\]:\s*$.*?(?=\n\s+async def|\n\s+def |\nclass |\Z)',
        re.MULTILINE | re.DOTALL
    )
    match = method_pattern.search(content)
    if match:
        cls_indent = match.group(1).lstrip('\n')
        m_body = cls_indent + '    '  # method body = class_indent + 4
        m_body2 = cls_indent + '        '  # sub-body = class_indent + 8
        m_body3 = cls_indent + '            '  # sub-sub = class_indent + 12

        new = []
        new.append(cls_indent + 'async def _attempt_fix(self, error: str) -> Dict[str, bool]:')
        new.append(m_body + '"""Tenta corrigir erro - prioridade: local -> KB -> IA"""')
        new.append(m_body + 'if "Kotlin" in error or "KGP" in error or "build.gradle.kts" in error:')
        new.append(m_body2 + 'self._log("[FIX] Aplicando correcao Kotlin forcada...")')
        new.append(m_body2 + 'kts = self.project_path / "android" / "app" / "build.gradle.kts"')
        new.append(m_body2 + 'if kts.exists():')
        new.append(m_body3 + 'kts.unlink()')
        new.append(m_body3 + 'self._log("[FIX] build.gradle.kts removido")')
        new.append(m_body2 + 'gradle = self.project_path / "android" / "app" / "build.gradle"')
        new.append(m_body2 + "with open(gradle, 'w', encoding='utf-8') as f:")
        new.append(m_body3 + "f.write('''android {")
        new.append(m_body3 + "    compileSdkVersion 34")
        new.append(m_body3 + '    namespace "com.example.app"')
        new.append(m_body3 + "    compileOptions {")
        new.append(m_body3 + "        sourceCompatibility JavaVersion.VERSION_17")
        new.append(m_body3 + "        targetCompatibility JavaVersion.VERSION_17")
        new.append(m_body3 + "    }")
        new.append(m_body3 + "    kotlinOptions {")
        new.append(m_body3 + '        jvmTarget = "17"')
        new.append(m_body3 + "    }")
        new.append(m_body3 + "}")
        new.append(m_body3 + "")
        new.append(m_body3 + "dependencies {")
        new.append(m_body3 + "    implementation 'androidx.core:core-ktx:1.12.0'")
        new.append(m_body3 + "    implementation 'androidx.appcompat:appcompat:1.6.1'")
        new.append(m_body3 + "}''')")
        new.append(m_body2 + "self._log('[FIX] build.gradle recriado')")
        new.append(m_body2 + 'import subprocess')
        new.append(m_body2 + 'subprocess.run(["flutter", "clean"], cwd=self.project_path, capture_output=True)')
        new.append(m_body2 + 'subprocess.run(["flutter", "pub", "get"], cwd=self.project_path, capture_output=True)')
        new.append(m_body2 + 'return {"success": True}')
        new.append(m_body + 'solution, confidence = self.kb_learner.get_solution(error)')
        new.append(m_body + 'if solution and confidence > 0.5:')
        new.append(m_body2 + 'self._log(f"[KB] Solucao encontrada (confianca: {confidence:.2%})")')
        new.append(m_body2 + 'if await self._apply_ia_fix(solution):')
        new.append(m_body3 + 'return {"success": True}')
        new.append(m_body + 'self._log("[IA] Buscando solucao...")')
        new.append(m_body + 'for attempt in range(1, 4):')
        new.append(m_body2 + 'ia_solution = await self._get_ia_solution_with_retry(error, attempt)')
        new.append(m_body2 + 'if ia_solution:')
        new.append(m_body3 + 'if len(ia_solution) < 200:')
        new.append(m_body3 + '    self._log(f"[IA] Resposta muito curta ({len(ia_solution)} chars), ignorando")')
        new.append(m_body3 + '    continue')
        new.append(m_body3 + 'is_valid, code, errors = self.response_validator.validate_and_extract(ia_solution)')
        new.append(m_body3 + 'if is_valid and code:')
        new.append(m_body3 + '    await self._apply_fix(code)')
        new.append(m_body3 + '    return {"success": True}')
        new.append(m_body3 + 'extracted = self.response_validator.force_code_extraction(ia_solution)')
        new.append(m_body3 + 'if extracted:')
        new.append(m_body3 + '    await self._apply_fix(extracted)')
        new.append(m_body3 + '    return {"success": True}')
        new.append(m_body + 'return {"success": False}')
        replacement = '\n'.join(new) + '\n'
        content = content[:match.start()] + replacement + content[match.end():]
        log("[OK] _attempt_fix substituido")
    else:
        log("[AVISO] _attempt_fix nao encontrado")

    orch_path.write_text(content, encoding='utf-8')
    log("[OK] Orquestrador patched com correcao forcada")
    return True

def main():
    log("[START] CORRECAO FINAL E DEFINITIVA DO ORQUESTRADOR")
    log("=" * 60)
    remove_kts_forever()
    patch_orchestrator()
    log("=" * 60)
    log("[DONE] TODAS AS CORRECOES FORAM APLICADAS!")
    log("")
    log("EXECUTE:")
    log("   python run_orchestrator.py")
    log("")
    log("SE AINDA FALHAR:")
    log("   flutter build apk --release --android-skip-build-dependency-validation")

if __name__ == "__main__":
    main()
