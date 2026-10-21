from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

import grpc
from google.protobuf import descriptor_pb2, descriptor_pool, message_factory

logger = logging.getLogger(__name__)

# Build protobuf reflection descriptors for retailer.intelligence
_pool = descriptor_pool.DescriptorPool()
_file_proto = descriptor_pb2.FileDescriptorProto()
_file_proto.name = "intelligence.proto"
_file_proto.package = "retailer.intelligence"

# 1. ActiveStoreInfo
_asi = _file_proto.message_type.add()
_asi.name = "ActiveStoreInfo"
for idx, (name, typ) in enumerate(
    [
        ("storeId", descriptor_pb2.FieldDescriptorProto.TYPE_STRING),
        ("name", descriptor_pb2.FieldDescriptorProto.TYPE_STRING),
        ("timezone", descriptor_pb2.FieldDescriptorProto.TYPE_STRING),
    ],
    1,
):
    f = _asi.field.add()
    f.name = name
    f.number = idx
    f.type = typ

# 2. GetActiveStoresRequest
_gas_req = _file_proto.message_type.add()
_gas_req.name = "GetActiveStoresRequest"
for idx, (name, typ) in enumerate(
    [
        ("limit", descriptor_pb2.FieldDescriptorProto.TYPE_INT32),
        ("page", descriptor_pb2.FieldDescriptorProto.TYPE_INT32),
    ],
    1,
):
    f = _gas_req.field.add()
    f.name = name
    f.number = idx
    f.type = typ

# 3. GetActiveStoresResponse
_gas_resp = _file_proto.message_type.add()
_gas_resp.name = "GetActiveStoresResponse"
f1 = _gas_resp.field.add()
f1.name = "success"
f1.number = 1
f1.type = descriptor_pb2.FieldDescriptorProto.TYPE_BOOL
f2 = _gas_resp.field.add()
f2.name = "message"
f2.number = 2
f2.type = descriptor_pb2.FieldDescriptorProto.TYPE_STRING
f3 = _gas_resp.field.add()
f3.name = "stores"
f3.number = 3
f3.type = descriptor_pb2.FieldDescriptorProto.TYPE_MESSAGE
f3.type_name = ".retailer.intelligence.ActiveStoreInfo"
f3.label = descriptor_pb2.FieldDescriptorProto.LABEL_REPEATED
f4 = _gas_resp.field.add()
f4.name = "total"
f4.number = 4
f4.type = descriptor_pb2.FieldDescriptorProto.TYPE_INT32

# 4. LowStockItem
_lsi = _file_proto.message_type.add()
_lsi.name = "LowStockItem"
for idx, (name, typ) in enumerate(
    [
        ("productId", descriptor_pb2.FieldDescriptorProto.TYPE_STRING),
        ("productName", descriptor_pb2.FieldDescriptorProto.TYPE_STRING),
        ("sku", descriptor_pb2.FieldDescriptorProto.TYPE_STRING),
        ("availableQuantity", descriptor_pb2.FieldDescriptorProto.TYPE_DOUBLE),
        ("lowStockThreshold", descriptor_pb2.FieldDescriptorProto.TYPE_DOUBLE),
    ],
    1,
):
    f = _lsi.field.add()
    f.name = name
    f.number = idx
    f.type = typ

# 5. GetStoreStockSummaryRequest
_gsss_req = _file_proto.message_type.add()
_gsss_req.name = "GetStoreStockSummaryRequest"
f = _gsss_req.field.add()
f.name = "storeId"
f.number = 1
f.type = descriptor_pb2.FieldDescriptorProto.TYPE_STRING

# 6. GetStoreStockSummaryResponse
_gsss_resp = _file_proto.message_type.add()
_gsss_resp.name = "GetStoreStockSummaryResponse"
for idx, (name, typ) in enumerate(
    [
        ("success", descriptor_pb2.FieldDescriptorProto.TYPE_BOOL),
        ("message", descriptor_pb2.FieldDescriptorProto.TYPE_STRING),
        ("storeId", descriptor_pb2.FieldDescriptorProto.TYPE_STRING),
    ],
    1,
):
    f = _gsss_resp.field.add()
    f.name = name
    f.number = idx
    f.type = typ
f4 = _gsss_resp.field.add()
f4.name = "lowStockItems"
f4.number = 4
f4.type = descriptor_pb2.FieldDescriptorProto.TYPE_MESSAGE
f4.type_name = ".retailer.intelligence.LowStockItem"
f4.label = descriptor_pb2.FieldDescriptorProto.LABEL_REPEATED

# 7. GetStoreDailySummaryRequest
_gsds_req = _file_proto.message_type.add()
_gsds_req.name = "GetStoreDailySummaryRequest"
for idx, (name, typ) in enumerate(
    [
        ("storeId", descriptor_pb2.FieldDescriptorProto.TYPE_STRING),
        ("periodType", descriptor_pb2.FieldDescriptorProto.TYPE_STRING),
        ("targetDate", descriptor_pb2.FieldDescriptorProto.TYPE_STRING),
    ],
    1,
):
    f = _gsds_req.field.add()
    f.name = name
    f.number = idx
    f.type = typ

# 8. GetStoreDailySummaryResponse
_gsds_resp = _file_proto.message_type.add()
_gsds_resp.name = "GetStoreDailySummaryResponse"
for idx, (name, typ) in enumerate(
    [
        ("success", descriptor_pb2.FieldDescriptorProto.TYPE_BOOL),
        ("message", descriptor_pb2.FieldDescriptorProto.TYPE_STRING),
        ("storeId", descriptor_pb2.FieldDescriptorProto.TYPE_STRING),
        ("period", descriptor_pb2.FieldDescriptorProto.TYPE_STRING),
        ("periodStartUtc", descriptor_pb2.FieldDescriptorProto.TYPE_STRING),
        ("periodEndUtc", descriptor_pb2.FieldDescriptorProto.TYPE_STRING),
        ("revenue", descriptor_pb2.FieldDescriptorProto.TYPE_DOUBLE),
        ("profit", descriptor_pb2.FieldDescriptorProto.TYPE_DOUBLE),
        ("salesCount", descriptor_pb2.FieldDescriptorProto.TYPE_INT32),
    ],
    1,
):
    f = _gsds_resp.field.add()
    f.name = name
    f.number = idx
    f.type = typ

_fd = _pool.Add(_file_proto)

ActiveStoreInfo = message_factory.GetMessageClass(
    _fd.message_types_by_name["ActiveStoreInfo"]
)
LowStockItem = message_factory.GetMessageClass(
    _fd.message_types_by_name["LowStockItem"]
)
GetActiveStoresRequest = message_factory.GetMessageClass(
    _fd.message_types_by_name["GetActiveStoresRequest"]
)
GetActiveStoresResponse = message_factory.GetMessageClass(
    _fd.message_types_by_name["GetActiveStoresResponse"]
)
GetStoreStockSummaryRequest = message_factory.GetMessageClass(
    _fd.message_types_by_name["GetStoreStockSummaryRequest"]
)
GetStoreStockSummaryResponse = message_factory.GetMessageClass(
    _fd.message_types_by_name["GetStoreStockSummaryResponse"]
)
GetStoreDailySummaryRequest = message_factory.GetMessageClass(
    _fd.message_types_by_name["GetStoreDailySummaryRequest"]
)
GetStoreDailySummaryResponse = message_factory.GetMessageClass(
    _fd.message_types_by_name["GetStoreDailySummaryResponse"]
)


class CoreGrpcCallError(RuntimeError):
    """Safe, structured failure from an Intelligence RPC call."""

    def __init__(self, method: str, status_code: grpc.StatusCode) -> None:
        self.method = method.rsplit("/", 1)[-1]
        self.status_code = status_code
        self.category = {
            grpc.StatusCode.UNAUTHENTICATED: "AUTHENTICATION_FAILED",
            grpc.StatusCode.PERMISSION_DENIED: "AUTHORIZATION_FAILED",
            grpc.StatusCode.DEADLINE_EXCEEDED: "TIMEOUT",
            grpc.StatusCode.UNAVAILABLE: "CORE_UNAVAILABLE",
        }.get(status_code, "CORE_RPC_FAILED")
        super().__init__(f"Core Intelligence RPC failed: {self.category}")


class CoreGrpcClient:
    """Client for Core's retailer.intelligence.IntelligenceService over gRPC."""

    def __init__(
        self,
        target_address: str = "localhost:50054",
        timeout: float = 5.0,
        max_retries: int = 2,
        root_ca_path: str | None = None,
        client_cert_path: str | None = None,
        client_key_path: str | None = None,
    ) -> None:
        self.target_address = target_address
        self.timeout = timeout
        self.max_retries = max_retries
        self.root_ca_path = root_ca_path
        self.client_cert_path = client_cert_path
        self.client_key_path = client_key_path
        self._channel: grpc.Channel | None = None

    def _get_channel(self) -> grpc.Channel:
        if self._channel is None:
            if not all(
                (self.root_ca_path, self.client_cert_path, self.client_key_path)
            ):
                raise RuntimeError(
                    "Secure Core Intelligence gRPC credentials are not configured"
                )
            try:
                root_ca = Path(self.root_ca_path).read_bytes()
                client_cert = Path(self.client_cert_path).read_bytes()
                client_key = Path(self.client_key_path).read_bytes()
            except (OSError, TypeError):
                raise RuntimeError(
                    "Secure Core Intelligence gRPC credentials are unavailable"
                ) from None
            if not all((root_ca, client_cert, client_key)):
                raise RuntimeError(
                    "Secure Core Intelligence gRPC credentials are unavailable"
                )

            credentials = grpc.ssl_channel_credentials(
                root_certificates=root_ca,
                private_key=client_key,
                certificate_chain=client_cert,
            )
            self._channel = grpc.secure_channel(
                self.target_address,
                credentials,
                options=[
                    ("grpc.keepalive_time_ms", 30000),
                    ("grpc.keepalive_timeout_ms", 5000),
                ],
            )
        return self._channel

    def close(self) -> None:
        if self._channel is not None:
            self._channel.close()
            self._channel = None

    def _invoke_with_retry(
        self, method_name: str, serializer: Any, deserializer: Any, request: Any
    ) -> Any:
        channel = self._get_channel()
        invoker = channel.unary_unary(
            method_name,
            request_serializer=serializer,
            response_deserializer=deserializer,
        )

        attempts = 0
        last_error: Exception | None = None

        while attempts <= self.max_retries:
            try:
                response = invoker(
                    request,
                    timeout=self.timeout,
                )
                return response
            except grpc.RpcError as rpc_err:
                code = rpc_err.code()
                last_error = rpc_err
                if code in (
                    grpc.StatusCode.UNAVAILABLE,
                    grpc.StatusCode.DEADLINE_EXCEEDED,
                ):
                    attempts += 1
                    if attempts <= self.max_retries:
                        time.sleep(0.1 * (2 ** (attempts - 1)))
                        continue
                logger.warning(
                    "core_grpc_call_failed",
                    extra={
                        "method": method_name,
                        "code": str(code),
                    },
                )
                raise CoreGrpcCallError(method_name, code) from None
            except Exception:
                logger.error(
                    "core_grpc_unexpected_error",
                    extra={"method": method_name},
                )
                raise CoreGrpcCallError(
                    method_name, grpc.StatusCode.UNKNOWN
                ) from None

        if last_error:
            raise CoreGrpcCallError(method_name, last_error.code()) from None

    def get_active_stores(self, limit: int = 50, page: int = 1) -> list[dict[str, Any]]:
        """Retrieve eligible active stores for proactive scheduling."""
        req = GetActiveStoresRequest(limit=limit, page=page)
        try:
            resp: Any = self._invoke_with_retry(
                "/retailer.intelligence.IntelligenceService/GetActiveStores",
                GetActiveStoresRequest.SerializeToString,
                GetActiveStoresResponse.FromString,
                req,
            )
            if not resp.success:
                raise RuntimeError("Core rejected active-store request")
            return [
                {"store_id": s.storeId, "name": s.name, "timezone": s.timezone}
                for s in resp.stores
            ]
        except Exception:
            logger.warning("get_active_stores_failed")
            raise

    def get_store_stock_summary(self, store_id: str) -> list[dict[str, Any]]:
        """Retrieve authoritative low-stock items for a store."""
        req = GetStoreStockSummaryRequest(storeId=store_id)
        try:
            resp: Any = self._invoke_with_retry(
                "/retailer.intelligence.IntelligenceService/GetStoreStockSummary",
                GetStoreStockSummaryRequest.SerializeToString,
                GetStoreStockSummaryResponse.FromString,
                req,
            )
            if not resp.success:
                raise RuntimeError("Core rejected stock summary request")
            return [
                {
                    "product_id": item.productId,
                    "product_name": item.productName,
                    "sku": item.sku,
                    "available_quantity": float(item.availableQuantity),
                    "low_stock_threshold": float(item.lowStockThreshold),
                }
                for item in resp.lowStockItems
            ]
        except Exception:
            logger.warning(
                "get_store_stock_summary_failed",
                extra={"store_id": store_id},
            )
            raise

    def get_store_daily_summary(
        self,
        store_id: str,
        period_type: str = "COMPLETED_DAY",
        target_date: str | None = None,
    ) -> dict[str, Any]:
        """Retrieve business metrics for the daily briefing."""
        req = GetStoreDailySummaryRequest(
            storeId=store_id,
            periodType=period_type,
            targetDate=target_date or "",
        )
        try:
            resp: Any = self._invoke_with_retry(
                "/retailer.intelligence.IntelligenceService/GetStoreDailySummary",
                GetStoreDailySummaryRequest.SerializeToString,
                GetStoreDailySummaryResponse.FromString,
                req,
            )
            if not resp.success:
                raise RuntimeError("Core rejected daily summary request")
            return {
                "success": bool(resp.success),
                "store_id": resp.storeId,
                "period": resp.period,
                "period_start_utc": resp.periodStartUtc,
                "period_end_utc": resp.periodEndUtc,
                "revenue": float(resp.revenue),
                "profit": float(resp.profit),
                "sales_count": int(resp.salesCount),
            }
        except Exception:
            logger.warning(
                "get_store_daily_summary_failed",
                extra={"store_id": store_id},
            )
            raise
