"""Persistence store for store-scoped proactive notifications."""

from __future__ import annotations

import abc
import logging
from typing import Any

from app.proactive.models import NotificationRecord

logger = logging.getLogger(__name__)


class NotificationStore(abc.ABC):
    """Abstract base for notification persistence."""

    @abc.abstractmethod
    async def save_notification(self, notification: NotificationRecord) -> None:
        """Persist a notification."""

    @abc.abstractmethod
    async def get_notifications(
        self,
        store_id: str,
        *,
        limit: int = 50,
        skip: int = 0,
        unread_only: bool = False,
    ) -> list[NotificationRecord]:
        """Fetch notifications scoped strictly to store_id."""

    @abc.abstractmethod
    async def count_unread(self, store_id: str) -> int:
        """Count unread notifications for a store."""

    @abc.abstractmethod
    async def mark_read(self, store_id: str, notification_id: str) -> bool:
        """Mark a notification as read within the given store context."""


class InMemoryNotificationStore(NotificationStore):
    """In-memory store for tests and when MongoDB is offline."""

    def __init__(self) -> None:
        self._notifications: dict[str, list[NotificationRecord]] = {}

    async def save_notification(self, notification: NotificationRecord) -> None:
        self._notifications.setdefault(notification.store_id, []).append(notification)

    async def get_notifications(
        self,
        store_id: str,
        *,
        limit: int = 50,
        skip: int = 0,
        unread_only: bool = False,
    ) -> list[NotificationRecord]:
        items = self._notifications.get(store_id, [])
        if unread_only:
            items = [item for item in items if not item.read]
        # Return newest first
        sorted_items = sorted(items, key=lambda x: x.created_at, reverse=True)
        return sorted_items[skip : skip + limit]

    async def count_unread(self, store_id: str) -> int:
        items = self._notifications.get(store_id, [])
        return sum(1 for item in items if not item.read)

    async def mark_read(self, store_id: str, notification_id: str) -> bool:
        items = self._notifications.get(store_id, [])
        for item in items:
            if item.id == notification_id:
                item.read = True
                return True
        return False


class MongoNotificationStore(NotificationStore):
    """Durable MongoDB-backed notification persistence."""

    COLLECTION_NAME = "ai_notifications"

    def __init__(self, mongo_db: Any) -> None:
        self._db = mongo_db
        self._collection = (
            mongo_db[self.COLLECTION_NAME] if mongo_db is not None else None
        )

    async def ensure_indexes(self) -> None:
        if self._collection is None:
            return
        try:
            await self._collection.create_index(
                [("storeId", 1), ("createdAt", -1)],
                name="idx_notifications_store_created",
            )
            await self._collection.create_index(
                [("storeId", 1), ("read", 1)],
                name="idx_notifications_store_read",
            )
        except Exception as exc:
            logger.warning("Failed to create notification indexes: %s", exc)

    async def save_notification(self, notification: NotificationRecord) -> None:
        if self._collection is None:
            return
        doc = notification.model_dump(by_alias=True)
        doc["_id"] = doc["id"]
        await self._collection.replace_one({"_id": doc["_id"]}, doc, upsert=True)

    async def get_notifications(
        self,
        store_id: str,
        *,
        limit: int = 50,
        skip: int = 0,
        unread_only: bool = False,
    ) -> list[NotificationRecord]:
        if self._collection is None:
            return []
        query: dict[str, Any] = {"storeId": store_id}
        if unread_only:
            query["read"] = False

        cursor = (
            self._collection.find(query)
            .sort("createdAt", -1)
            .skip(skip)
            .limit(limit)
        )
        results: list[NotificationRecord] = []
        async for doc in cursor:
            doc.pop("_id", None)
            try:
                results.append(NotificationRecord.model_validate(doc))
            except Exception as exc:
                logger.warning("Malformed notification doc %s: %s", doc.get("id"), exc)
        return results

    async def count_unread(self, store_id: str) -> int:
        if self._collection is None:
            return 0
        return await self._collection.count_documents({"storeId": store_id, "read": False})

    async def mark_read(self, store_id: str, notification_id: str) -> bool:
        if self._collection is None:
            return False
        res = await self._collection.update_one(
            {"_id": notification_id, "storeId": store_id},
            {"$set": {"read": True}},
        )
        return res.modified_count > 0
