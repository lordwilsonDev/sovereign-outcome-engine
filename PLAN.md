# BLACKSWANLABZ — END-TO-END MASTER PLAN (REV 3)
**The complete operating plan: from prospect to co-op owner, fully automated where possible.**

> **One sentence:** BlackSwanLabz finds operational opportunities using public and client-provided
> evidence, validates them adversarially, builds approved automations on the client's own sovereign
> node, measures the result, and continuously monitors — all so the client *owns their own intelligence*.

---

## 0. GOVERNING PRINCIPLE (non-negotiable)

> **We are not scouting customers. Information travels too fast. We have to offer great deals. We sell outcomes.**

Operational rules derived from it:
1. **No qualification gates.** Every business that lets us look gets a report and a deal — always.
2. **Consent is the floor, not the ceiling.** Access levels (from `client_control.yaml`) are never
   escalated by us. Level 0 = public research only; the system stops there until the client says otherwise.
3. **Risk reversal is the brand.** First workflow free in 7 days · 1 month free · 2x-or-free guarantee ·
   no surprise price increases · founding rate locked in.
4. **Honesty over hype.** Guarantees are set from measured findings, never invented ("we measure before we promise").

---

## 1. THE STACK (what actually exists, verified 2026-08-08)

| Layer | Tool | Status |
|---|---|---|
| Local AI runtime | **msb-v3** (`:8766`, qwen3:8b via Ollama, FastAPI+SQLite+Prometheus) | ✅ LIVE |
| Vault (knowledge + customer files) | `~/Documents/Vault` via msb-v3 bridge (`/mcp/proxy`, 26 tools) | ✅ LIVE |
| Audit/report engine | `sovereign-outcome-engine/outcome_engine.py` (`--vault` mode) | ✅ BUILT |
| Outreach/video | BlackSwanLabz `studio` CLI (CapCut draft JSON injection) | ✅ BUILT |
| Orchestration skill | this skill (`blackswanlabz-sovereign-engagement`) | ✅ BUILT |

---

## 2. THE SEVEN FIXES (from MoIE analysis) → WHERE THEY LAND

| # | Fix | Where it lands |
|---|---|---|
| 1 | HaaSS model | Founding Client Program pricing (`$999 + $99x6 + $199`), hardware owned by BSL |
| 2 | Mesh governance / co-op | Fox Valley AI Cooperative charter (drafted, ratified at node #8) |
| 3 | Vertical-first GTM | Logistics beachhead now; healthcare/legal/manufacturing packages via BUH DNA templates |
| 4 | Sovereign Data Audit → **Outcome Report** | `outcome_engine.py` — report ends in a deal, always |
| 5 | Mesh threshold + bridge node | Mac Studio bridge for first 10–20 clients; mesh at 8–12 nodes |
| 6 | Alternative funding | WEDC grants → CU SBA hardware financing → Tundra Angels → community round |
| 7 | Cultural reframe | "Own your own intelligence" + Sovereign Manifesto (in every report) |

---

## 3. THE 13-STAGE LIFECYCLE (from Master SOP v1)

```
Stage 0  Prospect    — who, from Target List v1 / leads CSV / referrals
Stage 1  Research    — Level 0 public research (12 lanes)
Stage 2  Intelligence— Company DNA file + outcome report (this engine)
Stage 3  Validation  — adversarial check of the opportunity
Stage 4  Baseline    — measure current state (hours, errors, cost)
Stage 5  Decision    — decision card ≥ 15/25 gate → client signs
Stage 6  Intervention— agreed automation/intervention
Stage 7  Build       — BUH DNA template + node deployment
Stage 8  Verification— works, reviewed, safe
Stage 9  Deployment  — live on the client's sovereign node
Stage 10 Measurement — verified time saved, quarterly
Stage 11 Continuous  — monitoring, next opportunity, co-op membership
Stage 12 Renewal     — expansion, referrals, profit-share
```

**The workflow file (`WORKFLOW.md`) operationalizes each stage with concrete actions, tools, and exit criteria.**
**The skill (`~/.agents/skills/blackswanlabz-sovereign-engagement/`) makes an AI agent able to execute Stages 0–5 fully, and Stages 6–12 with human gates.**

---

## 4. UNIT ECONOMICS (Founding Client Program — from the vault)

| Item | Value |
|---|---|
| Founding engagement | **$999** (first workflow live in 7 days) |
| Months 1–6 | **$99/month** |
| Ongoing | **$199/month** |
| Normal target (proven) | **$5,000–$7,500+** per engagement |
| Year-1 total per founding client | $999 + 6×$99 + 6×$199 = **$2,787** |
| 36-month per-client revenue | $999 + 6×$99 + 30×$199 = **$7,533** |
| Co-op surplus share | 40% to members · 30% reinvest · 20% BSL steward · 10% community |

**Year-1 targets (sanity):**
- 5 founding clients × $2,787 = **$13,935** (at founding pricing)
- 3 converts to normal pricing in year 2 → **$7,164/yr recurring**
- Break-even on bridge node (Mac Studio ~$4K) at client #3.

---

## 5. FUNDING PATH (sovereign-aligned)

1. **WEDC** grants (≤$4,500, non-dilutive) → fund engine + first bridge node
2. **Credit unions** (Fox Communities, Verve) → SBA 7(a)/504 financing on the hardware fleet
3. **Tundra Angels** ($100–500K) → strategic round at proof, not promise
4. **Community round** → clients become co-op shareholders (year 2)
5. **YC rejected** — its incentives contradict the sovereignty mission.

---

## 6. METRICS OF SUCCESS (weekly dashboard)

| Metric | Target |
|---|---|
| Outcome reports delivered | ≥ 3/week |
| Reports that become meetings | ≥ 50% |
| Meetings that become founding clients | ≥ 1/week |
| Founding clients to live node | ≤ 14 days from signature |
| Guarantee payouts (should be rare) | 0/month target |
| Verified hours saved (cumulative, all clients) | ≥ 40 hrs by week 8 |

---

## 7. THE 7-DAY LAUNCH SEQUENCE

| Day | Action |
|---|---|
| 1–2 | Run this skill end-to-end on **Pacur** (Stage 0–5 proof) — done 2026-08-08 |
| 3 | Deliver Pacur outcome report + Founding deal in person |
| 4 | Offer report to 1 logistics lead from pipeline (KEY Carrier / Ferree) — **customer file scaffolded for Ferree 2026-08-08**: client_control.yaml (L0 consent), Level-0 research worksheet, outcome report, decision card, event ledger (EVT-001/002). Research **flagged a lead-identity discrepancy**: public Ferree Movers = Schererville IN (est. 1929), which matches the pipeline's own "Chicagoland" note — the Fox Valley framing in REV 2/REV 3 needs correction. Human gate: verify before outreach. |
| 5 | If accepted: deploy first BUH DNA template (Load & Dispatch Summary) free — **BUH DNA engine built + demo-verified 2026-08-08** (`buh_dna.py` + 4 vertical templates; Ferree dispatch summary demo generated with local LLM, DRAFT→REVIEWED lifecycle working) |
| 6–7 | Draft co-op charter + open WEDC application; measure |

**Correction needed (REV 4):** the pipeline's warm leads are Gary/Chicagoland trucking & logistics
(KEY Carrier, Utlc, Ferree, Cargomaxx, Craters & Freighters) per `BlackSwanLabz-Deal-Pipeline.md`,
not Fox Valley. The vertical-first beachhead (logistics) still holds; the geography in REV 2/REV 3
should say "Chicagoland/Gary logistics" until Fox Valley leads are sourced separately.

---

*Author: Lord Wilson × BlackSwanLabz. Plan REV 3, 2026-08-08. Supersedes REV 2.*
