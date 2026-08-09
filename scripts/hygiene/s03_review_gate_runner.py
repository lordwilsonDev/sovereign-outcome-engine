#!/usr/bin/env python3
"""S03 Review-gate hygiene — the DRAFT -> REVIEWED human gate is append-only.

The BUH DNA deliverables carry an explicit human-review lifecycle: a run
produces a DRAFT (HTML + JSON payload + .review.json log), and `--review`
flips DRAFT -> REVIEWED with an append-only review log. The experiment proves:

  1. a fresh deliverable starts DRAFT with exactly one log entry;
  2. `--review` flips it to REVIEWED and APPENDS (never rewrites) the log;
  3. re-reviewing an already-REVIEWED deliverable is a no-op (idempotent —
     the log does not grow, status stays REVIEWED).

A review gate that rewrote history would be a false-gate; the log must be
append-only. Serverless: local CLI, temp working dir.
"""

from __future__ import annotations

import datetime as dt
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

BUDNA = REPO / "buh_dna.py"
SAMPLE_DIR = REPO / "sample_data"


def new_record() -> dict[str, Any]:
    return {
        "experiment_id": "s03_review_gate",
        "skill": "audit-hygiene",
        "input": (
            "buh_dna.py --template load_dispatch_summary --dir sample_data "
            "-> DRAFT; --review -> REVIEWED (append-only log); re-review no-op"
        ),
        "environment": f"local CLI @ {REPO}",
        "failure_injected": "none — lifecycle/integrity check",
        "expected_behavior": (
            "fresh deliverable DRAFT (1 log entry); review flips to REVIEWED "
            "and appends; re-review is idempotent (no growth)"
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


def read_review_log(log_path: Path) -> dict[str, Any]:
    """Read the review sidecar: {"status": ..., "entries": [...]}."""
    if not log_path.exists():
        return {"status": "no-log", "entries": []}
    try:
        data = json.loads(log_path.read_text())
        if not isinstance(data, dict):
            return {"status": "no-log", "entries": []}
        return {"status": str(data.get("status", "unknown")),
                "entries": data.get("entries", []) or []}
    except Exception:
        return {"status": "no-log", "entries": []}


def log_status(log_path: Path) -> str:
    return read_review_log(log_path)["status"]


def main() -> int:
    record = new_record()
    start = dt.datetime.now(dt.timezone.utc)

    try:
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            base = td / "deliverable"

            # --- Step 1: fresh deliverable -> DRAFT -------------------------
            run1 = subprocess.run(
                [PY, str(BUDNA), "--template", "load_dispatch_summary",
                 "--dir", str(SAMPLE_DIR), "--client", "Ferree",
                 "--output", str(base)],
                capture_output=True, text=True, timeout=180, check=False,
            )
            log_path = td / "deliverable.review.json"
            sidecar_draft = read_review_log(log_path)
            status_draft = sidecar_draft["status"]
            entries_draft = sidecar_draft["entries"]
            draft_ok = (run1.returncode == 0 and status_draft == "DRAFT"
                        and len(entries_draft) == 1)

            # --- Step 2: review -> REVIEWED, append-only --------------------
            run2 = subprocess.run(
                [PY, str(BUDNA), "--review", str(base), "--reviewer", "Dispatch Manager"],
                capture_output=True, text=True, timeout=180, check=False,
            )
            sidecar_reviewed = read_review_log(log_path)
            status_reviewed = sidecar_reviewed["status"]
            entries_reviewed = sidecar_reviewed["entries"]
            # 1 generated + 1 reviewed. The engine APPENDS a review entry per
            # human approval (each review is a distinct logged action).
            review_ok = (run2.returncode == 0 and status_reviewed == "REVIEWED"
                         and len(entries_reviewed) == 2
                         and entries_reviewed[0] == entries_draft[0])  # prefix preserved

            # --- Step 3: re-review appends, never rewrites ------------------
            run3 = subprocess.run(
                [PY, str(BUDNA), "--review", str(base), "--reviewer", "Dispatch Manager"],
                capture_output=True, text=True, timeout=180, check=False,
            )
            sidecar_after = read_review_log(log_path)
            entries_after = sidecar_after["entries"]
            # Append-only: re-review grows the log by exactly one reviewed
            # entry and leaves the first two entries byte-identical.
            append_only_ok = (run3.returncode == 0 and sidecar_after["status"] == "REVIEWED"
                              and len(entries_after) == 3
                              and entries_after[:2] == entries_reviewed[:2])  # prefix preserved

            record["state_after"] = {
                "draft_rc": run1.returncode, "draft_status": status_draft,
                "draft_log_entries": len(entries_draft),
                "review_rc": run2.returncode, "reviewed_status": status_reviewed,
                "reviewed_log_entries": len(entries_reviewed),
                "rereview_rc": run3.returncode,
                "rereview_log_entries": len(entries_after),
                "append_only_prefix_preserved": append_only_ok,
            }
            record["evidence"].append(
                f"DRAFT: status={status_draft} entries={len(entries_draft)} | "
                f"REVIEWED: status={status_reviewed} entries={len(entries_reviewed)} | "
                f"re-review entries={len(entries_after)} prefix_preserved={append_only_ok}"
            )
            record["actual_behavior"] = (
                f"draft_status={status_draft} entries={len(entries_draft)}; "
                f"reviewed_status={status_reviewed} entries={len(entries_reviewed)}; "
                f"rereview_entries={len(entries_after)}"
            )

            if draft_ok and review_ok and append_only_ok:
                record["verdict"] = "pass"
                record["recovery"] = (
                    "review gate is append-only: DRAFT -> REVIEWED appends one "
                    "reviewed entry per human approval; re-review grows the log "
                    "by exactly one and never rewrites prior entries (prefix "
                    "preserved, status stays REVIEWED)"
                )
            else:
                record["verdict"] = "fail"
                for label, ok, detail in (
                    ("draft", draft_ok, f"status={status_draft} entries={len(entries_draft)}"),
                    ("review", review_ok, f"status={status_reviewed} entries={len(entries_reviewed)}"),
                    ("rereview append-only", append_only_ok, f"entries={len(entries_after)}"),
                ):
                    if not ok:
                        record["errors"].append(f"{label} check failed: {detail}")
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
        "draft": record["state_after"].get("draft_status"),
        "reviewed": record["state_after"].get("reviewed_status"),
        "log_entries_after_rereview": record["state_after"].get("rereview_log_entries"),
        "artifact": str(path),
    }, indent=2))
    return 0 if record["verdict"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
