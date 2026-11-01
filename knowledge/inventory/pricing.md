---
module: inventory
feature: pricing
version: 1
language: en
updated_at: 2026-07-23
status: shipped
---

# Product Pricing & Purchase Price History

## Overview

Each product carries an **MRP** and a **Selling Price** (selling can never exceed MRP), with an automatic You Save / Discount % summary. Separately, DragBizz tracks your **purchase (cost) price history** through stock batches — every stock-in records the purchase price, building a per-supplier cost history that powers purchase-price suggestions and warnings.

## Workflow

1. **Set selling price** — on the product form: MRP + Selling Price; the live summary shows the discount. GST included/excluded affects how the base price is derived at billing.
2. **Purchase price** — entered on every **Stock In** (per batch, per unit). This is the source of cost history; the product form itself has no cost field.
3. **Cost history** — each product's batch history records purchase price, batch number, supplier, received date, and quantity (newest first).
4. **Suggestions & validation** — when recording purchases, DragBizz can suggest the last purchase price for the product (per supplier, from the latest active batch) and warns when a new price differs sharply from it: a strong warning above 50% difference, a mild one above 20%. These are warnings only — the price is never blocked.

## Business rules

- Selling Price ≤ MRP, both required, in INR.
- Purchase price is per batch (recorded at stock-in), minimum 0.
- Price suggestions come from the **latest active batch** for that product (and supplier when given) — they reflect cost, not selling price.
- Price validation is advisory: it always accepts the price but attaches difference warnings.
- Viewing price data needs `product` read permission.

## Examples

- "What did I last pay for Sugar 1kg from Gupta Traders?" → the latest batch purchase price for that product+supplier.
- Entering ₹80 when the last batch cost ₹50 → warning: "Price differs significantly from latest_batch price (60% difference)" — you can proceed.
- "Give 10% off on an item" → set Selling Price below MRP; the discount shows automatically on the product and catalog.

## Errors

- `Selling price cannot exceed MRP.` — adjust MRP or the selling price.
- `Product ID is required` — API usage without a product reference.
- Purchase price warnings (20%/50% difference) — informational, not blocking.

## FAQ

**Q: Does DragBizz suggest what selling price I should keep?** 
No. Suggestions and history are for **purchase (cost) prices** from your stock batches. Selling price is your decision (MRP-capped).

**Q: Where do I see a product's cost history?** 
It is built from batch records — check the batch details on the stock view (batch number, purchase price, supplier, received date).

**Q: Why did I get a price warning while adding stock?** 
The purchase price you entered differs a lot from the last batch for that product/supplier. It's a typo guard — you can still save.
