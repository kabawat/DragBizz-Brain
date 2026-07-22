---
module: faq
feature: desktop-sync
version: 1
language: en
updated_at: 2026-07-23
status: partial
---

# Desktop App & Offline Sync

## Overview

The **DragBizz Desktop** app (Windows/Linux, Electron-based) works **offline-first**: it keeps a local copy of your data, lets you keep billing without internet, and syncs changes to the cloud when you're back online. The web dashboard itself is online-only — it just shows a "You're offline / Check your connection" notice when the network drops.

## What syncs

Customers, products, categories, stock, invoices, expenses, sales orders, suppliers, purchase orders, bills, payments, khata transactions, customer payments, cashbook, and staff attendance/salary.

## How sync works

- Changes made offline are queued and pushed in batches (up to 50 operations at a time) when the connection returns; the app also pulls server changes since the last sync.
- Each record carries a **version number**. If the same record was edited on two devices, the server does not silently overwrite — it flags a **version conflict**.
- Conflict resolution options: keep the **server** version, keep **your local** version, or **merge** — except money-ledger records (khata transactions, payments, cashbook, salary), where the **server version always wins** to protect the books.
- Duplicate protection: an operation retried after a network drop is applied only once.

## Business rules

- Sync respects the same plan quotas as the web app — offline-created items over quota fail on sync with the usual quota message.
- Sync is per store and per signed-in device.
- Mobile app parity is not available yet — desktop + web today.

## Examples

- "Internet chala gaya, billing rukni nahi chahiye" → keep billing in the desktop app; invoices sync when you're back online.
- "Do computers par same product edit ho gaya" → the second one gets a conflict prompt: keep server, keep local, or merge.

## Errors

- "Version conflict" — the record changed elsewhere; choose a resolution.
- "Ledger entities only support server_wins resolution" — money records always take the server copy.
- `QUOTA_EXCEEDED` on sync — the offline change exceeded your plan limit.
- "You're offline / Check your connection" — web dashboard network notice.

## FAQ

**Q: Kya web dashboard offline chalta hai?** 
No — offline work needs the desktop app; the web app requires internet.

**Q: Can two counters bill offline at the same time?** 
Yes — each desktop device queues its own invoices; both sync when online. Conflicts only arise when the *same record* is edited in two places.

**Q: Why did my khata edit get overwritten after sync?** 
Ledger records always take the server version in conflicts, to keep money records consistent. Re-enter the adjustment if needed.
