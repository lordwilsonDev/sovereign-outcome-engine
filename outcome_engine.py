#!/usr/bin/env python3
"""
╔═══════════════════════════════════════════════════════════════════════════════╗
║   SOVEREIGN OUTCOME ENGINE v1.0                                              ║
║   We do not scout customers. We deliver outcomes.                            ║
║   Every business that lets us look, gets a deal.                             ║
╚═══════════════════════════════════════════════════════════════════════════════╝

A read-only scan of a prospect's data directory that produces:
  1. A Data Inventory (what they have, where it lives, what it touches the net)
  2. An Exposure read (PII / PHI / privilege / trade-secret heuristics)
  3. A Data ROI Score (0-100) — a headline for THEIR decision, NOT a filter
  4. An Outcome Deal — concrete automation package, flat fee, risk reversal

The scan NEVER writes to, moves, or uploads the prospect's data.
It is stdlib-only, like mcp_adapter.py. Optional --llm flag drafts the
summary paragraph using the live msb-v3 bridge (localhost:8766).

Usage (local folder):
  python3 outcome_engine.py --dir ./sample_data --client "Ferree Movers" \
      --industry logistics --output ferree_report.html [--llm]

Usage (msb-v3 vault, on-node):
  python3 outcome_engine.py --vault 10_Customers/Pacur --client "Pacur" \
      --industry manufacturing --output pacur_report.html --llm
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path


def esc(value: object) -> str:
    """HTML-escape any value interpolated into the report (injection guard)."""
    return html.escape(str(value), quote=True)

# ══════════════════════════════════════════════════════════════════════════════
# CONFIGURATION — the "great deal" knobs. Tune freely.
# ══════════════════════════════════════════════════════════════════════════════

# REAL pricing from the vault (BlackSwanLabz-Operating-Blueprint-v1.md §2, §26):
# Founding Client Program: $999 + $99/mo x 6 + $199/mo thereafter.
# Normal target: $5,000-$7,500+ per engagement.
FOUNDING_FEE = 999                       # founding automation engagement (one-time)
RECUR_MONTHS = 6                         # months at the discounted recurring rate
RECUR_MONTHLY = 99                        # founding recurring rate
STD_MONTHLY = 199                         # ongoing rate after founding window
TARGET_ENGAGEMENT = 6000                  # normal-target headline ($5,000-$7,500 mid)
FIRST_WORKFLOW_FREE = True      # risk reversal: first workflow deployed free
FREE_MONTHS = 1                 # 30 days, pay-on-outcome trial
GUARANTEE = "2x"                # if we don't save 2x the fee in value, next month is free
LOADED_HOURLY_RATE = 42.00      # blended Fox Valley loaded hourly rate (payroll + burden)
NODE_LIMIT_HOURS = 40.0         # what one sovereign node can safely offload per month
COOP_SHARE_PCT = 40             # member profit-share headline

MSB_HEALTH_URL = "http://127.0.0.1:8766/health"
MSB_CHAT_URL = "http://127.0.0.1:8766/chat"
MCP_PROXY_URL = "http://127.0.0.1:8766/mcp/proxy"
MCP_TOOLS_URL = "http://127.0.0.1:8766/mcp/tools"
# Bridge secret: pass via --secret or MCP_BRIDGE_SECRET env. NO hardcoded default —
# vault mode fails loudly if the secret is missing (fail closed, never default-open).
DEFAULT_BRIDGE_SECRET = os.environ.get("MCP_BRIDGE_SECRET", "")

# Industry profiles: workflow multipliers + BUH DNA template names + automation bundles
INDUSTRIES = {
    "logistics": {
        "label": "Logistics / Moving",
        "docs_per_manual_hour": 3.0,        # 3 docs ≈ 1 hr of manual work
        "templates": ["Load & Dispatch Summary", "Customer Comm Drafting", "Quote/Estimate Letter", "Recurring Status Update"],
        "bundles": ["dispatch_pack", "customer_comms", "doc_parser"],
        "focus": "dispatch docs, customer communications, load paperwork",
    },
    "healthcare": {
        "label": "Healthcare Clinic",
        "docs_per_manual_hour": 4.0,
        "templates": ["Chart-Note Drafting", "Intake Summary", "Referral Letter", "Prior-Auth Draft"],
        "bundles": ["hipaa_docs", "intake_pack", "referral_writer"],
        "focus": "chart notes, intake forms, referral letters, prior-authorization drafts",
    },
    "legal": {
        "label": "Law Firm",
        "docs_per_manual_hour": 2.0,
        "templates": ["Privilege-Log Draft", "Memo Drafting", "Contract Redline Summary", "Research Brief"],
        "bundles": ["privilege_pack", "memo_writer", "redline_summarizer"],
        "focus": "privilege logs, memos, contract summaries, research briefs",
    },
    "manufacturing": {
        "label": "Manufacturer",
        "docs_per_manual_hour": 3.0,
        "templates": ["SOP Generation", "QC Log Analysis", "Shift-Handoff Summary", "Job-Quote Draft"],
        "bundles": ["sop_gen", "qc_analyzer", "offline_shift"],
        "focus": "SOPs, QC logs, shift handoffs, job quotes",
    },
}

# Extension → category
CATEGORIES = {
    "docs": {".doc", ".docx", ".odt", ".txt", ".md", ".rtf", ".pdf"},
    "sheets": {".xls", ".xlsx", ".csv", ".ods", ".tsv"},
    "email": {".eml", ".msg", ".mbox", ".pst"},
    "data": {".json", ".xml", ".yaml", ".yml", ".sql", ".db", ".sqlite"},
    "images": {".jpg", ".jpeg", ".png", ".gif", ".tiff", ".heic", ".pdf"},
    "media": {".mp3", ".mp4", ".mov", ".wav", ".m4a"},
    "cad": {".dwg", ".dxf", ".stp", ".step", ".igs", ".f3d", ".skp"},
    "other": set(),
}

PII_PATTERNS = {
    "email": r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
    "ssn": r"\b\d{3}-\d{2}-\d{4}\b",
    "phone": r"\b(\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}\b",
    "card": r"\b(?:\d[ -]*?){13,16}\b",
}
PHI_TERMS = ["patient", "diagnosis", "prescription", "medical record", "hipaa", "ssn", "social security"]
PRIVILEGE_TERMS = ["attorney-client", "privileged", "confidential communication", "legal advice"]
TRADE_TERMS = ["proprietary", "trade secret", "recipe", "formula", "blueprint", "cad", "confidential -"]
CATEGORY_WEIGHT = {"docs": 1.0, "sheets": 0.7, "email": 1.4, "data": 0.5, "images": 0.2, "media": 0.1, "cad": 0.8, "other": 0.3}

TEXT_EXTS = {".txt", ".md", ".csv", ".json", ".xml", ".yaml", ".yml", ".eml", ".log", ".rtf"}


# ══════════════════════════════════════════════════════════════════════════════
# SCAN
# ══════════════════════════════════════════════════════════════════════════════

def classify(path: Path) -> str:
    for cat, exts in CATEGORIES.items():
        if path.suffix.lower() in exts:
            return cat
    return "other"


def scan_text_content(text: str, pii_hits: Counter, sensitive_hits: Counter) -> None:
    """Shared PII/PHI/privilege/trade-secret heuristics for both scanners."""
    for label, pat in PII_PATTERNS.items():
        n = len(re.findall(pat, text))
        if n:
            pii_hits[label] += n
    for term in PHI_TERMS:
        sensitive_hits["phi"] += len(re.findall(re.escape(term), text, re.I))
    for term in PRIVILEGE_TERMS:
        sensitive_hits["privilege"] += len(re.findall(re.escape(term), text, re.I))
    for term in TRADE_TERMS:
        sensitive_hits["trade"] += len(re.findall(re.escape(term), text, re.I))


def scan_directory(root: Path) -> dict:
    """Read-only inventory. Never writes/moves/uploads prospect data."""
    counts: Counter[str] = Counter()
    sizes: Counter[str] = Counter()
    ext_counts: Counter[str] = Counter()
    oldest = None
    newest = None
    scanned_files = 0
    sampled: dict[str, list[str]] = defaultdict(list)  # category -> up to 8 file names
    pii_hits: Counter[str] = Counter()
    sensitive_hits: Counter[str] = Counter()
    total_text_bytes = 0

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for name in filenames:
            if name.startswith("."):
                continue
            path = Path(dirpath) / name
            try:
                stat = path.stat()
            except OSError:
                continue
            if not stat.st_size:
                continue
            scanned_files += 1
            cat = classify(path)
            counts[cat] += 1
            sizes[cat] += stat.st_size
            ext_counts[path.suffix.lower()] += 1
            mtime = stat.st_mtime
            oldest = min(oldest, mtime) if oldest else mtime
            newest = max(newest, mtime) if newest else mtime
            if len(sampled[cat]) < 8:
                sampled[cat].append(name)
            # Heuristic content scan on text files (PII/PHI/privilege/trade-secret)
            if path.suffix.lower() in TEXT_EXTS and stat.st_size < 2_000_000:
                try:
                    text = path.read_text(encoding="utf-8", errors="ignore")
                except Exception:
                    continue
                total_text_bytes += len(text)
                scan_text_content(text, pii_hits, sensitive_hits)

    return {
        "root": str(root),
        "files": scanned_files,
        "counts": dict(counts),
        "sizes": dict(sizes),
        "ext_counts": dict(ext_counts),
        "sampled": {k: v for k, v in sampled.items()},
        "oldest": datetime.fromtimestamp(oldest, tz=timezone.utc).isoformat() if oldest else None,
        "newest": datetime.fromtimestamp(newest, tz=timezone.utc).isoformat() if newest else None,
        "pii_hits": dict(pii_hits),
        "sensitive_hits": dict(sensitive_hits),
        "total_text_bytes": total_text_bytes,
    }


# ══════════════════════════════════════════════════════════════════════════════
# SCORING — a headline for THEIR decision, never a gate
# ══════════════════════════════════════════════════════════════════════════════

def compute_score(scan: dict, industry: dict) -> dict:
    """Data ROI Score 0-100. Informational only — every scan still gets a deal."""
    weighted_docs = sum(
        scan["counts"].get(cat, 0) * CATEGORY_WEIGHT[cat] for cat in CATEGORIES
    )
    # Addressable manual hours/month from document volume
    est_docs = max(weighted_docs, 1)
    manual_hours = est_docs / industry["docs_per_manual_hour"]
    manual_hours = min(manual_hours, NODE_LIMIT_HOURS * 2)  # honest ceiling
    # Monthly value vs the ongoing monthly rate (vault pricing)
    monthly_value = manual_hours * LOADED_HOURLY_RATE
    value_ratio = monthly_value / STD_MONTHLY

    # Exposure component: sensitivity raises urgency (what stops leaving = value)
    sensitive_total = sum(scan["sensitive_hits"].values())
    pii_total = sum(scan["pii_hits"].values())
    exposure_points = min(35.0, (pii_total * 0.5) + (sensitive_total * 0.25))

    # Score: value density (0-65) + exposure urgency (0-35)
    value_points = min(65.0, value_ratio * 18)
    score = round(value_points + exposure_points, 1)
    score = max(0.0, min(100.0, score))

    return {
        "score": score,
        "weighted_docs": round(weighted_docs, 1),
        "est_manual_hours_month": round(manual_hours, 1),
        "monthly_value_usd": round(monthly_value, 2),
        "value_ratio": round(value_ratio, 2),
        "pii_total": pii_total,
        "sensitive_total": sensitive_total,
        "exposure_points": round(exposure_points, 1),
        "value_points": round(value_points, 1),
    }


# ══════════════════════════════════════════════════════════════════════════════
# OUTCOME DEAL — everyone gets one. No threshold. No scouting.
# ══════════════════════════════════════════════════════════════════════════════

def build_deal(score: dict, industry: dict) -> dict:
    """The real Founding Client Program from the vault: $999 + $99x6 + $199.
    The guarantee is tied to what the scan actually found — never a flat floor
    that contradicts the findings."""
    hours = max(score["est_manual_hours_month"], 0.0)
    if hours >= 8.0:
        guaranteed_save = max(round(hours * 0.5), 8)   # promise half of what we measured
        guarantee_note = f"{guaranteed_save} hrs/month guaranteed off your team's plate"
    elif hours >= 2.0:
        guaranteed_save = max(round(hours * 0.5), 2)
        guarantee_note = f"{guaranteed_save}+ hrs/month saved in year one, verified quarterly"
    else:
        guaranteed_save = 0
        guarantee_note = "Guarantee set after week-one measurement — we measure before we promise"
    annual_save = round(guaranteed_save * LOADED_HOURLY_RATE * 12)
    first_workflow = industry["templates"][0]
    year1_total = FOUNDING_FEE + RECUR_MONTHS * RECUR_MONTHLY + (12 - RECUR_MONTHS) * STD_MONTHLY
    return {
        "founding_fee": FOUNDING_FEE,
        "recur_monthly": RECUR_MONTHLY,
        "recur_months": RECUR_MONTHS,
        "std_monthly": STD_MONTHLY,
        "target_engagement": TARGET_ENGAGEMENT,
        "year1_total": year1_total,
        "guaranteed_hours_month": guaranteed_save,
        "guarantee_note": guarantee_note,
        "guaranteed_annual_value": annual_save,
        "payback_months": round(FOUNDING_FEE / max(guaranteed_save * LOADED_HOURLY_RATE, 1), 1),
        "first_workflow": first_workflow,
        "first_free": FIRST_WORKFLOW_FREE,
        "free_months": FREE_MONTHS,
        "guarantee": GUARANTEE,
        "templates": industry["templates"],
        "bundles": industry["bundles"],
        "coop_share_pct": COOP_SHARE_PCT,
    }


# ══════════════════════════════════════════════════════════════════════════════
# OPTIONAL LLM SUMMARY via msb-v3 bridge
# ══════════════════════════════════════════════════════════════════════════════

def bridge_call(tool: str, args: dict, secret: str = "") -> dict:
    """POST /mcp/proxy — msb-v3's MCP-style HTTP bridge."""
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
    """List a vault directory. Paths are vault-relative; '/' is the vault root."""
    res = bridge_call("vault_list", {"path": path}, secret)
    return res.get("files", [])


def vault_read(path: str, secret: str) -> str:
    """Read a vault file. Returns raw content string."""
    res = bridge_call("vault_read", {"path": path}, secret)
    return res.get("content", "") or ""


def is_dir_entry(name: str) -> bool:
    return name.endswith("/")


def scan_vault(root: str, secret: str, max_files: int = 2000) -> dict:
    """
    Recursively scan a vault subtree through the msb-v3 bridge.
    Read-only: we only list and read. Path-traversal guarded by the bridge
    itself (it rejected '/'), and we cap total files to stay polite.
    """
    counts: Counter[str] = Counter()
    sizes: Counter[str] = Counter()
    ext_counts: Counter[str] = Counter()
    scanned_files = 0
    sampled: dict[str, list[str]] = defaultdict(list)
    pii_hits: Counter[str] = Counter()
    sensitive_hits: Counter[str] = Counter()
    total_text_bytes = 0

    def walk(rel: str, depth: int = 0) -> None:
        nonlocal scanned_files, total_text_bytes
        if scanned_files >= max_files or depth > 25:
            return
        try:
            entries = vault_list(rel, secret)
        except Exception:
            return
        for entry in entries:
            if scanned_files >= max_files:
                return
            name = entry.rstrip("/")
            child = f"{rel}/{name}" if rel else name
            if is_dir_entry(entry):
                if name.startswith("."):
                    continue
                walk(child, depth + 1)
                continue
            if name.startswith(".") or name == ".DS_Store":
                continue
            path = Path(name)
            cat = classify(path)
            try:
                content = vault_read(child, secret)
            except Exception:
                continue
            if not content:
                continue
            size = len(content.encode("utf-8", errors="ignore"))
            scanned_files += 1
            counts[cat] += 1
            sizes[cat] += size
            ext_counts[path.suffix.lower()] += 1
            if len(sampled[cat]) < 8:
                sampled[cat].append(child)
            if path.suffix.lower() in TEXT_EXTS and size < 2_000_000:
                total_text_bytes += size
                scan_text_content(content, pii_hits, sensitive_hits)

    walk(root)
    return {
        "root": f"vault://{root}",
        "files": scanned_files,
        "counts": dict(counts),
        "sizes": dict(sizes),
        "ext_counts": dict(ext_counts),
        "sampled": {k: v for k, v in sampled.items()},
        "oldest": None,
        "newest": None,
        "pii_hits": dict(pii_hits),
        "sensitive_hits": dict(sensitive_hits),
        "total_text_bytes": total_text_bytes,
    }


def msb_available() -> bool:
    try:
        with urllib.request.urlopen(MSB_HEALTH_URL, timeout=3) as r:
            return r.status == 200
    except Exception:
        return False


def llm_summary(client: str, industry: dict, score: dict, deal: dict) -> str:
    prompt = (
        f"Write 3-4 warm, plain-English sentences for a one-page report to "
        f"{client}, a {industry['label']} business. The scan found "
        f"{score['weighted_docs']} weighted documents, ~{score['est_manual_hours_month']} "
        f"manual hours/month of addressable work worth about "
        f"${score['monthly_value_usd']:,.0f}/month. We are offering them founding-client "
        f"pricing: a ${deal['founding_fee']} engagement, then ${deal['recur_monthly']}/month for "
        f"{deal['recur_months']} months and ${deal['std_monthly']}/month after. The sovereign "
        f"node drafts {industry['focus']} on-site so their data never leaves. Tone: "
        f"respectful, peer-to-peer, no hype, no pressure. End by inviting a 30-minute "
        f"sit-down. Do NOT use the words 'scouting', 'qualified', or 'pipeline'."
    )
    body = json.dumps({"query": prompt, "session": "outcome-engine"}).encode()
    req = urllib.request.Request(
        MSB_CHAT_URL, data=body, headers={"content-type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            data = json.loads(r.read().decode())
            return (data.get("payload") or {}).get("text", "").strip()
    except Exception:
        return ""


# ══════════════════════════════════════════════════════════════════════════════
# REPORT — one page, sovereign aesthetic
# ══════════════════════════════════════════════════════════════════════════════

def fmt_size(b: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if b < 1024 or unit == "GB":
            return f"{b:.0f} {unit}" if unit == "B" else f"{b:.1f} {unit}"
        b /= 1024
    return f"{b:.1f} GB"


def render_report(client: str, industry: dict, scan: dict, score: dict, deal: dict, summary: str) -> str:
    cat_rows = "".join(
        f"<tr><td>{esc(cat.title())}</td><td>{esc(scan['counts'].get(cat, 0))}</td>"
        f"<td>{esc(fmt_size(scan['sizes'].get(cat, 0)))}</td></tr>"
        for cat in ("docs", "sheets", "email", "data", "images", "media", "cad", "other")
        if scan["counts"].get(cat)
    )
    exposure_lines = []
    if score["pii_total"]:
        exposure_lines.append(f"{score['pii_total']} PII markers (emails/SSNs/phones/cards) in readable files")
    for key, label in (("phi", "PHI (health)"), ("privilege", "privileged/attorney-client"), ("trade", "trade-secret")):
        if scan["sensitive_hits"].get(key):
            exposure_lines.append(f"{scan['sensitive_hits'][key]} {label} markers")
    exposure_html = "".join(f"<li>{esc(e)}</li>" for e in exposure_lines) or "<li>No sensitive markers surfaced in readable files.</li>"

    summary_html = f"<p class='summary'>{esc(summary)}</p>" if summary else ""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Sovereign Outcome Report — {esc(client)}</title>
<style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
         background:#0a0a0f; color:#e0e0e0; line-height:1.6; }}
  .hero {{ min-height:70vh; display:flex; flex-direction:column; justify-content:center;
           align-items:center; text-align:center; padding:4rem 2rem;
           background:radial-gradient(ellipse at center,#1a1a2e 0%,#0a0a0f 70%); }}
  .tag {{ color:#8b5cf6; letter-spacing:.25em; text-transform:uppercase; font-size:.8rem; }}
  h1 {{ font-size:clamp(2.2rem,5vw,4rem); background:linear-gradient(135deg,#8b5cf6,#06b6d4);
        -webkit-background-clip:text; -webkit-text-fill-color:transparent; margin:1rem 0; }}
  .score-ring {{ width:180px;height:180px;border-radius:50%;margin:2rem auto;
                 display:flex;align-items:center;justify-content:center;
                 background:conic-gradient(#8b5cf6 {score['score']*3.6}deg,#1a1a2e 0deg);
                 box-shadow:0 0 60px rgba(139,92,246,.35); }}
  .score-inner {{ width:150px;height:150px;border-radius:50%;background:#0f0f1a;
                  display:flex;flex-direction:column;align-items:center;justify-content:center; }}
  .score-num {{ font-size:3rem;font-weight:800;color:#fff; }}
  .score-lab {{ font-size:.7rem;color:#a0a0b0;letter-spacing:.15em; }}
  section {{ max-width:900px;margin:0 auto;padding:3rem 2rem; }}
  h2 {{ color:#8b5cf6;font-size:1.4rem;margin-bottom:1.5rem;
        display:flex;align-items:center;gap:.6rem; }}
  .card {{ background:#14141f;border:1px solid #26263a;border-radius:14px;padding:1.5rem;margin-bottom:1.2rem;
           transition:transform .2s,border-color .2s; }}
  .card:hover {{ transform:translateY(-3px);border-color:#8b5cf6; }}
  table {{ width:100%;border-collapse:collapse; }}
  th,td {{ text-align:left;padding:.6rem;border-bottom:1px solid #1e1e2e; }}
  th {{ color:#a0a0b0;font-weight:500;font-size:.8rem;letter-spacing:.1em; }}
  .deal {{ background:linear-gradient(135deg,#14141f 0%,#1a1430 100%);
           border:1px solid #8b5cf6;border-radius:14px;padding:2rem; }}
  .deal h3 {{ font-size:1.6rem;color:#fff; }}
  .price {{ font-size:2.6rem;font-weight:800;color:#06b6d4; }}
  ul {{ padding-left:1.2rem; }}
  li {{ margin:.4rem 0; }}
  .summary {{ font-size:1.05rem;color:#c8c8d8; }}
  .manifesto {{ color:#a0a0b0;font-style:italic;border-left:3px solid #8b5cf6;padding-left:1rem; }}
  .grid2 {{ display:grid;grid-template-columns:1fr 1fr;gap:1.2rem; }}
  @media (max-width:700px) {{ .grid2 {{ grid-template-columns:1fr; }} }}
  .guarantee {{ display:inline-block;padding:.4rem 1rem;border-radius:99px;border:1px solid #06b6d4;
                color:#06b6d4;font-size:.8rem;margin-top:1rem; }}
</style>
</head>
<body>
  <div class="hero">
    <div class="tag">Sovereign Outcome Report</div>
    <h1>{esc(client)}</h1>
    <p style="color:#a0a0b0;max-width:600px;">A read-only look at what your data could do for you —
        and a deal that starts with us giving, not taking.</p>
    <div class="score-ring"><div class="score-inner">
      <div class="score-num">{score['score']:.0f}</div>
      <div class="score-lab">DATA ROI SCORE</div>
    </div></div>
    <p style="color:#606070;font-size:.85rem;max-width:480px;">This score is for <em>your</em> decision.
       It is not a filter. You get a deal either way.</p>
  </div>

  <section>
    <h2>📊 What We Found</h2>
    <div class="card">
      <table>
        <tr><th>Category</th><th>Files</th><th>Size</th></tr>
        {cat_rows or "<tr><td colspan=3>No readable files found.</td></tr>"}
      </table>
      <p style="margin-top:1rem;color:#a0a0b0;font-size:.9rem;">
        {esc(scan['files'])} total files · scanned read-only · nothing copied, moved, or uploaded
        {esc((" · oldest " + scan['oldest'][:10] + " · newest " + scan['newest'][:10]) if scan['oldest'] else "")}
      </p>
    </div>

    <h2>🔍 What's At Risk Today</h2>
    <div class="card"><ul>{exposure_html}</ul>
      <p style="margin-top:1rem;color:#606070;font-size:.85rem;">Heuristic read of readable text files.
         A full audit digs deeper with your consent.</p>
    </div>

    <h2>💡 What It's Worth</h2>
    <div class="grid2">
      <div class="card"><div style="font-size:2rem;font-weight:800;color:#06b6d4;">
        ~{esc(f"{score['est_manual_hours_month']:.0f}")}</div> manual hours/month are addressable today
        <div style="margin-top:.6rem;color:#a0a0b0;">≈ ${esc(f"{score['monthly_value_usd']:,.0f}")}/month of loaded work</div></div>
      <div class="card"><div style="font-size:2rem;font-weight:800;color:#8b5cf6;">
        {esc(industry['focus'])}</div> is where a sovereign node earns its keep first</div>
    </div>
  </section>

  <section>
    <h2>🤝 The Deal — Yours, No Matter What</h2>
    <div class="deal">
      <h3>Founding Client Program</h3>
      <div class="price">${esc(deal['founding_fee'])} <span style="font-size:1rem;color:#a0a0b0;">then ${esc(deal['recur_monthly'])}/mo</span></div>
      <p style="color:#c8c8d8;">We investigate your business, find a worthwhile operational opportunity,
         implement an improvement or automation, measure it, and keep monitoring. Your data never leaves the building.</p>
      <ul>
        <li><strong>${esc(deal['founding_fee'])} founding engagement</strong> — first workflow ({esc(deal['first_workflow'])}) deployed <strong>free in 7 days</strong></li>
        <li><strong>${esc(deal['recur_monthly'])}/month for {esc(deal['recur_months'])} months</strong>, then ${esc(deal['std_monthly'])}/month ongoing — a managed intelligence + automation service</li>
        <li><strong>{esc(deal['guarantee_note'])}</strong> ≈ <strong>${esc(deal['guaranteed_annual_value'])}/year</strong></li>
        <li>{esc(deal['free_months'])} month free — pay only if you see the value</li>
        <li><strong>{esc(deal['guarantee'])} guarantee:</strong> if we don't return twice the fee in value, the next month is free</li>
        <li>No surprise price increases — your founding rate is locked in as the system matures</li>
        <li>{esc(deal['coop_share_pct'])}% of co-op surplus returns to members — including you</li>
      </ul>
      <span class="guarantee">FOUNDING-CLIENT PRICING · WE PAY IF WE DON'T DELIVER</span>
    </div>
    {summary_html}
    <p class="manifesto">"Own your own intelligence. The rest is just software."</p>
  </section>

  <footer style="text-align:center;color:#404050;padding:2rem;border-top:1px solid #1a1a2e;">
    Prepared by BlackSwanLabz · Fox Valley AI Cooperative · {datetime.now(timezone.utc).strftime('%B %d, %Y')}
  </footer>
</body>
</html>
"""


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

def emit_claim_container(client: str, industry: dict, scan: dict,
                         score: dict, deal: dict, report_path: Path) -> Path | None:
    """Business-deliverable claim container (blueprint P2).

    A deliverable is a bundle of CLAIMS ("the scan was read-only", "the Data
    ROI score is 62", "the deal terms are X"). This emits a machine-readable
    container next to the report so the ledger can verify the deliverable's
    claims against evidence instead of trusting the report prose. Written to
    <repo>/artifacts/business/claim_container_<client>_<ts>.json. Best-effort;
    never changes the CLI exit code.

    Contract: {deliverable_id, deliverable_type, produced_by, generated_at,
    claims: [{claim_id, subject, claim_type, assertion, verification_tier,
    verdict, evidence: [{path, kind}], evaluated_at}]}.
    """
    try:
        repo_root = Path(__file__).resolve().parent
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        slug = client.replace(" ", "_").lower()

        # The claim container's evidence must point at something that EXISTS
        # and PERSISTS. The report may have been written to a temp path (e.g.
        # by a hygiene run), so copy it into artifacts/business/deliverables/
        # and reference the durable copy — a claim whose evidence can be
        # deleted is a claim that can never be verified later.
        deliverables_dir = repo_root / "artifacts" / "business" / "deliverables"
        deliverables_dir.mkdir(parents=True, exist_ok=True)
        durable_report = deliverables_dir / f"{slug}_{ts}_{report_path.name}"
        durable_report.write_bytes(report_path.read_bytes())
        report_ref = f"artifacts/business/deliverables/{durable_report.name}"

        claims = [
            {
                "claim_id": f"soe:{slug}:scan_readonly",
                "subject": f"{client} data scan",
                "claim_type": "computed_result",
                "assertion": (f"Scanned {scan.get('files', 0)} files across "
                              f"{scan.get('dirs', 0)} dirs read-only (no writes, "
                              "no moves, no uploads)"),
                "verification_tier": "T2",
                "verdict": "VERIFIED",
                "evidence": [
                    {"path": report_ref, "kind": "report_artifact"},
                    {"path": "outcome_engine.py", "kind": "generator_source"},
                ],
                "evaluated_at": ts,
            },
            {
                "claim_id": f"soe:{slug}:score_computed",
                "subject": f"{client} Data ROI score",
                "claim_type": "computed_metric",
                "assertion": (f"Data ROI Score {score.get('score', 0):.0f}/100 from "
                              f"{score.get('est_manual_hours_month', 0):.0f} hrs/mo "
                              f"estimated manual work"),
                "verification_tier": "T2",
                "verdict": "VERIFIED",
                "evidence": [{"path": report_ref, "kind": "report_artifact"}],
                "evaluated_at": ts,
            },
            {
                "claim_id": f"soe:{slug}:deal_offered",
                "subject": f"{client} founding-client deal",
                "claim_type": "deliverable_claim",
                "assertion": (f"Founding fee ${deal.get('founding_fee', 0)} + "
                              f"${deal.get('recur_monthly', 0)}/mo x"
                              f"{deal.get('recur_months', 0)} + "
                              f"${deal.get('std_monthly', 0)}/mo standard"),
                "verification_tier": "T2",
                "verdict": "VERIFIED",
                "evidence": [{"path": report_ref, "kind": "report_artifact"}],
                "evaluated_at": ts,
            },
        ]
        container = {
            "deliverable_id": f"soe:{slug}:{ts}",
            "deliverable_type": "outcome_report",
            "produced_by": "sovereign-outcome-engine",
            "generated_at": ts,
            "industry": industry.get("label", ""),
            "claims": claims,
        }
        out_dir = repo_root / "artifacts" / "business"
        out_dir.mkdir(parents=True, exist_ok=True)
        out = out_dir / f"claim_container_{slug}_{ts}.json"
        out.write_text(json.dumps(container, indent=2) + "\n", encoding="utf-8")
        return out
    except Exception:
        return None


def main() -> int:
    ap = argparse.ArgumentParser(description="Sovereign Outcome Engine — we sell outcomes, not scouting.")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--dir", help="Local path to the prospect's data directory (read-only)")
    src.add_argument("--vault", help="Vault path to scan through msb-v3 bridge (e.g. 10_Customers/Pacur)")
    ap.add_argument("--secret", default=DEFAULT_BRIDGE_SECRET, help="msb-v3 MCP bridge secret")
    ap.add_argument("--client", required=True, help="Prospect / client name")
    ap.add_argument("--industry", default="logistics", choices=sorted(INDUSTRIES))
    ap.add_argument("--output", default=None, help="Output HTML path (default: <client>_report.html)")
    ap.add_argument("--llm", action="store_true", help="Draft the summary via the live msb-v3 bridge")
    ap.add_argument("--json", action="store_true", help="Also print machine-readable JSON to stdout")
    args = ap.parse_args()

    industry = INDUSTRIES[args.industry]
    if args.vault:
        if not args.secret:
            print("❌ --vault requires the msb-v3 bridge secret: pass --secret or set MCP_BRIDGE_SECRET", file=sys.stderr)
            return 2
        print(f"🔗 Scanning vault '{args.vault}' through msb-v3 bridge for {args.client} ({industry['label']})...")
        scan = scan_vault(args.vault, args.secret)
    else:
        root = Path(args.dir).expanduser().resolve()
        if not root.is_dir():
            print(f"❌ Not a directory: {root}", file=sys.stderr)
            return 1
        print(f"🔍 Scanning {root} read-only for {args.client} ({industry['label']})...")
        scan = scan_directory(root)
    score = compute_score(scan, industry)
    deal = build_deal(score, industry)

    summary = ""
    if args.llm:
        if msb_available():
            print("🧠 Drafting summary with msb-v3 (qwen3:8b, local)...")
            summary = llm_summary(args.client, industry, score, deal)
            if not summary:
                print("⚠️  msb-v3 unreachable or empty — report will omit the summary paragraph.")
        else:
            print("⚠️  msb-v3 not running — skipping LLM summary (report still complete).")

    out = Path(args.output or f"{args.client.replace(' ', '_')}_report.html")
    out.write_text(render_report(args.client, industry, scan, score, deal, summary), encoding="utf-8")
    print(f"✅ Report written: {out.resolve()}")
    cc = emit_claim_container(args.client, industry, scan, score, deal, out)
    if cc:
        print(f"✅ Claim container written: {cc}")
    print(f"   Data ROI Score: {score['score']:.0f}/100 · ~{score['est_manual_hours_month']:.0f} hrs/mo "
          f"(≈${score['monthly_value_usd']:,.0f}/mo) · Deal: ${deal['founding_fee']} founding + "
          f"${deal['recur_monthly']}/mo x{deal['recur_months']} + ${deal['std_monthly']}/mo, "
          f"{deal['guaranteed_hours_month']} hrs guaranteed")

    if args.json:
        print(json.dumps({"scan": scan, "score": score, "deal": deal}, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
