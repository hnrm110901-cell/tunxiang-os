"""低代码构建器 Pydantic schemas"""

from datetime import datetime
from typing import Any, Dict, Optional
from uuid import UUID

from pydantic import BaseModel


class ProjectCreate(BaseModel):
    developer_id: str
    project_name: str
    template_type: str


class ProjectUpdate(BaseModel):
    project_name: Optional[str] = None
    canvas: Optional[Dict[str, Any]] = None
    generated_code: Optional[str] = None
    status: Optional[str] = None


class ProjectOut(BaseModel):
    project_id: UUID
    developer_id: str
    project_name: str
    template_type: str
    status: str
    preview_url: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class TemplateOut(BaseModel):
    template_id: UUID
    template_type: str
    template_name: str
    description: str = ""
    usage_count: int = 0

    model_config = {"from_attributes": True}
