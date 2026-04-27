"""沙箱 Pydantic schemas"""

import uuid
from datetime import datetime

from pydantic import BaseModel


class SandboxCreate(BaseModel):
    developer_id: str
    app_id: str


class SandboxOut(BaseModel):
    sandbox_id: str
    sandbox_url: str
    test_tenant_id: uuid.UUID
    status: str
    expires_at: datetime

    model_config = {"from_attributes": True}
