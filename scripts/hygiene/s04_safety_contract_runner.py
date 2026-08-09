#!/usr/bin/env python3

"""S04 Safety-contract hygiene — sample data is synthetic AND scanning is read-only.

Two invariants the README promises:

  1. **synthetic data** — `sample_data/` never contains real customer data.
     Every email must use a reserved `.example` TLD (RFC 2606) or an
     explicit demo marker, and any SSN-format number must be accompanied by
     an explicit "placeholder/not a real" flag on the same line. A real
     personal email or a bare SSN in sample_data is a data-integrity breach.
  2. **read-only scanning** — running the scanner against sample_data must
     NOT modify, create, or delete anything inside sample_data (hash every
     file before and after; directory listing must be unchanged).

Serverless: local CLI, no network.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

REPO = Path(os.environ.get("MSB_REPO", Path(__file__).resolve().parents[2]))
EVIDENCE_DIR = REPO / "artifacts" / "hygiene"
EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
PY = os.environ.get("MSB_PYTHON", sys.executable)

ENGINE = REPO / "outcome_engine.py"
SAMPLE_DIR = REPO / "sample_data"

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+")
SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
PLACEHOLDER_FLAGS = ("placeholder", "not a real", "demo", "example")


def is_synthetic_email(email: str) -> bool:
    """True only for RFC 2606 .example TLDs or demo-marked domains/local parts.

    A loose "example in the string" check would let a real address like
    user@examplecorp.com false-pass — so the domain must END in .example, or
    the domain or local part must carry an explicit demo marker.
    """
    low = email.lower()
    local, sep, domain = low.partition("@")
    if not sep:
        return True  # malformed — not a usable real address
    return domain.endswith(".example") or "demo" in domain or local.startswith("demo")


def new_record() -> dict[str, Any]:
    return {
        "experiment_id": "s04_safety_contract",
        "skill": "data-hygiene",
        "input": (
            "sample_data is synthetic (emails .example/demo, SSNs flagged) "
            "AND scanning it is read-only (no file modified/created/deleted)"
        ),
        "environment": f"local CLI @ {REPO}",
        "failure_injected": "none — safety contract check",
        "expected_behavior": (
            "no real personal emails (must be .example or demo-marked); "
            "SSN-format numbers only with explicit placeholder flags; "
            "scanning does not mutate sample_data"
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


def snapshot_dir(root: Path) -> dict[str, str]:
    """path -> sha256 for every file under root (or {} if root missing)."""
    if not root.is_dir():
        return {}
    out = {}
    for p in sorted(root.rglob("*")):
        if p.is_file():
            out[str(p.relative_to(root))] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def main() -> int:
    record = new_record()
    start = dt.datetime.now(dt.timezone.utc)

    try:
        # --- Invariant 1: synthetic data ------------------------------------
        suspicious_emails: list[str] = []
        suspicious_ssns: list[str] = []
        for p in sorted(SAMPLE_DIR.rglob("*")):
            if not p.is_file():
                continue
            for i, line in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                for email in EMAIL_RE.findall(line):
                    if not is_synthetic_email(email):
                        suspicious_emails.append(f"{p.relative_to(SAMPLE_DIR)}:{i}: {email}")
                for ssn in SSN_RE.findall(line):
                    if not any(flag in line.lower() for flag in PLACEHOLDER_FLAGS):
                        suspicious_ssns.append(f"{p.relative_to(SAMPLE_DIR)}:{i}: {ssn}")
        synthetic_ok = not suspicious_emails and not suspicious_ssns

        # --- Invariant 2: read-only scan ------------------------------------
        # Pass --output to a temp path (like s02 does): the engine otherwise
        # writes <client>_report.html into the CWD — polluting the repo root
        # and hiding the mutation from a sample_data-only snapshot.
        before = snapshot_dir(SAMPLE_DIR)
        with tempfile.TemporaryDirectory() as td:
            proc = subprocess.run(
                [PY, str(ENGINE), "--dir", str(SAMPLE_DIR),
                 "--client", "Ferree", "--industry", "logistics", "--json",
                 "--output", str(Path(td) / "report.html")],
                capture_output=True, text=True, timeout=180, check=False,
            )
        after = snapshot_dir(SAMPLE_DIR)
        modified = [k for k in before if before.get(k) != after.get(k)]
        created = [k for k in after if k not in before]
        deleted = [k for k in before if k not in after]
        readonly_ok = not modified and not created and not deleted

        record["state_after"] = {
            "synthetic_ok": synthetic_ok,
            "suspicious_emails": suspicious_emails[:10],
            "suspicious_ssns": suspicious_ssns[:10],
            "readonly_ok": readonly_ok,
            "modified": modified[:10],
            "created": created[:10],
            "deleted": deleted[:10],
            "scan_rc": proc.returncode,
        }
        record["evidence"].append(
            f"synthetic_ok={synthetic_ok} emails={len(suspicious_emails)} "
            f"ssns={len(suspicious_ssns)} | readonly_ok={readonly_ok} "
            f"modified={len(modified)} created={len(created)} deleted={len(deleted)}"
        )
        record["actual_behavior"] = (
            f"synthetic_ok={synthetic_ok} (emails={len(suspicious_emails)}, "
            f"ssns={len(suspicious_ssns)}); readonly_ok={readonly_ok} "
            f"(modified={len(modified)}, created={len(created)}, deleted={len(deleted)})"
        )

        if synthetic_ok and readonly_ok:
            record["verdict"] = "pass"
            record["recovery"] = (
                "sample_data is synthetic (no real personal emails or bare "
                "SSNs) and the scanner is read-only (zero files changed)"
            )
        else:
            record["verdict"] = "fail"
            if suspicious_emails:
                record["errors"].append(f"non-synthetic emails: {suspicious_emails[:5]}")
            if suspicious_ssns:
                record["errors"].append(f"unflagged SSNs: {suspicious_ssns[:5]}")
            if modified or created or deleted:
                record["errors"].append(
                    f"scan mutated sample_data: modified={modified[:5]} "
                    f"created={created[:5]} deleted={deleted[:5]}"
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
        "synthetic_ok": record["state_after"].get("synthetic_ok"),
        "readonly_ok": record["state_after"].get("readonly_ok"),
        "artifact": str(path),
    }, indent=2))
    return 0 if record["verdict"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
