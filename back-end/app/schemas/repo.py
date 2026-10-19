from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class RepoStatus(StrEnum):
    not_connected = "not_connected"
    indexing = "indexing"
    ready = "ready"
    updating = "updating"
    error = "error"
    reauth_required = "reauth_required"


class RepoConnectRequest(BaseModel):
    url: str = Field(min_length=1, max_length=500, examples=["https://github.com/owner/name"])
    github_token: str | None = Field(
        default=None, max_length=255, description="Нужен для приватных репозиториев (PAT)."
    )
    replace: bool = Field(
        default=False, description="Подтверждение замены уже подключённого репозитория."
    )


class RepoStatusResponse(BaseModel):
    status: RepoStatus
    url: str | None = None
    owner: str | None = None
    name: str | None = None
    last_commit: str | None = None
    webhook_registered: bool = False
    connected_at: datetime | None = None
