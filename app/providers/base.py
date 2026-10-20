from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from app.schemas.chat import GenerationRequest, GenerationResponse


class ModelProvider(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        raise NotImplementedError

    @abstractmethod
    async def generate(self, request: GenerationRequest) -> GenerationResponse:
        raise NotImplementedError

    async def generate_stream(self, request: GenerationRequest) -> AsyncIterator[str]:
        response = await self.generate(request)
        if response.content:
            yield response.content
