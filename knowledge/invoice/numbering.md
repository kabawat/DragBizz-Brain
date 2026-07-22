---
module: invoice
feature: numbering
version: 1
language: en
updated_at: 2026-07-22
status: shipped
---

# Invoice Number Formats

## Overview

Invoice numbers are generated automatically from a configurable format template. The number is assigned when the invoice (or credit note) is created. Formats are chosen in **Settings → Invoice Number** from a catalog of templates; a live preview shows the next number without consuming it.

## Workflow

1. Open Settings (`/dashboard/settings`) → **Invoice Number** tab.
2. Browse the available format cards — each shows a name, description, example, and pattern. The current format is badged.
3. The **Next invoice number** preview updates live (previewing does not consume a sequence number).
4. Click **Save format** to apply the selected template to your store.

## Business rules

- Available placeholders: `{TYPE}` (INV for regular, CRN for credit notes), `{FY}` / `{FY_SHORT}` (Indian financial year, e.g. FY25-26 / 25-26), `{YYYY}`, `{YY}`, `{MM}`, `{DD}`, `{DATE}`, `{STORE}`, `{BRANCH}`, `{POS}`, `{SEQ:n}`.
- Every template must include `{SEQ:n}` (sequence with n digits, 1–12).
- Sequence reset policies: `NEVER`, `FY` (financial year), `YEAR`, `MONTH`, `DAY`.
- Default format: `{TYPE}/{FY}/{STORE}/{POS}/{SEQ:6}`.
- Numbers are unique per store. The number is assigned at **draft creation**, not at release.
- Credit notes get their own CRN-prefixed number from the same system.

## Examples

- Default format produces numbers like `INV/FY25-26/MAIN/POS1/000042`.
- A credit note against that invoice gets `CRN/FY25-26/MAIN/POS1/000043` style numbering.
- "Change my invoice numbers to reset every month" → pick a template with a MONTH reset policy.

## Errors

- `template must include {SEQ:n}` — the chosen pattern is missing a sequence placeholder.
- `No templates available` — no active templates for your store; contact support/admin.
- `Failed to save format` / `Failed to load` — retry; if persistent, check your connection or plan.
- Duplicate number conflicts are retried automatically once during creation.

## FAQ

**Q: Will changing the format renumber old invoices?** 
No. Existing invoices keep their numbers; only new invoices use the new format.

**Q: Does previewing consume a number?** 
No. The preview endpoint never increments the sequence.

**Q: Can drafts and released invoices have different numbering?** 
No. The number is assigned once at creation and stays with the invoice through its lifecycle.
