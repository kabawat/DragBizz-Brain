import logging
import time

from app.observability.metrics import MetricsRegistry
from app.orchestrator.model_config import ModelSelectionStore
from app.orchestrator.model_router import ModelRouter
from app.schemas.chat import GenerationRequest, GenerationResponse

logger = logging.getLogger(__name__)


class AiGateway:
    """Single entry point to LLM providers: applies the admin-selected
    provider/model and records provider latency/error metrics."""

    def __init__(
        self,
        model_router: ModelRouter,
        *,
        selection_store: ModelSelectionStore | None = None,
        metrics: MetricsRegistry | None = None,
    ) -> None:
        self._model_router = model_router
        self._selection_store = selection_store
        self._metrics = metrics

    async def generate(self, request: GenerationRequest) -> GenerationResponse:
        provider, model = await self._resolve()
        if model is not None:
            request = request.model_copy(update={"model": model})

        started = time.perf_counter()
        try:
            response = await provider.generate(request)
        except Exception:
            self._record(started, error=True)
            raise
        self._record(started, error=False)
        return response

    async def _resolve(self):
        """Admin selection wins when its provider is registered; otherwise
        fall back to the env-configured active provider and default model."""
        if self._selection_store is not None:
            selection = await self._selection_store.get()
            if selection is not None:
                provider = self._model_router.get(selection.provider)
                if provider is not None:
                    return provider, selection.model
                logger.warning(
                    "Selected provider '%s' is not registered; "
                    "falling back to active provider",
                    selection.provider,
                )
        return self._model_router.get_active(), None

    def _record(self, started: float, *, error: bool) -> None:
        if self._metrics is None:
            return
        self._metrics.record_provider_call(
            (time.perf_counter() - started) * 1000, error=error
        )
