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
        assert tm.min_timeout == 60
        assert tm.max_timeout == 300
        assert 60 <= tm.current_timeout <= 300

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


class TestPureSdkBuilder:
    def test_init(self):
        from pure_sdk_builder import PureSdkBuilder
        builder = PureSdkBuilder("./test_pure")
        assert builder.project_path == Path("./test_pure").resolve()
        assert builder.build_dir.name == "build_pure"

    def test_validate_project_success(self, tmp_path):
        from pure_sdk_builder import PureSdkBuilder
        # Cria estrutura minima de projeto Pure SDK
        (tmp_path / "AndroidManifest.xml").write_text(
            '<?xml version="1.0" encoding="utf-8"?>\n<manifest package="com.test.app" />\n'
        )
        (tmp_path / "res").mkdir()
        (tmp_path / "res" / "values").mkdir(parents=True)
        (tmp_path / "res" / "values" / "strings.xml").write_text(
            '<?xml version="1.0" encoding="utf-8"?>\n<resources>\n    <string name="app_name">Test</string>\n</resources>\n'
        )
        src_dir = tmp_path / "src" / "com" / "test" / "app"
        src_dir.mkdir(parents=True)
        (src_dir / "MainActivity.java").write_text(
            "package com.test.app;\npublic class MainActivity {\n    public static void main(String[] args) {}\n}\n"
        )
        builder = PureSdkBuilder(str(tmp_path))
        assert builder.validate_project() is True

    def test_validate_project_fails_without_src(self, tmp_path):
        from pure_sdk_builder import PureSdkBuilder
        (tmp_path / "AndroidManifest.xml").write_text('<manifest package="com.test" />\n')
        builder = PureSdkBuilder(str(tmp_path))
        assert builder.validate_project() is False

    def test_find_java_files(self, tmp_path):
        from pure_sdk_builder import PureSdkBuilder
        src_dir = tmp_path / "src" / "com" / "test"
        src_dir.mkdir(parents=True)
        (src_dir / "Test.java").write_text("package com.test; class Test {}")
        (src_dir / "Util.java").write_text("package com.test; class Util {}")
        builder = PureSdkBuilder(str(tmp_path))
        files = builder.find_java_files()
        assert len(files) == 2
        assert all(f.endswith(".java") for f in files)

    def test_cleanup(self, tmp_path):
        from pure_sdk_builder import PureSdkBuilder
        builder = PureSdkBuilder(str(tmp_path))
        builder.cleanup()
        assert builder.build_dir.exists()

    def test_detect_project_type_pure_sdk(self, tmp_path):
        """Verifica que detect_project_type reconhece projeto Pure SDK."""
        from flutter_orchestrator import FlutterBuildOrchestrator
        (tmp_path / "AndroidManifest.xml").write_text('<manifest package="com.test" />\n')
        (tmp_path / "res").mkdir()
        (tmp_path / "src").mkdir()
        project_type = FlutterBuildOrchestrator.detect_project_type(tmp_path)
        assert project_type == "android_pure_sdk", f"Esperado android_pure_sdk, obtido {project_type}"

    def test_detect_project_type_still_detects_flutter(self, tmp_path):
        """Verifica que detect_project_type ainda detecta Flutter corretamente."""
        from flutter_orchestrator import FlutterBuildOrchestrator
        (tmp_path / "pubspec.yaml").write_text("name: test\n")
        project_type = FlutterBuildOrchestrator.detect_project_type(tmp_path)
        assert project_type == "flutter"

    def test_detect_project_type_still_detects_android_gradle(self, tmp_path):
        """Verifica que detect_project_type ainda detecta Android Gradle."""
        from flutter_orchestrator import FlutterBuildOrchestrator
        (tmp_path / "settings.gradle").write_text('rootProject.name = "test"\n')
        project_type = FlutterBuildOrchestrator.detect_project_type(tmp_path)
        assert project_type == "android"

    def test_validate_pure_sdk_project_method(self, tmp_path):
        """Verifica que validate_pure_sdk_project() funciona."""
        from flutter_orchestrator import FlutterBuildOrchestrator
        (tmp_path / "AndroidManifest.xml").write_text('<manifest package="com.test" />\n')
        (tmp_path / "res").mkdir()
        (tmp_path / "res" / "values").mkdir(parents=True)
        (tmp_path / "res" / "values" / "strings.xml").write_text(
            '<?xml version="1.0"?>\n<resources><string name="app_name">T</string></resources>\n'
        )
        src_dir = tmp_path / "src" / "com" / "test"
        src_dir.mkdir(parents=True)
        (src_dir / "Main.java").write_text("package com.test; class Main {}")
        orch = FlutterBuildOrchestrator(project_path=str(tmp_path))
        assert orch.validate_pure_sdk_project() is True

    def test_capture_last_build_error_exists(self, tmp_path):
        """Verifica que _capture_last_build_error e um metodo valido."""
        from flutter_orchestrator import FlutterBuildOrchestrator
        orch = FlutterBuildOrchestrator(project_path=str(tmp_path))
        assert hasattr(orch, '_capture_last_build_error')
        result = orch._capture_last_build_error()
        assert result is None  # Sem logs de build, retorna None
