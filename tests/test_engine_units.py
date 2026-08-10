"""In-process unit suite for the Sovereign Outcome Engine.

The original pytest suite (test_outcome_engine_hygiene.py) drives the engines
via subprocess, which pytest-cov cannot see — so coverage of buh_dna.py and
outcome_engine.py read 0%. These tests import the modules directly and
exercise the real functions in-process: the measurable evidence behind the
factory's per-project coverage floor (60% on the two engine modules).

No network: every urllib path is monkeypatched or avoided.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import buh_dna as bd  # noqa: E402
import outcome_engine as oe  # noqa: E402


def _empty_scan() -> dict:
    return {
        "root": "/x", "files": 0,
        "counts": {}, "sizes": {}, "ext_counts": {},
        "sampled": {}, "oldest": None, "newest": None,
        "pii_hits": {}, "sensitive_hits": {}, "total_text_bytes": 0,
    }


def _scan_with(pii: dict | None = None, sensitive: dict | None = None,
               counts: dict | None = None) -> dict:
    s = _empty_scan()
    s["pii_hits"] = pii or {}
    s["sensitive_hits"] = sensitive or {}
    s["counts"] = counts or {}
    return s


SYNTH_TEMPLATE = {
    "id": "synthetic",
    "name": "Synthetic Template",
    "vertical": "logistics",
    "task": "Draft a note for {client}.",  # braces must not crash render
    "fields": {
        "name": {"label": "Customer Name", "pattern": r"Name:\s*(.+)?"},
        "contact_email": {"label": "Contact Email", "pattern": r"Email:\s*(.+)"},
    },
    "require": ["name"],
    "warn_terms": ["urgent"],
    "inputs": {
        "docs": {"match": ["note", "dispatch"], "exts": [".txt", ".md"]},
        "csv": {"match": ["followup"], "exts": [".csv"]},
    },
    "review": {"approver_role": "Owner", "checklist": ["Check the names", "Check the dates"]},
    "output": {"title": "Note for {client}", "doc_type": "Note"},
    "per_doc_minutes": 5,
}


# ── outcome_engine ───────────────────────────────────────────────────────────

def test_esc_escapes_html() -> None:
    assert oe.esc("<script>alert('x')</script>") == (
        "&lt;script&gt;alert(&#x27;x&#x27;)&lt;/script&gt;")


def test_classify_categories() -> None:
    assert oe.classify(Path("a.pdf")) == "docs"
    assert oe.classify(Path("b.csv")) == "sheets"
    assert oe.classify(Path("c.eml")) == "email"
    assert oe.classify(Path("d.json")) == "data"
    assert oe.classify(Path("e.jpg")) == "images"
    assert oe.classify(Path("f.mp3")) == "media"
    assert oe.classify(Path("g.dwg")) == "cad"
    assert oe.classify(Path("h.py")) == "other"
    assert oe.classify(Path("UPPER.PDF")) == "docs"  # case-insensitive


def test_scan_text_content_hits() -> None:
    pii, sensitive = __import__("collections").Counter(), __import__("collections").Counter()
    oe.scan_text_content(
        "mail a@b.com and b@c.com | SSN 123-45-6789 | call (555) 123-4567 | "
        "card 4111111111111111 | patient diagnosis hipaa | attorney-client "
        "privileged | proprietary trade secret formula",
        pii, sensitive,
    )
    assert pii["email"] == 2
    assert pii["ssn"] == 1
    assert pii["phone"] == 1
    assert pii["card"] >= 1
    assert sensitive["phi"] >= 3          # patient, diagnosis, hipaa
    assert sensitive["privilege"] >= 2    # attorney-client, privileged
    assert sensitive["trade"] >= 2        # proprietary, trade secret


def test_scan_directory_counts_and_skips(tmp_path) -> None:
    (tmp_path / "a.md").write_text("hello", encoding="utf-8")
    (tmp_path / "data.csv").write_text("x,y\n1,2", encoding="utf-8")
    (tmp_path / "img.jpg").write_bytes(b"\xff\xd8\xff")
    (tmp_path / "empty.txt").write_text("", encoding="utf-8")          # skipped: 0 bytes
    (tmp_path / ".secret.txt").write_text("hidden", encoding="utf-8")  # skipped: dotfile
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "notes.txt").write_text("contact a@b.com", encoding="utf-8")
    (tmp_path / ".hiddendir").mkdir()
    (tmp_path / ".hiddendir" / "z.md").write_text("nope", encoding="utf-8")  # skipped dir

    scan = oe.scan_directory(tmp_path)
    assert scan["files"] == 4  # a.md, data.csv, img.jpg, sub/notes.txt
    assert scan["counts"]["docs"] == 2
    assert scan["counts"]["sheets"] == 1
    assert scan["counts"]["images"] == 1
    assert scan["pii_hits"].get("email") == 1
    assert scan["oldest"] is not None and scan["newest"] is not None
    assert "notes.txt" in scan["sampled"]["docs"]


def test_compute_score_empty_scan() -> None:
    industry = oe.INDUSTRIES["logistics"]
    score = oe.compute_score(_empty_scan(), industry)
    assert score["score"] >= 0.0 and score["score"] <= 100.0
    assert score["pii_total"] == 0
    assert score["exposure_points"] == 0.0


def test_compute_score_exposure_raises_score() -> None:
    industry = oe.INDUSTRIES["logistics"]
    base = oe.compute_score(_scan_with(counts={"docs": 10}), industry)
    with_pii = oe.compute_score(
        _scan_with(counts={"docs": 10}, pii={"email": 20}, sensitive={"phi": 10}),
        industry)
    assert with_pii["score"] > base["score"]
    assert with_pii["pii_total"] == 20
    assert with_pii["sensitive_total"] == 10


def test_compute_score_clamps_at_100() -> None:
    industry = oe.INDUSTRIES["logistics"]
    big = _scan_with(counts={"docs": 10_000}, pii={"email": 1000}, sensitive={"trade": 1000})
    assert oe.compute_score(big, industry)["score"] <= 100.0


def test_build_deal_high_hours() -> None:
    industry = oe.INDUSTRIES["logistics"]
    score = {"est_manual_hours_month": 40.0}
    deal = oe.build_deal(score, industry)
    assert deal["guaranteed_hours_month"] >= 8
    assert "guaranteed off your team's plate" in deal["guarantee_note"]
    assert deal["founding_fee"] == oe.FOUNDING_FEE
    assert deal["first_workflow"] == industry["templates"][0]


def test_build_deal_mid_hours() -> None:
    industry = oe.INDUSTRIES["logistics"]
    deal = oe.build_deal({"est_manual_hours_month": 4.0}, industry)
    assert 2 <= deal["guaranteed_hours_month"] < 8
    assert "verified quarterly" in deal["guarantee_note"]


def test_build_deal_low_hours() -> None:
    industry = oe.INDUSTRIES["logistics"]
    deal = oe.build_deal({"est_manual_hours_month": 0.5}, industry)
    assert deal["guaranteed_hours_month"] == 0
    assert "measure before we promise" in deal["guarantee_note"]


def test_fmt_size() -> None:
    assert oe.fmt_size(0) == "0 B"
    assert oe.fmt_size(1023) == "1023 B"
    assert oe.fmt_size(1024) == "1.0 KB"
    assert oe.fmt_size(5 * 1024 * 1024) == "5.0 MB"
    assert oe.fmt_size(3 * 1024 ** 3) == "3.0 GB"


def test_is_dir_entry() -> None:
    assert oe.is_dir_entry("docs/")
    assert not oe.is_dir_entry("a.md")


def test_render_report_empty_scan() -> None:
    industry = oe.INDUSTRIES["logistics"]
    score = oe.compute_score(_empty_scan(), industry)
    deal = oe.build_deal(score, industry)
    html = oe.render_report("Nobody", industry, _empty_scan(), score, deal, "")
    assert "No readable files found" in html
    assert "No sensitive markers surfaced" in html
    assert "Nobody" in html


def test_render_report_populated_and_escaped() -> None:
    industry = oe.INDUSTRIES["logistics"]
    scan = _scan_with(counts={"docs": 3, "sheets": 1}, pii={"email": 2},
                      sensitive={"phi": 1})
    scan["sizes"] = {"docs": 1024, "sheets": 2048}
    scan["files"] = 4
    score = oe.compute_score(scan, industry)
    deal = oe.build_deal(score, industry)
    html = oe.render_report("<b>X</b>", industry, scan, score, deal,
                            "<script>alert(1)</script>")
    assert "&lt;b&gt;X&lt;/b&gt;" in html        # client escaped
    assert "&lt;script&gt;alert(1)" in html      # summary escaped
    assert "2 PII markers" in html
    assert "1 PHI (health) markers" in html
    assert "DATA ROI SCORE" in html


def test_scan_vault_via_bridge(monkeypatch) -> None:
    def fake_list(rel: str, secret: str) -> list:
        return {"": ["docs/", "a.md", ".DS_Store"],
                "docs": ["b.txt"]}.get(rel, [])

    def fake_read(rel: str, secret: str) -> str:
        return {"a.md": "contact: a@b.com", "b.txt": "plain text"}.get(rel.split("/")[-1], "")

    monkeypatch.setattr(oe, "vault_list", fake_list)
    monkeypatch.setattr(oe, "vault_read", fake_read)
    scan = oe.scan_vault("", "secret")
    assert scan["files"] == 2
    assert scan["counts"]["docs"] == 2
    assert scan["root"] == "vault://"
    assert scan["pii_hits"].get("email") == 1


def test_bridge_call_ok(monkeypatch) -> None:
    class _Resp:
        def read(self) -> bytes:
            return json.dumps({"ok": True, "result": {"files": ["x"]}}).encode()

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: _Resp())
    assert oe.bridge_call("vault_list", {"path": ""}, "s") == {"files": ["x"]}


def test_bridge_call_raises_on_failure(monkeypatch) -> None:
    class _Resp:
        def read(self) -> bytes:
            return json.dumps({"ok": False, "detail": "nope"}).encode()

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: _Resp())
    with pytest.raises(RuntimeError, match="bridge"):
        oe.bridge_call("vault_list", {}, "s")


def test_llm_summary_empty_on_failure(monkeypatch) -> None:
    def _boom(*a, **k):
        raise OSError("offline")

    monkeypatch.setattr("urllib.request.urlopen", _boom)
    industry = oe.INDUSTRIES["logistics"]
    score = oe.compute_score(_empty_scan(), industry)
    deal = oe.build_deal(score, industry)
    assert oe.llm_summary("Client", industry, score, deal) == ""


def test_msb_available_false_when_bridge_down(monkeypatch) -> None:
    def _boom(*a, **k):
        raise OSError("offline")

    monkeypatch.setattr("urllib.request.urlopen", _boom)
    assert oe.msb_available() is False


# ── buh_dna ──────────────────────────────────────────────────────────────────

def test_bd_esc() -> None:
    assert bd.esc("a&b") == "a&amp;b"


def test_now_iso_is_utc() -> None:
    assert bd.now_iso().endswith("+00:00")


def test_pretty_date() -> None:
    assert bd.pretty_date("2026-01-02T00:00:00+00:00") == "January 02, 2026"
    assert bd.pretty_date("garbage") == "garbage"


def test_fmt_minutes() -> None:
    assert bd.fmt_minutes(0) == "~0 min"
    assert bd.fmt_minutes(59) == "~59 min"
    assert bd.fmt_minutes(60) == "~1h"
    assert bd.fmt_minutes(90) == "~1h 30m"


def test_slugify() -> None:
    assert bd.slugify("Hello, World! 2.0") == "hello-world-2-0"
    assert bd.slugify("---") == ""


def test_load_template_real_spec() -> None:
    spec = bd.load_template("load_dispatch_summary")
    for key in ("id", "name", "vertical", "task", "fields", "review"):
        assert spec.get(key), f"missing {key}"


def test_load_template_unknown_raises() -> None:
    with pytest.raises(SystemExit, match="Unknown template"):
        bd.load_template("does_not_exist")


def test_list_templates() -> None:
    templates = bd.list_templates()
    assert len(templates) >= 4
    assert templates == sorted(templates)


def test_check_templates_ok(capsys) -> None:
    assert bd.check_templates() == 0
    assert "templates OK" in capsys.readouterr().out


def test_discover_local(tmp_path) -> None:
    (tmp_path / "dispatch-note.txt").write_text("x", encoding="utf-8")
    (tmp_path / "unrelated.pdf").write_text("x", encoding="utf-8")
    (tmp_path / "followup.csv").write_text("a,b\n1,2", encoding="utf-8")
    groups = bd.discover_local(tmp_path, SYNTH_TEMPLATE)
    assert [p.name for p in groups["docs"]] == ["dispatch-note.txt"]
    assert [p.name for p in groups["csv"]] == ["followup.csv"]


def test_read_local_text_normal(tmp_path) -> None:
    f = tmp_path / "a.txt"
    f.write_text("hello", encoding="utf-8")
    assert bd.read_local_text(f) == "hello"


def test_read_local_text_oversized(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(bd, "MAX_FILE_BYTES", 10)
    f = tmp_path / "big.txt"
    f.write_text("x" * 50, encoding="utf-8")
    assert bd.read_local_text(f) == ""


def test_extract_row_group_and_fallback() -> None:
    row = bd.extract_row("Name: John Smith\nEmail: j@x.io", "a.txt", SYNTH_TEMPLATE)
    assert row["name"] == "John Smith"
    assert row["contact_email"] == "j@x.io"

    # No capture group -> falls back to the whole match (group 0).
    tmpl = {"fields": {"ssn": {"pattern": r"\d{3}-\d{2}-\d{4}"}}}
    assert bd.extract_row("SSN 123-45-6789 here", "b.txt", tmpl)["ssn"] == "123-45-6789"

    # No match -> empty string.
    assert bd.extract_row("nothing here", "c.txt", SYNTH_TEMPLATE)["name"] == ""


def test_parse_csv_rows() -> None:
    rows = bd.parse_csv_rows("followup.csv", "name,email\nA,a@b.com\nB,\n")
    assert rows == [{"name": "A", "email": "a@b.com"}, {"name": "B", "email": ""}]
    assert bd.parse_csv_rows("x.csv", "not a csv at all") == []


def _rows() -> list[dict]:
    return [
        {"file": "one.txt", "name": "A", "contact_email": "a@b.com"},
        {"file": "two.txt", "name": "", "contact_email": "demo@example.com"},
    ]


def test_compute_flags() -> None:
    flags = bd.compute_flags(_rows(), SYNTH_TEMPLATE)
    messages = " | ".join(f["message"] for f in flags)
    assert any(f["level"] == "warn" and "Missing Customer Name" in f["message"] for f in flags)
    assert any("Demo/unroutable" in f["message"] for f in flags)


def test_compute_flags_warn_terms() -> None:
    rows = [{"file": "x.txt", "name": "A", "contact_email": "a@b.com",
             "note": "this is urgent"}]
    flags = bd.compute_flags(rows, SYNTH_TEMPLATE)
    assert any(f["level"] == "info" and "urgent" in f["message"] for f in flags)


def test_render_deliverable_draft() -> None:
    html = bd.render_deliverable(SYNTH_TEMPLATE, "Client & Co", _rows(), [],
                                 [], "", "DRAFT", None, 10)
    assert "DRAFT — AWAITING HUMAN REVIEW" in html
    assert "Customer Name" in html            # field label header rendered
    assert "A" in html and "a@b.com" in html  # extracted row cells rendered
    assert "2 document(s) matched" in html     # row-count hint
    assert "No follow-up list matched" in html
    assert "&amp;" in html  # client escaped
    assert "No LLM draft" in html


def test_render_deliverable_reviewed() -> None:
    review_entry = {"by": "Dr. Owner", "at": "2026-08-10T00:00:00+00:00"}
    html = bd.render_deliverable(SYNTH_TEMPLATE, "Clinic", _rows(),
                                 [{"name": "A", "email": "a@b.com"}],
                                 [{"level": "warn", "message": "Missing X"}],
                                 "Draft paragraph one.\nDraft paragraph two.",
                                 "REVIEWED", review_entry, 20)
    assert "REVIEWED" in html and "DRAFT" not in html
    assert "Dr. Owner" in html
    assert "August 10, 2026" in html
    assert "Draft paragraph one." in html
    assert "a@b.com" in html  # follow-up table rendered
    assert "Missing X" in html


def test_run_template_local(tmp_path) -> None:
    sample = REPO / "sample_data"
    out = tmp_path / "out.html"
    rc = bd.run_template("load_dispatch_summary", "Test Client", sample, None,
                         "", False, out)
    assert rc == 0
    assert out.exists()
    assert "Test Client" in out.read_text(encoding="utf-8")


def test_run_template_vault_requires_secret(tmp_path) -> None:
    rc = bd.run_template("load_dispatch_summary", "X", None, "10_Customers/X",
                         "", False, tmp_path / "o.html")
    assert rc == 2


def test_run_template_missing_dir(tmp_path) -> None:
    rc = bd.run_template("load_dispatch_summary", "X", tmp_path / "nope", None,
                         "", False, tmp_path / "o.html")
    assert rc == 1
