import pytest
from pydantic import BaseModel

from src.llm.client import CacheMiss, FakeLLMClient


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
