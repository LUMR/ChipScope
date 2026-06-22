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


class BackfillStatusOut(BaseModel):
    state: str | None = None          # running / done / error
    window: str | None = None         # "120" / "365" / "all"
    total: int = 0
    done: int = 0       # 已处理（含 failed），进度 = done/total
    ok: int = 0
    failed: int = 0
    started_at: int | None = None
    finished_at: int | None = None
    error: str | None = None


class BackfillTriggerResponse(BaseModel):
    task_id: str
    window: str
