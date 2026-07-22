---
module: invoice
feature: printing
version: 1
language: en
updated_at: 2026-07-22
status: shipped
---

# Invoice Printing, PDF & Templates

## Overview

Invoices can be printed or downloaded as PDF from the invoice view page using a selectable visual template. Templates include 40+ standard A4 designs (Modern is the default) and 5 thermal receipt designs for receipt printers.

## Workflow

1. **Choose a template** — Invoices → open an invoice → Template Settings, or go directly to `/dashboard/invoices/print-preview`. Click a template to select it; the choice is saved immediately on this device and you are returned to the previous page.
2. **Print** — on the invoice view page press Print (Ctrl+P or F2). Thermal templates use the mini/thermal print flow automatically.
3. **Download PDF** — Ctrl+D or the Download PDF action.
4. **Share** — the Send menu offers PDF, WhatsApp, Email, and Copy link.
5. **POS auto-print** — after a POS sale, the invoice opens with auto-print and returns to POS.

## Business rules

- Template choice is stored per device/browser (localStorage), not on the server — different computers can use different templates.
- Standard templates print A4-style documents; Thermal templates (Thermal Classic, Modern, Compact, Minimal, Bold) target receipt printers.
- Popular standard templates include: Modern (default), Classic, Minimal, Professional, Elegant, Aurora, Zenith, and many more.
- Printing is available for both drafts and released invoices from the view page.

## Examples

- "Print this bill on my thermal printer" → Template Settings → pick a Thermal template → Print.
- "Send the invoice PDF on WhatsApp" → invoice view → Send → WhatsApp (opens share with the invoice link/message).
- "Use a different design for invoices" → open print-preview, click the design you want — saved instantly.

## Errors

- Copy link not available — the invoice has no public ID yet; re-open the invoice or contact support.
- Print dialog issues are usually browser/printer-side; try Download PDF instead.

## FAQ

**Q: Is my template choice shared with my staff?** 
No. Template selection is saved per device. Each computer/browser picks its own.

**Q: Can I customize a template's fields or logo?** 
You choose among the built-in designs; store details, GSTIN, and signature come from your store settings and signatures.

**Q: Which template is used for thermal receipts?** 
Any template whose name starts with "Thermal" routes to the thermal print flow automatically.
