import asyncio
import subprocess
import time
import json
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
        fixes = []
        solution, confidence = self.kb_learner.get_solution(error)
        if solution:
            self._log(f"Solucao encontrada na KB (confianca: {confidence:.2%})")
            fixes.append(solution)
        if not solution or confidence < 0.6:
            self._log("Buscando solucao com IA...")
            ia_solution = await self._get_ia_solution(error)
            if ia_solution:
                fixes.append(ia_solution)
        if 'Kotlin Gradle Plugin' in error or 'KGP' in error:
            self._log("Aplicando correcao Kotlin...")
            fixer = KotlinGradleFixer(str(self.project_path))
            result = fixer.apply_fixes()
            if result['success']:
                return {'success': True}
        for fix in fixes:
            try:
                await self._apply_fix(fix)
                return {'success': True}
            except Exception as e:
                self._log(f"Falha ao aplicar correcao: {e}")
        return {'success': False}

    async def _get_ia_solution(self, error: str) -> Optional[str]:
        model, _ = self.model_manager.get_best_model('fix_solution')
        prompt = self._build_fix_prompt(error)
        try:
            response = await self._call_ia_model(model.name, prompt)
            if response:
                is_valid, code, errors = self.response_validator.validate_and_extract(response)
                if is_valid:
                    return code
                else:
                    self._log(f"Resposta invalida: {errors}")
            self.model_manager.record_model_result(model.name, False, 0)
            return None
        except Exception as e:
            self._log(f"Erro ao chamar IA: {e}")
            self.model_manager.record_model_result(model.name, False, 0)
            return None

    def _build_fix_prompt(self, error: str) -> str:
        return f"""
        Voce e especialista em Flutter/Dart. Corrija o erro de build abaixo.

        ERRO:
        {error}

        REGRAS OBRIGATORIAS:
        1. Sua resposta deve ser APENAS o codigo Dart completo e valido
        2. Nao inclua markdown, explicacoes ou texto extra
        3. Mantenha a estrutura completa do arquivo
        4. Use comentarios // para explicar mudancas
        5. O codigo deve ser valido e compilavel

        Exemplo de resposta valida:
        import 'package:flutter/material.dart';
        // seu codigo corrigido aqui...
        """

    async def _call_ia_model(self, model: str, prompt: str) -> Optional[str]:
        return None

    async def _apply_fix(self, fix: str):
        target_file = self.project_path / 'lib' / 'main.dart'
        with open(target_file, 'w', encoding='utf-8') as f:
            f.write(fix)

    def _log(self, message: str):
        timestamp = datetime.now().strftime("%H:%M:%S")
        print(f"[{timestamp}] {message}")

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
