"""Event handlers package."""

from app.events.handlers.sales_event import SalesEventHandler
from app.events.handlers.stock_event import StockEventHandler

__all__ = ["SalesEventHandler", "StockEventHandler"]
