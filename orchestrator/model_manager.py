# -*- coding: utf-8 -*-
import asyncio
import time
from typing import Dict, List, Optional, Tuple
from enum import Enum
from dataclasses import dataclass
import json


class ModelTier(Enum):
    FAST = "fast"
    MEDIUM = "medium"
    HEAVY = "heavy"


@dataclass
class ModelInfo:
    name: str
    tier: ModelTier
    avg_response_time: float = 0
    success_rate: float = 0
    attempts: int = 0
    last_used: float = 0
    is_available: bool = True
    failure_reason: str = ""


class IntelligentModelManager:
    def __init__(self):
        self.models = {
            ModelTier.FAST: [
                ModelInfo(name="meta/llama-3.1-70b-instruct", tier=ModelTier.FAST),
                ModelInfo(name="bytedance/seed-oss-36b-instruct", tier=ModelTier.FAST),
                ModelInfo(name="meta/llama-3.1-8b-instruct", tier=ModelTier.FAST),
            ],
            ModelTier.MEDIUM: [
                ModelInfo(name="abacusai/dracarys-llama-3.1-70b-instruct", tier=ModelTier.MEDIUM),
                ModelInfo(name="mistralai/mixtral-8x7b-instruct", tier=ModelTier.MEDIUM),
            ],
            ModelTier.HEAVY: [
                ModelInfo(name="01-ai/yi-large", tier=ModelTier.HEAVY),
                ModelInfo(name="aisingapore/sea-lion-7b-instruct", tier=ModelTier.HEAVY),
            ]
        }
        self.current_tier = ModelTier.FAST
        self.fallback_stack = []
        self.max_fallbacks = 5
        self.load_history()

    def load_history(self):
        try:
            with open('model_performance.json', 'r') as f:
                history = json.load(f)
                for model_name, data in history.items():
                    for tier in ModelTier:
                        for model in self.models[tier]:
                            if model.name == model_name:
                                model.avg_response_time = data.get('avg_time', 0)
                                model.success_rate = data.get('success_rate', 0)
                                model.attempts = data.get('attempts', 0)
        except FileNotFoundError:
            pass

    def save_history(self):
        history = {}
        for tier in ModelTier:
            for model in self.models[tier]:
                history[model.name] = {
                    'avg_time': model.avg_response_time,
                    'success_rate': model.success_rate,
                    'attempts': model.attempts
                }
        with open('model_performance.json', 'w') as f:
            json.dump(history, f, indent=2)

    def get_best_model(self, task_type: str = 'build_fix') -> Tuple[ModelInfo, int]:
        candidates = []
        for tier in [ModelTier.FAST, ModelTier.MEDIUM, ModelTier.HEAVY]:
            for model in self.models[tier]:
                if model.is_available:
                    score = 0
                    if model.attempts > 0:
                        score += model.success_rate * 100
                        if model.avg_response_time < 10:
                            score += 20
                        elif model.avg_response_time < 30:
                            score += 10
                    else:
                        score = 50
                    if model.last_used > 0:
                        time_since = time.time() - model.last_used
                        if time_since < 5:
                            score -= 10
                    candidates.append((model, score))
        candidates.sort(key=lambda x: x[1], reverse=True)
        if candidates:
            best_model = candidates[0][0]
            best_model.last_used = time.time()
            if best_model.avg_response_time > 0:
                estimated_time = best_model.avg_response_time * 1.2
            else:
                estimated_time = 30
            return best_model, int(estimated_time)
        for tier in ModelTier:
            for model in self.models[tier]:
                if model.is_available:
                    return model, 30
        return self.models[ModelTier.FAST][0], 30

    def record_model_result(self, model_name: str, success: bool, response_time: float):
        for tier in ModelTier:
            for model in self.models[tier]:
                if model.name == model_name:
                    model.attempts += 1
                    if success:
                        model.success_rate = ((model.success_rate * (model.attempts - 1)) + 1) / model.attempts
                    else:
                        model.success_rate = (model.success_rate * (model.attempts - 1)) / model.attempts
                    model.avg_response_time = ((model.avg_response_time * (model.attempts - 1)) + response_time) / model.attempts
                    break
        self.save_history()

    def get_fallback_model(self, failed_model: str) -> Optional[ModelInfo]:
        failed_models = [failed_model]
        for tier in [ModelTier.FAST, ModelTier.MEDIUM, ModelTier.HEAVY]:
            for model in self.models[tier]:
                if model.name not in failed_models and model.is_available:
                    return model
        return None

    def mark_model_unavailable(self, model_name: str, reason: str):
        for tier in ModelTier:
            for model in self.models[tier]:
                if model.name == model_name:
                    model.is_available = False
                    model.failure_reason = reason
                    break

    def get_performance_report(self) -> Dict:
        report = {}
        for tier in ModelTier:
            report[tier.value] = []
            for model in self.models[tier]:
                report[tier.value].append({
                    'name': model.name,
                    'avg_time': model.avg_response_time,
                    'success_rate': model.success_rate,
                    'attempts': model.attempts,
                    'available': model.is_available
                })
        return report
