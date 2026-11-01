---
module: inventory
feature: products
version: 1
language: en
updated_at: 2026-07-23
status: shipped
---

# Product Management

## Overview

Products are managed at `/dashboard/products`: add items one by one or in bulk, set pricing and GST, control whether they appear in your public catalog, and track them as goods (stock-tracked) or services (no stock). Every product needs a name, a category, an MRP, and a selling price.

## Workflow

1. **Add a product** — Products → **Add Product** (`/dashboard/products/create`). Form sections:
   - **Basic:** Product Name (required), Brand, Item type (Goods / Service), SKU (optional — auto-generated if left blank), Category (required, with "+ Add New Category"), Barcode (optional).
   - **Media:** upload product images (JPG/PNG/WebP, up to 5MB each).
   - **Pricing:** MRP and Selling Price (required), unit of measure (PCS, KG, LITER, etc.), currency fixed to INR. A live summary shows You Save / Discount %.
   - **GST** (shown if your store has a GST number): GST rate, HSN code, and GST Included/Excluded in the selling price.
   - **Catalog:** Show in Catalog toggle (on by default), optional description, features, tags, and specs.
2. **Search & filter** — search by name/SKU; filter by Catalog Visibility and Category; sort by newest or price.
3. **Row actions** — View Details, Stock In (opens the stock drawer), Edit, Duplicate, Delete.
4. **Bulk upload** — Products → **Bulk Upload**: download the template (CSV/XLSX/JSON), fill rows, upload (max 1000 rows). Columns include name, category (auto-created if new), uom, selling_price, plus optional mrp, gst_rate, brand, sku, barcode, hsn_code, opening_stock, purchase_price, supplier_contact, expiry_date. Results show created / skipped / failed per row.
5. **View & print** — the product page shows info, pricing, GST, status, and stock count, with a PDF download.

## Business rules

- Selling price cannot exceed MRP.
- SKU (uppercase letters/numbers/hyphens) and barcode must be unique within the store.
- Supported GST rates: 0, 0.25, 3, 5, 12, 18, 28 percent. GST fields require a store GST number; without it, GST cannot be collected.
- **Goods vs Service:** goods are stock-tracked (inventory/batches); services never touch stock and use SAC codes instead of HSN.
- Catalog visibility: only products with **Show in Catalog** on appear in your public catalog/QR store.
- A product **cannot be deleted while it has stock** — sell or return all units first (invoices/history do not block deletion).
- Bulk upload skips rows whose SKU or barcode already exists (in the store or earlier in the same file).
- Product creation counts against your plan's product quota; staff need `product` permissions (billing staff can read products via invoice permission).

## Examples

- "Add Sugar 1kg, MRP 55, selling 52, GST 5%" → Add Product → fill Basic + Pricing + GST → Save & Publish.
- "Hide an item from my online catalog" → edit the product → turn off Show in Catalog.
- "Import 500 products from Excel" → Bulk Upload → template → fill → upload; new category names are created automatically.

## Errors

- `Selling price cannot exceed MRP.`
- `Duplicate entry found` — SKU or barcode already exists in this store.
- `Product has N units in inventory. Cannot delete product with stock.`
- `Quota exceeded. Please upgrade your plan to create more products.` / daily limit reached.
- `File exceeds the maximum allowed rows (1000)` and file type/size errors on bulk upload.
- `Service products should use SAC code instead of HSN.`

## FAQ

**Q: Do I have to enter a SKU or barcode?** 
No — both are optional. A SKU is auto-generated if you leave it blank.

**Q: What is the difference between GST Included and Excluded?** 
Included: the selling price already contains GST (base is extracted at billing). Excluded: GST is added on top of the selling price.

**Q: Why can't I delete a product?** 
It still has stock. Bring its quantity to zero (sell/return) and delete again.

**Q: Can I upload multiple product photos?** 
Yes, the media section accepts multiple images (JPG/PNG/WebP, 5MB each).
