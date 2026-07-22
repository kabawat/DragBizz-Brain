---
module: dashboard
feature: overview
version: 1
language: en
updated_at: 2026-07-23
status: shipped
---

# Dashboard Home

## Overview

The dashboard home (`/dashboard`) is the landing page after login. Owners see business-wide metrics summed **across all their stores**, a per-store summary table, quick actions, and today's cashbook card. Staff see a simpler "Operations Overview" with tiles for the modules they have permission to use.

## Workflow

1. **Owner metric cards** (drag to reorder; order is remembered per device): Total Revenue, Total Profit, Total Customers, Total Products, Stock Value, Out of Stock, Total Payables.
2. **Stores Summary** — one row per store with revenue, profit, customers, products, stock value, out-of-stock count, and payables.
3. **Quick Actions** — Add Customer, Add Product, New Invoice, Add Supplier.
4. **Cashbook Today** card — today's Cash In, Cash Out, and Closing Balance with a link to the cashbook.
5. **Staff view** — staff members instead get "Operations Overview" tiles (Invoices & Billing, Point of Sale, Sales Orders, Products, Stock & Inventory, Customers, Expenses, Suppliers, Purchase Orders, Bills & Payments, Reports) filtered to their assigned read permissions.

## Business rules

- Owner totals aggregate all stores in the agency; the Stores Summary breaks them down per store.
- Staff never see agency-wide financial metrics — only their permitted module tiles.
- The cashbook card appears only when a store is selected and today's data exists.
- Revenue/profit figures follow the same rule as analytics: released invoices only.

## Examples

- "How is my business overall?" → the seven metric cards give the cross-store snapshot.
- "Which store has stock problems?" → Stores Summary → Out of Stock column.
- "I'm a staff member and see no tiles" → no modules assigned; ask the store owner to grant permissions.

## Errors

- "No data available" — the store has no recorded activity yet.
- "No Modules Assigned" (staff) — contact the store owner/manager for permissions.

## FAQ

**Q: Can I rearrange the dashboard?** 
Yes — drag the metric cards; the order is saved on your device.

**Q: Why do my dashboard numbers differ from a single store's analytics?** 
Dashboard totals sum all stores; analytics pages show the selected store only.
