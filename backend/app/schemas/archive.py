from pydantic import BaseModel


class ArchiveStatusOut(BaseModel):
    state: str | None = None
    trade_date: str | None = None
    total: int = 0
    ok: int = 0
    failed: int = 0
    started_at: int | None = None
    finished_at: int | None = None
    error: str | None = None


class ArchiveTriggerResponse(BaseModel):
    task_id: str
    trade_date: str
