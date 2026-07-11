import pytest
import tempfile
import os
from pathlib import Path

from orchestrator.timeout_manager import AdaptiveTimeoutManager
from orchestrator.ia_response_validator import IAResponseValidator
from orchestrator.model_manager import IntelligentModelManager
from orchestrator.kotlin_fixer import KotlinGradleFixer
from orchestrator.knowledge_base_learner import KnowledgeBaseLearner
from orchestrator.main_orchestrator import FlutterOrchestrator


class TestAdaptiveTimeoutManager:
    def test_init(self):
        tm = AdaptiveTimeoutManager()
        assert tm.min_timeout == 30
        assert tm.max_timeout == 300
        assert 30 <= tm.current_timeout <= 300

    def test_get_timeout_increases_with_attempt(self):
        tm = AdaptiveTimeoutManager()
        t1 = tm.get_timeout(1, 'fast')
        t3 = tm.get_timeout(3, 'heavy')
        assert t3 >= t1

    def test_record_attempt_updates_timeout(self):
        tm = AdaptiveTimeoutManager()
        tm.record_attempt(True, 5.0, "test-model", "fast")
        assert tm.current_timeout >= 30

    def test_get_stats(self):
        tm = AdaptiveTimeoutManager()
        prev = tm.current_timeout
        tm.record_attempt(True, 5.0, "test-model", "fast")
        stats = tm.get_stats()
        assert stats['total_attempts'] >= 1


class TestIAResponseValidator:
    def test_validate_valid_dart(self):
        v = IAResponseValidator()
        code = 'import "package:flutter/material.dart"; void main() => runApp(const MyApp()); class MyApp extends StatelessWidget { const MyApp({super.key}); @override Widget build(BuildContext c) => Container(); }'
        is_valid, extracted, errors = v.validate_and_extract(code)
        assert is_valid, f"Failed: {errors}"

    def test_validate_empty(self):
        v = IAResponseValidator()
        is_valid, extracted, errors = v.validate_and_extract("")
        assert not is_valid

    def test_force_code_extraction_with_markdown(self):
        v = IAResponseValidator()
        response = '```dart\nvoid main() => runApp(MyApp());\nclass MyApp extends StatelessWidget {}\n```'
        result = v.force_code_extraction(response)
        assert result is not None
        assert 'void main' in result

    def test_force_code_extraction_short_response(self):
        v = IAResponseValidator()
        result = v.force_code_extraction("OK")
        assert result is None


class TestIntelligentModelManager:
    def test_get_best_model(self):
        mm = IntelligentModelManager()
        model, est = mm.get_best_model()
        assert model is not None
        assert est > 0

    def test_get_performance_report(self):
        mm = IntelligentModelManager()
        report = mm.get_performance_report()
        assert 'fast' in report
        assert 'medium' in report
        assert 'heavy' in report

    def test_get_fallback_model(self):
        mm = IntelligentModelManager()
        fallback = mm.get_fallback_model("nonexistent-model")
        assert fallback is not None


class TestKotlinGradleFixer:
    def test_apply_fixes(self):
        tmpdir = tempfile.mkdtemp()
        android_dir = Path(tmpdir) / 'android'
        android_dir.mkdir(parents=True, exist_ok=True)
        (android_dir / 'build.gradle').write_text('buildscript {\n    dependencies {\n    }\n}')
        fixer = KotlinGradleFixer(tmpdir)
        result = fixer.apply_fixes()
        assert result['success']
        assert len(result['fixes_applied']) > 0

    def test_restore_on_error(self):
        tmpdir = tempfile.mkdtemp()
        # No android dir - should fail gracefully
        fixer = KotlinGradleFixer(tmpdir)
        result = fixer.apply_fixes()
        # Without android dir, some fixes may apply, some may not
        assert 'success' in result


class TestKnowledgeBaseLearner:
    def test_learn_and_get_stats(self):
        tmpdir = tempfile.mkdtemp()
        kb_path = Path(tmpdir) / 'test_kb.json'
        kbl = KnowledgeBaseLearner(kb_path=str(kb_path))
        kbl.learn_from_build('test log', 'error: something failed', 'fix: do X', True)
        stats = kbl.get_stats()
        assert stats['total_errors'] == 1
        assert stats['solved_errors'] == 1

    def test_get_solution(self):
        tmpdir = tempfile.mkdtemp()
        kb_path = Path(tmpdir) / 'test_kb.json'
        kbl = KnowledgeBaseLearner(kb_path=str(kb_path))
        kbl.learn_from_build('test', 'error: something failed', 'fix: do X', True)
        solution, confidence = kbl.get_solution('error: something failed')
        assert solution is not None, f"No solution found, stats: {kbl.get_stats()}"
        assert confidence > 0

    def test_no_solution_for_unknown(self):
        tmpdir = tempfile.mkdtemp()
        kb_path = Path(tmpdir) / 'test_kb.json'
        kbl = KnowledgeBaseLearner(kb_path=str(kb_path))
        solution, confidence = kbl.get_solution('unknown error')
        assert solution is None
        assert confidence == 0.0


class TestFlutterOrchestrator:
    def test_init(self):
        orch = FlutterOrchestrator("./test_project")
        assert str(orch.project_path).endswith("test_project")
        assert orch.max_retries == 3

    def test_validate_project_fails(self):
        tmpdir = tempfile.mkdtemp()
        orch = FlutterOrchestrator(tmpdir)
        import asyncio
        result = asyncio.run(orch._validate_project())
        assert not result['success']
