from typing import Literal
from pydantic import BaseModel, Field, ConfigDict


class RulesConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: str = Field(min_length=1)
    max_output_tokens: int = Field(ge=64, le=8192)
    prompt_prefix: str = Field(min_length=1)
    output_format: Literal["json", "text"] = "json"


class RoutingEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    intent: str = Field(min_length=1)
    tool_type: Literal["skill", "mcp", "llm"]
    tool_name: str = Field(min_length=1)
    fallback: str | None = None


class RoutingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    entries: list[RoutingEntry]
