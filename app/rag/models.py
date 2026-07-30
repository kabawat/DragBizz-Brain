from pydantic import BaseModel


class RetrievedChunk(BaseModel):
    id: str = ""
    text: str
    metadata: dict[str, str]
    score: float
