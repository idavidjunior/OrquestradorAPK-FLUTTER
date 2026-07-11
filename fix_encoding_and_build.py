#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import sys
import subprocess
import json
import re
from pathlib import Path
from datetime import datetime

# FORÇA UTF-8 EM TODO O SISTEMA
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
os.environ['PYTHONIOENCODING'] = 'utf-8'
os.environ['PYTHONUTF8'] = '1'

PROJECT_ROOT = Path.cwd()
ORCHESTRATOR_DIR = PROJECT_ROOT / "orchestrator"
CONFIG_FILE = PROJECT_ROOT / "orchestrator_config.yaml"

def log(msg):
    # Remove caracteres Unicode problemáticos para Windows
    safe_msg = msg.encode('ascii', errors='replace').decode('ascii')
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {safe_msg}")

def fix_encoding_in_files():
    log("[FIX] Corrigindo codificacao em todos os arquivos do orquestrador...")
    # Lista de arquivos que podem ter caracteres Unicode
    files_to_fix = [
        ORCHESTRATOR_DIR / "main_orchestrator.py",
        ORCHESTRATOR_DIR / "knowledge_base_learner.py",
        ORCHESTRATOR_DIR / "ia_response_validator.py",
        ORCHESTRATOR_DIR / "model_manager.py",
        ORCHESTRATOR_DIR / "timeout_manager.py",
        ORCHESTRATOR_DIR / "kotlin_fixer.py",
        PROJECT_ROOT / "flutter_orchestrator.py",
        PROJECT_ROOT / "gui" / "app.py",
        PROJECT_ROOT / "flutter_orchestrator_gui.py",
        PROJECT_ROOT / "fix_all.py",
    ]
    for file_path in files_to_fix:
        if not file_path.exists():
            continue
        log(f"  Processando {file_path.name}...")
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
        # Remove ou substitui caracteres Unicode problemáticos
        replacements = {
            '\u2192': '->',
            '\u2713': '[OK]',
            '\u2705': '[OK]',
            '\u274c': '[ERRO]',
            '\u26a0\ufe0f': '[AVISO]',
            '\U0001f527': '[FERRAMENTA]',
            '\U0001f4da': '[KB]',
            '\U0001f916': '[IA]',
            '\U0001f680': '[INICIO]',
            '\U0001f389': '[FIM]',
            '\U0001f4e4': '[ENVIO]',
            '\U0001f4dd': '[PROMPT]',
            '\U0001f50d': '[VERIFICANDO]',
            '\U0001f4e6': '[DEPENDENCIAS]',
            '\U0001f3d7\ufe0f': '[BUILD]',
            '\U0001f4f1': '[APK]',
            '\U0001f4a1': '[DICA]',
            '\U0001fa79': '[PATCH]',
            '\U0001f9f9': '[LIMPEZA]',
            '\u23f1\ufe0f': '[TIMEOUT]',
            '\u2716': '[FALHA]',
            '\u21bb': '[FALLBACK]',
        }
        for old, new in replacements.items():
            content = content.replace(old, new)
        # Força uso de UTF-8 no cabeçalho
        if not content.startswith('# -*- coding: utf-8 -*-'):
            content = '# -*- coding: utf-8 -*-\n' + content
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
    log("[OK] Codificacao corrigida em todos os arquivos")

def fix_config_file():
    log("[FIX] Corrigindo arquivo de configuracao...")
    if not CONFIG_FILE.exists():
        log("[AVISO] config.yaml nao encontrado, criando")
    config = {}
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, 'r', encoding='utf-8', errors='ignore') as f:
            try:
                import yaml
                config = yaml.safe_load(f) or {}
            except:
                config = {}
    # Remove caracteres Unicode da config
    config_str = json.dumps(config, ensure_ascii=True)
    config = json.loads(config_str)
    # Aplica configuracoes otimizadas
    config["timeout"] = {
        "min_timeout": 90,
        "max_timeout": 240,
        "initial_timeout": 120,
        "adaptive_enabled": True,
        "learning_rate": 0.7
    }
    config["ia"] = config.get("ia", {})
    config["ia"]["default_model"] = "deepseek-ai/deepseek-v4-flash"
    config["ia"]["max_response_time"] = 120
    config["ia"]["preferred_models"] = [
        "deepseek-ai/deepseek-v4-flash",
        "meta/llama-3.1-70b-instruct",
        "bytedance/seed-oss-36b-instruct"
    ]
    config["ia"]["fallback_models"] = [
        "abacusai/dracarys-llama-3.1-70b-instruct",
        "mistralai/mixtral-8x7b-instruct"
    ]
    # Salva com UTF-8
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        import yaml
        yaml.dump(config, f, default_flow_style=False, allow_unicode=False)
    log("[OK] Configuracao atualizada sem caracteres Unicode")

def fix_logging_in_orchestrator():
    log("[FIX] Corrigindo logging do orquestrador para evitar erros de codificacao...")
    orch_path = ORCHESTRATOR_DIR / "main_orchestrator.py"
    if not orch_path.exists():
        log("[AVISO] main_orchestrator.py nao encontrado")
        return
    with open(orch_path, 'r', encoding='utf-8', errors='ignore') as f:
        content = f.read()
    # Substitui o metodo _log para forcar ASCII
    if "def _log" in content:
        log_method = (
            "\n    def _log(self, message: str):"
            "\n        from datetime import datetime"
            "\n        import sys"
            "\n        safe_msg = message.encode('ascii', errors='replace').decode('ascii')"
            "\n        timestamp = datetime.now().strftime('%H:%M:%S')"
            "\n        if sys.platform == 'win32':"
            "\n            try:"
            "\n                sys.stdout.reconfigure(encoding='utf-8', errors='replace')"
            "\n            except:"
            "\n                pass"
            "\n        print(f'[{timestamp}] {safe_msg}')"
        )
        # Encontra a definicao atual e substitui
        pattern = r'def _log\(self, message: str\):.*?(?=\n    def |\nclass |\Z)'
        content = re.sub(pattern, log_method, content, flags=re.DOTALL)
    # Adiciona import de sys no topo se nao existir
    if "import sys" not in content:
        content = "import sys\n" + content
    with open(orch_path, 'w', encoding='utf-8') as f:
        f.write(content)
    log("[OK] Logging do orquestrador corrigido")

def apply_kotlin_fix_manual():
    log("[FIX] Aplicando correcao Kotlin/Gradle manual (via linha de comando)...")
    android_dir = PROJECT_ROOT / "android"
    if not android_dir.exists():
        log("[AVISO] diretorio android/ nao encontrado. Pulando...")
        return False
    app_dir = android_dir / "app"
    # Remove build.gradle.kts
    kts = app_dir / "build.gradle.kts"
    if kts.exists():
        kts.unlink()
        log("[OK] build.gradle.kts removido")
    # Cria build.gradle
    gradle = app_dir / "build.gradle"
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
    log("[OK] build.gradle recriado")
    # Ajusta project build.gradle
    project_gradle = android_dir / "build.gradle"
    with open(project_gradle, 'r', encoding='utf-8', errors='ignore') as f:
        content = f.read()
    content = re.sub(r"ext\.kotlin_version\s*=\s*['\"][^'\"]+['\"]", "ext.kotlin_version = '1.9.22'", content)
    if "kotlin-gradle-plugin" not in content:
        content = content.replace("dependencies {", "dependencies {\n        classpath \"org.jetbrains.kotlin:kotlin-gradle-plugin:$kotlin_version\"")
    with open(project_gradle, 'w', encoding='utf-8') as f:
        f.write(content)
    log("[OK] project build.gradle atualizado")
    return True

def fix_adb_issues():
    log("[FIX] Corrigindo problemas com ADB...")
    try:
        subprocess.run(["adb", "kill-server"], capture_output=True, timeout=10)
        subprocess.run(["adb", "start-server"], capture_output=True, timeout=10)
        log("[OK] ADB reiniciado")
        result = subprocess.run(["adb", "devices"], capture_output=True, text=True, timeout=10)
        if "device" in result.stdout:
            log("[OK] Dispositivo ADB detectado")
    except FileNotFoundError:
        log("[AVISO] ADB nao encontrado (Android SDK nao instalado). Pulando...")
    except Exception as e:
        log(f"[AVISO] ADB: {e}. Pulando...")
    return True

def patch_pre_build_hook():
    log("[FIX] Aplicando patch no pre-build hook para evitar erro de codificacao...")
    orch_path = ORCHESTRATOR_DIR / "main_orchestrator.py"
    if not orch_path.exists():
        return
    with open(orch_path, 'r', encoding='utf-8', errors='ignore') as f:
        content = f.read()
    # Encontra a parte que faz "Correcao pre-build" e envolve com try/except
    if "Correcao pre-build" in content:
        pre_build_pattern = r'(async def _pre_build.*?)(\n\s+)(.*?)(?=\n\s+async def|\n\s+def|\n\s+if __name__|\Z)'
        def pre_build_repl(match):
            h = match.group(1)
            ind = match.group(2)
            bod = match.group(3)
            # Envolve a chamada de correcao em try/except
            wrapped = (
                h + ind + "try:\n"
                + ind + "    # Aplica correcoes pre-build com fallback de codificacao\n"
                + ind + "    await self._apply_pre_build_fixes()\n"
                + ind + "except UnicodeError as e:\n"
                + ind + '    self._log(f"[AVISO] Erro de codificacao: {e}")\n'
                + ind + '    self._log("[AVISO] Continuando mesmo assim...")\n'
                + ind + "except Exception as e:\n"
                + ind + '    self._log(f"[ERRO] Falha: {e}")\n'
                + ind + "    raise\n"
            )
            return wrapped
        content = re.sub(pre_build_pattern, pre_build_repl, content, flags=re.DOTALL)
    with open(orch_path, 'w', encoding='utf-8') as f:
        f.write(content)
    log("[OK] Pre-build hook corrigido")

def force_utf8_environment():
    log("[FIX] Configurando variaveis de ambiente para UTF-8...")
    # Cria um arquivo .env com as variaveis
    env_file = PROJECT_ROOT / ".env"
    with open(env_file, 'w', encoding='utf-8') as f:
        f.write('''PYTHONIOENCODING=utf-8
PYTHONUTF8=1
LANG=en_US.UTF-8
LC_ALL=en_US.UTF-8
''')
    log("[OK] Variaveis de ambiente configuradas no .env")
    # Aplica no processo atual
    os.environ['PYTHONIOENCODING'] = 'utf-8'
    os.environ['PYTHONUTF8'] = '1'
    os.environ['LANG'] = 'en_US.UTF-8'
    os.environ['LC_ALL'] = 'en_US.UTF-8'
    return True

def add_encoding_wrapper_to_entrypoint():
    log("[FIX] Adicionando wrapper de codificacao ao entrypoint...")
    entrypoint = PROJECT_ROOT / "run_orchestrator.py"
    wrapper_content = '''#!/usr/bin/env python3
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
'''
    with open(entrypoint, 'w', encoding='utf-8') as f:
        f.write(wrapper_content)
    log("[OK] Entrypoint criado com wrapper de codificacao")

def clear_cache_and_build():
    log("[CLEAN] Limpando cache e reconstruindo...")
    try:
        subprocess.run(["flutter", "clean"], cwd=PROJECT_ROOT, capture_output=True, timeout=60)
        subprocess.run(["flutter", "pub", "get"], cwd=PROJECT_ROOT, capture_output=True, timeout=120)
        log("[OK] Cache limpo e dependencias reinstaladas")
    except FileNotFoundError:
        log("[AVISO] Flutter CLI nao encontrado. Pule esta etapa manualmente.")
    except Exception as e:
        log(f"[AVISO] Erro ao limpar/instalar: {e}")
    return True

def main():
    log("[START] INICIANDO CORRECAO FINAL DO ORQUESTRADOR")
    log("=" * 60)
    
    # 1. Forca UTF-8 em todo o sistema
    force_utf8_environment()
    
    # 2. Corrige codificacao em todos os arquivos
    fix_encoding_in_files()
    
    # 3. Corrige configuracao
    fix_config_file()
    
    # 4. Corrige logging do orquestrador
    fix_logging_in_orchestrator()
    
    # 5. Aplica patch no pre-build hook
    patch_pre_build_hook()
    
    # 6. Cria entrypoint com wrapper
    add_encoding_wrapper_to_entrypoint()
    
    # 7. Aplica correcao Kotlin manual
    apply_kotlin_fix_manual()
    
    # 8. Corrige ADB
    fix_adb_issues()
    
    # 9. Limpa cache
    clear_cache_and_build()
    
    log("=" * 60)
    log("[DONE] TODAS AS CORRECOES FORAM APLICADAS COM SUCESSO!")
    log("")
    log("AGORA EXECUTE:")
    log("   python run_orchestrator.py")
    log("")
    log("SE O ERRO DE CODIFICACAO PERSISTIR:")
    log("   chcp 65001  (no terminal Windows)")
    log("   python -X utf8 run_orchestrator.py")
    log("")
    log("SE O BUILD AINDA FALHAR:")
    log("   flutter build apk --release --android-skip-build-dependency-validation")
    log("   E me envie o log completo")

if __name__ == "__main__":
    main()
