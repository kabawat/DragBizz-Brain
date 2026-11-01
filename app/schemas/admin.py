from pydantic import BaseModel, Field


class ModelSelectionRequest(BaseModel):
    provider: str = Field(min_length=1, max_length=64)
    model: str = Field(min_length=1, max_length=128)


class ModelSelectionResponse(BaseModel):
    provider: str
    model: str
    available_providers: list[str] = Field(serialization_alias="availableProviders")
    allowed_models: list[str] = Field(serialization_alias="allowedModels")
    updated_by: str | None = Field(default=None, serialization_alias="updatedBy")
    updated_at: str | None = Field(default=None, serialization_alias="updatedAt")

    model_config = {"populate_by_name": True}


class TenantUsageResponse(BaseModel):
    store_id: str = Field(serialization_alias="storeId")
    day: str
    requests: int
    input_tokens: int = Field(serialization_alias="inputTokens")
    output_tokens: int = Field(serialization_alias="outputTokens")
    total_tokens: int = Field(serialization_alias="totalTokens")
    cost_usd: float = Field(serialization_alias="costUsd")
    daily_token_cap: int = Field(serialization_alias="dailyTokenCap")
    daily_cost_cap_usd: float = Field(serialization_alias="dailyCostCapUsd")

    model_config = {"populate_by_name": True}
