#!/usr/bin/env python3

"""S05 Claim-container hygiene — every emitted claim container conforms.

The engine emits a machine-readable claim container next to each report
(artifacts/business/claim_container_*.json) declaring what the deliverable
CLAIMS. The factory's producer adapter (validate_claim_containers.py in the
engineering-hygiene-factory) is the ledger-side gate; this runner invokes it
against every container this repo has emitted, so a malformed container can
never be committed silently — it fails the repo's own gate.

Serverless: local CLI, no network. The validator is stdlib-only.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO = Path(os.environ.get("MSB_REPO", Path(__file__).resolve().parents[2]))
EVIDENCE_DIR = REPO / "artifacts" / "hygiene"
EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
PY = os.environ.get("MSB_PYTHON", sys.executable)

VALIDATOR = (
    Path(os.environ.get("VALIDATE_CLAIM_CONTAINERS",
                        Path.home() / ".hermes" / "skills" / "engineering"
                        / "engineering-hygiene-factory"
                        / "scripts" / "validate_claim_containers.py"))
)
BUSINESS_DIR = REPO / "artifacts" / "business"


def new_record() -> dict[str, Any]:
    return {
        "experiment_id": "s05_claim_container",
        "skill": "business-hygiene",
        "input": "validate every claim_container_*.json under artifacts/business/",
        "environment": f"local CLI @ {REPO}",
        "failure_injected": "none — claim-container contract check",
        "expected_behavior": (
            "every emitted claim container passes the factory's claim "
            "validator (deliverable fields, claim fields, T0..T6 tier, "
            "ledger verdict enum, evidence paths exist)"
        ),
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


def _summary(record: dict[str, Any], path: Path) -> None:
    print(json.dumps({
        "experiment": record["experiment_id"],
        "verdict": record["verdict"],
        "artifact": str(path),
        "containers": len(list(BUSINESS_DIR.glob("claim_container_*.json"))),
    }, indent=2))


def main() -> int:
    record = new_record()
    start = dt.datetime.now(dt.timezone.utc)

    try:
        if not BUSINESS_DIR.is_dir() or not list(BUSINESS_DIR.glob("claim_container_*.json")):
            record["actual_behavior"] = "no claim containers emitted yet — nothing to validate"
            record["verdict"] = "pass"
            path = save(record)
            _summary(record, path)
            return 0

        if not VALIDATOR.exists():
            record["actual_behavior"] = (
                f"validator not found ({VALIDATOR}) — cannot validate "
                "claim containers (set VALIDATE_CLAIM_CONTAINERS)"
            )
            record["verdict"] = "fail"
            record["errors"].append("missing validator script")
            path = save(record)
            _summary(record, path)
            return 1

        proc = subprocess.run(
            [PY, str(VALIDATOR), "--dir", str(BUSINESS_DIR),
             "--repo-root", str(REPO)],
            capture_output=True, text=True, timeout=60, check=False,
        )
        elapsed = (dt.datetime.now(dt.timezone.utc) - start).total_seconds()
        record["latency_ms"] = int(elapsed * 1000)
        record["evidence"] = [str(BUSINESS_DIR)]

        if proc.returncode != 0:
            record["actual_behavior"] = (
                "claim-container validation FAILED: "
                + (proc.stdout or proc.stderr or "").strip()[-400:]
            )
            record["verdict"] = "fail"
            record["errors"].append("contract violation in emitted claim container(s)")
            path = save(record)
            _summary(record, path)
            return 1

        record["actual_behavior"] = (
            f"all claim containers pass validation (exit 0) — "
            f"{len(list(BUSINESS_DIR.glob('claim_container_*.json')))} container(s)"
        )
        record["verdict"] = "pass"
        path = save(record)
        _summary(record, path)
        return 0
    except Exception as exc:  # noqa: BLE001
        record["actual_behavior"] = f"runner error: {type(exc).__name__}: {exc}"
        record["verdict"] = "fail"
        record["errors"].append(str(exc))
        path = save(record)
        _summary(record, path)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
