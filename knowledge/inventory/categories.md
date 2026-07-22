---
module: inventory
feature: categories
version: 1
language: en
updated_at: 2026-07-23
status: shipped
---

# Product Categories

## Overview

Categories organize your products for filtering, the public catalog, and reporting. Create them from the product form ("+ Add New Category") or during bulk upload (new category names are created automatically). Categories support up to 3 levels of nesting and can require expiry dates for their products.

## Workflow

1. **Create** — while adding/editing a product, choose "+ Add New Category". Fields: Category Name (required), Description, "Products require expiry date" checkbox, Category Icon (up to 2MB), Tags.
2. **Use** — assign each product a category (required). Filter the product list and the public catalog by category.
3. **Edit/Delete** — via the category management APIs/product flows; deletion is blocked while the category has products or subcategories.

## Business rules

- Category names are unique per store at the same level (case-insensitive).
- Maximum nesting depth: 3 levels.
- Name length 2–100 characters; description up to 500.
- Deleting is a soft delete and is **blocked** if the category has active products (`ACTIVE` / `OUT_OF_STOCK`) or active subcategories — move or delete those first. Products are never reassigned automatically.
- Some system categories are protected and cannot be deleted.
- Category management uses the `product` staff permission (no separate category permission).
- The "requires expiry date" flag makes expiry mandatory when stocking products of this category.

## Examples

- "Make a Dairy category that requires expiry dates" → + Add New Category → name "Dairy" → tick "Products require expiry date".
- "Why can't I delete the Snacks category?" → it still has products; move them to another category first.

## Errors

- `Category with this name already exists at this level` — duplicate name.
- `Maximum category depth (3 levels) exceeded` — nesting too deep.
- `Cannot delete category with N products. Please move or delete products first.`
- `Cannot delete category with N subcategories...`
- `Category cannot be deleted` — protected category.

## FAQ

**Q: What happens to products when a category is deleted?** 
Nothing is moved automatically — deletion is blocked until you move or delete the products yourself.

**Q: Can bulk upload create categories?** 
Yes. Unknown category names in the upload file are created automatically (matched case-insensitively).

**Q: Do categories appear in my public catalog?** 
Yes — the public catalog groups products by category.
