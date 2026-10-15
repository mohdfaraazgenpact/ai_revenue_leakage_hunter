"""Provider-agnostic LLM access with a disk cache.

Usage::

    from src.llm.client import get_client
    llm = get_client()
    data = llm.generate_json(prompt, schema=MyPydanticModel, prompt_version="extract_terms.v1")

Only ``GeminiClient`` is implemented. Swapping to an enterprise endpoint for a client
pilot means adding one class with the same ``_call`` signature.

Environment (read from ``.env``):
    GEMINI_API_KEY   - Google AI Studio key (free tier: synthetic data only)
    GEMINI_MODEL     - default ``gemini-2.5-flash``
    LLM_CACHE_MODE   - ``readwrite`` (default) | ``readonly`` (offline demo) | ``off``
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[2]
CACHE_DIR = ROOT / "data" / "llm_cache"
DEFAULT_MODEL = "gemini-2.5-flash"


class CacheMiss(RuntimeError):
    """Raised in readonly cache mode when a response has not been cached."""


class LLMClient:
    """Base class: caching and JSON handling. Subclasses implement ``_call``."""

    def __init__(self, model: str, cache_mode: str = "readwrite", cache_dir: Path = CACHE_DIR):
        self.model = model
        self.cache_mode = cache_mode
        self.cache_dir = cache_dir

    # -- public API -------------------------------------------------------
    def generate_json(
        self,
        prompt: str,
        schema: type[BaseModel] | None = None,
        *,
        system: str | None = None,
        prompt_version: str = "unversioned",
    ) -> Any:
        raw = self._cached(prompt, system, prompt_version, schema, json_mode=True)
        return json.loads(raw)

    def generate_text(
        self, prompt: str, *, system: str | None = None, prompt_version: str = "unversioned"
    ) -> str:
        return self._cached(prompt, system, prompt_version, None, json_mode=False)

    # -- internals --------------------------------------------------------
    def _call(
        self, prompt: str, system: str | None, schema: type[BaseModel] | None, json_mode: bool
    ) -> str:
        raise NotImplementedError

    def _key(self, prompt, system, prompt_version, schema, json_mode) -> str:
        payload = json.dumps(
            {
                "model": self.model,
                "prompt_version": prompt_version,
                "system": system,
                "prompt": prompt,
                "schema": schema.__name__ if schema else None,
                "json": json_mode,
            },
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _cached(self, prompt, system, prompt_version, schema, json_mode) -> str:
        key = self._key(prompt, system, prompt_version, schema, json_mode)
        path = self.cache_dir / f"{key}.json"
        if self.cache_mode != "off" and path.exists():
            return json.loads(path.read_text(encoding="utf-8"))["response"]
        if self.cache_mode == "readonly":
            raise CacheMiss(f"No cached LLM response for {prompt_version} ({key[:12]})")
        response = self._call(prompt, system, schema, json_mode)
        if self.cache_mode != "off":
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(
                    {
                        "model": self.model,
                        "prompt_version": prompt_version,
                        "created_utc": datetime.now(timezone.utc).isoformat(),
                        "response": response,
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
        return response


class GeminiClient(LLMClient):
    RETRY_CODES = {429, 500, 502, 503, 504}

    def __init__(self, api_key: str, model: str = DEFAULT_MODEL, max_retries: int = 5, **kw):
        super().__init__(model=model, **kw)
        from google import genai  # imported lazily so tests never need the SDK/network

        self._genai = genai
        self._client = genai.Client(api_key=api_key)
        self.max_retries = max_retries

    def _call(self, prompt, system, schema, json_mode) -> str:
        from google.genai import errors, types

        config = types.GenerateContentConfig(
            temperature=0,
            system_instruction=system,
            response_mime_type="application/json" if json_mode else None,
            response_schema=schema if (json_mode and schema) else None,
        )
        delay = 2.0
        for attempt in range(self.max_retries + 1):
            try:
                resp = self._client.models.generate_content(
                    model=self.model, contents=prompt, config=config
                )
                return resp.text
            except errors.APIError as exc:
                if exc.code not in self.RETRY_CODES or attempt == self.max_retries:
                    raise
                time.sleep(delay)
                delay = min(delay * 2, 60)
        raise RuntimeError("unreachable")

    def list_models(self) -> list[str]:
        return [m.name for m in self._client.models.list()]


class FakeLLMClient(LLMClient):
    """Deterministic stand-in for tests: returns queued or callable responses."""

    def __init__(self, responses=None, **kw):
        kw.setdefault("cache_mode", "off")
        super().__init__(model="fake", **kw)
        self.responses = list(responses or [])
        self.calls: list[str] = []

    def _call(self, prompt, system, schema, json_mode) -> str:
        self.calls.append(prompt)
        r = self.responses.pop(0) if self.responses else "{}"
        r = r(prompt) if callable(r) else r
        return r if isinstance(r, str) else json.dumps(r)


def get_client(cache_mode: str | None = None) -> LLMClient:
    """Build the configured client from environment / .env."""
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
    mode = cache_mode or os.getenv("LLM_CACHE_MODE", "readwrite")
    model = os.getenv("GEMINI_MODEL") or DEFAULT_MODEL
    key = os.getenv("GEMINI_API_KEY", "").strip()
    if not key:
        if mode == "readonly":
            # Offline demo: serve purely from cache, no key needed.
            return _OfflineClient(model=model, cache_mode="readonly")
        raise RuntimeError("GEMINI_API_KEY is not set. Copy .env.example to .env and add your key.")
    return GeminiClient(api_key=key, model=model, cache_mode=mode)


class _OfflineClient(LLMClient):
    def _call(self, *a, **k):  # pragma: no cover - readonly mode never reaches here
        raise CacheMiss("Offline mode")
