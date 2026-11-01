"""Deterministic payment mix breakdown (Cash vs UPI vs Card vs Credit) engine.

Calculates collection breakdown across payment channels.
Strictly pure Python: ZERO LLM math. All monetary calculations use Decimal precision.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.insights.common import (
    CoverageMetadata,
    quantize_money,
    quantize_pct,
    to_decimal,
)

_CANONICAL_MODES = ("CASH", "UPI", "CARD", "CREDIT", "BANK_TRANSFER", "OTHER")


def _is_valid_released_invoice(invoice: dict[str, Any]) -> bool:
    """Filter out non-RELEASED, cancelled invoices or credit notes."""
    status = str(invoice.get("invoiceStatus") or "").upper().strip()
    if status and status != "RELEASED":
        return False
    if invoice.get("cancelledAt") or invoice.get("cancellationReason"):
        return False
    doc_type = (
        str(invoice.get("docType") or invoice.get("invoiceType") or "").upper().strip()
    )
    return doc_type != "CREDIT_NOTE"


def normalize_payment_mode(raw_mode: Any) -> str:
    """Normalize raw payment mode string into canonical categories."""
    if not isinstance(raw_mode, str) or not raw_mode.strip():
        return "OTHER"
    mode = raw_mode.strip().upper()
    if mode in ("CASH", "ROKAD", "ROKDA"):
        return "CASH"
    if mode in ("UPI", "GPAY", "GOOGLEPAY", "PHONEPE", "PAYTM", "BHIM", "QR"):
        return "UPI"
    if mode in ("CARD", "DEBIT_CARD", "CREDIT_CARD", "POS", "VISA", "MASTERCARD"):
        return "CARD"
    if mode in ("CREDIT", "UDHAAR", "UDHAR", "KHATA", "DUE", "UNPAID"):
        return "CREDIT"
    if mode in (
        "BANK_TRANSFER",
        "NEFT",
        "RTGS",
        "IMPS",
        "CHEQUE",
        "CHECK",
        "NET_BANKING",
    ):
        return "BANK_TRANSFER"
    return "OTHER"


def calculate_payment_mix(
    invoices: list[dict[str, Any]],
    *,
    window: str = "7d",
    is_complete: bool = True,
) -> dict[str, Any]:
    """Compute exact collection breakdown by payment mode and uncollected credit.

    Distinguishes actual collected money from uncollected customer credit (udhaar).
    All arithmetic is performed with Decimal precision.
    """
    valid_invoices = [
        inv
        for inv in invoices
        if isinstance(inv, dict) and _is_valid_released_invoice(inv)
    ]
    scanned_count = len(invoices)

    totals: dict[str, Decimal] = {m: Decimal("0.00") for m in _CANONICAL_MODES}
    counts: dict[str, int] = {m: 0 for m in _CANONICAL_MODES}
    total_invoiced = Decimal("0.00")
    total_collected = Decimal("0.00")
    total_credit = Decimal("0.00")

    for inv in valid_invoices:
        raw_mode = inv.get("paymentMode")
        mode = normalize_payment_mode(raw_mode)
        tot_amt = to_decimal(inv.get("totalAmount"))
        if tot_amt < Decimal("0.00"):
            tot_amt = Decimal("0.00")
        tot_amt = quantize_money(tot_amt)
        total_invoiced += tot_amt

        payment_status = str(inv.get("paymentStatus") or "").upper().strip()
        raw_paid = inv.get("paidAmount")
        raw_due = inv.get("dueAmount")

        collected = Decimal("0.00")
        due = Decimal("0.00")

        if mode == "CREDIT":
            if raw_paid is not None and to_decimal(raw_paid) > Decimal("0.00"):
                collected = min(tot_amt, quantize_money(to_decimal(raw_paid)))
                due = quantize_money(tot_amt - collected)
                if collected > Decimal("0.00"):
                    totals["OTHER"] += collected
                    counts["OTHER"] += 1
                    total_collected += collected
            else:
                due = tot_amt
            if due > Decimal("0.00"):
                totals["CREDIT"] += due
                counts["CREDIT"] += 1
                total_credit += due
        elif payment_status == "UNPAID":
            # Completely uncollected credit invoice, regardless of default paymentMode
            due = tot_amt
            totals["CREDIT"] += due
            counts["CREDIT"] += 1
            total_credit += due
        elif payment_status == "PARTIAL":
            if raw_paid is not None and to_decimal(raw_paid) > Decimal("0.00"):
                collected = min(tot_amt, quantize_money(to_decimal(raw_paid)))
            elif raw_due is not None:
                due_val = quantize_money(to_decimal(raw_due))
                collected = max(Decimal("0.00"), quantize_money(tot_amt - due_val))
            else:
                collected = Decimal("0.00")
            due = quantize_money(tot_amt - collected)

            if collected > Decimal("0.00"):
                totals[mode] += collected
                counts[mode] += 1
                total_collected += collected
            if due > Decimal("0.00"):
                totals["CREDIT"] += due
                counts["CREDIT"] += 1
                total_credit += due
        elif payment_status == "PAID":
            if raw_paid is not None and to_decimal(raw_paid) > Decimal("0.00"):
                collected = min(tot_amt, quantize_money(to_decimal(raw_paid)))
            else:
                collected = tot_amt
            totals[mode] += collected
            counts[mode] += 1
            total_collected += collected
            due = quantize_money(tot_amt - collected)
            if due > Decimal("0.00"):
                totals["CREDIT"] += due
                counts["CREDIT"] += 1
                total_credit += due
        else:
            # Payment status not provided (legacy/mock record)
            if raw_paid is not None and to_decimal(raw_paid) >= Decimal("0.00"):
                collected = min(tot_amt, quantize_money(to_decimal(raw_paid)))
                due = quantize_money(tot_amt - collected)
                if collected > Decimal("0.00"):
                    totals[mode] += collected
                    counts[mode] += 1
                    total_collected += collected
                if due > Decimal("0.00"):
                    totals["CREDIT"] += due
                    counts["CREDIT"] += 1
                    total_credit += due
            elif raw_due is not None and to_decimal(raw_due) > Decimal("0.00"):
                due = min(tot_amt, quantize_money(to_decimal(raw_due)))
                collected = quantize_money(tot_amt - due)
                if collected > Decimal("0.00"):
                    totals[mode] += collected
                    counts[mode] += 1
                    total_collected += collected
                if due > Decimal("0.00"):
                    totals["CREDIT"] += due
                    counts["CREDIT"] += 1
                    total_credit += due
            else:
                # Default assume full collection for legacy records
                collected = tot_amt
                totals[mode] += collected
                counts[mode] += 1
                total_collected += collected

    total_invoices = len(valid_invoices)
    breakdown: dict[str, dict[str, Any]] = {}
    primary_mode = "NONE"
    max_mode_amount = Decimal("0.00")

    for mode in _CANONICAL_MODES:
        mode_amt = totals[mode]
        mode_count = counts[mode]
        if total_invoiced > Decimal("0.00"):
            share_pct = quantize_pct((mode_amt / total_invoiced) * Decimal("100.0"))
            if mode_amt > max_mode_amount:
                max_mode_amount = mode_amt
                primary_mode = mode
        else:
            share_pct = Decimal("0.00")

        breakdown[mode] = {
            "amount": str(quantize_money(mode_amt)),
            "count": mode_count,
            "sharePct": float(share_pct),
        }

    return {
        "totalInvoiced": str(quantize_money(total_invoiced)),
        "totalAmount": str(quantize_money(total_invoiced)),
        "totalCollected": str(quantize_money(total_collected)),
        "totalUncollectedCredit": str(quantize_money(total_credit)),
        "invoiceCount": total_invoices,
        "primaryMode": primary_mode,
        "breakdown": breakdown,
        "coverage": CoverageMetadata(
            scanned_bills=scanned_count,
            window=window,
            is_complete=is_complete,
        ).to_dict(),
    }
