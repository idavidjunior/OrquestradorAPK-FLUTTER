import time
import threading
from datetime import datetime
from typing import Optional, Callable


class AIDebugLogger:
    """Armazena o dialogo completo entre o orquestrador e a IA para debug."""

    def __init__(self):
        self._entries = []
        self._lock = threading.Lock()
        self._listeners = []

    @property
    def entries(self):
        with self._lock:
            return list(self._entries)

    @property
    def last_entry(self):
        with self._lock:
            return self._entries[-1] if self._entries else None

    def add_entry(self, prompt: str, response: str, provider: str, model: str,
                  tier: int, elapsed: float, success: bool,
                  extracted_code: str = "", validation_errors=None,
                  error_info: str = ""):
        entry = {
            "id": int(time.time() * 1000),
            "timestamp": datetime.now().isoformat(),
            "prompt": prompt,
            "response": response,
            "provider": provider,
            "model": model,
            "tier": tier,
            "elapsed": elapsed,
            "success": success,
            "extracted_code": extracted_code,
            "validation_errors": validation_errors or [],
            "error_info": error_info,
            "prompt_size": len(prompt),
            "response_size": len(response),
        }
        with self._lock:
            self._entries.append(entry)
        for cb in self._listeners:
            try:
                cb(entry)
            except Exception:
                pass

    def on_new_entry(self, callback: Callable):
        self._listeners.append(callback)

    def clear(self):
        with self._lock:
            self._entries.clear()

    def summary(self) -> dict:
        with self._lock:
            total = len(self._entries)
            ok = sum(1 for e in self._entries if e["success"])
            return {
                "total": total,
                "success": ok,
                "failed": total - ok,
                "avg_elapsed": (sum(e["elapsed"] for e in self._entries) / total) if total else 0,
            }


_debug_logger = AIDebugLogger()


def get_debug_logger() -> AIDebugLogger:
    return _debug_logger
