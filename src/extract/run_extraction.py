"""Batch contract extraction.

    python -m src.extract.run_extraction                 # EXTRACTOR from .env (rule | llm)
    python -m src.extract.run_extraction --extractor both

Writes data/extracted/<extractor>/<contract>.json and review_queue.csv.
"""

from __future__ import annotations

import argparse
import csv
import os
import time
from pathlib import Path

from src.extract import llm_extractor, rule_extractor
from src.extract.document_loader import load_document

ROOT = Path(__file__).resolve().parents[2]
CONTRACTS = ROOT / "data" / "contracts"
OUT = ROOT / "data" / "extracted"
QUEUE_FIELDS = ["contract_id", "field", "issue", "quote"]


def contract_files(contracts_dir: Path = CONTRACTS) -> list[Path]:
    return sorted(
        p for p in contracts_dir.iterdir() if p.suffix.lower() in (".pdf", ".docx", ".txt")
    )


def run(extractor: str, contracts_dir: Path = CONTRACTS, out_root: Path = OUT, llm=None) -> dict:
    out = out_root / extractor
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("*.json"):
        old.unlink()
    if extractor == "llm" and llm is None:
        from src.llm.client import get_client

        llm = get_client()
    queue, ok, failed = [], 0, 0
    files = contract_files(contracts_dir)
    for i, path in enumerate(files, start=1):
        t0 = time.perf_counter()
        try:
            pages = load_document(path)
            if extractor == "rule":
                terms, issues = rule_extractor.extract(path, pages=pages), []
            else:
                terms, issues = llm_extractor.extract(path, llm, pages=pages)
            (out / f"{terms.contract_id}.json").write_text(
                terms.model_dump_json(indent=2), encoding="utf-8"
            )
            queue.extend(issues)
            ok += 1
            print(
                f"[{extractor}] {i}/{len(files)} {path.name} ok ({time.perf_counter() - t0:.1f}s, {len(issues)} review items)"
            )
        except Exception as exc:  # one bad contract must not stop the batch
            failed += 1
            queue.append(
                {
                    "contract_id": path.stem,
                    "field": "*",
                    "issue": f"extraction failed: {exc!r}"[:300],
                    "quote": "",
                }
            )
            print(f"[{extractor}] {i}/{len(files)} {path.name} FAILED: {exc!r}"[:200])
    with (out / "review_queue.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=QUEUE_FIELDS)
        w.writeheader()
        w.writerows(queue)
    return {"extractor": extractor, "ok": ok, "failed": failed, "review_items": len(queue)}


def main():
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--extractor", default=os.getenv("EXTRACTOR", "rule"), choices=["rule", "llm", "both"]
    )
    a = ap.parse_args()
    for name in ["rule", "llm"] if a.extractor == "both" else [a.extractor]:
        print(run(name))


if __name__ == "__main__":
    main()
