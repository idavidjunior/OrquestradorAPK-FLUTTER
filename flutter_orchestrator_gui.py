#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Flutter Build Orchestrator - Interface Gráfica
Uma interface moderna para orquestrar builds de aplicativos Flutter.
"""

import sys
import os

# Verificar se há suporte a GUI antes de importar tkinter
def check_gui_support():
    """Verifica se há suporte para interface gráfica"""
    # Verificar variável DISPLAY (Linux/Mac)
    if os.name == 'posix' and not os.environ.get('DISPLAY'):
        return False
    
    try:
        import tkinter
        # Tentar criar uma janela invisível para testar
        root = tkinter.Tk()
        root.withdraw()
        root.destroy()
        return True
    except Exception:
        return False

HAS_GUI_SUPPORT = check_gui_support()

if HAS_GUI_SUPPORT:
    import customtkinter as ctk
    import tkinter as tk
    from tkinter import filedialog, messagebox
    
    # Configuração inicial do tema (apenas se GUI disponível)
    ctk.set_appearance_mode("System")
    ctk.set_default_color_theme("blue")
    
    class FlutterOrchestratorGUI(ctk.CTk):
        pass

# Placeholder para evitar erro de sintaxe quando HAS_GUI_SUPPORT=False
class _FlutterOrchestratorGUI:
    pass
    def __init__(self):
        super().__init__()

        # Configuração da janela principal
        self.title("🚀 Flutter Build Orchestrator")
        self.geometry("900x700")
        self.minsize(800, 600)

        # Variáveis de estado
        self.project_path = tk.StringVar()
        self.output_path = tk.StringVar()
        self.build_type = tk.StringVar(value="release")
        self.auto_install = tk.BooleanVar(value=True)
        self.is_building = False
        self.process = None

        # Criar layout
        self.create_widgets()

    def create_widgets(self):
        """Cria todos os widgets da interface"""
        
        # Frame principal com padding
        self.main_frame = ctk.CTkFrame(self, corner_radius=0)
        self.main_frame.pack(fill="both", expand=True, padx=20, pady=20)

        # Título
        self.title_label = ctk.CTkLabel(
            self.main_frame, 
            text="🚀 Flutter Build Orchestrator", 
            font=ctk.CTkFont(size=24, weight="bold")
        )
        self.title_label.pack(pady=(0, 20))

        # Frame de configuração
        self.config_frame = ctk.CTkFrame(self.main_frame)
        self.config_frame.pack(fill="x", pady=(0, 20))

        # Seleção do projeto
        self.project_label = ctk.CTkLabel(self.config_frame, text="📁 Projeto Flutter:")
        self.project_label.grid(row=0, column=0, padx=(10, 10), pady=15, sticky="w")
        
        self.project_entry = ctk.CTkEntry(
            self.config_frame, 
            textvariable=self.project_path, 
            width=500,
            placeholder_text="Selecione a pasta do projeto Flutter..."
        )
        self.project_entry.grid(row=0, column=1, padx=10, pady=15, sticky="ew")
        
        self.project_btn = ctk.CTkButton(
            self.config_frame, 
            text="📂 Procurar", 
            command=self.browse_project,
            width=100
        )
        self.project_btn.grid(row=0, column=2, padx=10, pady=15)

        # Pasta de saída (opcional)
        self.output_label = ctk.CTkLabel(self.config_frame, text="📤 Pasta de Saída:")
        self.output_label.grid(row=1, column=0, padx=(10, 10), pady=15, sticky="w")
        
        self.output_entry = ctk.CTkEntry(
            self.config_frame, 
            textvariable=self.output_path, 
            width=500,
            placeholder_text="Deixe vazio para usar pasta padrão do projeto..."
        )
        self.output_entry.grid(row=1, column=1, padx=10, pady=15, sticky="ew")
        
        self.output_btn = ctk.CTkButton(
            self.config_frame, 
            text="📂 Procurar", 
            command=self.browse_output,
            width=100
        )
        self.output_btn.grid(row=1, column=2, padx=10, pady=15)

        # Opções de Build
        self.options_frame = ctk.CTkFrame(self.main_frame)
        self.options_frame.pack(fill="x", pady=(0, 20))

        self.options_label = ctk.CTkLabel(self.options_frame, text="⚙️ Opções de Build:", font=ctk.CTkFont(weight="bold"))
        self.options_label.grid(row=0, column=0, padx=10, pady=10, sticky="w")

        # Tipo de Build (Radio buttons)
        self.release_radio = ctk.CTkRadioButton(
            self.options_frame, 
            text="📦 Release (Produção)", 
            variable=self.build_type, 
            value="release"
        )
        self.release_radio.grid(row=1, column=0, padx=20, pady=5, sticky="w")

        self.debug_radio = ctk.CTkRadioButton(
            self.options_frame, 
            text="🐛 Debug (Testes)", 
            variable=self.build_type, 
            value="debug"
        )
        self.debug_radio.grid(row=1, column=1, padx=20, pady=5, sticky="w")

        # Auto-install checkbox
        self.auto_install_check = ctk.CTkCheckBox(
            self.options_frame, 
            text="🔄 Instalar Flutter automaticamente se não encontrado", 
            variable=self.auto_install
        )
        self.auto_install_check.grid(row=2, column=0, columnspan=2, padx=20, pady=10, sticky="w")

        # Botão de Build
        self.build_button = ctk.CTkButton(
            self.main_frame, 
            text="🔨 Iniciar Build", 
            command=self.start_build,
            height=50,
            font=ctk.CTkFont(size=16, weight="bold"),
            fg_color="#28a745",
            hover_color="#218838"
        )
        self.build_button.pack(fill="x", pady=(0, 20), padx=20)

        # Área de Log
        self.log_frame = ctk.CTkFrame(self.main_frame)
        self.log_frame.pack(fill="both", expand=True, pady=(0, 10))

        self.log_label = ctk.CTkLabel(self.log_frame, text="📋 Logs em Tempo Real:", font=ctk.CTkFont(weight="bold"))
        self.log_label.pack(anchor="w", padx=10, pady=(10, 5))

        self.log_text = ctk.CTkTextbox(self.log_frame, wrap="word", state="disabled")
        self.log_text.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        # Barra de progresso
        self.progress_bar = ctk.CTkProgressBar(self.main_frame, mode="indeterminate")
        self.progress_bar.pack(fill="x", padx=20, pady=(0, 10))
        self.progress_bar.set(0)

        # Status label
        self.status_label = ctk.CTkLabel(self.main_frame, text="✅ Pronto para iniciar", text_color="gray")
        self.status_label.pack(pady=(0, 10))

        # Configurar grid weights
        self.config_frame.grid_columnconfigure(1, weight=1)

    def browse_project(self):
        """Abre dialog para selecionar pasta do projeto"""
        folder = filedialog.askdirectory(title="Selecione a pasta do projeto Flutter")
        if folder:
            self.project_path.set(folder)
            self.log_message(f"📁 Projeto selecionado: {folder}", "info")

    def browse_output(self):
        """Abre dialog para selecionar pasta de saída"""
        folder = filedialog.askdirectory(title="Selecione a pasta de saída")
        if folder:
            self.output_path.set(folder)
            self.log_message(f"📤 Pasta de saída definida: {folder}", "info")

    def log_message(self, message, level="info"):
        """Adiciona mensagem ao log com cores diferentes"""
        self.log_text.configure(state="normal")
        
        timestamp = datetime.now().strftime("%H:%M:%S")
        
        # Cores baseadas no nível
        if level == "error":
            color = "#ff4444"
            prefix = "❌"
        elif level == "success":
            color = "#00cc66"
            prefix = "✅"
        elif level == "warning":
            color = "#ffaa00"
            prefix = "⚠️"
        elif level == "info":
            color = "#4488ff"
            prefix = "ℹ️"
        else:
            color = "#ffffff"
            prefix = "•"

        # Inserir texto colorido (simulado com tags)
        self.log_text.insert("end", f"[{timestamp}] {prefix} {message}\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def start_build(self):
        """Inicia o processo de build em uma thread separada"""
        if self.is_building:
            messagebox.showwarning("Atenção", "Um build já está em andamento!")
            return

        project_path = self.project_path.get().strip()
        
        if not project_path:
            messagebox.showerror("Erro", "Por favor, selecione a pasta do projeto Flutter!")
            return

        if not os.path.exists(project_path):
            messagebox.showerror("Erro", "A pasta do projeto não existe!")
            return

        # Verificar se é um projeto Flutter válido
        pubspec_file = os.path.join(project_path, "pubspec.yaml")
        if not os.path.exists(pubspec_file):
            messagebox.showerror("Erro", "Não foi encontrado 'pubspec.yaml'. Isso não parece ser um projeto Flutter válido!")
            return

        # Preparar para build
        self.is_building = True
        self.build_button.configure(text="⏳ Build em Andamento...", state="disabled", fg_color="#ffc107")
        self.progress_bar.start()
        self.status_label.configure(text="🔄 Iniciando processo de build...", text_color="#ffc107")
        
        # Limpar log anterior
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

        # Iniciar build em thread separada
        build_thread = threading.Thread(target=self.run_build_process, args=(project_path,), daemon=True)
        build_thread.start()

    def run_build_process(self, project_path):
        """Executa o processo de build"""
        try:
            start_time = datetime.now()
            
            self.log_message("🚀 Iniciando Flutter Build Orchestrator", "info")
            self.log_message(f"📁 Projeto: {project_path}", "info")
            self.log_message(f"📦 Tipo de build: {self.build_type.get().upper()}", "info")
            
            # Passo 1: Verificar/Instalar Flutter
            self.update_status("Verificando Flutter...")
            flutter_available = self.check_flutter()
            
            if not flutter_available:
                if self.auto_install.get():
                    self.log_message("⚠️ Flutter não encontrado. Tentando instalar automaticamente...", "warning")
                    self.update_status("Instalando Flutter...")
                    if not self.install_flutter():
                        raise Exception("Falha na instalação automática do Flutter")
                    self.log_message("✅ Flutter instalado com sucesso!", "success")
                else:
                    raise Exception("Flutter não encontrado. Marque 'Instalar automaticamente' ou instale manualmente.")
            
            # Passo 2: Limpeza
            self.update_status("Limpando build anterior...")
            self.log_message("🧹 Executando flutter clean...", "info")
            if not self.run_command(["flutter", "clean"], project_path):
                raise Exception("Falha na limpeza do projeto")
            
            # Passo 3: Obter dependências
            self.update_status("Baixando dependências...")
            self.log_message("📥 Executando flutter pub get...", "info")
            if not self.run_command(["flutter", "pub", "get"], project_path):
                raise Exception("Falha ao obter dependências")
            
            # Passo 4: Análise estática
            self.update_status("Analisando código...")
            self.log_message("🔍 Executando flutter analyze...", "info")
            # Não falhamos se houver warnings, apenas informamos
            self.run_command(["flutter", "analyze"], project_path, fail_on_error=False)
            
            # Passo 5: Build APK
            self.update_status("Compilando APK...")
            build_args = ["flutter", "build", "apk"]
            if self.build_type.get() == "release":
                build_args.append("--release")
            else:
                build_args.append("--debug")
            
            self.log_message(f"🔨 Compilando APK ({self.build_type.get().upper()})...", "info")
            if not self.run_command(build_args, project_path):
                raise Exception("Falha na compilação do APK")
            
            # Passo 6: Localizar e copiar APK
            self.update_status("Finalizando...")
            apk_path = self.find_apk(project_path, self.build_type.get())
            
            if apk_path and os.path.exists(apk_path):
                output_dir = self.output_path.get().strip()
                if not output_dir:
                    output_dir = os.path.join(project_path, "build_outputs")
                
                os.makedirs(output_dir, exist_ok=True)
                
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                apk_name = f"app_{self.build_type.get()}_{timestamp}.apk"
                final_path = os.path.join(output_dir, apk_name)
                
                import shutil
                shutil.copy2(apk_path, final_path)
                
                self.log_message(f"✅ APK gerado com sucesso!", "success")
                self.log_message(f"📦 Arquivo: {final_path}", "success")
                
                elapsed_time = datetime.now() - start_time
                self.log_message(f"⏱️ Tempo total: {elapsed_time}", "info")
                
                self.update_status("Build concluído com sucesso!")
                messagebox.showinfo("Sucesso", f"APK gerado com sucesso!\n\nArquivo: {final_path}")
            else:
                raise Exception("APK não encontrado após a compilação")
                
        except Exception as e:
            self.log_message(f"❌ Erro: {str(e)}", "error")
            self.update_status("Build falhou!")
            messagebox.showerror("Erro", f"Falha no build:\n{str(e)}")
        
        finally:
            self.is_building = False
            self.build_button.configure(text="🔨 Iniciar Build", state="normal", fg_color="#28a745")
            self.progress_bar.stop()
            self.progress_bar.set(0)

    def update_status(self, status):
        """Atualiza o label de status"""
        self.status_label.configure(text=status, text_color="#4488ff")

    def check_flutter(self):
        """Verifica se o Flutter está instalado"""
        try:
            result = subprocess.run(
                ["flutter", "--version"],
                capture_output=True,
                text=True,
                timeout=30
            )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False

    def install_flutter(self):
        """Instala o Flutter automaticamente"""
        system = platform.system()
        
        try:
            if system == "Windows":
                # Windows installation
                download_url = "https://storage.googleapis.com/flutter_infra_release/releases/stable/windows/flutter_windows_3.16.5-stable.zip"
                install_dir = os.path.expanduser("~\\flutter")
                
                self.log_message("📥 Baixando Flutter para Windows...", "info")
                # Nota: Implementação simplificada - em produção usaria urllib.request
                
            elif system == "Darwin":  # macOS
                download_url = "https://storage.googleapis.com/flutter_infra_release/releases/stable/macos/flutter_macos_3.16.5-stable.zip"
                install_dir = os.path.expanduser("~/flutter")
                
                self.log_message("📥 Baixando Flutter para macOS...", "info")
                
            elif system == "Linux":
                download_url = "https://storage.googleapis.com/flutter_infra_release/releases/stable/linux/flutter_linux_3.16.5-stable.tar.xz"
                install_dir = os.path.expanduser("~/flutter")
                
                self.log_message("📥 Baixando Flutter para Linux...", "info")
                
            else:
                self.log_message(f"Sistema operacional não suportado: {system}", "error")
                return False
            
            # Em uma implementação completa, aqui faríamos o download e extração
            # Por simplicidade, vamos simular o processo
            self.log_message("⚠️ Instalação automática requer implementação completa de download.", "warning")
            self.log_message("📖 Por favor, instale o Flutter manualmente seguindo: https://docs.flutter.dev/get-started/install", "info")
            
            return False  # Retorna False para indicar que precisa de instalação manual
            
        except Exception as e:
            self.log_message(f"Erro na instalação: {str(e)}", "error")
            return False

    def run_command(self, cmd, cwd, fail_on_error=True):
        """Executa um comando e retorna o resultado"""
        try:
            self.process = subprocess.Popen(
                cmd,
                cwd=cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                universal_newlines=True
            )
            
            # Ler output em tempo real
            for line in self.process.stdout:
                line = line.strip()
                if line:
                    self.log_message(line, "info")
            
            self.process.wait()
            
            if self.process.returncode != 0 and fail_on_error:
                return False
            return True
            
        except Exception as e:
            self.log_message(f"Erro ao executar comando: {str(e)}", "error")
            return False
        finally:
            self.process = None

    def find_apk(self, project_path, build_type):
        """Encontra o APK gerado"""
        build_dir = os.path.join(project_path, "build", "app", "outputs", "flutter-apk")
        
        if not os.path.exists(build_dir):
            return None
        
        # Procurar pelo APK mais recente
        apk_files = []
        for file in os.listdir(build_dir):
            if file.endswith(".apk"):
                full_path = os.path.join(build_dir, file)
                apk_files.append((full_path, os.path.getmtime(full_path)))
        
        if apk_files:
            # Ordenar por data (mais recente primeiro)
            apk_files.sort(key=lambda x: x[1], reverse=True)
            return apk_files[0][0]
        
        return None

if __name__ == "__main__":
    if HAS_GUI_SUPPORT:
        app = FlutterOrchestratorGUI()
        app.mainloop()
    else:
        # Fallback para interface de linha de comando
        print("\n" + "="*60)
        print("🚀 FLUTTER BUILD ORCHESTRATOR - MODO TERMINAL")
        print("="*60 + "\n")
        
        import argparse
        
        parser = argparse.ArgumentParser(description='Orquestrador de Build Flutter')
        parser.add_argument('project_path', nargs='?', help='Caminho do projeto Flutter')
        parser.add_argument('-o', '--output', help='Pasta de saída para o APK')
        parser.add_argument('--debug', action='store_true', help='Build em modo debug')
        parser.add_argument('--no-auto-install', action='store_true', help='Não instalar Flutter automaticamente')
        
        args = parser.parse_args()
        
        if not args.project_path:
            args.project_path = input("📁 Digite o caminho do projeto Flutter: ").strip()
        
        if not args.project_path:
            print("❌ Erro: Caminho do projeto não fornecido!")
            sys.exit(1)
        
        # Importar e usar a lógica de build
        from flutter_orchestrator import FlutterOrchestrator
        
        orchestrator = FlutterOrchestrator(
            project_path=args.project_path,
            output_path=args.output,
            build_type="debug" if args.debug else "release",
            auto_install=not args.no_auto_install
        )
        
        success = orchestrator.run()
        sys.exit(0 if success else 1)
