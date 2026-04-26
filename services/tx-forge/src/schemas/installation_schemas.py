"""安装 Pydantic schemas"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class InstallCreate(BaseModel):
    app_id: str
    store_ids: list[str] = Field(default=[])


class InstallOut(BaseModel):
    install_id: str
    app_id: str
    status: str
    installed_at: datetime
    store_ids: list[str]

    model_config = {"from_attributes": True}
