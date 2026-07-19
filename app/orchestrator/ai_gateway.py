from app.orchestrator.model_router import ModelRouter
from app.schemas.chat import GenerationRequest, GenerationResponse


class AiGateway:
    def __init__(self, model_router: ModelRouter) -> None:
        self._model_router = model_router

    async def generate(self, request: GenerationRequest) -> GenerationResponse:
        provider = self._model_router.get_active()
        return await provider.generate(request)
