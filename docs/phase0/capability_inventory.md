# Phase 0 Capability Inventory

> Generated from `app.tools.registry.build_unified_tool_registry()` by `scripts/generate_phase0_inventory.py`. This records what is registered at startup; it does not prove that a user's permissions allow a call or that the downstream operation succeeds.

**Registered tools:** 50
**Domains:** finance: 6, general: 3, inventory: 6, khata: 21, procurement: 5, sales: 9

## Runtime tool catalogue

| Tool | Domain | Access / risk | Confirmation | Required permission | Handler | Retailer methods |
|---|---|---|---:|---|---|---|
| `add_stock` | inventory | write / sensitive | yes | inventory:write | `app/tools/handlers/confirm_tools.py:add_stock` | add_stock |
| `bill_summary` | procurement | read / read | no | bills:read | `app/tools/handlers/read_tools.py:bill_summary` | get_bill_analytics |
| `cashbook_summary` | finance | read / read | no | cashbook:read | `app/tools/handlers/read_tools.py:cashbook_summary` | get_cashbook_summary |
| `create_collect_link` | khata | write / sensitive | yes | payments:write | `app/tools/handlers/confirm_tools.py:create_collect_link` | create_collect_link |
| `create_customer` | khata | write / write | no | customers:write | `app/tools/handlers/write_tools.py:create_customer` | create_customer |
| `create_expense` | finance | write / sensitive | yes | expenses:write | `app/tools/handlers/confirm_tools.py:create_expense` | create_expense |
| `create_invoice_draft` | sales | write / write | no | invoices:write | `app/tools/handlers/write_tools.py:create_invoice_draft` | create_invoice_draft |
| `create_purchase_order` | procurement | write / sensitive | yes | purchase_orders:write | `app/tools/handlers/confirm_tools.py:create_purchase_order` | create_purchase_order |
| `customer_detailed_analytics` | khata | read / read | no | customers:read | `app/tools/handlers/read_tools.py:customer_detailed_analytics` | get_customer_detailed_analytics |
| `customer_dossier` | khata | read / read | no | customers:read | `app/tools/handlers/read_tools.py:customer_dossier` | get_invoices |
| `customer_summary` | khata | read / read | no | customers:read | `app/tools/handlers/read_tools.py:customer_summary` | get_customer_analytics, get_customer_detailed_analytics |
| `expense_summary` | finance | read / read | no | expenses:read | `app/tools/handlers/read_tools.py:expense_summary` | get_expense_analytics |
| `get_customer_ledger` | khata | read / read | no | ledger:read | `app/tools/handlers/read_tools.py:get_customer_ledger` | get_customer_ledger |
| `get_customer_payment` | khata | read / read | no | payments:read | `app/tools/handlers/read_tools.py:get_customer_payment` | get_payment |
| `gst_summary` | finance | read / read | no | gst:read | `app/tools/handlers/read_tools.py:gst_summary` | get_gst_health_score, get_gst_summary |
| `inventory_velocity` | inventory | read / read | no | inventory:read | `app/tools/handlers/read_tools.py:inventory_velocity` | get_stock_items |
| `invoice_detailed_analytics` | sales | read / read | no | invoices:read | `app/tools/handlers/read_tools.py:invoice_detailed_analytics` | get_invoice_detailed_analytics |
| `invoice_summary` | sales | read / read | no | invoices:read | `app/tools/handlers/read_tools.py:invoice_summary` | get_invoice_analytics, get_invoice_detailed_analytics |
| `ledger_credit` | khata | write / sensitive | yes | ledger:write | `app/tools/handlers/confirm_tools.py:ledger_credit` | none detected |
| `ledger_debit` | khata | write / sensitive | yes | ledger:write | `app/tools/handlers/confirm_tools.py:ledger_debit` | none detected |
| `list_customer_accounts` | khata | read / read | no | customers:read | `app/tools/handlers/read_tools.py:list_customer_accounts` | list_customer_accounts |
| `list_expenses` | finance | read / read | no | expenses:read | `app/tools/handlers/read_tools.py:list_expenses` | get_expenses |
| `list_invoices` | sales | read / read | no | invoices:read | `app/tools/handlers/read_tools.py:list_invoices` | list_invoices |
| `list_payment_reminders` | khata | read / read | no | reminders:read | `app/tools/handlers/read_tools.py:list_payment_reminders` | list_payment_reminders |
| `list_purchase_orders` | procurement | read / read | no | purchase_orders:read | `app/tools/handlers/read_tools.py:list_purchase_orders` | get_purchase_orders |
| `list_sales_orders` | sales | read / read | no | sales:read | `app/tools/handlers/read_tools.py:list_sales_orders` | get_sales_orders |
| `list_staff` | general | read / read | no | staff:read | `app/tools/handlers/read_tools.py:list_staff` | get_staff |
| `list_stores` | general | read / read | no | stores:read | `app/tools/handlers/read_tools.py:list_stores` | get_stores |
| `merge_customers` | khata | write / sensitive | yes | customers:write | `app/tools/handlers/confirm_tools.py:merge_customers` | merge_customers |
| `payment_history` | khata | read / read | no | payments:read | `app/tools/handlers/read_tools.py:payment_history` | get_payments |
| `payment_mix` | khata | read / read | no | payments:read | `app/tools/handlers/read_tools.py:payment_mix` | none detected |
| `product_summary` | inventory | read / read | no | inventory:read | `app/tools/handlers/read_tools.py:product_summary` | get_product_analytics |
| `record_customer_payment` | khata | write / sensitive | yes | payments:write | `app/tools/handlers/confirm_tools.py:record_customer_payment` | create_customer_payment |
| `release_invoice` | sales | write / sensitive | yes | invoices:write | `app/tools/handlers/confirm_tools.py:release_invoice` | release_invoice |
| `sales_pareto` | sales | read / read | no | sales:read | `app/tools/handlers/read_tools.py:sales_pareto` | none detected |
| `search_customer` | khata | read / read | no | customers:read | `app/tools/handlers/read_tools.py:search_customer` | none detected |
| `search_product` | inventory | read / read | no | inventory:read | `app/tools/handlers/read_tools.py:search_product` | get_inventory, get_products |
| `search_supplier` | procurement | read / read | no | suppliers:read | `app/tools/handlers/read_tools.py:search_supplier` | get_suppliers |
| `send_payment_reminder` | khata | write / sensitive | yes | reminders:write | `app/tools/handlers/confirm_tools.py:send_payment_reminder` | create_payment_reminder |
| `set_opening_balance` | khata | write / sensitive | yes | ledger:write | `app/tools/handlers/confirm_tools.py:set_opening_balance` | create_customer_account |
| `stock_items` | inventory | read / read | no | inventory:read | `app/tools/handlers/read_tools.py:stock_items` | get_stock_items |
| `stock_summary` | inventory | read / read | no | inventory:read | `app/tools/handlers/read_tools.py:stock_summary` | get_stock |
| `store_brief` | general | read / read | no | stores:read | `app/tools/handlers/read_tools.py:store_brief` | get_customer_analytics, get_expense_analytics, get_revenue, get_stock |
| `supplier_summary` | procurement | read / read | no | suppliers:read | `app/tools/handlers/read_tools.py:supplier_summary` | get_bill_analytics, get_supplier_analytics |
| `today_sale` | sales | read / read | no | sales:read | `app/tools/handlers/read_tools.py:today_sale` | get_revenue |
| `top_customers` | khata | read / read | no | customers:read | `app/tools/handlers/read_tools.py:top_customers` | list_invoices |
| `update_customer` | khata | write / write | no | customers:write | `app/tools/handlers/write_tools.py:update_customer` | update_customer |
| `update_customer_payment` | khata | write / sensitive | yes | payments:write | `app/tools/handlers/confirm_tools.py:update_customer_payment` | update_customer_payment |
| `update_expense` | finance | write / write | no | expenses:write | `app/tools/handlers/write_tools.py:update_expense` | update_expense |
| `update_invoice_draft` | sales | write / write | no | invoices:write | `app/tools/handlers/write_tools.py:update_invoice_draft` | update_invoice_draft |

## Interpretation and limits

- Registration means a definition and handler are wired by the startup registry. It does not prove routing, permission, downstream availability, or end-to-end success.
- `effective_user_authorization` is deliberately not inferred here; it depends on the authenticated caller and runtime policy.
- Retailer methods are extracted from direct handler references. Indirect calls and external RAG/UI capabilities may need manual mapping.
- Analytics tools remain listed because they exist in the registry, but analytics feature testing is outside this phase's scope.
- Regenerate after tool registry/handler changes and review the diff:
  `source .venv/bin/activate && python scripts/generate_phase0_inventory.py`
