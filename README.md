# Flutter Build Orchestrator

Um programa de automação de build para aplicativos Flutter que orquestra todo o processo desde a validação do projeto até a geração do APK pronto para instalação.

## 🚀 Funcionalidades

- ✅ **Verificação de Pré-requisitos**: Checa se Flutter, Git e Java estão instalados
- ✅ **Validação do Projeto**: Verifica se o diretório contém um projeto Flutter válido
- ✅ **Instalação de Dependências**: Executa `flutter pub get` automaticamente
- ✅ **Análise de Código**: Roda `flutter analyze` para identificar problemas
- ✅ **Execução de Testes**: Roda testes unitários (opcional)
- ✅ **Compilação APK**: Gera APK em modo release ou debug
- ✅ **Cópia de Artifacts**: Copia APK e mapping file para diretório de output
- ✅ **Relatório de Build**: Gera relatório JSON com informações detalhadas
- ✅ **Logs Coloridos**: Output formatado com cores para melhor visualização

## 📋 Requisitos

- Python 3.7+
- Flutter SDK instalado
- Java JDK (para build Android)
- Git

## 💻 Instalação

Nenhum pacote adicional necessário! O script usa apenas bibliotecas padrão do Python.

```bash
# Certifique-se de que o script tem permissão de execução
chmod +x flutter_build_orchestrator.py
```

## 🎯 Uso Básico

```bash
# Build release (padrão)
python flutter_build_orchestrator.py /caminho/do/projeto

# Build com output personalizado
python flutter_build_orchestrator.py /caminho/do/projeto --output ./meus_apks

# Build debug (para testes)
python flutter_build_orchestrator.py /caminho/do/projeto --debug

# Pular testes e definir número da build
python flutter_build_orchestrator.py /caminho/do/projeto --skip-tests --build-number 42

# Ver ajuda completa
python flutter_build_orchestrator.py --help
```

## 🔧 Opções Disponíveis

| Opção | Descrição | Padrão |
|-------|-----------|--------|
| `project_path` | Caminho para o projeto Flutter | Obrigatório |
| `--output, -o` | Diretório de output para o APK | `build_output` |
| `--debug, -d` | Build em modo debug | Release |
| `--skip-tests` | Pular execução de testes | False |
| `--build-number, -b` | Número da build | Auto |
| `--verbose, -v` | Output verbose | False |

## 📁 Estrutura de Output

Após um build bem-sucedido, o diretório de output conterá:

```
build_output/
├── app_20240101_120000.apk      # APK compilado
├── mapping_20240101_120000.txt  # Mapping file (se existir)
└── build_report.json            # Relatório detalhado do build
```

## 📊 Relatório de Build

O arquivo `build_report.json` contém:

```json
{
  "build_info": {
    "project_path": "/caminho/do/projeto",
    "timestamp": "2024-01-01T12:00:00",
    "duration_seconds": 180.5,
    "success": true
  },
  "apk_info": {
    "path": "/caminho/output/app_20240101_120000.apk",
    "size_bytes": 25000000,
    "size_mb": 23.84
  },
  "build_log": [...]
}
```

## 🔄 Pipeline de Build

O orchestrador executa os seguintes passos em sequência:

1. **Pré-requisitos** → Verifica Flutter, Git, Java
2. **Validação** → Confirma projeto Flutter válido
3. **Dependências** → `flutter pub get`
4. **Análise** → `flutter analyze`
5. **Testes** → `flutter test` (opcional)
6. **Build** → `flutter build apk --release`
7. **Copy** → Copia APK para output
8. **Relatório** → Gera build_report.json

Se qualquer step falhar (exceto testes), o build é abortado.

## 🛠️ Exemplos de Uso

### CI/CD Pipeline

```bash
#!/bin/bash
# Script de exemplo para CI/CD

PROJECT_PATH="./my_flutter_app"
OUTPUT_DIR="./ci_builds"
BUILD_NUMBER=$CI_PIPELINE_ID

python flutter_build_orchestrator.py \
    $PROJECT_PATH \
    --output $OUTPUT_DIR \
    --build-number $BUILD_NUMBER \
    --skip-tests

if [ $? -eq 0 ]; then
    echo "✅ Build sucesso!"
    # Upload do APK para artifact storage
else
    echo "❌ Build falhou!"
    exit 1
fi
```

### Build Múltiplos Projetos

```bash
#!/bin/bash
# Build vários projetos de uma vez

projects=("app1" "app2" "app3")

for project in "${projects[@]}"; do
    echo "🔨 Building $project..."
    python flutter_build_orchestrator.py \
        "./$project" \
        --output "./builds/$project" \
        --skip-tests
done
```

## ⚠️ Notas Importantes

1. **Keystore**: Para builds release assinados, configure o `key.properties` no seu projeto Android
2. **Timeout**: O build tem timeout de 30 minutos. Ajuste se necessário no código
3. **Espaço em Disco**: Builds Flutter podem consumir vários GBs temporariamente
4. **Primeiro Build**: O primeiro build pode ser mais lento devido ao download do Gradle

## 🐛 Troubleshooting

### Flutter não encontrado
```bash
# Adicione Flutter ao PATH
export PATH="$PATH:/caminho/para/flutter/bin"
```

### Java não encontrado
```bash
# Ubuntu/Debian
sudo apt install openjdk-17-jdk

# macOS
brew install openjdk@17
```

### Erro de permissão
```bash
chmod +x flutter_build_orchestrator.py
```

## 📝 Licença

MIT License - Sinta-se livre para usar e modificar!

## 🤝 Contribuição

Contribuições são bem-vindas! Algumas ideias:
- Suporte a iOS (.ipa)
- Integração com Firebase App Distribution
- Upload automático para Google Play
- Suporte a múltiplas flavors

---

**Desenvolvido com ❤️ para automatizar builds Flutter**
