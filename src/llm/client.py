"""Provider-agnostic LLM access with a disk cache.

Usage::

    from src.llm.client import get_client
    llm = get_client()
    data = llm.generate_json(prompt, schema=MyPydanticModel, prompt_version="extract_terms.v1")

Providers: ``ClaudeCodeClient`` (Claude via the Claude Code CLI in headless ``claude -p``
mode, using the signed-in Claude licence, no API key) and ``GeminiClient`` (free Google
Gemini API). Adding a provider means adding one class with the same ``_call`` signature.

Environment (read from ``.env``):
    LLM_PROVIDER     - ``claude_code`` | ``gemini`` (default ``gemini`` when unset)
    CLAUDE_MODEL     - default ``claude-sonnet-5-5`` (full ID, so cache keys stay stable)
    CLAUDE_CODE_CLI  - optional path to ``claude``/``claude.exe``; otherwise PATH, then the
                       VS Code extension folder
    GEMINI_API_KEY   - Google AI Studio key (free tier: synthetic data only)
    GEMINI_MODEL     - default ``gemini-2.5-flash``
    LLM_CACHE_MODE   - ``readwrite`` (default) | ``readonly`` (offline demo) | ``off``
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[2]
CACHE_DIR = ROOT / "data" / "llm_cache"
DEFAULT_MODEL = "gemini-2.5-flash"
DEFAULT_CLAUDE_MODEL = "claude-sonnet-5-5"
PROVIDERS = ("claude_code", "gemini")


class CacheMiss(RuntimeError):
    """Raised in readonly cache mode when a response has not been cached."""


class LLMClient:
    """Base class: caching and JSON handling. Subclasses implement ``_call``."""

    provider = "base"

    def __init__(self, model: str, cache_mode: str = "readwrite", cache_dir: Path = CACHE_DIR):
        self.model = model
        self.cache_mode = cache_mode
        self.cache_dir = cache_dir
        self.last_meta: dict = {}  # provider metadata from the last live call (audit trail)

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
        self.last_meta = {}
        response = self._call(prompt, system, schema, json_mode)
        if self.cache_mode != "off":
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(
                    {
                        "provider": self.provider,
                        "model": self.model,
                        "prompt_version": prompt_version,
                        "created_utc": datetime.now(timezone.utc).isoformat(),
                        "meta": self.last_meta,
                        "response": response,
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
        return response


class ClaudeCodeError(RuntimeError):
    """The Claude Code CLI failed, returned an error result, or returned unusable output."""


def find_claude_cli() -> str | None:
    """CLAUDE_CODE_CLI, then PATH, then the newest VS Code extension's bundled binary."""
    explicit = os.getenv("CLAUDE_CODE_CLI", "").strip()
    if explicit:
        return explicit if Path(explicit).is_file() else None
    found = shutil.which("claude")
    if found:
        return found
    ext = Path.home() / ".vscode" / "extensions"
    candidates = sorted(
        ext.glob("anthropic.claude-code-*/resources/native-binary/claude*"),
        key=lambda p: p.stat().st_mtime,
    )
    return str(candidates[-1]) if candidates else None


class ClaudeCodeClient(LLMClient):
    """Claude through the Claude Code CLI in headless mode (``claude -p``).

    Uses the signed-in Claude licence, so no API key is stored in the project. Each call is a
    single stateless model turn with every tool disabled (``--tools ""``), user customisations
    off (``--safe-mode``: no CLAUDE.md, skills, hooks or MCP servers), no saved session, and an
    empty temporary working directory, so the model sees only the prompt it is given and can
    never read the answer key or the generator. JSON calls pass the Pydantic schema to
    ``--json-schema``; the CLI validates the output against it.

    There is no temperature setting in the CLI, so live calls are not bit-for-bit repeatable.
    The disk cache makes a run replayable; ``meta`` in each cache entry records the models
    the CLI actually used.
    """

    provider = "claude_code"
    DEFAULT_SYSTEM = (
        "You are a careful contract-analysis assistant. Follow the user's instructions exactly "
        "and use only the text provided in the message."
    )
    TRANSIENT = ("overloaded", "rate limit", "rate_limit", "429", "500", "502", "503", "529")

    def __init__(
        self,
        model: str = DEFAULT_CLAUDE_MODEL,
        cli: str | None = None,
        max_retries: int = 3,
        timeout_s: int = 600,
        runner=subprocess.run,
        **kw,
    ):
        super().__init__(model=model, **kw)
        self.cli = cli or find_claude_cli()
        if not self.cli:
            raise RuntimeError(
                "Claude Code CLI not found. Install Claude Code or set CLAUDE_CODE_CLI in .env "
                "to the full path of claude.exe."
            )
        self.max_retries = max_retries
        self.timeout_s = timeout_s
        self._run = runner  # injectable for tests

    def command(self, system: str | None, schema: type[BaseModel] | None) -> list[str]:
        cmd = [
            self.cli,
            "-p",
            "--output-format",
            "json",
            "--model",
            self.model,
            "--tools",
            "",
            "--safe-mode",
            "--strict-mcp-config",
            "--disable-slash-commands",
            "--no-session-persistence",
            "--system-prompt",
            system or self.DEFAULT_SYSTEM,
        ]
        if schema is not None:
            cmd += ["--json-schema", json.dumps(schema.model_json_schema())]
        return cmd

    def _call(self, prompt, system, schema, json_mode) -> str:
        cmd = self.command(system, schema if json_mode else None)
        delay = 5.0
        for attempt in range(self.max_retries + 1):
            try:
                return self._once(cmd, prompt, json_mode, structured=schema is not None)
            except (ClaudeCodeError, subprocess.TimeoutExpired) as exc:
                transient = isinstance(exc, subprocess.TimeoutExpired) or any(
                    t in str(exc).lower() for t in self.TRANSIENT
                )
                if not transient or attempt == self.max_retries:
                    raise
                time.sleep(delay)
                delay = min(delay * 2, 60)
        raise RuntimeError("unreachable")

    def _once(self, cmd: list[str], prompt: str, json_mode: bool, structured: bool) -> str:
        with tempfile.TemporaryDirectory(prefix="claude_llm_") as empty_cwd:
            proc = self._run(
                cmd,
                input=prompt,
                capture_output=True,
                text=True,
                encoding="utf-8",
                cwd=empty_cwd,
                timeout=self.timeout_s,
            )
        try:
            out = json.loads(proc.stdout)
        except (json.JSONDecodeError, TypeError):
            raise ClaudeCodeError(
                f"claude exited {proc.returncode} without a JSON result: "
                f"{(proc.stderr or proc.stdout or '')[:300]}"
            ) from None
        if proc.returncode != 0 or out.get("is_error") or out.get("subtype") != "success":
            detail = out.get("api_error_status") or out.get("result") or out.get("subtype")
            raise ClaudeCodeError(f"claude returned an error: {str(detail)[:300]}")
        self.last_meta = {
            "models_used": sorted(out.get("modelUsage", {})),
            "duration_ms": out.get("duration_ms"),
            "session_id": out.get("session_id"),
        }
        if not json_mode:
            return out.get("result", "")
        if structured:
            if out.get("structured_output") is None:
                raise ClaudeCodeError("claude returned no structured_output for a schema call")
            return json.dumps(out["structured_output"])
        return _strip_fences(out.get("result", ""))


def _strip_fences(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else ""
        t = t.rsplit("```", 1)[0]
    return t.strip()


class GeminiClient(LLMClient):
    provider = "gemini"
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


def _env():
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")


def configured_provider() -> str:
    _env()
    name = (os.getenv("LLM_PROVIDER") or "gemini").strip().lower()
    if name not in PROVIDERS:
        raise RuntimeError(f"LLM_PROVIDER must be one of {PROVIDERS}, got {name!r}")
    return name


def configured_model(provider: str | None = None) -> str:
    provider = provider or configured_provider()
    if provider == "claude_code":
        return os.getenv("CLAUDE_MODEL") or DEFAULT_CLAUDE_MODEL
    return os.getenv("GEMINI_MODEL") or DEFAULT_MODEL


def describe_llm(provider: str | None = None) -> str:
    """Human label for reports and the app, e.g. 'Claude (claude-sonnet-5-5, Claude Code)'."""
    provider = provider or configured_provider()
    name = {"claude_code": "Claude", "gemini": "Gemini"}[provider]
    via = ", Claude Code" if provider == "claude_code" else ""
    return f"{name} ({configured_model(provider)}{via})"


def llm_available() -> bool:
    """True when a live call can be made with the configured provider."""
    try:
        provider = configured_provider()
    except RuntimeError:
        return False
    if provider == "claude_code":
        return find_claude_cli() is not None
    return bool(os.getenv("GEMINI_API_KEY", "").strip())


def get_client(cache_mode: str | None = None) -> LLMClient:
    """Build the configured client from environment / .env."""
    provider = configured_provider()
    mode = cache_mode or os.getenv("LLM_CACHE_MODE", "readwrite")
    model = configured_model(provider)
    if mode == "readonly":
        # Offline demo: serve purely from cache; no key or CLI needed. The model name must
        # match the one that filled the cache, because it is part of the cache key.
        return _OfflineClient(model=model, cache_mode="readonly")
    if provider == "claude_code":
        return ClaudeCodeClient(model=model, cache_mode=mode)
    key = os.getenv("GEMINI_API_KEY", "").strip()
    if not key:
        raise RuntimeError("GEMINI_API_KEY is not set. Copy .env.example to .env and add your key.")
    return GeminiClient(api_key=key, model=model, cache_mode=mode)


class _OfflineClient(LLMClient):
    provider = "offline"

    def _call(self, *a, **k):  # pragma: no cover - readonly mode never reaches here
        raise CacheMiss("Offline mode")
