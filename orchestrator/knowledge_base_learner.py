import json
import hashlib
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from collections import defaultdict
import re


class KnowledgeBaseLearner:
    def __init__(self, kb_path: str = "knowledge_base.json"):
        self.kb_path = kb_path
        self.knowledge = self._load_kb()
        self.learning_stats = defaultdict(int)

    def _load_kb(self) -> Dict:
        try:
            with open(self.kb_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except FileNotFoundError:
            return self._initialize_kb()

    def _initialize_kb(self) -> Dict:
        return {
            'version': '2.0',
            'errors': {},
            'patterns': {},
            'solutions': {},
            'stats': {
                'total_errors': 0,
                'solved_errors': 0,
                'learning_rate': 0
            },
            'learned_patterns': []
        }

    def save_kb(self):
        with open(self.kb_path, 'w', encoding='utf-8') as f:
            json.dump(self.knowledge, f, indent=2, ensure_ascii=False)

    def learn_from_build(self, build_log: str, error: str, solution: Optional[str], success: bool):
        error_pattern = self._extract_error_pattern(error)
        error_hash = hashlib.md5(error_pattern.encode()).hexdigest()
        if error_hash not in self.knowledge['errors']:
            self.knowledge['errors'][error_hash] = {
                'pattern': error_pattern,
                'first_seen': datetime.now().isoformat(),
                'occurrences': 0,
                'solutions': [],
                'success_rate': 0
            }
        entry = self.knowledge['errors'][error_hash]
        entry['occurrences'] += 1
        if solution:
            solution_hash = hashlib.md5(solution.encode()).hexdigest()
            solution_entry = {
                'solution': solution,
                'attempts': 1,
                'success': 1 if success else 0,
                'last_used': datetime.now().isoformat()
            }
            existing = next((s for s in entry['solutions']
                           if hashlib.md5(s['solution'].encode()).hexdigest() == solution_hash), None)
            if existing:
                existing['attempts'] += 1
                if success:
                    existing['success'] += 1
                existing['last_used'] = datetime.now().isoformat()
            else:
                entry['solutions'].append(solution_entry)
        self.knowledge['stats']['total_errors'] += 1
        if success:
            self.knowledge['stats']['solved_errors'] += 1
        total = self.knowledge['stats']['total_errors']
        solved = self.knowledge['stats']['solved_errors']
        self.knowledge['stats']['learning_rate'] = solved / total if total > 0 else 0
        if build_log:
            patterns = self._extract_code_patterns(build_log)
            for pattern in patterns:
                if pattern not in self.knowledge['patterns']:
                    self.knowledge['patterns'][pattern] = {
                        'context': build_log[:500],
                        'first_seen': datetime.now().isoformat(),
                        'occurrences': 0
                    }
                self.knowledge['patterns'][pattern]['occurrences'] += 1
        self.save_kb()

    def _extract_error_pattern(self, error: str) -> str:
        pattern = re.sub(r'line \d+', 'line X', error)
        pattern = re.sub(r'[A-Za-z]:\\[^\s]+', 'PATH', pattern)
        pattern = re.sub(r'\d+\.\d+\.\d+', 'X.X.X', pattern)
        pattern = re.sub(r'[a-f0-9]{8,}', 'HASH', pattern)
        return pattern[:500]

    def _extract_code_patterns(self, text: str) -> List[str]:
        patterns = []
        imports = re.findall(r'import\s+[\'"]?([^\'"\s]+)', text)
        patterns.extend(imports)
        classes = re.findall(r'class\s+(\w+)', text)
        patterns.extend(classes)
        functions = re.findall(r'(?:void|Future|Widget|String|int|bool|double|dynamic)\s+(\w+)', text)
        patterns.extend(functions)
        return list(set(patterns))

    def get_solution(self, error: str) -> Tuple[Optional[str], float]:
        pattern = self._extract_error_pattern(error)
        error_hash = hashlib.md5(pattern.encode()).hexdigest()
        if error_hash in self.knowledge['errors']:
            entry = self.knowledge['errors'][error_hash]
            if entry['solutions']:
                best_solution = max(entry['solutions'],
                                  key=lambda x: x['success'] / x['attempts'] if x['attempts'] > 0 else 0)
                confidence = best_solution['success'] / best_solution['attempts'] if best_solution['attempts'] > 0 else 0
                return best_solution['solution'], confidence
        return None, 0.0

    def get_learned_patterns(self, context: str) -> List[str]:
        relevant = []
        for pattern, data in self.knowledge['patterns'].items():
            if pattern in context or any(word in context for word in pattern.split('_')):
                relevant.append({
                    'pattern': pattern,
                    'relevance': data['occurrences']
                })
        relevant.sort(key=lambda x: x['relevance'], reverse=True)
        return [r['pattern'] for r in relevant[:5]]

    def suggest_improvements(self) -> List[Dict]:
        suggestions = []
        for error_hash, entry in self.knowledge['errors'].items():
            if entry['occurrences'] > 3:
                success_rate = sum(s['success'] for s in entry['solutions']) / sum(s['attempts'] for s in entry['solutions']) if entry['solutions'] else 0
                if success_rate < 0.5:
                    suggestions.append({
                        'error': entry['pattern'],
                        'occurrences': entry['occurrences'],
                        'success_rate': success_rate,
                        'suggestion': 'Precisa de novas soluções para este erro'
                    })
        return suggestions

    def get_stats(self) -> Dict:
        return {
            'total_errors': self.knowledge['stats']['total_errors'],
            'solved_errors': self.knowledge['stats']['solved_errors'],
            'learning_rate': self.knowledge['stats']['learning_rate'],
            'unique_patterns': len(self.knowledge['patterns']),
            'unique_errors': len(self.knowledge['errors']),
            'total_solutions': sum(len(e['solutions']) for e in self.knowledge['errors'].values())
        }
