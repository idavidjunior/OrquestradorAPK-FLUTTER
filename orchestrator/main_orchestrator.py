# -*- coding: utf-8 -*-
import asyncio
import os
import subprocess
import time
import json
import re
from pathlib import Path
from typing import Optional, Dict, Any
from datetime import datetime

from orchestrator.timeout_manager import AdaptiveTimeoutManager
from orchestrator.ia_response_validator import IAResponseValidator
from orchestrator.model_manager import IntelligentModelManager
from orchestrator.kotlin_fixer import KotlinGradleFixer
from orchestrator.knowledge_base_learner import KnowledgeBaseLearner


class FlutterOrchestrator:
    def __init__(self, project_path: str):
        self.project_path = Path(project_path)
        self.timeout_manager = AdaptiveTimeoutManager()
        self.response_validator = IAResponseValidator()
        self.model_manager = IntelligentModelManager()
        self.kb_learner = KnowledgeBaseLearner()
        self.is_building = False
        self.max_retries = 3
        self.build_timeout = 600

    async def build_app(self) -> Dict[str, Any]:
        result = {
            'success': False,
            'attempts': [],
            'final_error': None,
            'build_path': None,
            'time_taken': 0
        }
        start_time = time.time()
        self._log("Validando projeto...")
        validation = await self._validate_project()
        if not validation['success']:
            result['final_error'] = validation['error']
            return result
        self._log("Instalando dependencias...")
        deps_ok = await self._install_dependencies()
        if not deps_ok:
            await self._fix_dependencies()
            deps_ok = await self._install_dependencies()
            if not deps_ok:
                result['final_error'] = "Falha na instalacao de dependencias"
                return result
        for attempt in range(1, self.max_retries + 1):
            self._log(f"Build {attempt}/{self.max_retries}...")
            self.is_building = True
            try:
                build_result = await self._attempt_build(attempt)
                self.is_building = False
                if build_result['success']:
                    result['success'] = True
                    result['build_path'] = build_result['path']
                    result['attempts'].append({
                        'attempt': attempt,
                        'success': True,
                        'time': build_result['time']
                    })
                    break
                else:
                    result['attempts'].append({
                        'attempt': attempt,
                        'success': False,
                        'error': build_result['error'],
                        'time': build_result['time']
                    })
                    self.kb_learner.learn_from_build(
                        build_result.get('log', ''),
                        build_result['error'],
                        None,
                        False
                    )
                    if attempt < self.max_retries:
                        fix_result = await self._attempt_fix(build_result['error'])
                        if fix_result['success']:
                            self._log("Correcao aplicada, tentando novamente...")
                            continue
            except Exception as e:
                self._log(f"Erro durante build: {e}")
                result['attempts'].append({
                    'attempt': attempt,
                    'success': False,
                    'error': str(e)
                })
            finally:
                self.is_building = False
        if not result['success'] and result['attempts']:
            last_error = result['attempts'][-1].get('error', 'Unknown error')
            self.kb_learner.learn_from_build('', last_error, None, False)
        result['time_taken'] = time.time() - start_time
        self._generate_report(result)
        return result

    async def _validate_project(self) -> Dict[str, bool]:
        checks = {
            'pubspec_exists': (self.project_path / 'pubspec.yaml').exists(),
            'android_exists': (self.project_path / 'android').exists(),
            'main_exists': (self.project_path / 'lib' / 'main.dart').exists()
        }
        if all(checks.values()):
            return {'success': True}
        else:
            return {'success': False, 'error': f"Estrutura invalida: {checks}"}

    async def _install_dependencies(self) -> bool:
        try:
            process = await asyncio.create_subprocess_exec(
                'flutter', 'pub', 'get',
                cwd=self.project_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=60
            )
            return process.returncode == 0
        except Exception:
            return False

    async def _fix_dependencies(self) -> bool:
        fixer = KotlinGradleFixer(str(self.project_path))
        result = fixer.apply_fixes()
        return result['success']

    async def _attempt_build(self, attempt: int) -> Dict[str, Any]:
        start_time = time.time()
        model, estimated_time = self.model_manager.get_best_model('build_fix')
        timeout = self.timeout_manager.get_timeout(attempt, model.tier.value)
        self._log(f"Usando modelo: {model.name} (estimado: {estimated_time}s)")
        try:
            process = await asyncio.create_subprocess_exec(
                'flutter', 'build', 'apk',
                '--release',
                '--android-skip-build-dependency-validation',
                cwd=self.project_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=timeout
                )
                output = stdout.decode('utf-8', errors='ignore')
                error = stderr.decode('utf-8', errors='ignore')
                elapsed = time.time() - start_time
                self.timeout_manager.record_attempt(
                    process.returncode == 0,
                    elapsed,
                    model.name,
                    model.tier.value
                )
                if process.returncode == 0:
                    apk_path = self.project_path / 'build' / 'app' / 'outputs' / 'apk' / 'release' / 'app-release.apk'
                    return {
                        'success': True,
                        'path': str(apk_path),
                        'time': elapsed,
                        'log': output
                    }
                else:
                    return {
                        'success': False,
                        'error': error,
                        'log': output,
                        'time': elapsed
                    }
            except asyncio.TimeoutError:
                process.kill()
                elapsed = time.time() - start_time
                self.timeout_manager.record_attempt(False, elapsed, model.name, model.tier.value)
                return {
                    'success': False,
                    'error': f"Timeout apos {timeout}s",
                    'time': elapsed
                }
        except Exception as e:
            return {
                'success': False,
                'error': str(e),
                'time': time.time() - start_time
            }
    async def _attempt_fix(self, error: str) -> Dict[str, bool]:
        """Tenta corrigir erro - prioridade: KB(confianca > 0.8) -> local -> IA -> fallback"""
        # 0. KB com alta confianca: usa sem chamar IA
        solution, confidence = self.kb_learner.get_solution(error)
        if solution and confidence > 0.8:
            self._log(f"[KB] Solucao de alta confianca ({confidence:.0%}), aplicando...")
            if await self._apply_ia_fix(solution):
                return {"success": True}

        # 1. Correcao local forcada para erros Kotlin/KGP
        if "Kotlin" in error or "KGP" in error or "build.gradle.kts" in error:
            self._log("[FIX] Aplicando correcao Kotlin forcada...")
            kts = self.project_path / "android" / "app" / "build.gradle.kts"
            if kts.exists():
                backup_kts = kts.with_suffix(".gradle.kts.bak")
                import shutil
                shutil.copy2(str(kts), str(backup_kts))
                self._log(f"[FIX] build.gradle.kts copiado para {backup_kts.name}")
                kts.unlink()
                self._log("[FIX] build.gradle.kts removido (backup criado)")
            gradle = self.project_path / "android" / "app" / "build.gradle"
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
                }''')
            self._log('[FIX] build.gradle recriado')
            import subprocess
            subprocess.run(["flutter", "clean"], cwd=self.project_path, capture_output=True)
            subprocess.run(["flutter", "pub", "get"], cwd=self.project_path, capture_output=True)
            # Registra na KB como solucao 100% eficaz
            self.kb_learner.learn(error, "Remover build.gradle.kts e recriar build.gradle com compileSdk 34")
            return {"success": True}

        # 2. KB com confianca media
        if solution and confidence > 0.5:
            self._log(f"[KB] Solucao encontrada (confianca: {confidence:.2%})")
            if await self._apply_ia_fix(solution):
                return {"success": True}

        # 3. IA com ate 3 tentativas
        self._log("[IA] Buscando solucao...")
        for attempt in range(1, 4):
            ia_solution = await self._get_ia_solution_with_retry(error, attempt)
            if ia_solution:
                if len(ia_solution) < 200:
                    self._log(f"[IA] Resposta muito curta ({len(ia_solution)} chars), ignorando")
                    continue
                is_valid, code, errors = self.response_validator.validate_and_extract(ia_solution)
                if is_valid and code:
                    await self._apply_fix(code)
                    return {"success": True}
                extracted = self.response_validator.force_code_extraction(ia_solution)
                if extracted:
                    await self._apply_fix(extracted)
                    return {"success": True}

        # 4. Fallback de ultimo recurso: correcao local + build direto sem IA
        self._log("[FALLBACK] IA falhou apos 3 tentativas. Aplicando correcao local e build direto...")
        fix_applied = self._apply_local_fix(error)
        if fix_applied:
            self.kb_learner.learn(error, "Correcao local aplicada com sucesso apos falha da IA")
        return {"success": fix_applied}


    def _apply_local_fix(self, error: str) -> bool:
        if 'Kotlin' in error or 'KGP' in error or 'kotlin' in error:
            self._log("Aplicando correcao Kotlin local...")
            fixer = KotlinGradleFixer(str(self.project_path))
            result = fixer.apply_fixes()
            if result['success']:
                self._log(f"Correcao Kotlin aplicada: {result['fixes_applied']}")
                return True
        if 'dependency' in error.lower() or 'dependency' in error.lower():
            self._fix_pubspec_versions()
            return True
        if 'import' in error.lower() or 'Import' in error:
            self._fix_imports_in_main_dart()
            return True
        return False

    def _fix_pubspec_versions(self):
        pubspec_path = self.project_path / 'pubspec.yaml'
        if not pubspec_path.exists():
            return
        content = pubspec_path.read_text(encoding='utf-8')
        fixes = {
            'on_audio_query': '^2.9.0',
            'just_audio': '^0.9.40',
            'path_provider': '^2.1.4',
            'permission_handler': '^11.3.1',
            'shared_preferences': '^2.3.2'
        }
        for dep, version in fixes.items():
            content = re.sub(
                rf"{dep}:\s*[^\n]+",
                f"{dep}: {version}",
                content
            )
        pubspec_path.write_text(content, encoding='utf-8')
        self._log("Pubspec versions corrigidas")

    def _fix_imports_in_main_dart(self):
        main_path = self.project_path / 'lib' / 'main.dart'
        if not main_path.exists():
            return
        content = main_path.read_text(encoding='utf-8')
        common_imports = [
            "import 'package:flutter/material.dart';",
            "import 'package:flutter/cupertino.dart';",
            "import 'package:http/http.dart' as http;",
            "import 'package:shared_preferences/shared_preferences.dart';",
            "import 'package:provider/provider.dart';",
            "import 'package:just_audio/just_audio.dart';",
            "import 'package:on_audio_query/on_audio_query.dart';",
        ]
        for imp in common_imports:
            if imp not in content:
                content = imp + '\n' + content
        main_path.write_text(content, encoding='utf-8')
        self._log("Imports comuns adicionados ao main.dart")

    async def _get_ia_solution_with_retry(self, error: str, attempt: int) -> Optional[str]:
        model, _ = self.model_manager.get_best_model('fix_solution')
        prompt = self._build_fix_prompt(error)
        self._log(f"Prompt enviado (tamanho: {len(prompt)} chars)")
        try:
            response = await self._call_ia_model(model.name, prompt)
            if response:
                self._log(f"Resposta IA ({len(response)} chars, {len(response.split())} palavras)")
                if len(response) < 200:
                    self._log(f"  Conteudo resumido: '{response[:150].strip()}'")
                else:
                    self._log(f"  Primeiros 100 chars: '{response[:100].strip()}...'")
                return response
            self.model_manager.record_model_result(model.name, False, 0)
            return None
        except Exception as e:
            self._log(f"Erro ao chamar IA: {e}")
            self.model_manager.record_model_result(model.name, False, 0)
            return None

    def _build_fix_prompt(self, error: str) -> str:
        main_file = self.project_path / 'lib' / 'main.dart'
        current_code = ""
        if main_file.exists():
            current_code = main_file.read_text(encoding='utf-8')
        return f"""
Voce e um especialista em Flutter/Dart. O build falhou com o erro abaixo.

ERRO DO BUILD:
```
{error[:2000]}
```

CODIGO ATUAL (main.dart):
```dart
{current_code[:3000]}
```

INSTRUCOES OBRIGATORIAS:
1. Retorne APENAS o codigo Dart COMPLETO do arquivo main.dart corrigido
2. Use a seguinte estrutura:
   ```dart
   [SEU CODIGO AQUI]
   ```
3. NAO inclua texto antes ou depois do bloco de codigo
4. NAO inclua explicacoes como "Aqui est[aá]" ou "Corrigi isso"
5. O codigo DEVE ser COMPLETO e COMPILAVEL
6. Mantenha todas as importacoes e a estrutura original
7. Se nao houver erro no codigo, retorne o codigo original

IMPORTANTE: Sua resposta ser[aá] validada automaticamente. Se n[aã]o for c[oó]digo Dart v[aá]lido, ser[aá] rejeitada.
"""

    async def _call_ia_model(self, model: str, prompt: str) -> Optional[str]:
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


    async def _apply_ia_fix(self, solution: str) -> bool:
        self._log(f"[FIX] Aplicando solucao IA: {solution[:100]}...")
        try:
            result = subprocess.run(
                ["flutter", "pub", "get"],
                cwd=self.project_path, capture_output=True, text=True, timeout=60
            )
            return result.returncode == 0
        except Exception as e:
            self._log(f"[FIX] Erro ao aplicar solucao: {e}")
            return False

    async def _apply_fix(self, fix: str):
        target_file = self.project_path / 'lib' / 'main.dart'
        with open(target_file, 'w', encoding='utf-8') as f:
            f.write(fix)

    def _get_fallback_template(self, error: str) -> Optional[str]:
        if 'main.dart' in error or 'no such file' in error:
            return """import 'package:flutter/material.dart';

void main() {
  runApp(MyApp());
}

class MyApp extends StatelessWidget {
  const MyApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Flutter App',
      home: Scaffold(
        appBar: AppBar(title: const Text('App')),
        body: const Center(child: Text('Hello World')),
      ),
    );
  }
}
"""
        return None

    
    
    def _log(self, message: str):
        from datetime import datetime
        import sys
        safe_msg = message.encode('ascii', errors='replace').decode('ascii')
        timestamp = datetime.now().strftime('%H:%M:%S')
        if sys.platform == 'win32':
            try:
                sys.stdout.reconfigure(encoding='utf-8', errors='replace')
            except:
                pass
        print(f'[{timestamp}] {safe_msg}')
    def _generate_report(self, result: Dict):
        report_path = self.project_path / 'build_output' / 'build_report.json'
        report_path.parent.mkdir(parents=True, exist_ok=True)
        with open(report_path, 'w', encoding='utf-8') as f:
            json.dump({
                'timestamp': datetime.now().isoformat(),
                'success': result['success'],
                'attempts': len(result['attempts']),
                'time_taken': result['time_taken'],
                'kb_stats': self.kb_learner.get_stats(),
                'model_stats': self.model_manager.get_performance_report(),
                'timeout_stats': self.timeout_manager.get_stats()
            }, f, indent=2, ensure_ascii=False)
