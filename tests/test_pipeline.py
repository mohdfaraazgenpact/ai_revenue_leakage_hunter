"""Detector runs never fall back to the answer key; oracle runs are labelled."""

import pytest

from src import pipeline


def test_detector_run_without_extracted_terms_fails_clearly(tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline, "DATA", tmp_path)
    monkeypatch.setenv("EXTRACTOR", "llm")
    with pytest.raises(pipeline.MissingExtractedTerms, match="--oracle"):
        pipeline.default_terms_dir()


def test_answer_key_directory_is_recognised_as_oracle():
    assert pipeline.is_oracle(pipeline.GOLD_DIR)
    assert not pipeline.is_oracle(pipeline.DATA / "extracted" / "rule")
    assert not pipeline.is_oracle(None)
