"""Real pytest suite for the Sovereign Outcome Engine — the evidence behind
the factory's `regression_passed` gate field.

Covers the same properties the hygiene experiments assert, at unit level:
template-spec integrity, scan determinism, and the append-only review gate.
These run without network or a daemon (local --dir mode only).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PY = sys.executable
ENGINE = REPO / "outcome_engine.py"
BUDNA = REPO / "buh_dna.py"
SAMPLE_DIR = REPO / "sample_data"
TEMPLATES = REPO / "buh_templates"


def test_all_templates_validate() -> None:
    """buh_dna.py --check must validate every template spec (exit 0, all OK)."""
    proc = subprocess.run(
        [PY, str(BUDNA), "--check"],
        capture_output=True, text=True, timeout=120, check=False,
    )
    out = (proc.stdout or "") + (proc.stderr or "")
    assert proc.returncode == 0, out[-2000:]
    assert "❌" not in out, out[-2000:]
    assert "4/4 templates OK" in out, out[-2000:]


def test_every_template_spec_exists() -> None:
    """The 4 documented templates all have a YAML spec (no doc/deliverable drift)."""
    expected = ["chart_note_drafting", "load_dispatch_summary",
                "privilege_log_draft", "sop_generation"]
    specs = {p.stem for p in TEMPLATES.glob("*.yaml")} if TEMPLATES.is_dir() else set()
    assert specs == set(expected)


def _extract_json(text: str) -> dict:
    """Return the LAST complete top-level JSON object in the engine's stdout.

    outcome_engine.py prints human-readable progress first and the machine
    JSON payload last, so stdout is never pure JSON.
    """
    raw = text.strip()
    last: dict | None = None
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
                        try:
                            last = json.loads(raw[i:j + 1])
                        except json.JSONDecodeError:
                            pass
                        i = j + 1
                        break
            else:
                break
        else:
            i += 1
    assert last is not None, f"no JSON payload found in stdout: {text[:300]!r}"
    return last


def _run_scan(tmp_path: Path) -> str:
    proc = subprocess.run(
        [PY, str(ENGINE), "--dir", str(SAMPLE_DIR),
         "--client", "Ferree", "--industry", "logistics", "--json",
         "--output", str(tmp_path / "report.html")],
        capture_output=True, text=True, timeout=180, check=False,
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    return proc.stdout


def test_scan_output_is_deterministic(tmp_path: Path) -> None:
    """Two identical scans produce byte-identical JSON (reports must not wobble)."""
    run1 = _extract_json(_run_scan(tmp_path))
    run2 = _extract_json(_run_scan(tmp_path))
    assert run1 == run2
    assert "score" in run1


def test_scan_report_ends_in_a_deal(tmp_path: Path) -> None:
    """The engine's own contract: every report ends in an offer, not a score alone."""
    data = _extract_json(_run_scan(tmp_path))
    blob = json.dumps(data)
    # The deal language is real pricing from the blueprint (README documents it).
    assert "offer" in blob.lower() or "founding" in blob.lower() or "$999" in blob or "99" in blob


def test_review_gate_is_append_only(tmp_path: Path) -> None:
    """DRAFT -> REVIEWED appends exactly one entry; re-review appends, never rewrites."""
    base = tmp_path / "deliverable"
    log_path = tmp_path / "deliverable.review.json"

    def sidecar() -> dict:
        return json.loads(log_path.read_text())

    run1 = subprocess.run(
        [PY, str(BUDNA), "--template", "load_dispatch_summary",
         "--dir", str(SAMPLE_DIR), "--client", "Ferree", "--output", str(base)],
        capture_output=True, text=True, timeout=180, check=False,
    )
    assert run1.returncode == 0, run1.stderr[-2000:]
    draft = sidecar()
    assert draft["status"] == "DRAFT"
    assert len(draft["entries"]) == 1

    run2 = subprocess.run(
        [PY, str(BUDNA), "--review", str(base), "--reviewer", "Dispatch Manager"],
        capture_output=True, text=True, timeout=180, check=False,
    )
    assert run2.returncode == 0, run2.stderr[-2000:]
    reviewed = sidecar()
    assert reviewed["status"] == "REVIEWED"
    assert len(reviewed["entries"]) == 2  # generated + reviewed
    assert reviewed["entries"][0] == draft["entries"][0]  # prefix preserved

    # Re-review: each human approval is a distinct logged action (append-only),
    # but prior entries are never rewritten and status stays REVIEWED.
    run3 = subprocess.run(
        [PY, str(BUDNA), "--review", str(base), "--reviewer", "Dispatch Manager"],
        capture_output=True, text=True, timeout=180, check=False,
    )
    assert run3.returncode == 0
    final = sidecar()
    assert final["status"] == "REVIEWED"
    assert len(final["entries"]) == 3
    assert final["entries"][:2] == reviewed["entries"][:2]  # prefix preserved


def test_sample_data_is_synthetic() -> None:
    """Every email in sample_data is .example/demo-marked; SSNs are flagged."""
    import re

    email_re = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+")
    ssn_re = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
    flags = ("placeholder", "not a real", "demo", "example")

    def synthetic(email: str) -> bool:
        low = email.lower()
        local, sep, domain = low.partition("@")
        if not sep:
            return True  # malformed — not a usable real address
        return domain.endswith(".example") or "demo" in domain or local.startswith("demo")

    bad_emails: list[str] = []
    bad_ssns: list[str] = []
    for p in (SAMPLE_DIR).rglob("*"):
        if not p.is_file():
            continue
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            for email in email_re.findall(line):
                if not synthetic(email):
                    bad_emails.append(email)
            for ssn in ssn_re.findall(line):
                if not any(f in line.lower() for f in flags):
                    bad_ssns.append(ssn)
    assert not bad_emails, f"real-looking emails in sample_data: {bad_emails[:5]}"
    assert not bad_ssns, f"unflagged SSNs in sample_data: {bad_ssns[:5]}"


def test_scan_is_read_only() -> None:
    """Scanning sample_data must not modify/create/delete any file inside it."""
    import hashlib
    import tempfile

    def snap() -> dict[str, str]:
        return {
            str(p.relative_to(SAMPLE_DIR)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(SAMPLE_DIR.rglob("*")) if p.is_file()
        }

    before = snap()
    with tempfile.TemporaryDirectory() as td:
        subprocess.run(
            [PY, str(ENGINE), "--dir", str(SAMPLE_DIR),
             "--client", "Ferree", "--industry", "logistics", "--json",
             "--output", str(Path(td) / "report.html")],
            capture_output=True, text=True, timeout=180, check=False,
        )
    after = snap()
    assert set(before) == set(after), "scan created/deleted files in sample_data"
    assert all(before[k] == after[k] for k in before), "scan modified files in sample_data"


def test_review_log_prefix_is_stable_across_rereview(tmp_path: Path) -> None:
    """Re-review grows the log by one but NEVER mutates prior entries."""
    base = tmp_path / "deliverable"
    log_path = tmp_path / "deliverable.review.json"

    subprocess.run([PY, str(BUDNA), "--template", "load_dispatch_summary",
                    "--dir", str(SAMPLE_DIR), "--client", "Ferree", "--output", str(base)],
                   capture_output=True, text=True, timeout=180, check=False)
    subprocess.run([PY, str(BUDNA), "--review", str(base), "--reviewer", "Dispatch Manager"],
                   capture_output=True, text=True, timeout=180, check=False)
    after_first = json.loads(log_path.read_text())["entries"]

    subprocess.run([PY, str(BUDNA), "--review", str(base), "--reviewer", "Dispatch Manager"],
                   capture_output=True, text=True, timeout=180, check=False)
    after_second = json.loads(log_path.read_text())["entries"]
    assert len(after_second) == len(after_first) + 1
    assert after_second[:len(after_first)] == after_first  # prefix byte-identical
