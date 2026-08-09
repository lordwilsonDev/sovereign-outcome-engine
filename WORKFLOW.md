# BLACKSWANLABZ — OPERATIONAL WORKFLOW (Stage 0–12)
**Executable by an AI agent using the `blackswanlabz-sovereign-engagement` skill + msb-v3.**

Each stage: **Do** → **Produce** → **Exit when**. Human gates marked 🔴.

---

## STAGE 0 — PROSPECT

**Do:**
- Source prospects from: `blackswanlabz-leads.csv`, `10_Projects/BlackSwanLabz-Fox-Valley-Target-List-v1.md`, `BlackSwanLabz-Deal-Pipeline.md`, or warm referrals.
- Score fit against the profile: *"lots of people + lots of handoffs + lots of communication + repetitive administrative work + measurable consequences when something gets missed."*
- Create the customer file scaffold if none exists:
  `10_Customers/<Name>/` with `client_control.yaml`, `decision_cards/`, `event_ledger/`, `outreach/`, `research/`.

**Produce:** customer file + EVT entry (type SYSTEM) in the event ledger.

**Exit when:** `client_control.yaml` exists with a client_id.

---

## STAGE 1 — RESEARCH (Level 0, public only)

**Do:**
- 12 research lanes: Customer Voice · Customer Acquisition · Customer Journey · Operations · Logistics/Supply Chain · Employees · Leadership · Technology/Automation · Reputation · Financial · Competitors · External.
- Gather only public evidence (website, LinkedIn, reviews, job postings, news). Record each item as OBSERVED / DOCUMENTED / DECLARED / INFERRED.

**Produce:** `research/` notes; EVT (type RESEARCH).

**Exit when:** ≥ 3 evidence lanes populated.

---

## STAGE 2 — INTELLIGENCE (the Outcome Report — automated)

**Do:**
- Run the outcome engine against the customer's vault folder (respecting consent):
  ```bash
  cd ~/sovereign-outcome-engine
  python3 outcome_engine.py --vault 10_Customers/<Name> --client "<Name>" \
      --industry <vertical> --output <Name>_report.html --llm
  ```
- The report contains: Data ROI Score (for *their* decision — not a filter), exposure read,
  addressable hours/value, and **the Founding Client Program deal. Always.**

**Produce:** `<Name>_report.html` + EVT (type RESEARCH/OUTREACH).

**Exit when:** report generated and reviewed by a human 🔴.

---

## STAGE 3 — VALIDATION (adversarial)

**Do:**
- Invert the opportunity: *"Why would this NOT work here?"* Check: data actually available? owner able to approve? culture ready? measured baseline possible?
- Use MoIE inversion logic (see `ail-moie-white-papers`).

**Produce:** validation notes in decision card `evidence` block.

**Exit when:** the opportunity survives its own inversion.

---

## STAGE 4 — BASELINE

**Do:**
- Measure current state: manual hours/week on the target workflow, error rate, cost of missed handoffs.
- Use the outcome engine's hours estimate as the starting figure, refine with the client's numbers.

**Produce:** baseline numbers in the decision card + EVT (type MEASUREMENT).

**Exit when:** baseline is a number, not a guess.

---

## STAGE 5 — DECISION (🔴 human gate)

**Do:**
- Fill the **decision card** (13 fields, from `BlackSwanLabz-Templates/decision-card-template.yaml`):
  evidence / impact / readiness / economics / risk → `opportunity_score` (max 25).
- **Advance only if score ≥ 15** (the `decision_threshold`).
- Present the outcome report + deal to the client. Founding Client Program offer.

**Produce:** decision card in `decision_cards/` + EVT (type DECISION).

**Exit when:** client says yes (or the opportunity is honestly archived).

---

## STAGE 6 — INTERVENTION

**Do:**
- Write the intervention spec: what gets automated, on which workflow, with what human review.
- Select the BUH DNA template (per vertical) as the starting shape.

**Produce:** intervention spec + EVT (type DECISION).

**Exit when:** client approves scope in writing.

---

## STAGE 7 — BUILD

**Do:**
- Build the automation on a sovereign node (msb-v3 runtime + BUH template):
  - e.g. logistics → Load & Dispatch Summary; healthcare → Chart-Note Drafting; legal → Privilege-Log Draft; manufacturing → SOP Generation.
- Run the concrete template engine (in `sovereign-outcome-engine/`):
  ```bash
  python3 buh_dna.py --template load_dispatch_summary --dir ./sample_data \
      --client "<Name>" --output <name>_dispatch_summary.html --llm
  # or on-node against the vault:
  python3 buh_dna.py --template load_dispatch_summary --vault 10_Customers/<Name> \
      --client "<Name>" --secret <bridge-secret> --llm
  ```
- The output is a **DRAFT** deliverable with a human-review checklist and a
  review gate (`buh_dna.py --review <file> --reviewer <name>` flips DRAFT → REVIEWED).
- Keep data on-node; never route client data to a third party.

**Produce:** working automation + EVT (type DEPLOYMENT).

**Exit when:** the template produces correct output on test data.

---

## STAGE 8 — VERIFICATION

**Do:**
- Run the automation against real (consented) data. Check accuracy, edge cases, and the human-review loop.
- Fix anything that fails. **Never present unverified output.**

**Produce:** verification results + EVT.

**Exit when:** output is correct and safe.

---

## STAGE 9 — DEPLOYMENT

**Do:**
- Put the automation live for the client's team. Train 1–2 staff. First month free per the deal.

**Produce:** live deployment + EVT (type DEPLOYMENT).

**Exit when:** the client's team is using it daily.

---

## STAGE 10 — MEASUREMENT

**Do:**
- Measure verified hours saved vs baseline. Quarterly.
- If we didn't return 2x the fee in value → next month free (the guarantee, honored).

**Produce:** measurement report + EVT (type MEASUREMENT).

**Exit when:** verified numbers exist for at least 1 quarter.

---

## STAGE 11 — CONTINUOUS OPERATIONS

**Do:**
- Monitor for the *next* opportunity (the recurring intelligence service, $99→$199/mo).
- Invite the client to join the Fox Valley AI Cooperative (profit-share 40% to members).
- Log everything in the event ledger — append-only, one entry per event.

**Produce:** monthly intelligence brief + EVT.

**Exit when:** client is a co-op member OR the account is honestly archived.

---

## STAGE 12 — RENEWAL / EXPANSION

**Do:**
- Annual renewal at agreed pricing (no surprise increases). Expand to adjacent workflows.
- Collect referrals (great deals travel).

**Produce:** renewal + EVT.

**Exit when:** renewed or gracefully exited.

---

## DATA FLOW SUMMARY

```
client_control.yaml (consent) 
   → outcome_engine.py --vault (read-only scan via msb-v3 bridge)
   → <Name>_report.html (the deal, always)
   → decision_cards/<ID>.yaml (13 fields, ≥15 to advance)
   → event_ledger/event-ledger.yaml (EVT-###, append-only)
   → outreach/ (the delivered report + follow-ups)
```

## NON-NEGOTIABLES

1. Consent levels from `client_control.yaml` are never escalated by automation.
2. No threshold hides the deal: every report ends in an offer.
3. Guarantees come from measurement, never invention.
4. Client data never leaves the node/vault.
5. The event ledger is the single source of truth — if it isn't logged, it didn't happen.
