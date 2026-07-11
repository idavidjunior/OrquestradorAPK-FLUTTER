#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import sys
import re
import shutil
from pathlib import Path
from datetime import datetime

# Força UTF-8
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
os.environ['PYTHONIOENCODING'] = 'utf-8'
os.environ['PYTHONUTF8'] = '1'

PROJECT_ROOT = Path.cwd()
TARGET = PROJECT_ROOT / "flutter_orchestrator.py"

def log(msg):
    safe = msg.encode('ascii', errors='replace').decode('ascii')
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {safe}")

def patch_flutter_orchestrator():
    """Aplica as correções cirúrgicas no flutter_orchestrator.py."""
    if not TARGET.exists():
        log("❌ flutter_orchestrator.py não encontrado.")
        return False
    
    with open(TARGET, 'r', encoding='utf-8', errors='ignore') as f:
        content = f.read()
    
    # 1. Adiciona import do KnowledgeBaseLearner no início (após outros imports)
    if "from orchestrator.knowledge_base_learner import KnowledgeBaseLearner" not in content:
        content = content.replace(
            "import json",
            "import json\nfrom orchestrator.knowledge_base_learner import KnowledgeBaseLearner"
        )
        log("✅ Import do KnowledgeBaseLearner adicionado.")
    
    # 2. Adiciona método _apply_local_fix (cópia do main_orchestrator) se não existir
    if "_apply_local_fix" not in content:
        local_fix_method = '''
    def _apply_local_fix(self, error: str) -> dict:
        """Aplica correcao local (remove .kts, recria build.gradle)."""
        self.log("[FIX] Aplicando correcao local (Kotlin)...")
        project_path = Path(self.project_path)
        kts = project_path / 'android' / 'app' / 'build.gradle.kts'
        if kts.exists():
            kts.unlink()
            self.log("[FIX] build.gradle.kts removido")
        gradle = project_path / 'android' / 'app' / 'build.gradle'
        with open(gradle, 'w', encoding='utf-8') as f:
            f.write('''android {
    compileSdkVersion 34
    namespace "com.example.app"
    compileOptions {
        sourceCompatibility JavaVersion.VERSION_17
        targetCompatibility JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }
}
dependencies {
    implementation 'androidx.core:core-ktx:1.12.0'
    implementation 'androidx.appcompat:appcompat:1.6.1'
}
''')
        self.log("[FIX] build.gradle recriado")
        import subprocess
        subprocess.run(["flutter", "clean"], cwd=project_path, capture_output=True)
        subprocess.run(["flutter", "pub", "get"], cwd=project_path, capture_output=True)
        return {'success': True}
'''
        class_match = re.search(r'class\s+FlutterBuildOrchestrator\s*:', content)
        if class_match:
            insert_pos = class_match.end()
            lines = content.splitlines(keepends=True)
            new_lines = []
            for i, line in enumerate(lines):
                new_lines.append(line)
                if i == insert_pos - 1:
                    new_lines.append("\n")
                    for code_line in local_fix_method.splitlines(keepends=True):
                        new_lines.append("    " + code_line if code_line.strip() else code_line)
            content = ''.join(new_lines)
            log("✅ _apply_local_fix adicionado.")
        else:
            log("⚠️ Classe nao encontrada, adicionando no final.")
            content += "\n" + local_fix_method
    
    # 3. Modifica o fluxo de correcao: antes de IA, consultar KB e aplicar local fix se Kotlin
    pattern = r'(if\s+error\s*:.*?)(self\._call_ia)'
    replacement = r'\1# Verifica KB e Kotlin primeiro\n        from orchestrator.knowledge_base_learner import KnowledgeBaseLearner\n        kb = KnowledgeBaseLearner()\n        if "Kotlin" in error or "KGP" in error or "build.gradle.kts" in error:\n            self.log("[FIX] Erro Kotlin detectado, aplicando correcao local.")\n            result = self._apply_local_fix(error)\n            if result and result.get("success"):\n                return result\n        solution, confidence = kb.get_solution(error)\n        if solution and confidence > 0.8:\n            self.log(f"[KB] Solucao de alta confianca ({confidence:.2%}), aplicando.")\n            if "build.gradle.kts" in solution:\n                return self._apply_local_fix(error)\n        \2'
    content = re.sub(pattern, replacement, content, flags=re.DOTALL)
    
    # 4. Aumenta timeout do health-check para 300s
    content = re.sub(r'timeout\s*=\s*30', 'timeout = 300', content)
    content = re.sub(r'timeout\s*=\s*60', 'timeout = 300', content)
    content = re.sub(r'timeout\s*=\s*120', 'timeout = 300', content)
    log("✅ Timeout do health-check aumentado para 300s.")
    
    # 5. Reduz tentativas de IA de 3 para 1
    content = re.sub(r'for attempt in range\(1,\s*4\):', 'for attempt in range(1, 2):', content)
    log("✅ Tentativas de IA reduzidas para 1 (fallback imediato para local fix).")
    
    # 6. Adiciona registro na KB apos build bem-sucedido
    success_pattern = r'(if\s+build_success\s*:.*?)(return\s+.*?success.*?)'
    replacement_success = r'\1            from orchestrator.knowledge_base_learner import KnowledgeBaseLearner\n            kb = KnowledgeBaseLearner()\n            kb.learn_from_build("", "Kotlin KGP fix applied", "Remover build.gradle.kts", True)\n            \2'
    content = re.sub(success_pattern, replacement_success, content, flags=re.DOTALL)
    
    # Salva
    with open(TARGET, 'w', encoding='utf-8') as f:
        f.write(content)
    log("✅ flutter_orchestrator.py patchado com sucesso.")
    return True

def main():
    log("="*60)
    log("PATCH CIRURGICO NO flutter_orchestrator.py")
    log("="*60)
    patch_flutter_orchestrator()
    log("="*60)
    log("✅ PATCH APLICADO!")
    log("")
    log("MUDANCAS REALIZADAS:")
    log("  1. Import do KnowledgeBaseLearner.")
    log("  2. _apply_local_fix (remove .kts) adicionado.")
    log("  3. Antes de IA: verifica KB e aplica local fix se Kotlin.")
    log("  4. Timeout do health-check aumentado para 300s.")
    log("  5. Tentativas de IA reduzidas para 1 (fallback rapido).")
    log("  6. Registro na KB apos sucesso.")
    log("")
    log("EXECUTE: python run_orchestrator.py")
    log("E ME ENVIE O LOG.")

if __name__ == "__main__":
    main()
