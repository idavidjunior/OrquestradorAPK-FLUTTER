import time
import json
from datetime import datetime
from collections import deque
from typing import Dict, Optional, List


class AdaptiveTimeoutManager:
    def __init__(self, config_path: str = "timeout_config.json"):
        self.config_path = config_path
        self.history = deque(maxlen=50)
        self.current_timeout = 90
        self.min_timeout = 30
        self.max_timeout = 300
        self.load_config()

    def load_config(self):
        try:
            with open(self.config_path, 'r') as f:
                config = json.load(f)
                self.current_timeout = config.get('base_timeout', 90)
                self.history = deque(config.get('history', []), maxlen=50)
        except FileNotFoundError:
            self.save_config()

    def save_config(self):
        with open(self.config_path, 'w') as f:
            json.dump({
                'base_timeout': self.current_timeout,
                'history': list(self.history),
                'last_update': datetime.now().isoformat()
            }, f, indent=2)

    def get_timeout(self, attempt_number: int, model_tier: str = 'medium') -> int:
        base = self.current_timeout
        attempt_multiplier = 1 + ((attempt_number - 1) * 0.3)
        tier_multipliers = {'fast': 0.7, 'medium': 1.0, 'heavy': 1.5}
        tier_multiplier = tier_multipliers.get(model_tier, 1.0)
        calculated = base * attempt_multiplier * tier_multiplier
        return int(max(self.min_timeout, min(self.max_timeout, calculated)))

    def record_attempt(self, success: bool, response_time: float, model: str, tier: str):
        self.history.append({
            'timestamp': datetime.now().isoformat(),
            'success': success,
            'response_time': response_time,
            'model': model,
            'tier': tier
        })
        recent = list(self.history)[-20:]
        if recent:
            avg_time = sum(r['response_time'] for r in recent) / len(recent)
            success_rate = sum(1 for r in recent if r['success']) / len(recent)
            if success_rate > 0.8:
                new_timeout = max(avg_time * 1.3, self.min_timeout)
            elif success_rate < 0.4:
                new_timeout = avg_time * 2.0
            else:
                new_timeout = avg_time * 1.5
            self.current_timeout = max(self.min_timeout,
                                      min(self.max_timeout, int(new_timeout)))
            self.save_config()

    def get_stats(self) -> Dict:
        if not self.history:
            return {}
        recent = list(self.history)[-20:]
        return {
            'total_attempts': len(self.history),
            'recent_success_rate': sum(1 for r in recent if r['success']) / len(recent),
            'avg_response_time': sum(r['response_time'] for r in recent) / len(recent),
            'current_timeout': self.current_timeout,
            'model_performance': self._get_model_performance()
        }

    def _get_model_performance(self) -> Dict:
        performance = {}
        for entry in self.history:
            model = entry['model']
            if model not in performance:
                performance[model] = {'attempts': 0, 'successes': 0, 'avg_time': 0}
            performance[model]['attempts'] += 1
            if entry['success']:
                performance[model]['successes'] += 1
            performance[model]['avg_time'] = ((performance[model]['avg_time'] *
                (performance[model]['attempts'] - 1) + entry['response_time']) /
                performance[model]['attempts'])
        return performance
