import asyncio
from orchestrator.main_orchestrator import FlutterOrchestrator


async def test_build_scenarios():
    orchestrator = FlutterOrchestrator("./test_project")

    print("\nTeste 1: Build normal")
    result = await orchestrator.build_app()
    print(f"Resultado: {result['success']}")

    print("\nTeste 2: Build com erro Kotlin")
    result = await orchestrator.build_app()
    print(f"Resultado: {result['success']}")
    print(f"Tentativas: {len(result['attempts'])}")

    print("\nTeste 3: Build com recuperacao")
    result = await orchestrator.build_app()
    print(f"Resultado: {result['success']}")
    if result['success']:
        print(f"APK: {result['build_path']}")

    print("\nEstatisticas:")
    print(f"KB: {orchestrator.kb_learner.get_stats()}")
    print(f"Modelos: {orchestrator.model_manager.get_performance_report()}")
    print(f"Timeout: {orchestrator.timeout_manager.get_stats()}")


if __name__ == "__main__":
    asyncio.run(test_build_scenarios())
