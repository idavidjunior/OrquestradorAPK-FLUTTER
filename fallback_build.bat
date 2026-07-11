@echo off
echo [FALLBACK] Executando build manual...
flutter clean
flutter pub get
flutter build apk --release --android-skip-build-dependency-validation
if errorlevel 1 (
    echo [FALLBACK] Build falhou. Tentando remover .kts...
    cd android\app
    del build.gradle.kts 2>nul
    cd ..\..
    flutter build apk --release --android-skip-build-dependency-validation
)
pause
