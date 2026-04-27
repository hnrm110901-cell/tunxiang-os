"""Agent编排工作流 Pydantic schemas"""

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class WorkflowCreate(BaseModel):
    workflow_name: str
    description: str = ""
    creator_id: str
    steps: List[Dict[str, Any]]
    trigger: Optional[Dict[str, Any]] = None
    estimated_value_fen: int = 0


class WorkflowOut(BaseModel):
    workflow_id: UUID
    workflow_name: str
    description: str
    status: str
    steps: List[Dict[str, Any]] = Field(default=[])
    trigger: Optional[Dict[str, Any]] = None
    install_count: int = 0
    avg_execution_ms: int = 0
    success_rate: float = 0.0

    model_config = {"from_attributes": True}


class WorkflowRunStart(BaseModel):
    store_id: Optional[str] = None
    trigger_type: str = "manual"
    trigger_data: Dict[str, Any] = Field(default={})


class WorkflowRunOut(BaseModel):
    id: UUID
    workflow_id: UUID
    status: str
    steps_completed: int = 0
    steps_total: int = 0
    total_tokens: int = 0
    total_cost_fen: int = 0
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None

    model_config = {"from_attributes": True}
