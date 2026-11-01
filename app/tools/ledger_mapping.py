"""Ledger type mapping — single source of truth (never invert).

ledger_credit → PAYMENT  (customer pays us: due ↓, paid ↑)
ledger_debit  → DEBIT    (customer owes more: due ↑)
"""

from typing import Final, Literal

LedgerRetailerType = Literal["PAYMENT", "DEBIT"]

LEDGER_CREDIT_TYPE: Final[LedgerRetailerType] = "PAYMENT"
LEDGER_DEBIT_TYPE: Final[LedgerRetailerType] = "DEBIT"
