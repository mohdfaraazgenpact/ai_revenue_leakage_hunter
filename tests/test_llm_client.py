import json
import subprocess
from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from src.llm import client as llm_client
from src.llm.client import (
    CacheMiss,
    ClaudeCodeClient,
    ClaudeCodeError,
    FakeLLMClient,
    get_client,
)


class Out(BaseModel):
    rate_pct: float


def test_generate_json_parses_response():
    llm = FakeLLMClient([{"rate_pct": 3.5}])
    assert llm.generate_json("p", schema=Out) == {"rate_pct": 3.5}


def test_cache_serves_repeat_calls_without_calling_model(tmp_path):
    llm = FakeLLMClient([{"rate_pct": 3.5}], cache_mode="readwrite", cache_dir=tmp_path)
    first = llm.generate_json("same prompt", schema=Out, prompt_version="v1")
    second = llm.generate_json("same prompt", schema=Out, prompt_version="v1")
    assert first == second
    assert len(llm.calls) == 1


def test_prompt_version_changes_cache_key(tmp_path):
    llm = FakeLLMClient(
        [{"rate_pct": 1}, {"rate_pct": 2}], cache_mode="readwrite", cache_dir=tmp_path
    )
    assert llm.generate_json("p", prompt_version="v1") == {"rate_pct": 1}
    assert llm.generate_json("p", prompt_version="v2") == {"rate_pct": 2}


def test_readonly_cache_miss_raises(tmp_path):
    llm = FakeLLMClient(cache_mode="readonly", cache_dir=tmp_path)
    with pytest.raises(CacheMiss):
        llm.generate_json("never cached")
    assert llm.calls == []


# ---- ClaudeCodeClient (claude -p) with a fake subprocess runner: no CLI, no network ----
def _result(**kw):
    out = {"type": "result", "subtype": "success", "is_error": False, "result": ""}
    out.update(kw)
    return SimpleNamespace(returncode=0, stdout=json.dumps(out), stderr="")


class Runner:
    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def __call__(self, cmd, **kw):
        self.calls.append((cmd, kw))
        o = self.outcomes.pop(0)
        if isinstance(o, BaseException):
            raise o
        return o


def _claude(runner, **kw):
    kw.setdefault("cache_mode", "off")
    return ClaudeCodeClient(cli="claude.exe", runner=runner, **kw)


def test_claude_json_call_uses_schema_and_isolated_tool_less_session():
    runner = Runner(_result(structured_output={"rate_pct": 3.5}, modelUsage={"claude-x": {}}))
    llm = _claude(runner, model="claude-x")
    assert llm.generate_json("contract text", schema=Out) == {"rate_pct": 3.5}
    cmd, kw = runner.calls[0]
    assert cmd[cmd.index("--tools") + 1] == ""  # no file, shell or web access
    assert "--safe-mode" in cmd and "--no-session-persistence" in cmd
    assert cmd[cmd.index("--model") + 1] == "claude-x"
    assert json.loads(cmd[cmd.index("--json-schema") + 1])["properties"]["rate_pct"]
    assert kw["input"] == "contract text"  # prompt via stdin, never on the command line
    assert "contract text" not in " ".join(cmd)
    assert kw["cwd"] != str(llm_client.ROOT)  # empty temp dir, not the project
    assert llm.last_meta["models_used"] == ["claude-x"]


def test_claude_text_call_has_no_schema():
    runner = Runner(_result(result="A narrative."))
    assert _claude(runner).generate_text("explain") == "A narrative."
    assert "--json-schema" not in runner.calls[0][0]


def test_claude_json_without_schema_strips_code_fences():
    runner = Runner(_result(result='```json\n{"a": 1}\n```'))
    assert _claude(runner).generate_json("p") == {"a": 1}


def test_claude_error_result_raises_and_is_not_cached(tmp_path):
    runner = Runner(_result(is_error=True, subtype="error_during_execution", result="bad schema"))
    llm = _claude(runner, cache_mode="readwrite", cache_dir=tmp_path, max_retries=0)
    with pytest.raises(ClaudeCodeError, match="bad schema"):
        llm.generate_json("p", schema=Out)
    assert not list(tmp_path.glob("*.json"))


def test_claude_missing_structured_output_raises():
    with pytest.raises(ClaudeCodeError, match="structured_output"):
        _claude(Runner(_result(result="{}")), max_retries=0).generate_json("p", schema=Out)


def test_claude_non_json_stdout_raises():
    bad = SimpleNamespace(returncode=1, stdout="", stderr="not logged in")
    with pytest.raises(ClaudeCodeError, match="not logged in"):
        _claude(Runner(bad), max_retries=0).generate_text("p")


def test_claude_retries_transient_errors(monkeypatch):
    monkeypatch.setattr(llm_client.time, "sleep", lambda s: None)
    runner = Runner(
        _result(is_error=True, subtype="error", api_error_status=529, result="Overloaded"),
        subprocess.TimeoutExpired("claude", 600),
        _result(structured_output={"rate_pct": 1.0}),
    )
    assert _claude(runner).generate_json("p", schema=Out) == {"rate_pct": 1.0}
    assert len(runner.calls) == 3


def test_claude_does_not_retry_permanent_errors(monkeypatch):
    monkeypatch.setattr(llm_client.time, "sleep", lambda s: None)
    runner = Runner(_result(is_error=True, subtype="error", result="invalid model"))
    with pytest.raises(ClaudeCodeError):
        _claude(runner).generate_text("p")
    assert len(runner.calls) == 1


def test_claude_cache_records_provider_and_meta(tmp_path):
    runner = Runner(_result(structured_output={"rate_pct": 2.0}, modelUsage={"m": {}}))
    llm = _claude(runner, cache_mode="readwrite", cache_dir=tmp_path)
    llm.generate_json("p", schema=Out, prompt_version="v1")
    entry = json.loads(next(tmp_path.glob("*.json")).read_text(encoding="utf-8"))
    assert entry["provider"] == "claude_code" and entry["meta"]["models_used"] == ["m"]


def test_get_client_selects_claude_code(monkeypatch, tmp_path):
    fake_cli = tmp_path / "claude.exe"
    fake_cli.write_text("")
    monkeypatch.setenv("LLM_PROVIDER", "claude_code")
    monkeypatch.setenv("CLAUDE_MODEL", "claude-test")
    monkeypatch.setenv("CLAUDE_CODE_CLI", str(fake_cli))
    llm = get_client(cache_mode="off")
    assert isinstance(llm, ClaudeCodeClient) and llm.model == "claude-test"
    assert get_client(cache_mode="readonly").model == "claude-test"  # same cache keys offline


def test_get_client_claude_code_without_cli_raises(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_PROVIDER", "claude_code")
    monkeypatch.setenv("CLAUDE_CODE_CLI", str(tmp_path / "missing.exe"))
    with pytest.raises(RuntimeError, match="Claude Code CLI not found"):
        get_client(cache_mode="readwrite")


def test_unknown_provider_is_rejected(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    with pytest.raises(RuntimeError, match="LLM_PROVIDER"):
        get_client()
