#!/usr/bin/env python3
"""
Flutter Build Orchestrator
Automatiza todo o processo de build de um aplicativo Flutter, gerando um APK pronto para instalação.
Inclui download e instalação automática de pré-requisitos se necessário.
"""

import os
import sys
import subprocess
import shutil
import argparse
import platform
import zipfile
import tarfile
import re
from pathlib import Path
from datetime import datetime
from urllib.request import urlretrieve, urlopen
from urllib.error import URLError

try:
    import yaml
    YAML_AVAILABLE = True
except ImportError:
    YAML_AVAILABLE = False
    print("AVISO: PyYAML não instalado. Algumas validações estarão limitadas.")

class Colors:
    """Cores para formatação do terminal."""
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    GREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'

def log_info(message):
    print(f"{Colors.BLUE}[INFO]{Colors.ENDC} {message}")

def log_success(message):
    print(f"{Colors.GREEN}[SUCESSO]{Colors.ENDC} {message}")

def log_warning(message):
    print(f"{Colors.WARNING}[ATENÇÃO]{Colors.ENDC} {message}")

def log_error(message):
    print(f"{Colors.FAIL}[ERRO]{Colors.ENDC} {message}")

def log_step(message):
    print(f"\n{Colors.HEADER}{'='*60}{Colors.ENDC}")
    print(f"{Colors.BOLD}{message}{Colors.ENDC}")
    print(f"{Colors.HEADER}{'='*60}{Colors.ENDC}\n")

class FlutterOrchestrator:
    def __init__(self, project_path, output_dir=None, release=True, auto_install=False):
        self.project_path = Path(project_path).resolve()
        self.release = release
        self.output_dir = Path(output_dir).resolve() if output_dir else self.project_path / "build_output"
        self.auto_install = auto_install
        self.start_time = None
        
        # Comandos base
        self.flutter_cmd = "flutter"
        self.gradle_cmd = "./gradlew" if os.name != 'nt' else "gradlew.bat"
        
        # URLs e configurações de download
        self.flutter_url = "https://storage.googleapis.com/flutter_infra_release/releases/stable/linux/flutter_linux_3.24.0-stable.tar.xz"
        if platform.system() == "Darwin":
            self.flutter_url = "https://storage.googleapis.com/flutter_infra_release/releases/stable/macos/flutter_macos_3.24.0-stable.zip"
        elif platform.system() == "Windows":
            self.flutter_url = "https://storage.googleapis.com/flutter_infra_release/releases/stable/windows/flutter_windows_3.24.0-stable.zip"
        
        self.install_dir = Path.home() / ".flutter_auto"
        self.java_url = "https://download.java.net/java/GA/jdk17.0.2/dfd4a8d0985749f896bed50d7138ee7f/8/GPL/openjdk-17.0.2_linux-x64_bin.tar.gz"

    def download_file(self, url, dest_path, description="Arquivo"):
        """Baixa um arquivo com barra de progresso."""
        log_info(f"Baixando {description}...")
        
        try:
            with urlopen(url) as response:
                total_size = int(response.getheader('Content-Length', 0))
                block_size = 8192
                downloaded = 0
                
                with open(dest_path, 'wb') as f:
                    while True:
                        buffer = response.read(block_size)
                        if not buffer:
                            break
                        f.write(buffer)
                        downloaded += len(buffer)
                        
                        if total_size > 0:
                            percent = (downloaded / total_size) * 100
                            sys.stdout.write(f'\r  Progresso: {percent:.1f}%')
                            sys.stdout.flush()
                    
                    print()  # Nova linha após progresso
                    
            log_success(f"Download concluído: {dest_path}")
            return True
        except Exception as e:
            log_error(f"Falha no download: {e}")
            return False

    def extract_archive(self, archive_path, dest_dir):
        """Extrai arquivos ZIP ou TAR."""
        log_info(f"Extraindo {archive_path.name}...")
        
        try:
            if archive_path.suffix == '.zip':
                with zipfile.ZipFile(archive_path, 'r') as zip_ref:
                    for member in zip_ref.namelist():
                        # Protege contra path traversal (CVE-2007-4559)
                        if '..' in member or member.startswith('/'):
                            log_warning(f"Arquivo suspeito ignorado: {member}")
                            continue
                        zip_ref.extract(member, dest_dir)
            elif archive_path.suffix in ['.tar', '.gz', '.xz']:
                mode = 'r:xz' if archive_path.suffix == '.xz' else 'r:gz'
                if archive_path.suffix == '.tar':
                    mode = 'r:'
                with tarfile.open(archive_path, mode) as tar_ref:
                    for member in tar_ref.getmembers():
                        # Protege contra path traversal
                        if '..' in member.name or member.name.startswith('/'):
                            log_warning(f"Arquivo suspeito ignorado: {member.name}")
                            continue
                        tar_ref.extract(member, dest_dir)
            
            log_success("Extração concluída.")
            return True
        except Exception as e:
            log_error(f"Falha na extração: {e}")
            return False

    def install_flutter(self):
        """Baixa e instala o Flutter automaticamente."""
        log_step("Instalando Flutter Automaticamente")
        
        self.install_dir.mkdir(parents=True, exist_ok=True)
        
        # Determina nome do arquivo baseado na URL
        filename = self.flutter_url.split('/')[-1]
        archive_path = self.install_dir / filename
        
        # Download
        if not self.download_file(self.flutter_url, archive_path, "Flutter SDK"):
            return False
        
        # Extração
        if not self.extract_archive(archive_path, self.install_dir):
            return False
        
        # Limpa arquivo compactado
        if archive_path.exists():
            archive_path.unlink()
        
        # Configura caminho do Flutter
        flutter_bin = self.install_dir / "flutter" / "bin"
        self.flutter_cmd = str(flutter_bin / "flutter")
        
        # Adiciona ao PATH temporariamente para esta sessão
        os.environ['PATH'] = str(flutter_bin) + os.pathsep + os.environ.get('PATH', '')
        
        log_success(f"Flutter instalado em: {self.install_dir / 'flutter'}")
        log_warning("IMPORTANTE: Para uso futuro, adicione ao seu PATH permanentemente:")
        log_warning(f"  export PATH=\"$PATH:{flutter_bin}\"")
        
        # Aceita licenças automaticamente
        log_info("Aceitando licenças do Android...")
        try:
            subprocess.run(
                [self.flutter_cmd, "doctor", "--android-licenses"],
                input="y\ny\ny\ny\ny\n",
                text=True,
                capture_output=True,
                timeout=120,
            )
            log_info("Licenças Android aceitas.")
        except Exception as e:
            log_warning(f"Não foi possível aceitar licenças automaticamente ({e}). "
                        "Execute manualmente: flutter doctor --android-licenses")
        
        return True

    def check_prerequisites(self):
        """Verifica se Flutter e Java estão instalados e acessíveis."""
        log_step("1. Verificando Pré-requisitos")
        
        flutter_found = False
        try:
            result = subprocess.run(
                [self.flutter_cmd, "--version"],
                capture_output=True, text=True, timeout=30)
            if result.returncode == 0:
                log_success("Flutter detectado.")
                version_line = result.stdout.split('\n')[0]
                log_info(f"Versão: {version_line}")
                flutter_found = True
            else:
                raise Exception("Flutter não respondeu corretamente ao comando --version.")
        except FileNotFoundError:
            log_error("Flutter não encontrado no PATH.")
        except Exception as e:
            log_error(f"Erro ao verificar Flutter: {e}")
        
        # Se não encontrou Flutter e auto_install está habilitado
        if not flutter_found:
            if self.auto_install:
                log_warning("Auto-instalação ativada. Tentando instalar Flutter...")
                if not self.install_flutter():
                    log_error("Falha na instalação automática do Flutter.")
                    return False
                # Re-verifica após instalação
                return self.check_prerequisites()
            else:
                log_error("Flutter não está instalado.")
                log_info("Use a flag --auto-install para baixar e instalar automaticamente.")
                return False

        # Verificação básica do Java/Android SDK
        java_found = False
        try:
            subprocess.run(["java", "-version"], capture_output=True, timeout=15)
            log_success("Java JDK detectado.")
            java_found = True
        except FileNotFoundError:
            log_warning("Java não encontrado no PATH.")
        
        if not java_found and self.auto_install:
            log_warning("Java não detectado. A instalação do Android Studio é recomendada para o SDK completo.")
            log_info("O Flutter pode funcionar com o Java embutido do Android Studio.")
        
        return True

    def validate_project(self):
        """Valida se o diretório contém um projeto Flutter válido."""
        log_step("2. Validando Projeto")
        
        pubspec_file = self.project_path / "pubspec.yaml"
        if not pubspec_file.exists():
            log_error(f"Arquivo pubspec.yaml não encontrado em {self.project_path}.")
            log_error("Este não parece ser um projeto Flutter válido.")
            return False
        
        # Valida e corrige o pubspec.yaml antes de prosseguir
        if not self._validate_and_fix_pubspec(pubspec_file):
            log_error("Falha ao validar/corrigir pubspec.yaml. Build não pode continuar.")
            return False
        
        lib_main = self.project_path / "lib" / "main.dart"
        if not lib_main.exists():
            log_warning(f"Arquivo lib/main.dart não encontrado. O build pode falhar se a entrada não for padrão.")
        
        log_success("Estrutura do projeto validada.")
        return True

    def _validate_and_fix_pubspec(self, pubspec_path: Path) -> bool:
        """
        Valida e tenta corrigir automaticamente erros no pubspec.yaml.
        Problemas conhecidos que corrige:
        - Linhas mescladas sem quebra (ex: 'version: 1.0.0+1  environment:')
        - Indentação incorreta
        - Nomes de pacotes com espaços extras
        """
        log_info("Validando sintaxe do pubspec.yaml...")
        
        try:
            content = pubspec_path.read_text(encoding='utf-8')
        except Exception as e:
            log_error(f"Não foi possível ler pubspec.yaml: {e}")
            return False
        
        original_content = content
        fixed = False
        
        # Correção 1: Quebrar linhas mescladas (problema crítico do log)
        # Padrão: "version: X.Y.Z+ABC  environment:" ou similar
        # Detecta quando há duas chaves YAML na mesma linha sem quebra
        lines = content.split('\n')
        new_lines = []
        
        for i, line in enumerate(lines):
            # Detecta padrões como "version: 1.0.0+1  environment:" ou "sdk: ^3.0  flutter:"
            # Procura por múltiplos pares chave-valor na mesma linha
            merged_pattern = r'^(\s*)(\w+):\s*([^\n]+?)\s+(\w+):\s*(.*)$'
            match = re.match(merged_pattern, line)
            
            if match and not line.strip().startswith('#'):
                indent, key1, val1, key2, val2 = match.groups()
                # Verifica se parece ser uma fusão acidental
                if key1 in ['version', 'sdk', 'environment', 'dependencies', 'flutter'] or \
                   key2 in ['version', 'sdk', 'environment', 'dependencies', 'flutter']:
                    log_warning(f"Linha {i+1} detectada como mesclada: '{line[:60]}...'")
                    log_info(f"  Corrigindo: separando '{key1}' e '{key2}' em linhas distintas")
                    new_lines.append(f"{indent}{key1}: {val1.strip()}")
                    new_lines.append(f"{indent}{key2}: {val2.strip()}")
                    fixed = True
                else:
                    new_lines.append(line)
            else:
                new_lines.append(line)
        
        content = '\n'.join(new_lines)
        
        # Correção 2: Remover espaços extras em nomes de pacotes
        # Padrão: "just_au  on_audio_query:" -> "on_audio_query:"
        pkg_pattern = r'^(\s+)([\w_]+)\s+([\w_]+):\s*(.*)$'
        new_lines = []
        for line in content.split('\n'):
            match = re.match(pkg_pattern, line)
            if match and not line.strip().startswith('#'):
                indent, pkg1, pkg2, version = match.groups()
                # Mantém apenas o segundo nome (geralmente o correto)
                log_warning(f"Pacote com espaço extra detectado: '{pkg1}  {pkg2}'")
                log_info(f"  Corrigindo para: '{pkg2}'")
                new_lines.append(f"{indent}{pkg2}: {version}")
                fixed = True
            else:
                new_lines.append(line)
        
        content = '\n'.join(new_lines)
        
        # Correção 3: Garantir indentação consistente (2 espaços)
        # Substitui tabs por espaços
        if '\t' in content:
            log_warning("Tabs detectados no pubspec.yaml - convertendo para espaços")
            content = content.replace('\t', '  ')
            fixed = True
        
        # Se houve correções, salva o arquivo
        if fixed:
            log_success("Correções aplicadas ao pubspec.yaml")
            try:
                pubspec_path.write_text(content, encoding='utf-8')
            except Exception as e:
                log_error(f"Não foi possível salvar pubspec.yaml corrigido: {e}")
                return False
        
        # Validação final com yaml library se disponível
        if YAML_AVAILABLE:
            try:
                yaml.safe_load(content)
                log_success("pubspec.yaml é sintaticamente válido")
                return True
            except yaml.YAMLError as e:
                log_error(f"Erro de sintaxe YAML persistente: {e}")
                log_error("O pubspec.yaml continua inválido após as correções automáticas.")
                log_error("Corrija manualmente o arquivo antes de tentar o build novamente.")
                return False  # YAML comprovadamente inválido — abortar é melhor que falhar no meio do build
        else:
            # Sem yaml library, apenas retorna True após correções básicas
            log_info("PyYAML não disponível - validação limitada aplicada")
            return True

    def clean_build(self):
        """Limpa builds anteriores."""
        log_step("3. Limpando Build Anterior")
        
        try:
            log_info("Executando 'flutter clean'...")
            subprocess.run(
                [self.flutter_cmd, "clean"],
                cwd=self.project_path, check=True, timeout=60)
            
            # Limpa pacotes obtidos para garantir integridade (opcional, mas recomendado para CI)
            log_info("Removendo pasta .packages e build...")
            # O flutter clean já faz isso, mas garantimos limpeza extra se necessário
            
            log_success("Limpeza concluída.")
            return True
        except subprocess.CalledProcessError:
            log_error("Falha ao limpar o projeto.")
            return False

    def get_dependencies(self):
        """Instala/atualiza dependências do projeto."""
        log_step("4. Obtendo Dependências")
        
        try:
            log_info("Executando 'flutter pub get'...")
            subprocess.run(
                [self.flutter_cmd, "pub", "get"],
                cwd=self.project_path, check=True, timeout=300)
            log_success("Dependências resolvidas e instaladas.")
            return True
        except subprocess.CalledProcessError:
            log_error("Falha ao obter dependências. Verifique sua conexão ou o arquivo pubspec.yaml.")
            return False

    def analyze_code(self):
        """Analisa o código em busca de erros estáticos."""
        log_step("5. Analisando Código Estático")
        
        try:
            log_info("Executando 'flutter analyze'...")
            # Não usamos check=True estritamente aqui pois warnings não devem parar o build necessariamente,
            # mas errors sim. O flutter analyze retorna 1 se houver errors.
            result = subprocess.run(
                [self.flutter_cmd, "analyze"],
                cwd=self.project_path, capture_output=True, text=True, timeout=120)
            
            if result.returncode != 0:
                log_warning("Análise estática encontrou problemas:")
                print(result.stdout)
                print(result.stderr)
                
                # Se houver "error" (não apenas warning), paramos
                if "error:" in result.stdout.lower() or "error:" in result.stderr.lower():
                    log_error("Erros críticos de análise encontrados. Build abortado.")
                    return False
                else:
                    log_warning("Apenas warnings encontrados. Continuando o build...")
            else:
                log_success("Nenhum problema encontrado na análise estática.")
            
            return True
        except Exception as e:
            log_error(f"Erro durante a análise: {e}")
            return False

    def build_apk(self):
        """Compila o aplicativo Android (APK)."""
        mode_str = "Release" if self.release else "Debug"
        log_step(f"6. Compilando APK ({mode_str})")
        
        try:
            output_dir_created = False
            if not self.output_dir.exists():
                self.output_dir.mkdir(parents=True, exist_ok=True)
                output_dir_created = True

            build_type_flag = "--release" if self.release else "--debug"
            
            log_info(f"Iniciando compilação {mode_str}...")
            log_info("Isso pode demorar alguns minutos na primeira vez.")
            
            # Comando de build
            cmd = [self.flutter_cmd, "build", "apk", build_type_flag]
            
            # Executa e mostra output em tempo real
            process = subprocess.Popen(
                cmd,
                cwd=self.project_path,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True
            )
            
            for line in process.stdout:
                print(line, end='') # Imprime o log do flutter em tempo real
            
            process.wait()
            
            if process.returncode != 0:
                raise subprocess.CalledProcessError(process.returncode, cmd)

            # Localizar o APK gerado
            # O caminho padrão é build/app/outputs/flutter-apk/app-*.apk
            build_output_path = self.project_path / "build" / "app" / "outputs" / "flutter-apk"
            
            if not build_output_path.exists():
                raise FileNotFoundError("Diretório de saída do build não encontrado.")

            apks = list(build_output_path.glob("app-*.apk"))
            
            if not apks:
                raise FileNotFoundError("Nenhum arquivo APK foi gerado.")

            # Pega o APK mais recente
            latest_apk = max(apks, key=os.path.getctime)
            
            # Copia para a pasta de destino final
            final_name = f"app-{mode_str.lower()}-{datetime.now().strftime('%Y%m%d-%H%M%S')}.apk"
            final_path = self.output_dir / final_name
            
            shutil.copy2(latest_apk, final_path)
            
            log_success(f"Build concluído com sucesso!")
            log_info(f"APK gerado: {final_path}")
            log_info(f"Tamanho: {final_path.stat().st_size / (1024*1024):.2f} MB")
            
            return True

        except subprocess.CalledProcessError:
            log_error("Falha na compilação do APK. Verifique os logs acima para detalhes.")
            return False
        except Exception as e:
            log_error(f"Erro inesperado durante o build: {e}")
            return False

    def run(self):
        """Executa todo o pipeline de orquestração."""
        self.start_time = datetime.now()
        print(f"\n{Colors.BOLD}Iniciando Flutter Build Orchestrator{Colors.ENDC}")
        print(f"Projeto: {self.project_path}")
        print(f"Data: {self.start_time.strftime('%Y-%m-%d %H:%M:%S')}\n")

        steps = [
            ("Pré-requisitos", self.check_prerequisites),
            ("Validação do Projeto", self.validate_project),
            ("Limpeza", self.clean_build),
            ("Dependências", self.get_dependencies),
            ("Análise de Código", self.analyze_code),
            ("Compilação APK", self.build_apk),
        ]

        for step_name, step_func in steps:
            if not step_func():
                log_error(f"O processo falhou na etapa: {step_name}")
                print(f"\n{Colors.FAIL}Build Abortado.{Colors.ENDC}")
                return False
        
        end_time = datetime.now()
        duration = end_time - self.start_time
        
        log_step("Conclusão")
        log_success(f"Todo o processo foi concluído com sucesso em {duration}.")
        log_info(f"Seu APK está pronto para instalar no celular em: {self.output_dir}")
        
        return True

def main():
    parser = argparse.ArgumentParser(
        description="Orquestra o build de um projeto Flutter gerando um APK.",
        formatter_class=argparse.RawTextHelpFormatter
    )
    
    parser.add_argument(
        "project_path", 
        help="Caminho para a raiz do projeto Flutter (onde fica o pubspec.yaml)."
    )
    
    parser.add_argument(
        "-o", "--output", 
        help="Diretório de saída para o APK final. (Padrão: <projeto>/build_output)", 
        default=None
    )
    
    parser.add_argument(
        "--debug", 
        action="store_true", 
        help="Gera um APK de debug (menor, mas mais lento). Padrão é Release."
    )
    
    parser.add_argument(
        "--auto-install", 
        action="store_true", 
        help="Baixa e instala automaticamente o Flutter se não estiver presente no sistema."
    )

    args = parser.parse_args()

    if not os.path.exists(args.project_path):
        log_error(f"Caminho do projeto não existe: {args.project_path}")
        sys.exit(1)

    orchestrator = FlutterOrchestrator(
        project_path=args.project_path,
        output_dir=args.output,
        release=not args.debug,
        auto_install=args.auto_install
    )

    success = orchestrator.run()
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()
