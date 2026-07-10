"""Unit tests for FlutterBuildOrchestrator."""

import json
import tempfile
from pathlib import Path
from datetime import datetime

import pytest


@pytest.fixture
def mock_project(tmp_path):
    """Create a minimal mock Flutter project structure."""
    pubspec = tmp_path / "pubspec.yaml"
    pubspec.write_text(
        "name: test_app\n"
        "description: Test\n"
        "version: 1.0.0+1\n"
        "environment:\n"
        "  sdk: ^3.0.0\n"
        "dependencies:\n"
        "  flutter:\n"
        "    sdk: flutter\n"
    )
    lib = tmp_path / "lib"
    lib.mkdir()
    (lib / "main.dart").write_text("void main() {}")
    android = tmp_path / "android" / "app" / "src" / "main"
    android.mkdir(parents=True)
    (android / "AndroidManifest.xml").write_text(
        '<?xml version="1.0"?>\n<manifest package="com.test.app">\n'
        '<application></application>\n</manifest>\n'
    )
    return tmp_path


def test_orchestrator_initialization():
    """Test that the orchestrator initializes with correct paths."""
    from flutter_orchestrator import FlutterBuildOrchestrator

    orch = FlutterBuildOrchestrator(project_path="/tmp/test")
    assert orch.project_path == Path("/tmp/test").resolve()
    assert orch.output_dir == Path("/tmp/test/build_output").resolve()
    assert orch.build_log == []
    assert orch.start_time is not None


def test_orchestrator_with_custom_output():
    """Test custom output directory."""
    from flutter_orchestrator import FlutterBuildOrchestrator

    orch = FlutterBuildOrchestrator(
        project_path="/tmp/test", output_dir="/tmp/output"
    )
    assert orch.output_dir == Path("/tmp/output").resolve()


def test_orchestrator_auto_install_default():
    """Test auto_install defaults to False."""
    from flutter_orchestrator import FlutterBuildOrchestrator

    orch = FlutterBuildOrchestrator(project_path="/tmp/test")
    assert orch.auto_install is False


def test_orchestrator_auto_install_enabled():
    """Test auto_install can be enabled."""
    from flutter_orchestrator import FlutterBuildOrchestrator

    orch = FlutterBuildOrchestrator(project_path="/tmp/test", auto_install=True)
    assert orch.auto_install is True


def test_validate_project_success(mock_project):
    """Test project validation passes for a valid Flutter project."""
    from flutter_orchestrator import FlutterBuildOrchestrator

    orch = FlutterBuildOrchestrator(project_path=str(mock_project))
    assert orch.validate_flutter_project() is True


def test_validate_project_fails_without_pubspec(tmp_path):
    """Test project validation fails when pubspec.yaml is missing."""
    from flutter_orchestrator import FlutterBuildOrchestrator

    orch = FlutterBuildOrchestrator(project_path=str(tmp_path))
    assert orch.validate_flutter_project() is False


def test_build_report_generation(mock_project):
    """Test that build report is generated correctly."""
    from flutter_orchestrator import FlutterBuildOrchestrator

    orch = FlutterBuildOrchestrator(project_path=str(mock_project))
    orch.output_dir.mkdir(parents=True, exist_ok=True)

    # Create a fake APK for the report
    fake_apk = orch.output_dir / "app_test.apk"
    fake_apk.write_text("fake apk content")

    orch.generate_build_report(fake_apk, success=True)
    report_path = orch.output_dir / "build_report.json"
    assert report_path.exists()

    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["build_info"]["success"] is True
    assert report["build_info"]["project_path"] == str(mock_project.resolve())
    assert report["apk_info"]["path"] == str(fake_apk.resolve())
    assert report["apk_info"]["size_mb"] is not None


def test_build_report_failure(mock_project):
    """Test build report for a failed build."""
    from flutter_orchestrator import FlutterBuildOrchestrator

    orch = FlutterBuildOrchestrator(project_path=str(mock_project))
    orch.output_dir.mkdir(parents=True, exist_ok=True)
    orch.generate_build_report(None, success=False)

    report = json.loads(
        (orch.output_dir / "build_report.json").read_text(encoding="utf-8")
    )
    assert report["build_info"]["success"] is False
    assert report["apk_info"]["path"] is None
    assert report["apk_info"]["size_bytes"] is None


def test_build_logging(mock_project):
    """Test that build steps are logged."""
    from flutter_orchestrator import FlutterBuildOrchestrator

    orch = FlutterBuildOrchestrator(project_path=str(mock_project))
    orch.log("Test message", "INFO")
    orch.log("Error message", "ERROR")

    assert len(orch.build_log) == 2
    assert orch.build_log[0]["level"] == "INFO"
    assert orch.build_log[0]["message"] == "Test message"
    assert orch.build_log[1]["level"] == "ERROR"
    assert orch.build_log[1]["message"] == "Error message"


def test_pubspec_validation_fix_merged_lines(mock_project):
    """Test that pubspec.yaml merged lines are fixed."""
    pubspec = mock_project / "pubspec.yaml"
    pubspec.write_text(
        "name: test_app\n"
        "version: 1.0.0+1  environment:\n"
        "  sdk: ^3.0.0\n"
        "dependencies:\n"
        "  flutter:\n"
        "    sdk: flutter\n"
    )

    from flutter_orchestrator import FlutterBuildOrchestrator

    orch = FlutterBuildOrchestrator(project_path=str(mock_project))
    orch.validate_flutter_project()

    content = pubspec.read_text(encoding="utf-8")
    assert "version:" in content
    assert "environment:" in content
    # They should now be on separate lines
    assert "version: 1.0.0+1  environment:" not in content


def test_pubspec_tabs_to_spaces(mock_project):
    """Test that tabs in pubspec.yaml are converted to spaces."""
    pubspec = mock_project / "pubspec.yaml"
    pubspec.write_text(
        "name: test_app\n"
        "version: 1.0.0+1\n"
        "environment:\n"
        "\tsdk: ^3.0.0\n"
        "dependencies:\n"
        "\tflutter:\n"
        "\t\tsdk: flutter\n"
    )

    from flutter_orchestrator import FlutterBuildOrchestrator

    orch = FlutterBuildOrchestrator(project_path=str(mock_project))
    orch.validate_flutter_project()

    content = pubspec.read_text(encoding="utf-8")
    assert "\t" not in content


def test_orchestrator_resolve_path():
    """Test that project path is resolved to absolute."""
    from flutter_orchestrator import FlutterBuildOrchestrator

    orch = FlutterBuildOrchestrator(project_path=".")
    assert orch.project_path.is_absolute()


def test_log_callback():
    """Test that log_callback is called on each log."""
    from flutter_orchestrator import FlutterBuildOrchestrator

    calls = []
    orch = FlutterBuildOrchestrator(
        project_path=".", log_callback=lambda msg, lvl: calls.append((msg, lvl))
    )
    orch.log("test msg", "INFO")
    assert len(calls) == 1
    assert calls[0][0] == "test msg"
    assert calls[0][1] == "INFO"


def test_orchestrator_cancel():
    """Test that cancel flag prevents further steps."""
    from flutter_orchestrator import FlutterBuildOrchestrator

    orch = FlutterBuildOrchestrator(project_path=".")
    assert orch._cancelled is False
    orch.cancel()
    assert orch._cancelled is True


def test_orchestrator_cancel_after_start(tmp_path):
    """Test cancel during orchestrate (cancelled before any step)."""
    from flutter_orchestrator import FlutterBuildOrchestrator

    project = tmp_path / "project"
    project.mkdir()
    orch = FlutterBuildOrchestrator(project_path=str(project))
    orch.cancel()
    result = orch.orchestrate()
    assert result is False


# ── New tests for robustness improvements ──────────────────────────────


def test_is_dart_code_positive():
    from flutter_orchestrator import FlutterBuildOrchestrator
    orch = FlutterBuildOrchestrator(project_path=".")
    assert orch._is_dart_code("void main() {}") is True
    assert orch._is_dart_code("import 'package:flutter/material.dart'; class App {}") is True
    assert orch._is_dart_code("class MyWidget extends StatelessWidget { Widget build() { return Container(); } }") is True


def test_is_dart_code_negative():
    from flutter_orchestrator import FlutterBuildOrchestrator
    orch = FlutterBuildOrchestrator(project_path=".")
    assert orch._is_dart_code("<?xml version='1.0'?>") is False
    assert orch._is_dart_code("plugins {\n    id 'com.android.application'\n}") is False
    assert orch._is_dart_code("buildscript { repositories { google() } }") is False
    assert orch._is_dart_code("") is False
    assert orch._is_dart_code("a") is False


def test_is_dart_code_with_xml_rejection():
    from flutter_orchestrator import FlutterBuildOrchestrator
    orch = FlutterBuildOrchestrator(project_path=".")
    xml = '<?xml version="1.0" encoding="utf-8"?>\n<manifest package="com.test"></manifest>'
    assert orch._is_dart_code(xml) is False


def test_backup_file_creates_backup(mock_project):
    from flutter_orchestrator import FlutterBuildOrchestrator
    orch = FlutterBuildOrchestrator(project_path=str(mock_project))
    main_dart = mock_project / "lib" / "main.dart"
    backup = orch._backup_file(main_dart)
    assert backup is not None
    assert backup.exists()
    assert backup.name.startswith("main.dart.")
    assert backup.name.endswith(".bak")
    assert backup.read_text() == "void main() {}"


def test_backup_file_returns_none_for_missing():
    from flutter_orchestrator import FlutterBuildOrchestrator
    orch = FlutterBuildOrchestrator(project_path=".")
    backup = orch._backup_file(Path("/nonexistent/file.dart"))
    assert backup is None


def test_write_dart_safe_valid(mock_project):
    from flutter_orchestrator import FlutterBuildOrchestrator
    orch = FlutterBuildOrchestrator(project_path=str(mock_project))
    main_dart = mock_project / "lib" / "main.dart"
    result = orch._write_dart_safe(main_dart, "void main() { print('hello'); }")
    assert result is True
    assert main_dart.read_text().strip() == "void main() { print('hello'); }"


def test_write_dart_safe_rejects_xml(mock_project):
    from flutter_orchestrator import FlutterBuildOrchestrator
    orch = FlutterBuildOrchestrator(project_path=str(mock_project))
    main_dart = mock_project / "lib" / "main.dart"
    original = main_dart.read_text()
    xml = '<?xml version="1.0"?><manifest></manifest>'
    result = orch._write_dart_safe(main_dart, xml)
    assert result is False, "Should reject non-Dart content"
    assert main_dart.read_text() == original, "Should not modify file"


def test_analyze_code_returns_false_on_errors(mock_project):
    """analyze_code should return False when flutter analyze finds errors."""
    from flutter_orchestrator import FlutterBuildOrchestrator
    import subprocess

    original_run = subprocess.run

    def mock_run_failure(*args, **kwargs):
        class FakeResult:
            returncode = 1
            stdout = "error: some compilation error"
            stderr = ""
        return FakeResult()

    subprocess.run = mock_run_failure
    try:
        orch = FlutterBuildOrchestrator(project_path=str(mock_project))
        result = orch.analyze_code()
        assert result is False, "Should return False when flutter analyze has errors"
    finally:
        subprocess.run = original_run


def test_fallback_models_defined():
    from flutter_orchestrator import FlutterBuildOrchestrator
    assert hasattr(FlutterBuildOrchestrator, "FALLBACK_MODELS")
    assert len(FlutterBuildOrchestrator.FALLBACK_MODELS) > 0
    assert "mistralai/ministral-14b-instruct-2512" in FlutterBuildOrchestrator.FALLBACK_MODELS


def test_ministral_model_in_provider_config():
    from flutter_orchestrator import FlutterBuildOrchestrator
    cfg = FlutterBuildOrchestrator.AI_PROVIDER_CONFIG
    assert "Mistral Mini" in cfg
    assert cfg["Mistral Mini"]["model"] == "mistralai/ministral-14b-instruct-2512"


def test_apply_pre_build_fixes_returns_true(tmp_path):
    """_apply_pre_build_fixes must always return True (non-blocking)."""
    from flutter_orchestrator import FlutterBuildOrchestrator
    project = tmp_path / "proj"
    project.mkdir()
    (project / "lib").mkdir()
    (project / "lib" / "main.dart").write_text("void main() {}")
    (project / "pubspec.yaml").write_text("name: test\n")
    orch = FlutterBuildOrchestrator(project_path=str(project))
    result = orch._apply_pre_build_fixes()
    assert result is True


def test_log_adapter_interface():
    from flutter_orchestrator import FlutterBuildOrchestrator
    calls = []
    orch = FlutterBuildOrchestrator(
        project_path=".", log_callback=lambda msg, lvl: calls.append((msg, lvl))
    )
    adapter = orch._LogAdapter(orch.log)
    adapter.ok("test ok")
    adapter.err("test err")
    adapter.warn("test warn")
    adapter.info("test info")
    assert len(calls) == 4
    assert calls[0][1] == "SUCCESS"
    assert calls[1][1] == "ERROR"
    assert calls[2][1] == "WARNING"
    assert calls[3][1] == "INFO"

