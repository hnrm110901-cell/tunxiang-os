"""MCP Pydantic schemas"""

from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class MCPServerCreate(BaseModel):
    app_id: str
    server_name: str = Field(..., max_length=200)
    transport: str = Field(default="streamable-http", max_length=30)
    base_url: Optional[str] = Field(default=None, max_length=500)
    capabilities: dict = Field(default={"tools": [], "resources": [], "prompts": []})
    health_endpoint: Optional[str] = Field(default=None, max_length=500)


class MCPServerOut(BaseModel):
    server_id: str
    app_id: str
    server_name: str
    transport: str
    base_url: Optional[str]
    capabilities: dict
    health_status: str
    tool_count: Optional[int] = None

    model_config = {"from_attributes": True}


class MCPToolCreate(BaseModel):
    server_id: str
    tool_name: str = Field(..., max_length=200)
    description: str = Field(default="")
    input_schema: dict = Field(default={})
    output_schema: dict = Field(default={})
    ontology_bindings: list = Field(default=[])
    trust_tier_required: str = Field(default="T1", max_length=10)


class MCPToolOut(BaseModel):
    tool_id: str
    server_id: str
    tool_name: str
    description: str
    input_schema: dict
    output_schema: dict
    ontology_bindings: list
    trust_tier_required: str
    call_count: int
    avg_latency_ms: int

    model_config = {"from_attributes": True}


class OntologyBindingCreate(BaseModel):
    app_id: str
    entity_name: str = Field(..., max_length=50)
    access_mode: str = Field(..., max_length=10)
    allowed_fields: list = Field(default=[])
    constraints: list = Field(default=[])


class OntologyBindingOut(BaseModel):
    app_id: str
    entity_name: str
    access_mode: str
    allowed_fields: list
    constraints: list

    model_config = {"from_attributes": True}


class ManifestSubmit(BaseModel):
    app_id: str
    manifest_content: dict


class ManifestValidationResult(BaseModel):
    valid: bool
    errors: list[str] = Field(default=[])
    warnings: list[str] = Field(default=[])
