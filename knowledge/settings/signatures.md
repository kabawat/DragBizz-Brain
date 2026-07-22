---
module: settings
feature: signatures
version: 1
language: en
updated_at: 2026-07-23
status: shipped
---

# Signatures

## Overview

Create digital signatures for your invoices at **Settings → Signatures** (`/dashboard/settings?tab=signature`). A saved signature can be attached to an invoice when creating it and appears on the printed/PDF invoice.

## Workflow

1. Settings → Signatures → **Create Signature**.
2. Choose a method in the drawer:
   - **Type** — type your name in a signature font (font/color options).
   - **Draw** — draw on the canvas with mouse/touch; Clear to redo.
   - **Upload** — upload a signature image file.
   - **Digital Identity** — shown as **Coming Soon**; not usable yet.
3. Save — "Signature saved successfully!". The signature is now selectable on invoices.
4. Delete removes a signature after confirmation (invoices that already used it keep their copy reference).

## Business rules

- No limit on how many signatures you can save.
- There is **no default signature** — pick one per invoice when needed.
- Deletion is a soft delete (support can restore); the signature disappears from your list.

## Examples

- "Invoice par sign chahiye" → create one here, then select it while making the invoice.
- "Owner and manager both sign" → save two signatures and choose the right one per invoice.

## Errors

- "Agency, method, and content are required" — empty canvas/text/file; provide the signature content.
- "Signature not found or already deleted" — it was removed; create a new one.

## FAQ

**Q: Is this a legally certified digital signature (DSC)?** 
No — it's a signature image for invoice presentation. Certificate-based digital identity is marked Coming Soon.

**Q: Can I set one signature as default for all invoices?** 
Not currently — signatures are chosen per invoice.
