#!/usr/bin/env python3
"""Gemini Code Fixer — corrige c\u00f3digo Dart com IA via API Gemini."""

import hashlib
import json
import time
from datetime import datetime
from pathlib import Path
from urllib.request import Request, urlopen


class GeminiCodeFixer:
    """
    Usa a API Gemini para analisar erros do compilador Dart,
    corrigir o c\u00f3digo e retornar o c\u00f3digo corrigido com explica\u00e7\u00f5es.
    Inclui tratamento robusto para erro 429 (Rate Limit Exceeded).
    """

    MODELS = [
        "gemini-2.0-flash",
        "gemini-1.5-flash",
        "gemini-1.5-flash-latest",
        "gemini-pro",
    ]
    BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    MAX_RETRIES = 3
    RETRY_DELAY_SECONDS = 5

    def __init__(self, api_key: str, log):
        self.api_key = api_key
        self.log = log

    @classmethod
    def _working_url(cls, api_key: str):
        for model in cls.MODELS:
            url = cls.BASE_URL.format(model=model)
            try:
                req = Request(
                    url,
                    data=json.dumps({"contents": [{"parts": [{"text": "hi"}]}]}).encode(),
                    headers={"Content-Type": "application/json",
                             "x-goog-api-key": api_key},
                    method="POST"
                )
                with urlopen(req, timeout=10) as r:
                    if r.status == 200:
                        return url
            except Exception:
                return url
        return None

    def fix(self, code: str, errors: list):
        if not self.api_key:
            return None

        error_text = "\n".join(errors[:60])
        prompt = (
            "Voc\u00ea \u00e9 um especialista em Flutter/Dart.\n"
            "O c\u00f3digo abaixo falhou ao compilar com os erros listados.\n\n"
            f"ERROS DO COMPILADOR:\n{error_text}\n\n"
            "C\u00d3DIGO DART (main.dart):\n"
            f"```dart\n{code}\n```\n\n"
            "TAREFA:\n"
            "1. Analise cada erro e corrija o c\u00f3digo\n"
            "2. Mantenha a l\u00f3gica e funcionalidade originais intactas\n"
            "3. Corrija apenas o que \u00e9 necess\u00e1rio para compilar\n"
            "4. Retorne APENAS o c\u00f3digo Dart corrigido, sem explica\u00e7\u00f5es\n"
            "5. N\u00e3o inclua marcadores de c\u00f3digo na resposta\n"
            "6. Adicione coment\u00e1rio logo ap\u00f3s o import com as corre\u00e7\u00f5es:\n"
            "   // CORRE\u00c7\u00d5ES APLICADAS:\n"
            "   // - [descri\u00e7\u00e3o curta de cada corre\u00e7\u00e3o]\n\n"
            "IMPORTANTE: Retorne SOMENTE o c\u00f3digo Dart puro."
        )

        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.1,
                "maxOutputTokens": 8192,
            }
        }

        cache_key = hashlib.md5((code + "\n".join(errors)).encode()).hexdigest()
        cache_dir = Path.home() / ".flutter_orchestrator_cache"
        cache_file = cache_dir / f"gemini_fix_{cache_key}.json"

        if cache_file.exists():
            try:
                cache_data = json.loads(cache_file.read_text(encoding="utf-8"))
                self.log.ok("Usando corre\u00e7\u00e3o em cache")
                return cache_data.get("fixed_code")
            except Exception:
                pass

        url = GeminiCodeFixer._working_url(self.api_key)
        if not url:
            self.log.err("Nenhum modelo Gemini dispon\u00edvel para esta chave")
            return None

        model_name = url.split("/models/")[1].split(":")[0]
        self.log.info(f"Usando: {model_name}")
        payload_bytes = json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json",
                   "x-goog-api-key": self.api_key}

        last_error = None
        delay = self.RETRY_DELAY_SECONDS

        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                self.log.info(
                    f"Enviando c\u00f3digo para Gemini... "
                    f"(tentativa {attempt}/{self.MAX_RETRIES})"
                )
                req = Request(url, data=payload_bytes, headers=headers, method="POST")
                with urlopen(req, timeout=90) as r:
                    resp = json.loads(r.read())

                fixed_code = (
                    resp.get("candidates", [{}])[0]
                    .get("content", {})
                    .get("parts", [{}])[0]
                    .get("text", "")
                ).strip()

                if not fixed_code:
                    self.log.err("Gemini retornou resposta vazia")
                    return None

                if fixed_code.startswith("```"):
                    lines = fixed_code.split("\n")
                    fixed_code = "\n".join(
                        l for l in lines if not l.strip().startswith("```")
                    ).strip()

                try:
                    cache_dir.mkdir(exist_ok=True)
                    cache_file.write_text(
                        json.dumps({
                            "fixed_code": fixed_code,
                            "timestamp": datetime.now().isoformat(),
                            "errors": errors
                        }, indent=2),
                        encoding="utf-8"
                    )
                except Exception:
                    pass

                self.log.ok("Gemini retornou c\u00f3digo corrigido")
                return fixed_code

            except Exception as e:
                last_error = e
                err_str = str(e)

                if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str or "quota" in err_str.lower():
                    if attempt < self.MAX_RETRIES:
                        self.log.warn(
                            f"Limite de requisi\u00e7\u00f5es (429). "
                            f"Aguardando {delay}s..."
                        )
                        time.sleep(delay)
                        delay *= 2
                        continue
                    self.log.err("Limite de requisi\u00e7\u00f5es excedido ap\u00f3s "
                                 "todas as tentativas.")
                    return None
                else:
                    self.log.err(f"Gemini API falhou: {e}")
                    return None

        self.log.err(f"Gemini API falhou ap\u00f3s {self.MAX_RETRIES} tentativas")
        return None

    @staticmethod
    def validate_key(api_key: str):
        try:
            url = "https://generativelanguage.googleapis.com/v1beta/models"
            req = Request(url, headers={
                "Content-Type": "application/json",
                "x-goog-api-key": api_key
            })
            with urlopen(req, timeout=10) as r:
                data = json.loads(r.read())
            models = [m.get("name", "") for m in data.get("models", [])]
            gemini = [m for m in models if "gemini" in m.lower()]
            if gemini:
                return True, f"OK \u2014 {len(gemini)} modelos dispon\u00edveis"
            return False, "Chave v\u00e1lida mas sem modelos Gemini"
        except Exception as e:
            err = str(e)
            if "400" in err or "API_KEY_INVALID" in err:
                return False, "Chave inv\u00e1lida"
            if "403" in err:
                return False, "Sem permiss\u00e3o"
            return False, f"Erro de conex\u00e3o: {err}"
