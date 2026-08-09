#!/usr/bin/env python3
"""S01 Template-check hygiene — buh_dna.py --check validates every template.

The BUH DNA template specs (buh_templates/*.yaml) are the configuration the
delivery automations load at runtime. A malformed spec fails silently at
ingest time, so `buh_dna.py --check` (the project's own validator) must pass
against every template. This experiment runs it and requires all templates OK.

Serverless: no daemon, no network.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
from pathlib import Path
from typing import Any

REPO = Path(os.environ.get("MSB_REPO", Path(__file__).resolve().parents[2]))
EVIDENCE_DIR = REPO / "artifacts" / "hygiene"
EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
PY = os.environ.get("MSB_PYTHON", "/opt/homebrew/Caskroom/miniforge/base/bin/python")

BUDNA = REPO / "buh_dna.py"


def new_record() -> dict[str, Any]:
    return {
        "experiment_id": "s01_template_check",
        "skill": "configuration-hygiene",
        "input": "buh_dna.py --check (validates all buh_templates/*.yaml specs)",
        "environment": f"local CLI @ {REPO}",
        "failure_injected": "none — configuration integrity check",
        "expected_behavior": "all templates validate (exit 0, N/N templates OK)",
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


def main() -> int:
    record = new_record()
    start = dt.datetime.now(dt.timezone.utc)

    templates = sorted((REPO / "buh_templates").glob("*.yaml")) if (REPO / "buh_templates").is_dir() else []
    record["state_before"]["template_count"] = len(templates)
    record["state_before"]["template_files"] = [t.name for t in templates]

    try:
        proc = subprocess.run(
            [PY, str(BUDNA), "--check"],
            capture_output=True, text=True, timeout=120, check=False,
        )
        out = (proc.stdout or "") + (proc.stderr or "")
        ok_markers = out.count("✅")
        failed_markers = out.count("❌")
        record["state_after"] = {
            "returncode": proc.returncode,
            "ok_markers": ok_markers,
            "failed_markers": failed_markers,
            "summary_line": [l for l in out.splitlines() if "template" in l.lower() and "OK" in l][:2],
        }
        record["evidence"].append(
            f"exit={proc.returncode} ok_markers={ok_markers} "
            f"failed_markers={failed_markers} templates_found={len(templates)}"
        )
        passed = (proc.returncode == 0 and failed_markers == 0
                  and len(templates) > 0 and ok_markers >= len(templates))
        record["actual_behavior"] = (
            f"exit={proc.returncode} ok_markers={ok_markers} "
            f"failed_markers={failed_markers} of {len(templates)} templates"
        )
        if passed:
            record["verdict"] = "pass"
            record["recovery"] = "all template specs validate via buh_dna.py --check"
        else:
            record["verdict"] = "fail"
            record["errors"].append(
                f"template check failed: exit={proc.returncode} "
                f"ok={ok_markers} fail={failed_markers} of {len(templates)}"
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
        "templates": len(templates),
        "ok_markers": record["state_after"].get("ok_markers"),
        "artifact": str(path),
    }, indent=2))
    return 0 if record["verdict"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
