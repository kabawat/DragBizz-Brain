import pytest

from app.core.exceptions import AppError
from app.orchestrator.model_router import ModelRouter
from app.providers.base import ModelProvider
from app.schemas.chat import GenerationRequest, GenerationResponse


class FakeProvider(ModelProvider):
    @property
    def name(self) -> str:
        return "fake"

    async def generate(self, request: GenerationRequest) -> GenerationResponse:
        return GenerationResponse(
            provider=self.name,
            model="fake-model",
            content=request.messages[-1].content,
        )


def test_router_requires_an_active_provider() -> None:
    router = ModelRouter()

    with pytest.raises(AppError, match="No AI provider"):
        router.get_active()


def test_router_registers_and_selects_provider() -> None:
    provider = FakeProvider()
    router = ModelRouter()

    router.register(provider)
    router.set_active(provider.name)

    assert router.get_active() is provider
    assert router.available_providers() == ("fake",)


def test_router_rejects_duplicate_provider() -> None:
    router = ModelRouter()
    router.register(FakeProvider())

    with pytest.raises(ValueError, match="already registered"):
        router.register(FakeProvider())
