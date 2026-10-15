"""Daily build: generate -> extract (rule + Gemini) -> evaluate extraction -> pipeline -> evaluate -> gate.

    python -m src.build_all                  # full build
    python -m src.build_all --skip-generate  # keep current synthetic data
    python -m src.build_all --check          # exit 1 if the AI path misses the acceptance thresholds

Gemini extraction runs when GEMINI_API_KEY is set, or from cache when LLM_CACHE_MODE=readonly.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from src import evaluate, evaluate_extraction, generate_synthetic_data, pipeline, results_report
from src.extract import run_extraction

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"


def _llm_possible() -> bool:
    load_dotenv(ROOT / ".env")
    if os.getenv("GEMINI_API_KEY", "").strip():
        return True
    cache = DATA / "llm_cache"
    return (
        os.getenv("LLM_CACHE_MODE") == "readonly" and cache.exists() and any(cache.glob("*.json"))
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-generate", action="store_true")
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()

    if not a.skip_generate:
        print("== generate synthetic data")
        generate_synthetic_data.main()
    print("== extract: rules baseline")
    print(run_extraction.run("rule"))
    sources = ["gold", "rule"]
    if _llm_possible():
        print("== extract: Gemini")
        print(run_extraction.run("llm"))
        sources.append("llm")
    else:
        print("== extract: Gemini SKIPPED (no GEMINI_API_KEY in .env)")
    print("== evaluate extraction")
    evaluate_extraction.main()

    results = {}
    primary = "llm" if "llm" in sources else "rule"
    for src in [s for s in sources if s != primary] + [primary]:  # primary last -> data/output
        terms_dir = DATA / "eval" / "gold" if src == "gold" else DATA / "extracted" / src
        print(f"== pipeline + evaluate: {src}")
        summ = pipeline.run(terms_dir, explain=(src == primary and src == "llm"))["summary"]
        res = evaluate.evaluate()
        evaluate.write_report(res, src, str(terms_dir))
        results[src] = {
            "underbilling": summ["potential_underbilling"],
            "recall": res["line_recall"],
            "precision": res["line_precision"],
            "dollar_error_pct": res["dollar_error_pct"],
            "gate": evaluate.check(res) or "PASS",
        }
    print(json.dumps(results, indent=2))
    print(f"== README results block -> {results_report.update_readme()}")
    if a.check:
        if "llm" not in results:
            print("Eval gate: AI path not run (no Gemini key) - nothing to gate.")
            return 0
        if results["llm"]["gate"] != "PASS":
            print(f"EVAL GATE FAILED (llm): {results['llm']['gate']}")
            return 1
        print("EVAL GATE PASSED (llm)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
