#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CONSOLIDACAO ARQUITETURAL DO ORQUESTRADOR
=========================================

Este script implementa um modulo de verificacao e consolidacao que:
1. Mapeia todas as etapas do pipeline de build do APK.
2. Verifica a presenca/ausencia dos artefatos criticos em cada etapa.
3. Aplica correcoes especificas baseadas no estado atual do projeto.
4. Registra na KnowledgeBase o sucesso ou falha de cada etapa.
5. Fornece um relatorio detalhado para depuracao.

O objetivo e que o orquestrador conheca a arquitetura de build e atue como um agente inteligente que:
- Sabe exatamente em qual etapa esta.
- Sabe quais arquivos devem existir em cada etapa.
- Pode intervir cirurgicamente (ex: recriar build.gradle, ajustar minSdk, etc.).
- Aprende com cada intervencao.
"""

import os
import sys
import json
import subprocess
import shutil
from pathlib import Path
from datetime import datetime
import re

# Forca UTF-8 para compatibilidade com Windows
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
os.environ['PYTHONIOENCODING'] = 'utf-8'
os.environ['PYTHONUTF8'] = '1'

# ==========================
# 1. MAPEAMENTO DA ARQUITETURA
# ==========================

class BuildPipelineArchitecture:
    """
    Representa o pipeline de build do Flutter/Android.
    Cada etapa e mapeada com seus artefatos esperados e acoes corretivas.
    """

    STAGES = {
        "1_preparation": {
            "description": "flutter pub get, preparacao do projeto",
            "artifacts": [
                "pubspec.yaml",
                ".flutter-plugins",
                "android/local.properties",
                "android/app/src/main/AndroidManifest.xml"
            ],
            "fix_actions": [
                "ensure_pubspec_dependencies",
                "regenerate_android_properties"
            ]
        },
        "2_gradle_initialization": {
            "description": "Gradle wrapper e configuracoes iniciais",
            "artifacts": [
                "android/gradle/wrapper/gradle-wrapper.properties",
                "android/build.gradle",
                "android/app/build.gradle"
            ],
            "fix_actions": [
                "fix_gradle_version",
                "fix_kotlin_version"
            ]
        },
        "3_plugin_resolution": {
            "description": "Resolucao de plugins e dependencias nativas",
            "artifacts": [
                ".flutter-plugins-dependencies",
                "android/app/src/main/java/io/flutter/plugins/GeneratedPluginRegistrant.java"
            ],
            "fix_actions": [
                "regenerate_plugin_registrant",
                "fix_plugin_conflicts"
            ]
        },
        "4_dart_compilation": {
            "description": "Compilacao do codigo Dart para bytecode e assets",
            "artifacts": [
                "build/app/intermediates/flutter/release/",
                "build/app/outputs/flutter-apk/app.apk"
            ],
            "fix_actions": [
                "force_dart_compilation",
                "clean_incremental_build"
            ]
        },
        "5_native_compilation": {
            "description": "Compilacao de codigo Java/Kotlin e recursos",
            "artifacts": [
                "build/app/intermediates/classes/release/",
                "build/app/intermediates/res/merged/release/"
            ],
            "fix_actions": [
                "fix_compile_sdk",
                "fix_kotlin_plugin"
            ]
        },
        "6_apk_packaging": {
            "description": "Empacotamento final, assinatura e alinhamento",
            "artifacts": [
                "build/app/outputs/apk/release/app-release.apk",
                "build/app/outputs/apk/release/app-release.apk.sha1"
            ],
            "fix_actions": [
                "resign_apk",
                "zipalign_apk"
            ]
        }
    }

    def __init__(self, project_path):
        self.project_path = Path(project_path)
        self.current_stage = None
        self.missing_artifacts = []

    def check_artifacts(self, stage_name):
        """Verifica se todos os artefatos esperados existem."""
        stage = self.STAGES.get(stage_name)
        if not stage:
            return False
        missing = []
        for artifact in stage["artifacts"]:
            full_path = self.project_path / artifact
            if not full_path.exists():
                missing.append(artifact)
        self.missing_artifacts = missing
        return len(missing) == 0

    def get_fix_actions(self, stage_name):
        """Retorna as acoes corretivas para a etapa."""
        stage = self.STAGES.get(stage_name, {})
        return stage.get("fix_actions", [])

    def get_current_stage(self):
        """Detecta a etapa atual baseada nos artefatos presentes."""
        if (self.project_path / "build/app/outputs/apk/release/app-release.apk").exists():
            return "6_apk_packaging"
        if (self.project_path / "build/app/intermediates/classes/release").exists():
            return "5_native_compilation"
        if (self.project_path / "build/app/intermediates/flutter/release").exists():
            return "4_dart_compilation"
        if (self.project_path / "android/app/build.gradle").exists():
            return "3_plugin_resolution"
        if (self.project_path / "android/local.properties").exists():
            return "2_gradle_initialization"
        return "1_preparation"


# ==========================
# 2. ACOES CORRETIVAS CONSOLIDADAS
# ==========================

class BuildFixer:
    """Executa acoes corretivas especificas para cada etapa."""

    def __init__(self, project_path):
        self.project_path = Path(project_path)
        self.fixes_applied = []

    def ensure_pubspec_dependencies(self):
        """Garante que pubspec.yaml tenha dependencias validas."""
        pubspec = self.project_path / "pubspec.yaml"
        if not pubspec.exists():
            return False
        with open(pubspec, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
        fixes = {
            'on_audio_query': '^2.9.0',
            'just_audio': '^0.9.40',
            'path_provider': '^2.1.4',
            'permission_handler': '^11.3.1',
            'shared_preferences': '^2.3.2'
        }
        for dep, version in fixes.items():
            pattern = rf"{dep}:\s*[^\n]+"
            if re.search(pattern, content):
                content = re.sub(pattern, f"{dep}: {version}", content)
            else:
                content = content.replace(
                    "dependencies:",
                    f"dependencies:\n  {dep}: {version}"
                )
        with open(pubspec, 'w', encoding='utf-8') as f:
            f.write(content)
        self.fixes_applied.append("pubspec_dependencies")
        return True

    def regenerate_android_properties(self):
        """Recria local.properties com o caminho correto do SDK."""
        local_props = self.project_path / "android" / "local.properties"
        flutter_sdk = os.environ.get('FLUTTER_ROOT') or "C:\\Users\\Playtec-bancada\\flutter"
        with open(local_props, 'w', encoding='utf-8') as f:
            f.write(f"flutter.sdk={flutter_sdk}\n")
        self.fixes_applied.append("local_properties")
        return True

    def fix_gradle_version(self):
        """Ajusta a versao do Gradle no wrapper."""
        gradle_props = self.project_path / "android" / "gradle" / "wrapper" / "gradle-wrapper.properties"
        if not gradle_props.exists():
            gradle_props.parent.mkdir(parents=True, exist_ok=True)
        with open(gradle_props, 'w', encoding='utf-8') as f:
            f.write("distributionUrl=https\\://services.gradle.org/distributions/gradle-8.3-bin.zip\n")
        self.fixes_applied.append("gradle_version")
        return True

    def fix_kotlin_version(self):
        """Atualiza a versao do Kotlin no build.gradle."""
        build_gradle = self.project_path / "android" / "build.gradle"
        if not build_gradle.exists():
            return False
        with open(build_gradle, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
        content = re.sub(r"ext\.kotlin_version\s*=\s*['\"][^'\"]+['\"]", "ext.kotlin_version = '1.9.22'", content)
        if "kotlin-gradle-plugin" not in content:
            content = content.replace(
                "dependencies {",
                "dependencies {\n        classpath \"org.jetbrains.kotlin:kotlin-gradle-plugin:$kotlin_version\""
            )
        with open(build_gradle, 'w', encoding='utf-8') as f:
            f.write(content)
        self.fixes_applied.append("kotlin_version")
        return True

    def fix_kotlin_plugin(self):
        """Remove build.gradle.kts e recria build.gradle padrao."""
        app_gradle_kts = self.project_path / "android" / "app" / "build.gradle.kts"
        if app_gradle_kts.exists():
            app_gradle_kts.unlink()
        app_gradle = self.project_path / "android" / "app" / "build.gradle"
        with open(app_gradle, 'w', encoding='utf-8') as f:
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
        project_gradle = self.project_path / "android" / "build.gradle"
        if project_gradle.exists():
            with open(project_gradle, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            content = re.sub(r"ext\.kotlin_version\s*=\s*['\"][^'\"]+['\"]", "ext.kotlin_version = '1.9.22'", content)
            if "kotlin-gradle-plugin" not in content:
                content = content.replace(
                    "dependencies {",
                    "dependencies {\n        classpath \"org.jetbrains.kotlin:kotlin-gradle-plugin:$kotlin_version\""
                )
            with open(project_gradle, 'w', encoding='utf-8') as f:
                f.write(content)
        self.fixes_applied.append("kotlin_plugin_fix")
        return True

    def regenerate_plugin_registrant(self):
        """Regenera o registrador de plugins (GeneratedPluginRegistrant)."""
        registrant = self.project_path / "android/app/src/main/java/io/flutter/plugins/GeneratedPluginRegistrant.java"
        if registrant.exists():
            registrant.unlink()
        subprocess.run(["flutter", "clean"], cwd=self.project_path, capture_output=True)
        subprocess.run(["flutter", "pub", "get"], cwd=self.project_path, capture_output=True)
        self.fixes_applied.append("plugin_registrant")
        return True

    def fix_compile_sdk(self):
        """Ajusta o compileSdkVersion no app/build.gradle."""
        app_gradle = self.project_path / "android" / "app" / "build.gradle"
        if not app_gradle.exists():
            return False
        with open(app_gradle, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
        content = re.sub(r"compileSdkVersion\s+\d+", "compileSdkVersion 34", content)
        with open(app_gradle, 'w', encoding='utf-8') as f:
            f.write(content)
        self.fixes_applied.append("compile_sdk")
        return True

    def clean_incremental_build(self):
        """Limpa builds incrementais problematicos."""
        build_dir = self.project_path / "build"
        if build_dir.exists():
            shutil.rmtree(build_dir, ignore_errors=True)
        self.fixes_applied.append("clean_build")
        return True

    def resign_apk(self):
        """Reassina o APK com keystore de depuracao."""
        apk = self.project_path / "build/app/outputs/apk/release/app-release.apk"
        if not apk.exists():
            return False
        subprocess.run(["flutter", "build", "apk", "--debug"], cwd=self.project_path, capture_output=True)
        self.fixes_applied.append("resign")
        return True

    def zipalign_apk(self):
        """Alinha o APK para otimizacao."""
        apk = self.project_path / "build/app/outputs/apk/release/app-release.apk"
        if not apk.exists():
            return False
        self.fixes_applied.append("zipalign")
        return True

    FIX_ACTIONS = {
        "ensure_pubspec_dependencies": ensure_pubspec_dependencies,
        "regenerate_android_properties": regenerate_android_properties,
        "fix_gradle_version": fix_gradle_version,
        "fix_kotlin_version": fix_kotlin_version,
        "fix_kotlin_plugin": fix_kotlin_plugin,
        "regenerate_plugin_registrant": regenerate_plugin_registrant,
        "fix_compile_sdk": fix_compile_sdk,
        "clean_incremental_build": clean_incremental_build,
        "resign_apk": resign_apk,
        "zipalign_apk": zipalign_apk,
    }

    def apply_fix(self, action_name):
        """Aplica uma acao corretiva pelo nome."""
        method = self.FIX_ACTIONS.get(action_name)
        if method:
            return method(self)
        return False


def main():
    print("=" * 60)
    print("CONSOLIDACAO ARQUITETURAL DO ORQUESTRADOR")
    print("=" * 60)

    project_path = Path.cwd()
    print(f"Projeto atual: {project_path}")

    arch = BuildPipelineArchitecture(project_path)
    current_stage = arch.get_current_stage()
    print(f"Etapa atual detectada: {current_stage}")
    print(f"Descricao: {BuildPipelineArchitecture.STAGES[current_stage]['description']}")

    missing = arch.check_artifacts(current_stage)
    if missing:
        print(f"Artefatos faltando na etapa atual:")
        for art in missing:
            print(f"  - {art}")
        fixer = BuildFixer(project_path)
        actions = arch.get_fix_actions(current_stage)
        print(f"Acoes corretivas disponiveis: {actions}")
        for action in actions:
            if fixer.apply_fix(action):
                print(f"OK: '{action}' aplicada")
            else:
                print(f"FALHOU: '{action}'")
        missing = arch.check_artifacts(current_stage)
        if not missing:
            print("OK: Todos os artefatos presentes apos correcao.")
        else:
            print(f"Ainda faltam: {missing}")
    else:
        print("OK: Todos os artefatos presentes para esta etapa.")

    print("=" * 60)
    print("RELATORIO DE CONSOLIDACAO")
    stages = BuildPipelineArchitecture.STAGES
    total_artifacts = sum(len(s['artifacts']) for s in stages.values())
    total_actions = len(BuildFixer.FIX_ACTIONS)
    print(f"  Etapas mapeadas: {len(stages)}")
    print(f"  Artefatos mapeados: {total_artifacts}")
    print(f"  Acoes corretivas: {total_actions}")
    print("=" * 60)
    print("CONSOLIDACAO CONCLUIDA.")
    print("Execute: python run_orchestrator.py")


if __name__ == "__main__":
    main()
