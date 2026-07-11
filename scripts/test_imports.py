from orchestrator.timeout_manager import AdaptiveTimeoutManager
from orchestrator.ia_response_validator import IAResponseValidator
from orchestrator.model_manager import IntelligentModelManager
from orchestrator.kotlin_fixer import KotlinGradleFixer
from orchestrator.knowledge_base_learner import KnowledgeBaseLearner
from orchestrator.main_orchestrator import FlutterOrchestrator


print("[OK] Todos os modulos importados com sucesso!")

kb = KnowledgeBaseLearner()
print("[KB] Stats:", kb.get_stats())

mm = IntelligentModelManager()
print("[Model] Stats:", mm.get_performance_report())
