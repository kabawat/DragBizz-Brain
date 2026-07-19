from abc import ABC, abstractmethod

from app.schemas.chat import GenerationRequest, GenerationResponse


class ModelProvider(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        raise NotImplementedError

    @abstractmethod
    async def generate(self, request: GenerationRequest) -> GenerationResponse:
        raise NotImplementedError
