from app.core.exceptions import AppError
from app.providers.base import ModelProvider


class ModelRouter:
    def __init__(self) -> None:
        self._providers: dict[str, ModelProvider] = {}
        self._active_provider: str | None = None

    def register(self, provider: ModelProvider) -> None:
        if provider.name in self._providers:
            raise ValueError(f"Provider '{provider.name}' is already registered")
        self._providers[provider.name] = provider

    def set_active(self, provider_name: str) -> None:
        if provider_name not in self._providers:
            raise ValueError(f"Provider '{provider_name}' is not registered")
        self._active_provider = provider_name

    def get_active(self) -> ModelProvider:
        if self._active_provider is None:
            raise AppError(
                code="AI_PROVIDER_NOT_CONFIGURED",
                message="No AI provider has been configured",
                status_code=503,
            )
        return self._providers[self._active_provider]

    def available_providers(self) -> tuple[str, ...]:
        return tuple(sorted(self._providers))
