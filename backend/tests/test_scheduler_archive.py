import pytest

from app.scheduler import build_scheduler, daily_minute_archive


def test_build_scheduler_has_minute_archive_job():
    sched = build_scheduler()
    job_ids = [j.id for j in sched.get_jobs()]
    assert "daily_minute_archive" in job_ids
    job = next(j for j in sched.get_jobs() if j.id == "daily_minute_archive")
    assert job.trigger.__class__.__name__ == "CronTrigger"
    fields = {f.name: str(f) for f in job.trigger.fields}
    assert fields["hour"] == "15"
    assert fields["minute"] == "30"


@pytest.mark.asyncio
async def test_daily_minute_archive_calls_archive(monkeypatch):
    """daily_minute_archive 应调用 archive_minute_quotes(当天)。"""
    import app.scheduler as sched_mod
    called = {}

    async def _fake_archive(session_factory, tdx, trade_date, on_progress=None):
        called["trade_date"] = trade_date

    class _FakeTdx:
        def close(self): pass

    monkeypatch.setattr(sched_mod, "archive_minute_quotes", _fake_archive)
    monkeypatch.setattr(sched_mod, "TdxClient", lambda: _FakeTdx())
    await daily_minute_archive()
    assert "trade_date" in called
