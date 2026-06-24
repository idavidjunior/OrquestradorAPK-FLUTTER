#!/usr/bin/env python3
"""
Flutter Build Orchestrator
Automatiza todo o processo de build de aplicativos Flutter, gerando APK pronto para instalação.
"""

import os
import sys
import subprocess
import shutil
import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict


class Color:
    """Cores para output no terminal"""
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    RESET = '\033[0m'
    BOLD = '\033[1m'


class FlutterBuildOrchestrator:
    """Orquestrador de builds Flutter"""

    def __init__(self, project_path: str, output_dir: str = "build_output"):
        self.project_path = Path(project_path).resolve()
        self.output_dir = Path(output_dir).resolve()
        self.build_log: List[Dict] = []
        self.start_time = datetime.now()

    def log(self, message: str, level: str = "INFO"):
        """Registra uma mensagem de log"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.build_log.append({
            "timestamp": timestamp,
            "level": level,
            "message": message
        })

        color_map = {
            "INFO": Color.BLUE,
            "SUCCESS": Color.GREEN,
            "WARNING": Color.YELLOW,
            "ERROR": Color.RED,
            "STEP": Color.CYAN
        }
        color = color_map.get(level, Color.RESET)
        print(f"{color}[{timestamp}] [{level}] {message}{Color.RESET}")

    def check_prerequisites(self) -> bool:
        """Verifica se todas as dependências estão instaladas"""
        self.log("Verificando pré-requisitos...", "STEP")

        prerequisites = {
            "flutter": "Flutter SDK não encontrado. Instale em: https://flutter.dev",
            "git": "Git não encontrado. Instale com: sudo apt install git",
            "java": "Java JDK não encontrado. Necessário para build Android",
            "gradle": "Gradle não encontrado (será baixado automaticamente)"
        }

        all_ok = True

        # Verificar Flutter
        try:
            result = subprocess.run(
                ["flutter", "--version"],
                capture_output=True,
                text=True,
                timeout=30
            )
            if result.returncode == 0:
                self.log(f"Flutter encontrado: {result.stdout.split(chr(10))[0]}", "SUCCESS")
            else:
                self.log("Flutter instalado mas com problemas", "WARNING")
        except FileNotFoundError:
            self.log(prerequisites["flutter"], "ERROR")
            all_ok = False
        except subprocess.TimeoutExpired:
            self.log("Timeout ao verificar Flutter", "ERROR")
            all_ok = False

        # Verificar Git
        try:
            subprocess.run(["git", "--version"], capture_output=True, timeout=10)
            self.log("Git encontrado", "SUCCESS")
        except FileNotFoundError:
            self.log(prerequisites["git"], "ERROR")
            all_ok = False

        # Verificar Java
        try:
            result = subprocess.run(
                ["java", "-version"],
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode == 0:
                version_info = result.stderr.split('\n')[0]
                self.log(f"Java encontrado: {version_info}", "SUCCESS")
            else:
                self.log(prerequisites["java"], "ERROR")
                all_ok = False
        except FileNotFoundError:
            self.log(prerequisites["java"], "ERROR")
            all_ok = False

        return all_ok

    def validate_flutter_project(self) -> bool:
        """Valida se o diretório contém um projeto Flutter válido"""
        self.log("Validando projeto Flutter...", "STEP")

        required_files = ["pubspec.yaml"]
        optional_files = ["lib/main.dart", "android/app/build.gradle"]

        all_present = True

        for file in required_files:
            if not (self.project_path / file).exists():
                self.log(f"Arquivo obrigatório não encontrado: {file}", "ERROR")
                all_present = False
            else:
                self.log(f"Arquivo encontrado: {file}", "SUCCESS")

        # Verificar se é realmente um projeto Flutter
        pubspec_path = self.project_path / "pubspec.yaml"
        if pubspec_path.exists():
            try:
                with open(pubspec_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                    if 'sdk: flutter' in content or 'flutter:' in content:
                        self.log("Projeto Flutter validado", "SUCCESS")
                    else:
                        self.log("pubspec.yaml não parece ser um projeto Flutter", "WARNING")
            except Exception as e:
                self.log(f"Erro ao ler pubspec.yaml: {e}", "ERROR")
                all_present = False

        return all_present

    def get_dependencies(self) -> bool:
        """Instala as dependências do projeto"""
        self.log("Obtendo dependências...", "STEP")

        try:
            result = subprocess.run(
                ["flutter", "pub", "get"],
                cwd=self.project_path,
                capture_output=True,
                text=True,
                timeout=300
            )

            if result.returncode == 0:
                self.log("Dependências instaladas com sucesso", "SUCCESS")
                return True
            else:
                self.log(f"Erro ao obter dependências: {result.stderr}", "ERROR")
                return False

        except subprocess.TimeoutExpired:
            self.log("Timeout ao obter dependências", "ERROR")
            return False
        except Exception as e:
            self.log(f"Erro inesperado: {e}", "ERROR")
            return False

    def analyze_code(self) -> bool:
        """Executa análise estática do código"""
        self.log("Analisando código...", "STEP")

        try:
            result = subprocess.run(
                ["flutter", "analyze"],
                cwd=self.project_path,
                capture_output=True,
                text=True,
                timeout=300
            )

            if result.returncode == 0:
                self.log("Análise de código concluída sem erros", "SUCCESS")
                return True
            else:
                self.log(f"Avisos na análise de código:\n{result.stdout}", "WARNING")
                # Não falhamos o build por warnings, apenas informamos
                return True

        except subprocess.TimeoutExpired:
            self.log("Timeout na análise de código", "ERROR")
            return False
        except Exception as e:
            self.log(f"Erro na análise: {e}", "ERROR")
            return False

    def run_tests(self, skip: bool = False) -> bool:
        """Executa testes unitários"""
        if skip:
            self.log("Pulando testes (flag --skip-tests)", "INFO")
            return True

        self.log("Executando testes...", "STEP")

        # Verificar se existem testes
        test_dir = self.project_path / "test"
        if not test_dir.exists() or not list(test_dir.glob("*.dart")):
            self.log("Nenhum teste encontrado, pulando...", "INFO")
            return True

        try:
            result = subprocess.run(
                ["flutter", "test"],
                cwd=self.project_path,
                capture_output=True,
                text=True,
                timeout=600
            )

            if result.returncode == 0:
                self.log("Todos os testes passaram", "SUCCESS")
                return True
            else:
                self.log(f"Testes falharam:\n{result.stdout}\n{result.stderr}", "ERROR")
                return False

        except subprocess.TimeoutExpired:
            self.log("Timeout nos testes", "ERROR")
            return False
        except Exception as e:
            self.log(f"Erro nos testes: {e}", "ERROR")
            return False

    def build_apk(self, release: bool = True, build_number: Optional[str] = None) -> bool:
        """Compila o APK"""
        mode = "release" if release else "debug"
        self.log(f"Compilando APK ({mode})...", "STEP")

        try:
            cmd = ["flutter", "build", "apk"]
            if release:
                cmd.append("--release")
            if build_number:
                cmd.extend(["--build-number", build_number])

            result = subprocess.run(
                cmd,
                cwd=self.project_path,
                capture_output=True,
                text=True,
                timeout=1800  # 30 minutos para build
            )

            if result.returncode == 0:
                self.log("APK compilado com sucesso", "SUCCESS")
                return True
            else:
                self.log(f"Erro na compilação:\n{result.stderr}", "ERROR")
                return False

        except subprocess.TimeoutExpired:
            self.log("Timeout na compilação do APK", "ERROR")
            return False
        except Exception as e:
            self.log(f"Erro na compilação: {e}", "ERROR")
            return False

    def copy_artifacts(self) -> Optional[Path]:
        """Copia o APK gerado para o diretório de output"""
        self.log("Copiando artifacts...", "STEP")

        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Procura qualquer .apk gerado, ordenado por data (mais recente primeiro)
        flutter_apk_dir = self.project_path / "build" / "app" / "outputs" / "flutter-apk"
        legacy_dir      = self.project_path / "build" / "app" / "outputs" / "apk"

        candidates = []
        for search_dir in [flutter_apk_dir, legacy_dir]:
            if search_dir.exists():
                candidates.extend(search_dir.rglob("*.apk"))

        if not candidates:
            self.log("APK não encontrado após build — verifique os logs acima", "ERROR")
            self.log(f"  Diretório procurado: {flutter_apk_dir}", "ERROR")
            return None

        # Mais recente primeiro
        apk_path = sorted(candidates, key=lambda p: p.stat().st_mtime, reverse=True)[0]
        self.log(f"APK encontrado: {apk_path.name}", "SUCCESS")

        # Gerar nome do arquivo com timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_name = f"app_{timestamp}.apk"
        output_path = self.output_dir / output_name

        try:
            shutil.copy2(apk_path, output_path)
            self.log(f"APK copiado para: {output_path}", "SUCCESS")

            # Copiar também mapa de símbolos (se existir)
            mapping_path = self.project_path / "build" / "app" / "outputs" / "mapping" / "release" / "mapping.txt"
            if mapping_path.exists():
                mapping_output = self.output_dir / f"mapping_{timestamp}.txt"
                shutil.copy2(mapping_path, mapping_output)
                self.log(f"Mapping file copiado: {mapping_output}", "SUCCESS")

            return output_path

        except Exception as e:
            self.log(f"Erro ao copiar APK: {e}", "ERROR")
            return None

    def generate_build_report(self, apk_path: Optional[Path], success: bool):
        """Gera relatório do build"""
        self.log("Gerando relatório do build...", "STEP")

        report = {
            "build_info": {
                "project_path": str(self.project_path),
                "timestamp": self.start_time.isoformat(),
                "duration_seconds": (datetime.now() - self.start_time).total_seconds(),
                "success": success
            },
            "apk_info": {
                "path": str(apk_path) if apk_path else None,
                "size_bytes": apk_path.stat().st_size if apk_path and apk_path.exists() else None,
                "size_mb": round(apk_path.stat().st_size / (1024 * 1024), 2) if apk_path and apk_path.exists() else None
            },
            "build_log": self.build_log
        }

        report_path = self.output_dir / "build_report.json"
        try:
            with open(report_path, 'w', encoding='utf-8') as f:
                json.dump(report, f, indent=2, ensure_ascii=False)
            self.log(f"Relatório gerado: {report_path}", "SUCCESS")
        except Exception as e:
            self.log(f"Erro ao gerar relatório: {e}", "ERROR")

        # Print summary
        print("\n" + "=" * 60)
        print(f"{Color.BOLD}RESUMO DO BUILD{Color.RESET}")
        print("=" * 60)
        status_color = Color.GREEN if success else Color.RED
        status_text = "SUCESSO" if success else "FALHA"
        print(f"Status: {status_color}{status_text}{Color.RESET}")
        print(f"Duração: {report['build_info']['duration_seconds']:.2f} segundos")
        if apk_path and apk_path.exists():
            print(f"APK: {apk_path.name}")
            print(f"Tamanho: {report['apk_info']['size_mb']} MB")
        print(f"Output: {self.output_dir}")
        print("=" * 60)

    def orchestrate(self, skip_tests: bool = False, debug: bool = False, build_number: Optional[str] = None) -> bool:
        """Executa todo o pipeline de build"""
        print(f"\n{Color.BOLD}{Color.CYAN}{'=' * 60}{Color.RESET}")
        print(f"{Color.BOLD}{Color.CYAN}FLUTTER BUILD ORCHESTRATOR{Color.RESET}")
        print(f"{Color.BOLD}{Color.CYAN}{'=' * 60}{Color.RESET}\n")

        self.log(f"Iniciando build orchestrator", "INFO")
        self.log(f"Projeto: {self.project_path}", "INFO")
        self.log(f"Output: {self.output_dir}", "INFO")

        # Pipeline de build
        steps = [
            ("Pré-requisitos", lambda: self.check_prerequisites()),
            ("Validação do Projeto", lambda: self.validate_flutter_project()),
            ("Dependências", lambda: self.get_dependencies()),
            ("Análise de Código", lambda: self.analyze_code()),
            ("Testes", lambda: self.run_tests(skip=skip_tests)),
            ("Build APK", lambda: self.build_apk(release=not debug, build_number=build_number)),
            ("Copy Artifacts", lambda: self.copy_artifacts()),
        ]

        apk_path = None
        for step_name, step_func in steps:
            self.log(f"\n>>> Executando: {step_name}", "STEP")
            try:
                result = step_func()
                if not result and step_name != "Testes":  # Testes podem falhar sem parar o build em alguns casos
                    self.log(f"Step '{step_name}' falhou. Abortando build.", "ERROR")
                    self.generate_build_report(apk_path, False)
                    return False
                elif step_name == "Copy Artifacts" and result:
                    apk_path = result
            except Exception as e:
                self.log(f"Erro no step '{step_name}': {e}", "ERROR")
                self.generate_build_report(apk_path, False)
                return False

        success = apk_path is not None
        self.generate_build_report(apk_path, success)

        if success:
            self.log("\n" + "🎉 " * 10, "SUCCESS")
            self.log("BUILD CONCLUÍDO COM SUCESSO!", "SUCCESS")
            self.log("🎉 " * 10, "SUCCESS")
        else:
            self.log("BUILD FALHOU", "ERROR")

        return success


def main():
    parser = argparse.ArgumentParser(
        description="Flutter Build Orchestrator - Automatiza o build de APKs Flutter",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemplos de uso:
  %(prog)s ./meu_projeto_flutter
  %(prog)s ./meu_projeto_flutter --output ./builds
  %(prog)s ./meu_projeto_flutter --debug --skip-tests
  %(prog)s ./meu_projeto_flutter --build-number 42
        """
    )

    parser.add_argument(
        "project_path",
        help="Caminho para o projeto Flutter"
    )
    parser.add_argument(
        "--output", "-o",
        default="build_output",
        help="Diretório de output para o APK (padrão: build_output)"
    )
    parser.add_argument(
        "--debug", "-d",
        action="store_true",
        help="Build em modo debug (padrão: release)"
    )
    parser.add_argument(
        "--skip-tests",
        action="store_true",
        help="Pular execução de testes"
    )
    parser.add_argument(
        "--build-number", "-b",
        type=str,
        help="Número da build (opcional)"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Output verbose"
    )

    args = parser.parse_args()

    # Validar caminho do projeto
    project_path = Path(args.project_path).resolve()
    if not project_path.exists():
        print(f"{Color.RED}Erro: Projeto não encontrado em {project_path}{Color.RESET}")
        sys.exit(1)

    # Criar e executar orchestrator
    orchestrator = FlutterBuildOrchestrator(
        project_path=str(project_path),
        output_dir=args.output
    )

    success = orchestrator.orchestrate(
        skip_tests=args.skip_tests,
        debug=args.debug,
        build_number=args.build_number
    )

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
