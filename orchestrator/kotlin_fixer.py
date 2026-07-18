# -*- coding: utf-8 -*-
import os
import re
import shutil
from pathlib import Path
from typing import Optional, List, Dict


class KotlinGradleFixer:
    def __init__(self, project_path: str):
        self.project_path = Path(project_path)
        self.backup_dir = self.project_path / '.gradle_backup'
        self.fixes_applied = []

    def apply_fixes(self) -> Dict:
        results = {
            'success': False,
            'fixes_applied': [],
            'errors': [],
            'backup_created': False
        }
        try:
            self._create_backup()
            results['backup_created'] = True
            if self._fix_project_gradle():
                results['fixes_applied'].append('project_build_gradle')
            if self._fix_app_gradle():
                results['fixes_applied'].append('app_build_gradle')
            if self._fix_pubspec():
                results['fixes_applied'].append('pubspec_yaml')
            if self._fix_gradle_properties():
                results['fixes_applied'].append('gradle_properties')
            results['success'] = True
        except Exception as e:
            results['errors'].append(str(e))
            self._restore_backup()
        return results

    def _create_backup(self):
        if self.backup_dir.exists():
            shutil.rmtree(self.backup_dir)
        self.backup_dir.mkdir(parents=True)
        files_to_backup = [
            'android/build.gradle',
            'android/app/build.gradle',
            'pubspec.yaml',
            'android/gradle.properties'
        ]
        for file in files_to_backup:
            src = self.project_path / file
            if src.exists():
                dst = self.backup_dir / file
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)

    def _restore_backup(self):
        if self.backup_dir.exists():
            for file in self.backup_dir.rglob('*'):
                if file.is_file():
                    rel_path = file.relative_to(self.backup_dir)
                    dst = self.project_path / rel_path
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(file, dst)

    def _fix_project_gradle(self) -> bool:
        gradle_path = self.project_path / 'android' / 'build.gradle'
        if not gradle_path.exists():
            return False
        with open(gradle_path, 'r', encoding='utf-8') as f:
            content = f.read()
        content = re.sub(
            r"ext\.kotlin_version\s*=\s*['\"]([^'\"]+)['\"]",
            "ext.kotlin_version = '1.9.22'",
            content
        )
        if "ext.kotlin_version" not in content:
            content = re.sub(
                r"(buildscript\s*\{)",
                r"\1\n    ext.kotlin_version = '1.9.22'",
                content
            )
        content = re.sub(
            r"classpath\s+['\"]com\.android\.tools\.build:gradle:[^'\"]+['\"]",
            "classpath 'com.android.tools.build:gradle:7.4.2'",
            content
        )
        if "kotlin-gradle-plugin" not in content:
            content = re.sub(
                r"(dependencies\s*\{)",
                r"\1\n        classpath \"org.jetbrains.kotlin:kotlin-gradle-plugin:\$kotlin_version\"",
                content
            )
        with open(gradle_path, 'w', encoding='utf-8') as f:
            f.write(content)
        return True

    def _fix_app_gradle(self) -> bool:
        gradle_path = self.project_path / 'android' / 'app' / 'build.gradle'
        if not gradle_path.exists():
            return False
        with open(gradle_path, 'r', encoding='utf-8') as f:
            content = f.read()
        content = re.sub(
            r"compileSdk(Version)?\s+\d+",
            "compileSdkVersion 36",
            content
        )
        if "namespace" not in content:
            content = re.sub(
                r"(android\s*\{)",
                r"\1\n    namespace \"com.example.app\"",
                content
            )
        if "compileOptions" not in content:
            content = re.sub(
                r"(android\s*\{.*?)(\n    )",
                r"\1\2    compileOptions {\n        sourceCompatibility JavaVersion.VERSION_17\n        targetCompatibility JavaVersion.VERSION_17\n    }\n",
                content,
                flags=re.DOTALL
            )
        else:
            content = re.sub(
                r"sourceCompatibility\s+JavaVersion\.VERSION_\d+",
                "sourceCompatibility JavaVersion.VERSION_17",
                content
            )
            content = re.sub(
                r"targetCompatibility\s+JavaVersion\.VERSION_\d+",
                "targetCompatibility JavaVersion.VERSION_17",
                content
            )
        if "kotlinOptions" not in content:
            content = re.sub(
                r"(android\s*\{.*?)(\n    \})",
                r"\1    kotlinOptions {\n        jvmTarget = \"17\"\n    }\n\2",
                content,
                flags=re.DOTALL
            )
        with open(gradle_path, 'w', encoding='utf-8') as f:
            f.write(content)
        return True

    def _fix_pubspec(self) -> bool:
        pubspec_path = self.project_path / 'pubspec.yaml'
        if not pubspec_path.exists():
            return False
        with open(pubspec_path, 'r', encoding='utf-8') as f:
            content = f.read()
        content = re.sub(
            r"on_audio_query:\s*[^\n]+",
            "on_audio_query: ^2.9.0",
            content
        )
        with open(pubspec_path, 'w', encoding='utf-8') as f:
            f.write(content)
        return True

    def _fix_gradle_properties(self) -> bool:
        props_path = self.project_path / 'android' / 'gradle.properties'
        properties = {
            'android.useAndroidX': 'true',
            'android.enableJetifier': 'true',
            'org.gradle.jvmargs': '-Xmx4G',
            'android.enableR8': 'true',
            'android.enableResourceOptimizations': 'true'
        }
        existing = {}
        if props_path.exists():
            with open(props_path, 'r', encoding='utf-8') as f:
                for line in f:
                    if '=' in line and not line.startswith('#'):
                        key, value = line.strip().split('=', 1)
                        existing[key] = value
        existing.update(properties)
        with open(props_path, 'w', encoding='utf-8') as f:
            for key, value in existing.items():
                f.write(f"{key}={value}\n")
        return True
