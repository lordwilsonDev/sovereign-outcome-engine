#!/usr/bin/env python3
"""S02 Scan-determinism hygiene — outcome_engine.py JSON output is reproducible.

A sovereign outcome report is a *deliverable*: the same prospect data must
yield the same report on every run (the price/deal/score cannot wobble run
to run). This experiment runs `outcome_engine.py --json` against the
synthetic sample_data twice and requires the machine-readable output to be
byte-identical (same sha256).

Serverless: no daemon, no network (local --dir mode only).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

REPO = Path(os.environ.get("MSB_REPO", Path(__file__).resolve().parents[2]))
EVIDENCE_DIR = REPO / "artifacts" / "hygiene"
EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
PY = os.environ.get("MSB_PYTHON", "/opt/homebrew/Caskroom/miniforge/base/bin/python")

ENGINE = REPO / "outcome_engine.py"
SAMPLE_DIR = REPO / "sample_data"


def new_record() -> dict[str, Any]:
    return {
        "experiment_id": "s02_scan_determinism",
        "skill": "determinism",
        "input": (
            "outcome_engine.py --dir sample_data --client Ferree --industry "
            "logistics --json run twice; outputs must be byte-identical"
        ),
        "environment": f"local CLI @ {REPO}",
        "failure_injected": "none — reproducibility check",
        "expected_behavior": "two runs produce identical JSON (same sha256)",
        "actual_behavior": "",
        "latency_ms": 0,
        "errors": [],
        "state_before": {},
        "state_after": {},
        "recovery": "",
        "false_repair": False,
        "evidence": [],
        "verdict": "unknown",
    }


def save(record: dict[str, Any]) -> Path:
    ts = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = EVIDENCE_DIR / f"{record['experiment_id']}_{ts}.json"
    path.write_text(json.dumps(record, indent=2, default=str), encoding="utf-8")
    return path


def extract_json(text: str) -> str:
    """Return the LAST top-level JSON object in the engine's stdout.

    outcome_engine.py prints human-readable progress FIRST and the machine
    JSON LAST (json.dumps at the end of main), so the JSON is never the whole
    stdout. This brace-scans for complete top-level objects and returns the
    final one — the scan/score/deal payload.
    """
    raw = text.strip()
    last: str | None = None
    i, n = 0, len(raw)
    while i < n:
        if raw[i] == "{":
            depth = 0
            for j in range(i, n):
                if raw[j] == "{":
                    depth += 1
                elif raw[j] == "}":
                    depth -= 1
                    if depth == 0:
                        candidate = raw[i:j + 1]
                        try:
                            json.loads(candidate)
                            last = candidate
                        except json.JSONDecodeError:
                            pass
                        i = j + 1
                        break
            else:
                break
        else:
            i += 1
    return last or ""


def run_scan(out_path: Path, report_path: Path) -> tuple[int, str]:
    """Run the scan; write the extracted JSON payload to out_path."""
    proc = subprocess.run(
        [PY, str(ENGINE), "--dir", str(SAMPLE_DIR),
         "--client", "Ferree", "--industry", "logistics", "--json",
         "--output", str(report_path)],
        capture_output=True, text=True, timeout=180, check=False,
    )
    payload = extract_json(proc.stdout)
    if payload:
        out_path.write_text(payload, encoding="utf-8")
    return proc.returncode, payload


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    record = new_record()
    start = dt.datetime.now(dt.timezone.utc)

    if not SAMPLE_DIR.is_dir():
        record["verdict"] = "blocked"
        record["errors"].append(f"sample_data dir missing at {SAMPLE_DIR}")
        record["actual_behavior"] = "precondition failed — no sample_data"
        path = save(record)
        print(json.dumps({"experiment": record["experiment_id"], "verdict": "blocked",
                          "artifact": str(path)}, indent=2))
        return 0

    try:
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            out1, out2 = td / "run1.json", td / "run2.json"
            report = td / "report.html"
            rc1, _ = run_scan(out1, report)
            rc2, _ = run_scan(out2, report)

            hash1 = sha256_file(out1) if out1.exists() else ""
            hash2 = sha256_file(out2) if out2.exists() else ""
            identical = bool(hash1) and hash1 == hash2
            valid_json = True
            try:
                data = json.loads(out1.read_text()) if out1.exists() else None
                if data is None:
                    valid_json = False
            except Exception:
                valid_json = False

            record["state_after"] = {
                "run1_rc": rc1, "run2_rc": rc2,
                "sha256_run1": hash1[:16], "sha256_run2": hash2[:16],
                "identical": identical, "valid_json": valid_json,
            }
            record["evidence"].append(
                f"rc={rc1}/{rc2} sha1={hash1[:16]} sha2={hash2[:16]} "
                f"identical={identical} valid_json={valid_json}"
            )
            record["actual_behavior"] = (
                f"run1_rc={rc1} run2_rc={rc2} identical={identical} valid_json={valid_json}"
            )

            if rc1 == 0 and rc2 == 0 and identical and valid_json:
                record["verdict"] = "pass"
                record["recovery"] = "outcome engine output is deterministic across runs"
            else:
                record["verdict"] = "fail"
                record["errors"].append(
                    f"non-deterministic or invalid: rc={rc1}/{rc2} "
                    f"identical={identical} valid_json={valid_json}"
                )
    except Exception as e:
        record["verdict"] = "fail"
        record["errors"].append(str(e))
    finally:
        record["latency_ms"] = int(
            (dt.datetime.now(dt.timezone.utc) - start).total_seconds() * 1000
        )

    path = save(record)
    print(json.dumps({
        "experiment": record["experiment_id"],
        "verdict": record["verdict"],
        "identical": record["state_after"].get("identical"),
        "sha256": record["state_after"].get("sha256_run1"),
        "artifact": str(path),
    }, indent=2))
    return 0 if record["verdict"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
