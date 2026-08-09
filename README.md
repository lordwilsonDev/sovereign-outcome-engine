# Sovereign Outcome Engine

**We do not scout customers. We deliver outcomes. Every business that lets us look gets a deal.**

A read-only scan of a prospect's data directory that produces a one-page Sovereign Outcome Report:
Data Inventory → Exposure read → Data ROI Score → **an outcome deal, no matter what the score is**.

## Why it exists

The original plan framed a "Sovereign Data Audit" as a qualification funnel (pursue only scores ≥ 60).
That is scouting — a sales motion wearing a sovereignty costume. It's wrong for two reasons:

1. **We sell outcomes, not audits.** The report *is* the first outcome delivered. It must end in a deal, always.
2. **Information travels too fast.** Fox Valley is small; word moves at coffee-shop speed. A prospect
   who gets a report without a deal tells everyone. A prospect who gets a great deal tells everyone too.
   Choose which rumor you want.

## The deal (risk reversal, by default) — REAL pricing from the vault

Pulled from `BlackSwanLabz-Operating-Blueprint-v1.md` §2 / §26 (Founding Client Program):

- **$999 founding engagement** — first workflow deployed **free in 7 days**
- **$99/month × 6 months**, then **$199/month ongoing** (managed intelligence + automation service)
- **1 month free** — pay only if the value shows up
- **2x guarantee** — if we don't return twice the fee in value, next month is free
- **No surprise price increases** — founding rate locked in as the system matures
- **40% of co-op surplus returns to members** — including the prospect
- Normal target pricing once proven: **$5,000–$7,500+ per engagement**

## Usage

```bash
# Scan a LOCAL folder (synthetic demo, never real customer data)
python3 outcome_engine.py --dir ./sample_data --client "Ferree Movers" --industry logistics

# Scan a REAL vault path through the msb-v3 bridge (on-node, read-only)
python3 outcome_engine.py --vault 10_Customers/Pacur --client "Pacur" \
    --industry manufacturing --output pacur_report.html --llm

# Machine-readable output for pipelines
python3 outcome_engine.py --vault 10_Projects/BlackSwanLabz-Deal-Pipeline.md \
    --client "KEY Carrier" --industry logistics --llm --json
```

## Vault mode

`--vault <path>` scans through msb-v3's MCP bridge (`vault_list`/`vault_read` over `/mcp/proxy`)
instead of the local filesystem. The bridge itself rejects path traversal; the scanner caps at
2000 files. Bridge secret comes from `--secret` or `MCP_BRIDGE_SECRET` (defaults to the dev secret
already committed in `msb-v3/scripts/run.sh`).

## BUH DNA templates (Stage 7 — the delivery automations)

The plan's Stage-7 "BUH DNA template + node deployment" is now real: `buh_dna.py`
loads a YAML template spec from `buh_templates/`, ingests the client's documents
(local dir or vault via the bridge — read-only), extracts structured fields
**deterministically**, flags anything it can't vouch for (missing fields, sensitive
terms, demo emails), optionally drafts the narrative with the **local** model, and
renders a **reviewable** deliverable with an explicit human-review gate
(DRAFT → REVIEWED, append-only review log). Narrow task · narrow output · reviewable.

```bash
# Logistics beachhead — the "free in 7 days" first workflow
python3 buh_dna.py --template load_dispatch_summary --dir ./sample_data \
    --client "Ferree Movers" --output ferree_dispatch_summary.html --llm

# On-node, from a customer's vault folder
python3 buh_dna.py --template load_dispatch_summary --vault 10_Customers/<Name> \
    --client "<Name>" --secret <bridge-secret> --llm

# Approve a deliverable (human gate) — flips DRAFT -> REVIEWED and re-renders
python3 buh_dna.py --review ferree_dispatch_summary.html --reviewer "Dispatch Manager"
```

| Template | Vertical | Deliverable |
|---|---|---|
| `load_dispatch_summary` | logistics | one-page daily dispatch brief |
| `chart_note_drafting` | healthcare | SOAP chart-note draft |
| `privilege_log_draft` | legal | privilege-log entries |
| `sop_generation` | manufacturing | standard operating procedure draft |

Other commands: `--list` (show templates), `--check` (validate all specs). Every
run writes three files: the HTML deliverable, a `.json` payload (machine-readable),
and a `.review.json` log (append-only review lifecycle).

## Industry profiles (config at top of `outcome_engine.py`)

| Industry | Focus | First BUH DNA template |
|---|---|---|
| `logistics` | dispatch docs, customer comms, load paperwork | Load & Dispatch Summary |
| `healthcare` | chart notes, intake, referrals, prior-auth | Chart-Note Drafting |
| `legal` | privilege logs, memos, contract summaries | Privilege-Log Draft |
| `manufacturing` | SOPs, QC logs, shift handoffs, quotes | SOP Generation |

## Real-data findings (2026-08-08)

- Pacur (`10_Customers/Pacur`) is at **level_0_public_research** only — no write/read access granted
  yet, so the honest report reflects that (score reflects what's visible). The `client_control.yaml`
  schema (`progressive_access`, `$999_offer_extended`, decision thresholds) is exactly the consent
  front door the engine should respect: an audit must never escalate access on its own.
- The engine's pricing now matches the vault's Founding Client Program instead of a made-up flat fee.

## Safety

- **Read-only by construction** — the scanner never writes to, moves, or uploads prospect data.
- `sample_data/` is synthetic (placeholders, demo emails) — never put real customer data here.
- The exposure scan is a heuristic on readable text files only; the report says so, honestly.

Both safety claims are **enforced by the hygiene suite** (`s04_safety_contract`,
in `scripts/hygiene/`): a scan of `sample_data/` must leave every file
byte-identical (read-only verified by hash), and any email must use a
reserved `.example` TLD or a demo marker while any SSN-format number must be
explicitly flagged as a placeholder. The engineering-hygiene factory gate
(`~/.hermes/skills/engineering/engineering-hygiene-factory`) runs this
suite plus the project pytest (`tests/`) and reports PASS only when all
members and both safety invariants hold.

## Where this fits the stack

- msb-v3 (live at `:8766`) provides the local LLM for the optional summary paragraph.
- The report is the front door; the HaaSS node + BUH templates are the delivery.
- Next: wire the report generator to msb-v3's vault tools so the audit itself runs on-node.
