from __future__ import annotations

from collections.abc import Sequence

TOOL_PROGRESS_LABELS: dict[str, str] = {
    # Sales & Invoices
    "today_sale": "Fetching today's sales & revenue records…",
    "sales_summary": "Fetching sales summary & performance…",
    "list_invoices": "Fetching sales and invoice records…",
    "get_invoice_detail": "Fetching invoice details…",
    "sales_pareto": "Calculating sales Pareto & profit analysis…",
    "dead_stock": "Analyzing slow-moving & dead stock…",
    "sales_order_summary": "Fetching sales orders summary…",
    "list_sales_orders": "Fetching sales order records…",
    "get_sales_order_detail": "Fetching sales order details…",
    "create_invoice_draft": "Preparing invoice draft…",
    "release_invoice": "Finalizing and releasing invoice…",

    # Inventory & Stock
    "stock_summary": "Checking current stock & inventory levels…",
    "search_product": "Searching product catalog…",
    "list_products": "Fetching product details & catalog…",
    "get_product_detail": "Fetching product details…",
    "low_stock_alerts": "Checking low stock alerts…",
    "stock_movement": "Checking stock movement history…",
    "category_list": "Fetching product categories…",
    "add_stock": "Preparing stock update…",
    "create_product": "Preparing product details…",
    "update_product": "Updating product details…",

    # Customers & Khata
    "customer_summary": "Fetching customer accounts & dues…",
    "search_customer": "Searching customer directory…",
    "list_customer_accounts": "Fetching customer account details…",
    "get_customer_ledger": "Preparing customer ledger & statement…",
    "customer_dossier": "Compiling customer profile & history…",
    "overdue_customers": "Checking overdue customer balances…",
    "payment_reminders": "Checking payment reminders…",
    "customer_stats": "Analyzing customer statistics…",
    "create_customer": "Preparing customer details…",
    "ledger_debit": "Preparing customer debit entry…",
    "ledger_credit": "Preparing customer payment credit…",

    # Suppliers & Procurement
    "supplier_summary": "Checking supplier and purchase records…",
    "search_supplier": "Searching supplier directory…",
    "list_suppliers": "Fetching supplier list…",
    "get_supplier_detail": "Fetching supplier details…",
    "purchase_order_summary": "Checking purchase order summary…",
    "list_purchase_orders": "Fetching purchase order records…",
    "list_supplier_bills": "Fetching supplier bill records…",
    "get_purchase_order_detail": "Fetching purchase order details…",
    "supplier_bills": "Checking supplier bills & dues…",
    "create_supplier": "Preparing supplier details…",
    "create_purchase_order": "Preparing purchase order…",

    # Expenses & Finance
    "expense_summary": "Fetching expense records…",
    "list_expenses": "Fetching expense records…",
    "cashbook_summary": "Checking cashbook & cashflow records…",
    "gst_summary": "Calculating GST & tax summary…",
    "create_expense": "Preparing expense details…",
    "update_expense": "Updating expense details…",

    # General & Analytics
    "store_brief": "Fetching store overview & performance…",
    "detailed_analytics": "Compiling store analytics & metrics…",
    "list_staff": "Fetching staff directory…",
    "export_report": "Preparing report export…",
}

_TOOL_DOMAIN_MAP: dict[str, str] = {
    "today_sale": "sales",
    "sales_summary": "sales",
    "list_invoices": "sales",
    "get_invoice_detail": "sales",
    "sales_pareto": "sales",
    "dead_stock": "inventory",
    "sales_order_summary": "sales",
    "list_sales_orders": "sales",
    "get_sales_order_detail": "sales",
    "create_invoice_draft": "sales",
    "release_invoice": "sales",
    "stock_summary": "inventory",
    "search_product": "inventory",
    "list_products": "inventory",
    "get_product_detail": "inventory",
    "low_stock_alerts": "inventory",
    "stock_movement": "inventory",
    "category_list": "inventory",
    "add_stock": "inventory",
    "create_product": "inventory",
    "update_product": "inventory",
    "customer_summary": "customer",
    "search_customer": "customer",
    "list_customer_accounts": "customer",
    "get_customer_ledger": "customer",
    "customer_dossier": "customer",
    "overdue_customers": "customer",
    "payment_reminders": "customer",
    "customer_stats": "customer",
    "create_customer": "customer",
    "ledger_debit": "customer",
    "ledger_credit": "customer",
    "supplier_summary": "supplier",
    "search_supplier": "supplier",
    "list_suppliers": "supplier",
    "get_supplier_detail": "supplier",
    "purchase_order_summary": "supplier",
    "list_purchase_orders": "supplier",
    "list_supplier_bills": "supplier",
    "get_purchase_order_detail": "supplier",
    "supplier_bills": "supplier",
    "create_supplier": "supplier",
    "create_purchase_order": "supplier",
    "expense_summary": "finance",
    "list_expenses": "finance",
    "cashbook_summary": "finance",
    "gst_summary": "finance",
    "create_expense": "finance",
    "update_expense": "finance",
    "store_brief": "general",
    "detailed_analytics": "general",
    "list_staff": "general",
    "export_report": "general",
}

_DOMAIN_GROUP_LABELS: dict[str, str] = {
    "sales": "sales and invoice records",
    "inventory": "inventory and product records",
    "customer": "customer and ledger records",
    "supplier": "supplier and purchase records",
    "finance": "expense and financial records",
    "general": "store data",
}


def get_tool_progress_label(tool_name: str) -> str:
    """Return user-safe, authentic progress label for a registered tool."""
    if tool_name in TOOL_PROGRESS_LABELS:
        return TOOL_PROGRESS_LABELS[tool_name]
    humanized = tool_name.replace("_", " ")
    return f"Processing {humanized}…"


def get_parallel_tools_label(tool_names: Sequence[str]) -> str:
    """Generate a coherent combined status for parallel tool executions without flickering."""
    if not tool_names:
        return "Working on your request…"
    if len(tool_names) == 1:
        return get_tool_progress_label(tool_names[0])

    domains = [_TOOL_DOMAIN_MAP.get(name, "general") for name in tool_names]
    unique_domains = list(dict.fromkeys(domains))

    if len(unique_domains) == 1:
        domain = unique_domains[0]
        if domain == "sales":
            return "Fetching sales, revenue & invoice records…"
        if domain == "inventory":
            return "Checking inventory, stock & product details…"
        if domain == "customer":
            return "Fetching customer records & ledger balances…"
        if domain == "supplier":
            return "Checking supplier details & purchase orders…"
        if domain == "finance":
            return "Fetching expenses, cashflow & tax records…"
        return "Fetching store intelligence records…"

    if len(unique_domains) == 2:
        part1 = _DOMAIN_GROUP_LABELS.get(unique_domains[0], "records")
        part2 = _DOMAIN_GROUP_LABELS.get(unique_domains[1], "records")
        return f"Fetching {part1} & {part2}…"

    return "Fetching relevant store records & details…"
