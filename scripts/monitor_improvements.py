from orchestrator.knowledge_base_learner import KnowledgeBaseLearner
from orchestrator.model_manager import IntelligentModelManager
import json

kb = KnowledgeBaseLearner()
mm = IntelligentModelManager()

print("METRICAS DO SISTEMA")
print("=" * 50)

print("\nKnowledgeBase:")
stats = kb.get_stats()
print(f"  Total erros: {stats['total_errors']}")
print(f"  Resolvidos: {stats['solved_errors']}")
print(f"  Taxa aprendizado: {stats['learning_rate']:.2%}")
print(f"  Padroes unicos: {stats['unique_patterns']}")
print(f"  Erros unicos: {stats['unique_errors']}")
print(f"  Solucoes: {stats['total_solutions']}")

print("\nModelos:")
report = mm.get_performance_report()
for tier, models in report.items():
    print(f"  {tier}:")
    for m in models:
        if m['attempts'] > 0:
            print(f"    - {m['name'][:40]}: {m['success_rate']:.0%} ({m['avg_time']:.1f}s) {m['attempts']}x")
        else:
            print(f"    - {m['name'][:40]}: (sem uso)")

print("\nSugestoes:")
suggestions = kb.suggest_improvements()
if suggestions:
    for s in suggestions[:5]:
        print(f"  - {s['error'][:60]}...")
        print(f"    Taxa: {s['success_rate']:.0%}, Ocorrencias: {s['occurrences']}")
else:
    print("  (nenhuma sugestao - sistema esta aprendendo)")
