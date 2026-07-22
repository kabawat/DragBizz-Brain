---
module: settings
feature: store
version: 1
language: en
updated_at: 2026-07-23
status: shipped
---

# Store Settings & Multi-Store

## Overview

Manage your stores at **Settings → Store** (`/dashboard/settings?tab=store`). Each store card shows name, address, GST/PAN, and contacts, with the active one marked **Current Store**. From here you can add stores (up to your plan's store limit), edit details, open the public **Catalog QR**, and delete a store — a two-step, OTP-protected action. Switching between stores happens from the store selector in the top header.

## Workflow

1. **Add / edit a store** — required: Store Name, Phone, City. Optional: GST number (with a **Verify** button that auto-checks a 15-character GSTIN), PAN, category, email, street/state/pincode/landmark, and a "Products require expiry date" toggle.
2. **Catalog QR** — the store card opens a QR modal for the public catalog link (unique catalog ID per store). You can copy the link, download a printable PDF, print the QR, or open the catalog. An optional "In-Store Dining Location" can be added to the QR.
3. **Delete a store** — available only when it is not the current store and you have more than one store:
   - Step 1: a warning lists what gets permanently deleted (invoices, bills, products, etc.); choose OTP by **SMS or Email** → Send OTP.
   - Step 2: enter the **6-digit OTP** (valid 10 minutes) → **Verify & Delete**. Deletion is permanent.

## Business rules

- **Owner only** — staff cannot create, edit, or delete stores.
- Store count is plan-gated: Khata Free/Startup/Basic = 1 store, Standard = 2, Premium = 5.
- GSTIN and PAN are format-validated ("Invalid GST format" / "Invalid PAN format"); both are optional.
- The catalog ID is generated automatically when the store is created; it can be regenerated (which changes the public link/QR).
- You must always keep at least one active store — the last store cannot be deleted.
- Store delete is a **hard delete** — data is not recoverable.
- Store logo upload is not available.

## Examples

- "Add my second shop" → Settings → Store → Create New Store (needs Standard plan or higher).
- "Dukaan ka QR print karna hai" → store card → Catalog QR → Print QR / Download PDF.
- "Change my store's GST number" → Edit → GST field → Verify → Save.

## Errors

- "You have reached your … limit of 1 for store. Please upgrade your plan for more capacity." — store limit hit.
- "You must have at least one active store. The last store cannot be deleted."
- "Invalid OTP" / "Invalid or expired delete token" — re-request the OTP (10-minute validity).
- "No contact information available…" — the account lacks the phone/email needed for the chosen OTP channel.
- "Invalid GST format" / "Invalid PAN format".

## FAQ

**Q: Can staff manage stores?** 
No — store settings are owner-only. Staff only see Appearance, Language, and Profile in Settings.

**Q: What happens to invoices when I delete a store?** 
They are permanently deleted with the store — that's why deletion needs OTP confirmation. Export anything you need first.

**Q: How do customers use the Catalog QR?** 
Scanning it opens your public catalog where they can browse products and place sales orders — no login needed.
