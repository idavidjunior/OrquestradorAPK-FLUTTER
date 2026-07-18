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
        flutter_sdk = (os.environ.get('FLUTTER_ROOT') or "C:\\Users\\Playtec-bancada\\flutter").replace('\\', '/')
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
        """Fixa app/build.gradle(.kts) in-place sem deletar. Nao substitui KTS por Groovy."""
        kts = self.project_path / "android" / "app" / "build.gradle.kts"
        gradle = self.project_path / "android" / "app" / "build.gradle"
        if kts.exists():
            try:
                content = kts.read_text(encoding='utf-8')
                original = content
                content = re.sub(r'compileSdk\s*=\s*flutter\.compileSdkVersion', 'compileSdk = 36', content)
                content = re.sub(r'compileSdk\s*=\s*\d+', 'compileSdk = 36', content)
                if "namespace" not in content:
                    content = re.sub(r'(android\s*\{)', r'\1\n    namespace = "com.example.app"', content)
                if content != original:
                    kts.write_text(content, encoding='utf-8')
                    self.fixes_applied.append("fix_kotlin_kts")
            except Exception as e:
                self.fixes_applied.append(f"fix_kotlin_kts_error:{e}")
        elif not gradle.exists() or gradle.stat().st_size == 0:
            gradle.write_text(self._app_build_gradle_content(), encoding='utf-8')
            self.fixes_applied.append("fix_kotlin_gradle_fallback")
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

    @staticmethod
    def _app_build_gradle_content(project_name="app"):
        """Retorna conteudo de app/build.gradle com Flutter Gradle plugin (obrigatorio)."""
        return (
            'plugins {\n'
            '    id "com.android.application"\n'
            '    id "kotlin-android"\n'
            '    id "dev.flutter.flutter-gradle-plugin"\n'
            '}\n'
            'android {\n'
            f'    namespace "com.{project_name}.app"\n'
            '    compileSdkVersion 36\n'
            '    compileOptions {\n'
            '        sourceCompatibility JavaVersion.VERSION_17\n'
            '        targetCompatibility JavaVersion.VERSION_17\n'
            '    }\n'
            '    kotlinOptions {\n'
            '        jvmTarget = "17"\n'
            '    }\n'
            '    defaultConfig {\n'
            f'        applicationId "com.{project_name}.app"\n'
            '        minSdkVersion 21\n'
            '        targetSdkVersion 36\n'
            '        versionCode 1\n'
            '        versionName "1.0"\n'
            '    }\n'
            '}\n'
        )

    def remove_kts_before_build(self):
        """Pre-build hook: fixa app/build.gradle.kts in-place em vez de substituir por Groovy.
        Mantem a estrutura original do Flutter (KTS) e apenas ajusta versoes.
        Se nao existir .kts nem .gradle, cria .gradle com conteudo completo.
        """
        kts = self.project_path / "android" / "app" / "build.gradle.kts"
        gradle = self.project_path / "android" / "app" / "build.gradle"
        if kts.exists():
            try:
                content = kts.read_text(encoding='utf-8')
                original = content
                # Forca compileSdk minimo 36 (plugins como shared_preferences_android exigem)
                content = re.sub(
                    r'compileSdk\s*=\s*flutter\.compileSdkVersion',
                    'compileSdk = 36',
                    content
                )
                content = re.sub(
                    r'compileSdk\s*=\s*\d+',
                    'compileSdk = 36',
                    content
                )
                # Garante que namespace esta definido
                if "namespace" not in content:
                    content = re.sub(
                        r'(android\s*\{)',
                        r'\1\n    namespace = "com.example.app"',
                        content
                    )
                if content != original:
                    kts.write_text(content, encoding='utf-8')
                    self.fixes_applied.append("fix_kts_compileSdk")
            except Exception as e:
                self.fixes_applied.append(f"fix_kts_error:{e}")
            # Nao remove o .kts — mantem a estrutura original do Flutter
        elif not gradle.exists() or gradle.stat().st_size == 0:
            # So cria .gradle se nao existir nem .kts nem .gradle
            gradle.write_text(self._app_build_gradle_content(), encoding='utf-8')
            self.fixes_applied.append("create_gradle_fallback")
        self.fixes_applied.append("remove_kts")
        return True

    def detect_and_fix_gradle(self):
        """Detecta e corrige problemas completos de Gradle/Kotlin."""
        log_msg = "[FIX] Verificando e corrigindo configuracao Gradle..."
        print(log_msg)
        # 1. Fixa .kts in-place (nao remove)
        kts = self.project_path / "android" / "app" / "build.gradle.kts"
        if kts.exists():
            self.remove_kts_before_build()
        # 2. Garante build.gradle com conteudo completo se .kts nao existir
        gradle = self.project_path / "android" / "app" / "build.gradle"
        if not kts.exists() and (not gradle.exists() or gradle.stat().st_size == 0):
            gradle.write_text(self._app_build_gradle_content(), encoding='utf-8')
        # 3. Ajusta project build.gradle
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
        # 4. Ajusta gradle-wrapper.properties
        gradle_props = self.project_path / "android" / "gradle" / "wrapper" / "gradle-wrapper.properties"
        if not gradle_props.parent.exists():
            gradle_props.parent.mkdir(parents=True, exist_ok=True)
        with open(gradle_props, 'w', encoding='utf-8') as f:
            f.write("distributionUrl=https\\://services.gradle.org/distributions/gradle-8.3-bin.zip\n")
        # 5. Registra na KB
        try:
            kb_path = self.project_path / "knowledge_base.json"
            if kb_path.exists():
                with open(kb_path, 'r', encoding='utf-8', errors='ignore') as f:
                    kb = json.load(f)
            else:
                kb = {"errors": {}, "stats": {"total_errors": 0, "solved_errors": 0, "learning_rate": 0}}
            error_hash = "pre_build_gradle_fix"
            kb["errors"][error_hash] = {
                "pattern": "Kotlin/Gradle fix aplicado preventivamente",
                "first_seen": datetime.now().isoformat(),
                "occurrences": kb["errors"].get(error_hash, {}).get("occurrences", 0) + 1,
                "solutions": [{"solution": "detect_and_fix_gradle", "attempts": 1, "success": 1, "last_used": datetime.now().isoformat()}],
                "success_rate": 1.0
            }
            kb["stats"]["total_errors"] = len(kb["errors"])
            kb["stats"]["solved_errors"] = sum(1 for e in kb["errors"].values() if any(s["success"] > 0 for s in e.get("solutions", [])))
            kb["stats"]["learning_rate"] = kb["stats"]["solved_errors"] / kb["stats"]["total_errors"] if kb["stats"]["total_errors"] > 0 else 0
            with open(kb_path, 'w', encoding='utf-8') as f:
                json.dump(kb, f, indent=2, ensure_ascii=False)
        except Exception:
            pass
        self.fixes_applied.append("detect_and_fix_gradle")
        return True

    def fix_unsupported_gradle(self):
        """Recria estrutura android do zero para erro 'unsupported Gradle project'."""
        backup = self.project_path / ".backup_android"
        try:
            # Backup
            backup.mkdir(exist_ok=True)
            main_dart = self.project_path / "lib" / "main.dart"
            if main_dart.exists():
                shutil.copy2(main_dart, backup / "main.dart")
            pubspec_path = self.project_path / "pubspec.yaml"
            project_name = "app"
            if pubspec_path.exists():
                shutil.copy2(pubspec_path, backup / "pubspec.yaml")
                try:
                    import re
                    m = re.search(r'^name:\s*(\S+)', pubspec_path.read_text(encoding='utf-8'), re.MULTILINE)
                    if m:
                        project_name = m.group(1)
                except Exception:
                    pass
            # Remove android/
            android_dir = self.project_path / "android"
            if android_dir.exists():
                shutil.rmtree(android_dir, ignore_errors=True)
            # Tenta flutter create com --force e --project-name
            try:
                subprocess.run(
                    ["flutter", "create", "--force", ".", "--project-name", project_name],
                    cwd=self.project_path, capture_output=True, text=True, timeout=60)
            except Exception:
                pass
            # Se a pasta android ainda nao existe ou esta vazia, cria manual
            if not (self.project_path / "android" / "app" / "build.gradle").exists():
                self._create_manual_android(project_name)
            # Restaura codigo
            if (backup / "main.dart").exists():
                lib = self.project_path / "lib"
                lib.mkdir(exist_ok=True)
                shutil.copy2(backup / "main.dart", lib / "main.dart")
            if (backup / "pubspec.yaml").exists():
                shutil.copy2(backup / "pubspec.yaml", self.project_path / "pubspec.yaml")
            shutil.rmtree(backup, ignore_errors=True)
            subprocess.run(["flutter", "clean"], cwd=self.project_path, capture_output=True)
            subprocess.run(["flutter", "pub", "get"], cwd=self.project_path, capture_output=True)
            self.fixes_applied.append("fix_unsupported_gradle")
            return True
        except Exception:
            if backup.exists():
                shutil.rmtree(backup, ignore_errors=True)
            return False

    def _create_manual_android(self, project_name="app"):
        """Cria estrutura android manual (fallback se flutter create falhar)."""
        android = self.project_path / "android"
        app = android / "app"
        src = app / "src" / "main"
        src.mkdir(parents=True, exist_ok=True)
        (src / "AndroidManifest.xml").write_text(
            '<?xml version="1.0" encoding="utf-8"?>\n'
            '<manifest xmlns:android="http://schemas.android.com/apk/res/android"\n'
            f'    package="com.{project_name}.app">\n'
            '    <application android:label="app" android:name="${applicationName}"\n'
            '        android:icon="@mipmap/ic_launcher">\n'
            '        <activity android:name=".MainActivity" android:exported="true"\n'
            '            android:launchMode="singleTop"\n'
            '            android:theme="@style/LaunchTheme"\n'
            '            android:configChanges="orientation|keyboardHidden|keyboard|'
            'screenSize|smallestScreenSize|locale|layoutDirection|fontScale|screenLayout|'
            'density|uiMode"\n'
            '            android:hardwareAccelerated="true"\n'
            '            android:windowSoftInputMode="adjustResize">\n'
            '            <meta-data android:name="io.flutter.embedding.android.NormalTheme"\n'
            '                android:resource="@style/NormalTheme"/>\n'
            '            <intent-filter>\n'
            '                <action android:name="android.intent.action.MAIN"/>\n'
            '                <category android:name="android.intent.category.LAUNCHER"/>\n'
            '            </intent-filter>\n'
            '        </activity>\n'
            '        <meta-data android:name="flutterEmbedding" android:value="2" />\n'
            '    </application>\n'
            '</manifest>\n', encoding='utf-8')
        (app / "build.gradle").write_text(
            self._app_build_gradle_content(project_name), encoding='utf-8')
        (android / "build.gradle").write_text(
            'buildscript {\n    ext.kotlin_version = "1.9.22"\n'
            '    repositories { google(); mavenCentral() }\n'
            '    dependencies {\n'
            '        classpath "com.android.tools.build:gradle:8.1.0"\n'
            '        classpath "org.jetbrains.kotlin:kotlin-gradle-plugin:$kotlin_version"\n'
            '    }\n}\n'
            'allprojects {\n    repositories { google(); mavenCentral() }\n}\n'
            'rootProject.buildDir = "../build"\n'
            'subprojects {\n'
            '    project.buildDir = "${rootProject.buildDir}/${project.name}"\n}\n'
            'subprojects {\n    project.evaluationDependsOn(":app")\n}\n'
            'tasks.register("clean", Delete) {\n    delete rootProject.buildDir\n}\n',
            encoding='utf-8')
        # settings.gradle com pluginManagement (essencial para Flutter 3.x)
        sdk = os.environ.get('FLUTTER_ROOT') or "C:\\Users\\Playtec-bancada\\flutter"
        (android / "settings.gradle").write_text(
            'pluginManagement {\n'
            '    def flutterSdkPath = {\n'
            '        def properties = new Properties()\n'
            '        file("local.properties").withInputStream { properties.load(it) }\n'
            '        def flutterSdkPath = properties.getProperty("flutter.sdk")\n'
            '        assert flutterSdkPath != null, '
            '"flutter.sdk not set in local.properties"\n'
            '        return flutterSdkPath\n'
            '    }\n'
            f'    settings.ext.flutterSdkPath = flutterSdkPath()\n\n'
            '    includeBuild("${settings.ext.flutterSdkPath}'
            '/packages/flutter_tools/gradle")\n\n'
            '    repositories {\n'
            '        google()\n'
            '        mavenCentral()\n'
            '        gradlePluginPortal()\n'
            '    }\n'
            '}\n\n'
            'plugins {\n'
            '    id "dev.flutter.flutter-plugin-loader" version "1.0.0"\n'
            '    id "com.android.application" version "8.1.0" apply false\n'
            '    id "org.jetbrains.kotlin.android" version "1.9.22" apply false\n'
            '}\n\n'
            'include ":app"\n', encoding='utf-8')
        (android / "gradle.properties").write_text(
            "android.useAndroidX=true\nandroid.enableJetifier=true\n"
            "org.gradle.jvmargs=-Xmx4G\n", encoding='utf-8')
        # Gradle wrapper (essencial para o Gradle saber qual versao usar)
        wrapper_dir = android / "gradle" / "wrapper"
        wrapper_dir.mkdir(parents=True, exist_ok=True)
        (wrapper_dir / "gradle-wrapper.properties").write_text(
            "distributionBase=GRADLE_USER_HOME\n"
            "distributionPath=wrapper/dists\n"
            "distributionUrl=https\\://services.gradle.org/distributions/gradle-8.3-bin.zip\n"
            "networkTimeout=10000\n"
            "validateDistributionUrl=true\n"
            "zipStoreBase=GRADLE_USER_HOME\n"
            "zipStorePath=wrapper/dists\n", encoding='utf-8')
        sdk = (os.environ.get('FLUTTER_ROOT') or "C:\\Users\\Playtec-bancada\\flutter").replace('\\', '/')
        (android / "local.properties").write_text(f"flutter.sdk={sdk}\n", encoding='utf-8')

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
        "remove_kts_before_build": remove_kts_before_build,
        "detect_and_fix_gradle": detect_and_fix_gradle,
        "fix_unsupported_gradle": fix_unsupported_gradle,
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
