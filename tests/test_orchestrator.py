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
    assert orch.output_dir == Path("build_output").resolve()
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
