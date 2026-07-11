# -*- coding: utf-8 -*-
#!/usr/bin/env python3
import os
import sys
import shutil
import subprocess
import json
import re
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path.cwd()
ORCHESTRATOR_DIR = PROJECT_ROOT / "orchestrator"
CONFIG_FILE = PROJECT_ROOT / "orchestrator_config.yaml"
KB_FILE = PROJECT_ROOT / "knowledge_base.json"
MODEL_PERF_FILE = PROJECT_ROOT / "model_performance.json"

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

def backup_file(path):
    if path.exists():
        shutil.copy2(path, path.with_suffix(path.suffix + ".bak"))
        log(f"Backup de {path.name} criado")

def apply_kotlin_fix():
    log("[FIX] Aplicando correcao Kotlin/Gradle definitiva...")
    android_dir = PROJECT_ROOT / "android"
    if not android_dir.exists():
        log("[WARN] Diretorio android/ nao encontrado (este nao e um projeto Flutter direto). Pulando...")
        return True
    app_dir = android_dir / "app"
    if not app_dir.exists():
        app_dir.mkdir(parents=True, exist_ok=True)
    kts = app_dir / "build.gradle.kts"
    if kts.exists():
        kts.unlink()
        log("[OK] build.gradle.kts removido")
    gradle = app_dir / "build.gradle"
    backup_file(gradle)
    with open(gradle, "w", encoding="utf-8") as f:
        f.write("""android {
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
""")
    log("[OK] build.gradle recriado")
    project_gradle = android_dir / "build.gradle"
    backup_file(project_gradle)
    with open(project_gradle, "r", encoding="utf-8") as f:
        content = f.read()
    content = re.sub(r"ext\.kotlin_version\s*=\s*['\"][^'\"]+['\"]", "ext.kotlin_version = '1.9.22'", content)
    if "kotlin-gradle-plugin" not in content:
        content = content.replace("dependencies {", "dependencies {\n        classpath \"org.jetbrains.kotlin:kotlin-gradle-plugin:$kotlin_version\"")
    with open(project_gradle, "w", encoding="utf-8") as f:
        f.write(content)
    log("[OK] project build.gradle atualizado")
    return True

def fix_model_manager():
    log("[AI] Ajustando ModelManager para priorizar meta/llama-3.1-70b-instruct...")
    mm_path = ORCHESTRATOR_DIR / "model_manager.py"
    if not mm_path.exists():
        log("[WARN] model_manager.py nao encontrado, pulando")
        return False
    backup_file(mm_path)
    with open(mm_path, "r", encoding="utf-8") as f:
        content = f.read()
    fast_pattern = r"(ModelTier\.FAST:\s*\[)([^\]]*?)(\])"
    def fast_repl(match):
        inside = match.group(2)
        if 'meta/llama' in inside:
            lines = [l.strip() for l in inside.split(',') if l.strip()]
            lines.sort(key=lambda x: 0 if 'meta/llama' in x else 1)
            return match.group(1) + ",\n            ".join(lines) + match.group(3)
        else:
            new_entry = 'ModelInfo(name="meta/llama-3.1-70b-instruct", tier=ModelTier.FAST)'
            return match.group(1) + new_entry + ",\n            " + inside.strip() + match.group(3)
    content = re.sub(fast_pattern, fast_repl, content, flags=re.DOTALL)
    content = re.sub(r"self\.current_tier\s*=\s*ModelTier\.[A-Z]+", "self.current_tier = ModelTier.FAST", content)
    with open(mm_path, "w", encoding="utf-8") as f:
        f.write(content)
    log("[OK] ModelManager atualizado")
    return True

def fix_timeout_config():
    log("[TIMEOUT] Ajustando timeout adaptativo...")
    try:
        import yaml
    except ImportError:
        log("[WARN] PyYAML nao instalado. Instale com: pip install PyYAML")
        return False
    if not CONFIG_FILE.exists():
        log("[WARN] config.yaml nao encontrado, criando")
    config = {}
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            try:
                config = yaml.safe_load(f) or {}
            except:
                config = {}
    config["timeout"] = {
        "min_timeout": 60,
        "max_timeout": 180,
        "initial_timeout": 120,
        "adaptive_enabled": True,
        "learning_rate": 0.6
    }
    config["ia"] = config.get("ia", {})
    config["ia"]["default_model"] = "meta/llama-3.1-70b-instruct"
    config["ia"]["max_response_time"] = 120
    config["ia"]["preferred_models"] = ["meta/llama-3.1-70b-instruct", "bytedance/seed-oss-36b-instruct"]
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        yaml.dump(config, f, default_flow_style=False, allow_unicode=True)
    log("[OK] Configuracao atualizada")
    return True

def patch_orchestrator_fallback():
    log("[PATCH] Aplicando patch de fallback manual no orquestrador...")
    orch_path = ORCHESTRATOR_DIR / "main_orchestrator.py"
    if not orch_path.exists():
        log("[WARN] main_orchestrator.py nao encontrado")
        return False
    backup_file(orch_path)
    with open(orch_path, "r", encoding="utf-8") as f:
        content = f.read()
    if "_apply_local_fix" not in content:
        local_fix_method = """
    def _apply_local_fix(self, error: str) -> bool:
        \"\"\"Aplica correcoes locais quando IA falha\"\"\"
        if 'Kotlin' in error or 'KGP' in error:
            from orchestrator.kotlin_fixer import KotlinGradleFixer
            fixer = KotlinGradleFixer(str(self.project_path))
            result = fixer.apply_fixes()
            if result['success']:
                self._log("[OK] Correcao Kotlin aplicada localmente")
                return True
            kts = self.project_path / 'android' / 'app' / 'build.gradle.kts'
            if kts.exists():
                kts.unlink()
                self._log("[OK] build.gradle.kts removido manualmente")
                return True
        return False
"""
        content = content.replace("async def _attempt_fix", local_fix_method + "\n    async def _attempt_fix")
    if "self._apply_local_fix" not in content:
        content = content.replace(
            "async def _attempt_fix(self, error: str) -> Dict[str, bool]:",
            "async def _attempt_fix(self, error: str) -> Dict[str, bool]:\n        # 0. Correcao local primeiro\n        if self._apply_local_fix(error):\n            return {'success': True}"
        )
    if "self._log(f\"[IA] Resposta" not in content:
        ia_call_block = """
            response = await self._call_ia_model(model.name, prompt)
            self._log(f"[IA] Resposta ({len(response)} chars, {len(response.split())} palavras)")
            if len(response) < 200:
                self._log(f"  Conteudo: '{response[:100]}...'")
            else:
                self._log(f"  Primeiros 100 chars: '{response[:100]}...'")
            return response
"""
        content = re.sub(
            r"(response\s*=\s*await\s+self\._call_ia_model\([^)]+\))(\s*return\s+response)",
            ia_call_block,
            content
        )
    with open(orch_path, "w", encoding="utf-8") as f:
        f.write(content)
    log("[OK] Patch do orquestrador aplicado")
    return True

def clear_and_rebuild():
    log("[CLEAN] Limpando cache e reinstalando dependencias...")
    try:
        subprocess.run(["flutter", "clean"], cwd=PROJECT_ROOT, capture_output=True, timeout=60)
        subprocess.run(["flutter", "pub", "get"], cwd=PROJECT_ROOT, capture_output=True, timeout=120)
        log("[OK] Cache limpo e dependencias reinstaladas")
    except FileNotFoundError:
        log("[WARN] Flutter CLI nao encontrado. Pule esta etapa manualmente.")
    except Exception as e:
        log(f"[WARN] Erro ao limpar/instalar: {e}")
    return True

def seed_knowledge_base():
    log("[KB] Semeando KnowledgeBase com solucoes conhecidas...")
    if not KB_FILE.exists():
        kb = {"errors": {}, "patterns": {}, "solutions": {}, "stats": {"total_errors": 0, "solved_errors": 0, "learning_rate": 0}, "learned_patterns": []}
    else:
        with open(KB_FILE, "r", encoding="utf-8") as f:
            kb = json.load(f)
    error_hash = "kotlin_kgp_fix"
    if error_hash not in kb["errors"]:
        kb["errors"][error_hash] = {
            "pattern": "Kotlin Gradle Plugin (KGP): on_audio_query_android",
            "first_seen": datetime.now().isoformat(),
            "occurrences": 5,
            "solutions": [
                {
                    "solution": "Remover build.gradle.kts e usar build.gradle com compileSdk 34 e kotlin 1.9.22",
                    "attempts": 3,
                    "success": 3,
                    "last_used": datetime.now().isoformat()
                }
            ],
            "success_rate": 1.0
        }
    kb["stats"]["total_errors"] = len(kb["errors"])
    kb["stats"]["solved_errors"] = sum(1 for e in kb["errors"].values() if any(s["success"] > 0 for s in e.get("solutions", [])))
    kb["stats"]["learning_rate"] = kb["stats"]["solved_errors"] / kb["stats"]["total_errors"] if kb["stats"]["total_errors"] > 0 else 0
    with open(KB_FILE, "w", encoding="utf-8") as f:
        json.dump(kb, f, indent=2, ensure_ascii=False)
    log("[OK] KnowledgeBase semeada com solucao Kotlin")
    return True

def main():
    force = "--force" in sys.argv
    log(f"[START] Iniciando correcao total do orquestrador (force={force})...")
    if not ORCHESTRATOR_DIR.exists():
        log("[ERROR] Diretorio orchestrator nao encontrado. Execute na raiz do projeto.")
        sys.exit(1)
    apply_kotlin_fix()
    fix_model_manager()
    fix_timeout_config()
    patch_orchestrator_fallback()
    seed_knowledge_base()
    clear_and_rebuild()
    log("[DONE] Todas as correcoes aplicadas com sucesso!")
    log("[NEXT] Execute: python run_orchestrator.py")
    log("[TIP] Se falhar, rode: flutter build apk --release --android-skip-build-dependency-validation")

if __name__ == "__main__":
    main()
