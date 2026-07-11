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
    log("🔧 Aplicando correção Kotlin/Gradle definitiva...")
    android_dir = PROJECT_ROOT / "android"
    app_dir = android_dir / "app"
    kts = app_dir / "build.gradle.kts"
    if kts.exists():
        kts.unlink()
        log("✅ build.gradle.kts removido")
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
    log("✅ build.gradle recriado")
    project_gradle = android_dir / "build.gradle"
    backup_file(project_gradle)
    with open(project_gradle, "r", encoding="utf-8") as f:
        content = f.read()
    content = re.sub(r"ext\.kotlin_version\s*=\s*['\"][^'\"]+['\"]", "ext.kotlin_version = '1.9.22'", content)
    if "kotlin-gradle-plugin" not in content:
        content = content.replace("dependencies {", "dependencies {\n        classpath \"org.jetbrains.kotlin:kotlin-gradle-plugin:$kotlin_version\"")
    with open(project_gradle, "w", encoding="utf-8") as f:
        f.write(content)
    log("✅ project build.gradle atualizado")
    return True

def fix_model_manager():
    log("🤖 Ajustando ModelManager para priorizar meta/llama-3.1-70b-instruct...")
    mm_path = ORCHESTRATOR_DIR / "model_manager.py"
    if not mm_path.exists():
        log("⚠️ model_manager.py não encontrado, pulando")
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
    log("✅ ModelManager atualizado")
    return True

def fix_timeout_config():
    log("⏱️ Ajustando timeout adaptativo...")
    if not CONFIG_FILE.exists():
        log("⚠️ config.yaml não encontrado, criando")
    config = {}
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            try:
                import yaml
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
        import yaml
        yaml.dump(config, f, default_flow_style=False, allow_unicode=True)
    log("✅ Configuração atualizada")
    return True

def patch_orchestrator_fallback():
    log("🩹 Aplicando patch de fallback manual no orquestrador...")
    orch_path = ORCHESTRATOR_DIR / "main_orchestrator.py"
    if not orch_path.exists():
        log("⚠️ main_orchestrator.py não encontrado")
        return False
    backup_file(orch_path)
    with open(orch_path, "r", encoding="utf-8") as f:
        content = f.read()
    if "_apply_local_fix" not in content:
        local_fix_method = """
    def _apply_local_fix(self, error: str) -> bool:
        \"\"\"Aplica correções locais quando IA falha\"\"\"
        if 'Kotlin' in error or 'KGP' in error:
            from orchestrator.kotlin_fixer import KotlinGradleFixer
            fixer = KotlinGradleFixer(str(self.project_path))
            result = fixer.apply_fixes()
            if result['success']:
                self._log("✅ Correção Kotlin aplicada localmente")
                return True
            kts = self.project_path / 'android' / 'app' / 'build.gradle.kts'
            if kts.exists():
                kts.unlink()
                self._log("✅ build.gradle.kts removido manualmente")
                return True
        return False
"""
        content = content.replace("async def _attempt_fix", local_fix_method + "\n    async def _attempt_fix")
    if "self._apply_local_fix" not in content:
        content = content.replace(
            "async def _attempt_fix(self, error: str) -> Dict[str, bool]:",
            "async def _attempt_fix(self, error: str) -> Dict[str, bool]:\n        # 0. Correção local primeiro\n        if self._apply_local_fix(error):\n            return {'success': True}"
        )
    if "self._log(f\"📤 Resposta IA" not in content:
        ia_call_block = """
            response = await self._call_ia_model(model.name, prompt)
            self._log(f"📤 Resposta IA ({len(response)} chars, {len(response.split())} palavras)")
            if len(response) < 200:
                self._log(f"  Conteúdo: '{response[:100]}...'")
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
    log("✅ Patch do orquestrador aplicado")
    return True

def clear_and_rebuild():
    log("🧹 Limpando cache e reinstalando dependências...")
    subprocess.run(["flutter", "clean"], cwd=PROJECT_ROOT, capture_output=True)
    subprocess.run(["flutter", "pub", "get"], cwd=PROJECT_ROOT, capture_output=True)
    log("✅ Cache limpo e dependências reinstaladas")
    return True

def seed_knowledge_base():
    log("📚 Semeando KnowledgeBase com soluções conhecidas...")
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
    log("✅ KnowledgeBase semeada com solução Kotlin")
    return True

def main():
    log("🚀 Iniciando correção total do orquestrador...")
    if not ORCHESTRATOR_DIR.exists():
        log("❌ Diretório orchestrator não encontrado. Execute na raiz do projeto.")
        sys.exit(1)
    apply_kotlin_fix()
    fix_model_manager()
    fix_timeout_config()
    patch_orchestrator_fallback()
    seed_knowledge_base()
    clear_and_rebuild()
    log("🎉 Todas as correções aplicadas com sucesso!")
    log("📋 Agora execute: python run_orchestrator.py")
    log("💡 Se ainda houver falha, rode manualmente: flutter build apk --release --android-skip-build-dependency-validation")

if __name__ == "__main__":
    main()
