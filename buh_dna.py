#!/usr/bin/env python3
"""
╔═══════════════════════════════════════════════════════════════════════════════╗
║   BUH DNA TEMPLATE ENGINE v1.0                                                ║
║   Narrow task · Narrow output · Reviewable.                                   ║
╚═══════════════════════════════════════════════════════════════════════════════╝

The Stage-7 delivery automations for the BlackSwanLabz sovereign stack. A BUH DNA
template is a YAML spec (in ./buh_templates/) that turns client documents into a
narrow, reviewable deliverable — Load & Dispatch Summary, Chart-Note Draft,
Privilege-Log Draft, SOP Draft.

Each run:
  1. Ingests the documents the template asks for (local dir OR vault via msb-v3
     bridge — read-only).
  2. Extracts structured fields deterministically (no guessing).
  3. Computes honesty flags (missing required fields, sensitive terms, demo email).
  4. Optionally drafts the narrative with the LOCAL model (msb-v3 /chat) — a
     narrow task prompt, never client data leaving the node.
  5. Renders a reviewable HTML deliverable + machine-readable JSON sidecars.
  6. Tracks the review lifecycle: DRAFT -> REVIEWED (append-only log).

Usage (local demo data):
  python3 buh_dna.py --template load_dispatch_summary --dir ./sample_data \
      --client "Ferree Movers" --output ferree_dispatch.html --llm

Usage (vault, on-node):
  python3 buh_dna.py --template load_dispatch_summary --vault 10_Customers/Pacur \
      --client "Pacur" --secret <bridge-secret> --llm

Other commands:
  python3 buh_dna.py --list                          # show available templates
  python3 buh_dna.py --review out.html --reviewer X  # approve a deliverable
  python3 buh_dna.py --check                         # validate all templates load
"""

from __future__ import annotations

import argparse
import csv
import html
import io
import json
import os
import re
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import yaml  # PyYAML — available on the node (verified 6.0.2)
except ImportError:  # pragma: no cover
    yaml = None

TEMPLATES_DIR = Path(__file__).resolve().parent / "buh_templates"
MSB_HEALTH_URL = "http://127.0.0.1:8766/health"
MSB_CHAT_URL = "http://127.0.0.1:8766/chat"
MCP_PROXY_URL = "http://127.0.0.1:8766/mcp/proxy"
# No hardcoded bridge secret — vault mode fails fast unless --secret / env provides one.
DEFAULT_SECRET = os.environ.get("MCP_BRIDGE_SECRET", "")
MAX_FILE_BYTES = 2_000_000
REVIEW_STATUSES = ("DRAFT", "REVIEWED")


# ══════════════════════════════════════════════════════════════════════════════
# SMALL HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def esc(value: object) -> str:
    """HTML-escape any value interpolated into a deliverable (injection guard)."""
    return html.escape(str(value), quote=True)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def pretty_date(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso).strftime("%B %d, %Y")
    except Exception:
        return iso[:10]


def fmt_minutes(minutes: int) -> str:
    if minutes < 60:
        return f"~{minutes} min"
    h, m = divmod(minutes, 60)
    return f"~{h}h {m:02d}m" if m else f"~{h}h"


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9-]+", "-", text.lower()).strip("-")


# ══════════════════════════════════════════════════════════════════════════════
# TEMPLATE LOADING
# ══════════════════════════════════════════════════════════════════════════════

def load_template(template_id: str) -> dict:
    """Load and validate a BUH DNA template spec from ./buh_templates/."""
    if yaml is None:
        raise SystemExit("❌ PyYAML is required: pip install pyyaml")
    path = TEMPLATES_DIR / f"{template_id}.yaml"
    if not path.exists():
        known = ", ".join(sorted(list_templates()))
        raise SystemExit(f"❌ Unknown template '{template_id}'. Available: {known}")
    try:
        spec = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as e:
        raise SystemExit(f"❌ Template '{template_id}' failed to parse: {e}")
    required = ("id", "name", "vertical", "task", "fields", "review")
    missing = [k for k in required if not spec.get(k)]
    if missing:
        raise SystemExit(f"❌ Template '{template_id}' missing required keys: {', '.join(missing)}")
    return spec


def list_templates() -> list[str]:
    if not TEMPLATES_DIR.is_dir():
        return []
    return sorted(p.stem for p in TEMPLATES_DIR.glob("*.yaml"))


def check_templates() -> int:
    bad = 0
    for tid in list_templates():
        try:
            spec = load_template(tid)
            print(f"✅ {tid:28s} {spec['vertical']:14s} {spec['name']}")
        except SystemExit as e:
            bad += 1
            print(f"❌ {tid}: {e}")
    print(f"\n{len(list_templates()) - bad}/{len(list_templates())} templates OK"
          if list_templates() else "No templates found")
    return 1 if bad else 0


# ══════════════════════════════════════════════════════════════════════════════
# INPUT INGESTION — local dir (read-only)
# ══════════════════════════════════════════════════════════════════════════════

def discover_local(root: Path, template: dict) -> dict[str, list[Path]]:
    """Bucket files under root into the template's input groups (docs / csv).
    Matching: path contains any keyword for that group (case-insensitive) AND
    extension is allowed. Hidden dirs are skipped (same convention as
    outcome_engine.scan_directory). Read-only walk — never writes into input."""
    groups: dict[str, list[Path]] = {"docs": [], "csv": []}
    for key, group in template.get("inputs", {}).items():
        keywords = [k.lower() for k in group.get("match", [])]
        exts = {e.lower() for e in group.get("exts", [])}
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]
            for name in filenames:
                if name.startswith("."):
                    continue
                p = Path(dirpath) / name
                if p.suffix.lower() not in exts:
                    continue
                hay = f"{p} {p.name}".lower()
                if any(k in hay for k in keywords):
                    groups.setdefault(key, []).append(p)
    return groups


def read_local_text(path: Path) -> str:
    """Read a text file for extraction. Files over the size cap return '' and
    are excluded from the deliverable (documented, not silently guessed)."""
    if path.stat().st_size > MAX_FILE_BYTES:
        print(f"   ⚠️  Skipping oversized file (>{MAX_FILE_BYTES // 1_000_000}MB): {path.name}")
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""


# ══════════════════════════════════════════════════════════════════════════════
# INPUT INGESTION — vault via msb-v3 bridge (read-only)
# ══════════════════════════════════════════════════════════════════════════════

def bridge_call(tool: str, args: dict, secret: str) -> dict:
    body = json.dumps({"tool": tool, "args": args}).encode()
    req = urllib.request.Request(
        MCP_PROXY_URL, data=body,
        headers={"content-type": "application/json", "x-mcp-secret": secret},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        payload = json.loads(resp.read().decode())
    if not payload.get("ok"):
        raise RuntimeError(f"bridge {tool} failed: {payload.get('detail', payload)}")
    return payload.get("result") or {}


def vault_list(path: str, secret: str) -> list:
    return bridge_call("vault_list", {"path": path}, secret).get("files", [])


def vault_read(path: str, secret: str) -> str:
    return bridge_call("vault_read", {"path": path}, secret).get("content", "") or ""


def discover_vault(root: str, template: dict, secret: str, max_files: int = 500) -> dict[str, list[tuple[str, str]]]:
    """Walk a vault subtree through the bridge, bucketing files like discover_local.
    Returns {group: [(rel_path, content), ...]}. Path traversal guarded by bridge."""
    groups: dict[str, list[tuple[str, str]]] = {"docs": [], "csv": []}
    hits = 0

    def walk(rel: str, depth: int = 0) -> None:
        nonlocal hits
        if hits >= max_files or depth > 15:
            return
        try:
            entries = vault_list(rel, secret)
        except Exception:
            return
        for entry in entries:
            if hits >= max_files:
                return
            name = entry.rstrip("/")
            child = f"{rel}/{name}" if rel else name
            if entry.endswith("/"):
                if not name.startswith("."):
                    walk(child, depth + 1)
                continue
            if name.startswith(".") or name == ".DS_Store":
                continue
            path = Path(name)
            for key, group in template.get("inputs", {}).items():
                keywords = [k.lower() for k in group.get("match", [])]
                exts = {e.lower() for e in group.get("exts", [])}
                if path.suffix.lower() not in exts:
                    continue
                hay = f"{child} {name}".lower()
                if any(k in hay for k in keywords):
                    content = vault_read(child, secret)
                    if content and len(content) <= MAX_FILE_BYTES:
                        groups.setdefault(key, []).append((child, content))
                        hits += 1
                    break  # one bucket per file

    walk(root)
    return groups


# ══════════════════════════════════════════════════════════════════════════════
# EXTRACTION — deterministic fields + CSV
# ══════════════════════════════════════════════════════════════════════════════

def extract_row(text: str, name: str, template: dict) -> dict:
    """Pull the template's fields from one document via its regex patterns.
    Patterns without a capture group fall back to the whole match (no crash)."""
    row: dict = {"file": name}
    for field, cfg in template.get("fields", {}).items():
        pattern = cfg.get("pattern", "")
        m = re.search(pattern, text, re.IGNORECASE)
        if not m:
            value = ""
        elif m.lastindex:
            value = m.group(1).strip()
        else:
            value = m.group(0).strip()
        row[field] = value
    return row


def parse_csv_rows(path: str, text: str) -> list[dict]:
    """Parse a CSV's header + data rows into dicts (for follow-up lists etc.)."""
    rows: list[dict] = []
    try:
        reader = csv.DictReader(io.StringIO(text))
        for r in reader:
            if r and any((v or "").strip() for v in r.values()):
                rows.append({k: (v or "").strip() for k, v in r.items()})
    except Exception:
        pass
    return rows


# ══════════════════════════════════════════════════════════════════════════════
# HONESTY FLAGS — nothing invented, everything visible
# ══════════════════════════════════════════════════════════════════════════════

def compute_flags(rows: list[dict], template: dict) -> list[dict]:
    flags: list[dict] = []
    for row in rows:
        file = row.get("file", "?")
        for field in template.get("require", []):
            if not (row.get(field) or "").strip():
                label = template["fields"].get(field, {}).get("label", field)
                flags.append({"level": "warn", "message": f"Missing {label} — {file}"})
        for term in template.get("warn_terms", []):
            if re.search(re.escape(term), " ".join(str(v) for v in row.values()), re.IGNORECASE):
                flags.append({"level": "info", "message": f"Term '{term}' present — {file} (review context)"})
    # Honesty: demo/unroutable contact emails are flagged, not silently used.
    for row in rows:
        email = str(row.get("contact_email", "") or "").strip()
        if re.search(r"\.example\b", email, re.IGNORECASE):
            flags.append({"level": "warn", "message": f"Demo/unroutable contact email in {row.get('file', '?')} — do not send real outreach to it"})
    return flags


# ══════════════════════════════════════════════════════════════════════════════
# LLM DRAFT — narrow task, local model only
# ══════════════════════════════════════════════════════════════════════════════

def msb_available() -> bool:
    """Probe msb-v3 with retries. The server can be momentarily busy finishing a
    prior synchronous LLM generation (its event loop blocks) and come back
    healthy seconds later — one probe alone produces false negatives."""
    import time
    for _ in range(4):
        try:
            with urllib.request.urlopen(MSB_HEALTH_URL, timeout=8) as r:
                if r.status == 200:
                    return True
        except Exception:
            pass
        time.sleep(3)
    return False


def llm_draft(template: dict, client: str, rows: list[dict], followups: list[dict], flags: list[dict]) -> str:
    """Draft the deliverable narrative with the local model. Narrow prompt:
    template task + ONLY the extracted context. Nothing leaves the node."""
    lines = [f"CLIENT: {client}"]
    lines.append("\nDOCUMENTS (extracted):")
    for i, row in enumerate(rows, 1):
        bits = [f"{k}={v}" for k, v in row.items() if v]
        lines.append(f"{i}. {row.get('file', f'doc {i}')} :: {' | '.join(bits)}")
    if followups:
        lines.append("\nFOLLOW-UP LIST:")
        for r in followups:
            lines.append("- " + " | ".join(f"{k}={v}" for k, v in r.items() if v))
    if flags:
        lines.append("\nFLAGS (do not hide these):")
        for f in flags:
            lines.append(f"- [{f['level']}] {f['message']}")
    # .replace (not str.format) so a template task containing literal { } braces
    # (e.g. JSON examples in a prompt) can never crash the run.
    prompt = template["task"].replace("{client}", client) + "\n\n" + "\n".join(lines)
    # Fresh session per run (timestamped) so msb-v3's chat history can't bleed
    # a previous draft into this one-shot generation.
    run_key = f"{template['id']}-{slugify(client)}-{now_iso()}"
    body = json.dumps({"query": prompt, "session": f"buh-{run_key}"}).encode()
    req = urllib.request.Request(MSB_CHAT_URL, data=body, headers={"content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            data = json.loads(r.read().decode())
            return (data.get("payload") or {}).get("text", "").strip()
    except Exception:
        return ""


# ══════════════════════════════════════════════════════════════════════════════
# RENDER — reviewable HTML deliverable (sovereign aesthetic)
# ══════════════════════════════════════════════════════════════════════════════

def render_deliverable(template: dict, client: str, rows: list[dict], followups: list[dict],
                       flags: list[dict], summary: str, status: str, review_entry: dict | None,
                       estimate_minutes: int) -> str:
    reviewed = status == "REVIEWED"
    banner_color = "#10b981" if reviewed else "#f59e0b"
    banner_text = "REVIEWED" if reviewed else "DRAFT — AWAITING HUMAN REVIEW"

    # Document rows table
    field_labels = [(k, cfg.get("label", k)) for k, cfg in template.get("fields", {}).items()]
    row_html = ""
    for row in rows:
        cells = "".join(f"<td>{esc(row.get(k, ''))}</td>" for k, _ in field_labels)
        row_html += f"<tr>{cells}</tr>"
    head_html = "".join(f"<th>{esc(label)}</th>" for _, label in field_labels)
    table_html = (
        f"<table><thead><tr>{head_html}</tr></thead><tbody>{row_html}</tbody></table>"
        if rows else "<p class='empty'>No matching documents found in the input. Nothing was invented to fill the gap.</p>"
    )

    # Follow-ups
    followup_html = ""
    if followups:
        cols = list(followups[0].keys())
        head = "".join(f"<th>{esc(c)}</th>" for c in cols)
        body = "".join(
            "<tr>" + "".join(f"<td>{esc(r.get(c, ''))}</td>" for c in cols) + "</tr>"
            for r in followups
        )
        followup_html = f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"
    else:
        followup_html = "<p class='empty'>No follow-up list matched.</p>"

    # Flags
    if flags:
        flags_html = "".join(
            f"<li class='flag {esc(f['level'])}'>{esc(f['message'])}</li>" for f in flags
        )
    else:
        flags_html = "<li class='flag ok'>No flags — every required field present, no sensitive-term hits.</li>"

    # Review section
    approver = esc(template.get("review", {}).get("approver_role", "Owner"))
    checklist = template.get("review", {}).get("checklist", [])
    checklist_html = "".join(f"<li><span class='cb'>{'✓' if reviewed else '☐'}</span> {esc(c)}</li>" for c in checklist)
    review_meta = ""
    if review_entry:
        who = esc(review_entry.get("by", ""))
        when = pretty_date(review_entry.get("at", ""))
        review_meta = f"<p class='review-meta'>Approved by <strong>{who}</strong> · {when}</p>"

    summary_html = f"<div class='card'><h3>📝 Draft ({esc(template['vertical'])} — local model)</h3><div class='draft'>{''.join(f'<p>{esc(p)}</p>' for p in summary.splitlines() if p.strip())}</div><p class='hint'>Auto-drafted by qwen3:8b on the sovereign node. Verify against source documents.</p></div>" if summary else "<p class='hint'>No LLM draft — run with --llm and msb-v3 running to add the narrative.</p>"

    title = template.get("output", {}).get("title", "{client}").format(client=client)
    tagline = esc(template.get("tagline", template.get("name", "")))
    doc_type = esc(template.get("output", {}).get("doc_type", ""))

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{esc(title)}</title>
<style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
         background:#0a0a0f; color:#e0e0e0; line-height:1.6; }}
  .hero {{ padding:3rem 2rem 2rem; text-align:center;
           background:radial-gradient(ellipse at center,#151530 0%,#0a0a0f 70%); }}
  .tag {{ color:#8b5cf6; letter-spacing:.25em; text-transform:uppercase; font-size:.75rem; }}
  h1 {{ font-size:clamp(1.8rem,4vw,2.8rem); margin:.8rem 0 .4rem;
        background:linear-gradient(135deg,#8b5cf6,#06b6d4);
        -webkit-background-clip:text; -webkit-text-fill-color:transparent; }}
  .sub {{ color:#a0a0b0; font-size:.95rem; max-width:640px; margin:0 auto; }}
  .banner {{ display:inline-block; margin-top:1rem; padding:.45rem 1.2rem; border-radius:99px;
             border:1px solid {banner_color}; color:{banner_color};
             font-size:.8rem; letter-spacing:.12em; }}
  section {{ max-width:960px; margin:0 auto; padding:2rem; }}
  h2 {{ color:#8b5cf6; font-size:1.25rem; margin-bottom:1rem;
        display:flex; align-items:center; gap:.5rem; }}
  .card {{ background:#14141f; border:1px solid #26263a; border-radius:14px;
           padding:1.4rem; margin-bottom:1.2rem; }}
  table {{ width:100%; border-collapse:collapse; font-size:.9rem; }}
  th,td {{ text-align:left; padding:.55rem; border-bottom:1px solid #1e1e2e; vertical-align:top; }}
  th {{ color:#a0a0b0; font-weight:500; font-size:.75rem; letter-spacing:.1em; text-transform:uppercase; }}
  .empty {{ color:#606070; font-style:italic; }}
  .flag {{ margin:.4rem 0; padding:.5rem .8rem; border-radius:8px; list-style:none; font-size:.9rem; }}
  .flag.warn {{ background:#2a1a10; border:1px solid #7c4a03; color:#fbbf24; }}
  .flag.info {{ background:#101a2a; border:1px solid #1e3a5f; color:#7dd3fc; }}
  .flag.ok {{ background:#0f2418; border:1px solid #14532d; color:#6ee7b7; }}
  .draft p {{ margin:.5rem 0; }}
  .hint {{ color:#606070; font-size:.8rem; margin-top:.8rem; font-style:italic; }}
  .cb {{ color:#06b6d4; margin-right:.4rem; }}
  .review-meta {{ color:#10b981; margin-top:.8rem; font-size:.9rem; }}
  .estimate {{ display:inline-block; padding:.35rem .9rem; border-radius:99px;
               border:1px solid #06b6d4; color:#06b6d4; font-size:.8rem; }}
  ul.checklist {{ padding-left:0; list-style:none; }}
  ul.checklist li {{ padding:.35rem 0; border-bottom:1px dashed #1e1e2e; }}
  footer {{ text-align:center; color:#404050; padding:2rem; border-top:1px solid #1a1a2e; font-size:.8rem; }}
</style>
</head>
<body>
  <div class="hero">
    <div class="tag">BUH DNA Template · {esc(template['vertical'])}</div>
    <h1>{esc(title)}</h1>
    <p class="sub">{tagline}</p>
    <div class="banner">{banner_text}</div>
    <p style="color:#606070;font-size:.8rem;margin-top:.8rem;">{esc(client)} · {pretty_date(now_iso())} · {doc_type}</p>
  </div>

  <section>
    <h2>🚚 Documents Extracted</h2>
    <div class="card">{table_html}
      <p class="hint">{esc(len(rows))} document(s) matched the template's input spec ·
         read-only · nothing copied off the node.
         <span class="estimate">{fmt_minutes(estimate_minutes)} of manual drafting avoided this run</span></p>
    </div>

    <h2>⚠️ Flags — read before distributing</h2>
    <div class="card"><ul style="padding-left:0;">{flags_html}</ul></div>

    <h2>📇 Customer Follow-Up List</h2>
    <div class="card">{followup_html}</div>

    <h2>✍️ Draft</h2>
    {summary_html}

    <h2>🔏 Review Gate</h2>
    <div class="card">
      <p style="color:#a0a0b0;">Required sign-off: <strong>{approver}</strong></p>
      <ul class="checklist">{checklist_html}</ul>
      {review_meta}
    </div>
  </section>

  <footer>
    Generated by BlackSwanLabz · Fox Valley AI Cooperative · sovereign node · {datetime.now(timezone.utc).strftime('%B %d, %Y')}<br>
    We measure before we promise. This draft is the evidence; the review gate is the contract.
  </footer>
</body>
</html>
"""


# ══════════════════════════════════════════════════════════════════════════════
# RUN A TEMPLATE
# ══════════════════════════════════════════════════════════════════════════════

def run_template(template_id: str, client: str, local_dir: Path | None, vault_path: str | None,
                 secret: str, llm: bool, output: Path) -> int:
    template = load_template(template_id)

    # 1. INGEST (read-only)
    groups: dict[str, list[Any]] = {}
    if vault_path:
        if not secret:
            print("❌ --vault requires the bridge secret: pass --secret or set MCP_BRIDGE_SECRET", file=sys.stderr)
            return 2
        print(f"🔗 Scanning vault '{vault_path}' via msb-v3 bridge...")
        groups = discover_vault(vault_path, template, secret)
        doc_sources = [(name, text) for name, text in groups.get("docs", [])]
        csv_sources = [(name, text) for name, text in groups.get("csv", [])]
    else:
        if local_dir is None:
            print("❌ --dir is required when --vault is not given", file=sys.stderr)
            return 1
        root = local_dir.expanduser().resolve()
        if not root.is_dir():
            print(f"❌ Not a directory: {root}", file=sys.stderr)
            return 1
        print(f"🔍 Scanning {root} read-only...")
        groups = discover_local(root, template)
        doc_sources = [(p.name, read_local_text(p)) for p in groups.get("docs", [])]
        csv_sources = [(p.name, read_local_text(p)) for p in groups.get("csv", [])]

    # 2. EXTRACT (deterministic)
    rows = [extract_row(text, name, template) for name, text in doc_sources if text]
    followups: list[dict] = []
    for name, text in csv_sources:
        if text:
            followups.extend(parse_csv_rows(name, text))

    # 3. FLAGS (honesty)
    flags = compute_flags(rows, template)

    # 4. ESTIMATE (measure before promise — derived from matched doc volume)
    per_doc = int(template.get("per_doc_minutes", 10))
    estimate_minutes = len(rows) * per_doc

    # 5. LLM DRAFT (narrow task, local model, optional)
    summary = ""
    if llm:
        if msb_available():
            print("🧠 Drafting with msb-v3 (qwen3:8b, local)...")
            summary = llm_draft(template, client, rows, followups, flags)
            if not summary:
                print("⚠️  Draft empty — report will omit the narrative.")
        else:
            print("⚠️  msb-v3 not running — skipping LLM draft (deliverable still complete).")

    # 6. SIDECARS + RENDER
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    review_path = output.with_suffix(".review.json")
    data_path = output.with_suffix(".json")

    generated_entry = {"at": now_iso(), "action": "generated", "by": "buh_dna.py"}
    review_sidecar = {"status": "DRAFT", "entries": [generated_entry]}
    review_path.write_text(json.dumps(review_sidecar, indent=2), encoding="utf-8")

    payload = {
        "template": template_id,
        "template_name": template["name"],
        "vertical": template["vertical"],
        "client": client,
        "generated_at": now_iso(),
        "rows": rows,
        "followups": followups,
        "flags": flags,
        "summary": summary,
        "estimate_minutes": estimate_minutes,
        "approver_role": template.get("review", {}).get("approver_role", ""),
        "review_checklist": template.get("review", {}).get("checklist", []),
        "status": "DRAFT",
    }
    data_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    html_text = render_deliverable(template, client, rows, followups, flags, summary,
                                   "DRAFT", generated_entry, estimate_minutes)
    output.write_text(html_text, encoding="utf-8")

    print(f"✅ Deliverable: {output}")
    print(f"   Payload:     {data_path}")
    print(f"   Review log:  {review_path}  (status: DRAFT)")
    print(f"   {len(rows)} doc(s) · {len(followups)} follow-up row(s) · {len(flags)} flag(s)"
          f" · {fmt_minutes(estimate_minutes)} manual drafting estimated")
    return 0


# ══════════════════════════════════════════════════════════════════════════════
# REVIEW LIFECYCLE — flip DRAFT -> REVIEWED, append-only log, re-render
# ══════════════════════════════════════════════════════════════════════════════

def review_deliverable(deliverable: Path, reviewer: str) -> int:
    """Mark a generated deliverable as human-reviewed and re-render it."""
    deliverable = deliverable.resolve()
    if not deliverable.exists():
        print(f"❌ Deliverable not found: {deliverable}", file=sys.stderr)
        return 1
    data_path = deliverable.with_suffix(".json")
    review_path = deliverable.with_suffix(".review.json")
    if not data_path.exists():
        print(f"❌ No payload sidecar ({data_path.name}) — can't re-render this deliverable.", file=sys.stderr)
        return 1
    if not review_path.exists():
        print(f"❌ No review log ({review_path.name}).", file=sys.stderr)
        return 1

    payload = json.loads(data_path.read_text(encoding="utf-8"))
    sidecar = json.loads(review_path.read_text(encoding="utf-8"))
    if sidecar.get("status") == "REVIEWED":
        print("ℹ️  Already REVIEWED — appending another approval entry.")
    entry = {"at": now_iso(), "action": "reviewed", "by": reviewer or "Human Reviewer"}
    sidecar.setdefault("entries", []).append(entry)
    sidecar["status"] = "REVIEWED"
    review_path.write_text(json.dumps(sidecar, indent=2), encoding="utf-8")

    # Keep the machine-readable payload in sync with the review status.
    payload["status"] = "REVIEWED"
    data_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    template = load_template(payload["template"])
    # Re-render with the review checklist snapshot from generation time, so an
    # edit to the template spec after generation cannot silently change the
    # checklist on the reviewed artifact.
    if payload.get("review_checklist"):
        template.setdefault("review", {})["checklist"] = payload["review_checklist"]
    html_text = render_deliverable(
        template, payload["client"], payload["rows"], payload["followups"],
        payload["flags"], payload["summary"], "REVIEWED", entry,
        payload.get("estimate_minutes", 0),
    )
    deliverable.write_text(html_text, encoding="utf-8")

    print(f"✅ {deliverable.name} marked REVIEWED by {reviewer or 'Human Reviewer'} ({pretty_date(now_iso())})")
    print(f"   Review log appended: {review_path}")
    return 0


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main() -> int:
    ap = argparse.ArgumentParser(description="BUH DNA Template Engine — narrow task, narrow output, reviewable.")
    ap.add_argument("--template", help="Template id (see --list)")
    ap.add_argument("--list", action="store_true", help="List available templates")
    ap.add_argument("--check", action="store_true", help="Validate all templates load")
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--dir", help="Local input directory (read-only)")
    src.add_argument("--vault", help="Vault path through msb-v3 bridge (e.g. 10_Customers/Pacur)")
    ap.add_argument("--client", default="Client", help="Client / business name")
    ap.add_argument("--secret", default=DEFAULT_SECRET, help="msb-v3 MCP bridge secret (vault mode)")
    ap.add_argument("--llm", action="store_true", help="Draft narrative via the live local model")
    ap.add_argument("--output", default=None, help="Output HTML path (default: ./<template>_<client>.html)")
    ap.add_argument("--review", metavar="FILE", help="Mark an existing deliverable as human-reviewed")
    ap.add_argument("--reviewer", default="", help="Who approved (for --review)")
    args = ap.parse_args()

    if args.list:
        templates = list_templates()
        if not templates:
            print(f"⚠️  No templates in {TEMPLATES_DIR}")
            return 0
        print(f"BUH DNA templates ({TEMPLATES_DIR}):")
        for tid in templates:
            spec = load_template(tid)
            print(f"  • {tid:28s} {spec['vertical']:14s} {spec['name']}")
        return 0

    if args.check:
        return check_templates()

    if args.review:
        return review_deliverable(Path(args.review), args.reviewer)

    if not args.template:
        ap.error("--template is required (or use --list / --check / --review)")
    if not args.dir and not args.vault:
        ap.error("one of --dir / --vault is required")

    output = Path(args.output or f"{args.template}_{slugify(args.client)}.html")
    return run_template(args.template, args.client,
                        Path(args.dir) if args.dir else None,
                        args.vault, args.secret, args.llm, output)


if __name__ == "__main__":
    raise SystemExit(main())
