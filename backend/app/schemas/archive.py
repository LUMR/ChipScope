from pydantic import BaseModel


class ArchiveStatusOut(BaseModel):
    state: str | None = None
    trade_date: str | None = None
    total: int = 0
    done: int = 0       # 已处理数（进度 = done/total）
    ok: int = 0         # 成功数
    failed: int = 0
    started_at: int | None = None
    finished_at: int | None = None
    error: str | None = None


class ArchiveTriggerResponse(BaseModel):
    task_id: str
    trade_date: str
