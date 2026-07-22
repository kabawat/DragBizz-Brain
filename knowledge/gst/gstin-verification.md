---
module: gst
feature: gstin-verification
version: 1
language: en
updated_at: 2026-07-23
status: shipped
---

# GSTIN Verification

## Overview

DragBizz verifies GST numbers against official government records and auto-fills the registered details. Verify buttons appear wherever you enter a GSTIN: store settings/onboarding, the customer form (company details), and the supplier form.

## Workflow

1. Enter the **15-character GSTIN** in the field — the Verify button activates (it also auto-verifies on leaving the field).
2. Press **Verify**. DragBizz checks the number with the official registry and shows "GST Verified Successfully!".
3. Auto-fill on success:
   - **Store** (settings/onboarding): store name, PAN, and address are pre-filled from the registration.
   - **Customer** (Add company details): company name is filled and the GST record linked.
   - **Supplier**: the agency/legal name is filled and the GST record linked.

## Business rules

- What comes back: legal name, trade name, PAN, state and state code, registered address, registration type (Regular / Composition / Casual / Non-Resident), status (Active / Cancelled / Suspended / Pending), and GST effective date.
- Results are cached — repeat verifications of the same GSTIN within about 15 days answer instantly without re-hitting the registry.
- Verification is available on all plans (no premium gate), with a rate limit of about 10 GST requests per minute.
- A verified badge (green check) replaces the button once verified.
- Composition-registered stores cannot collect GST on invoices — DragBizz's mismatch check flags it.

## Examples

- "Set up my store with GST" → Settings → Store → enter GSTIN → Verify → name/PAN/address auto-fill.
- "Add a B2B customer with their GSTIN" → customer form → Add company details → GSTIN → Verify → company name fills in.
- "Check if a supplier's GST number is genuine" → supplier form → GST Number → Verify → status shows Active/Cancelled.

## Errors

- "Please enter a valid 15-digit GST number" — wrong length/format.
- `Invalid GST number` / `Taxpayer information not found` — the registry has no record for this GSTIN.
- `GST Verification Error: ...` — registry/API issue; try again shortly.
- Rate limited — too many GST requests in a minute; wait and retry.

## FAQ

**Q: Is verification mandatory?** 
No — GSTIN fields are optional. Verification just confirms the number and saves you typing the registered details.

**Q: The name auto-filled differently from what I typed — why?** 
Verification fills the **registered** legal/trade name from government records; you can edit it afterwards.

**Q: Does verifying a customer's GSTIN make my sales B2B?** 
Invoices to customers with a saved company GSTIN are counted as B2B in GST analytics.
