"""自选股筹码补全：parse_days / 进程内状态 / 编排主流程测试。"""
import pytest

from app.services.chip_backfill import (
    ALL_DAYS,
    parse_days,
    get_backfill_status,
    set_backfill_status,
    is_backfill_running,
    set_backfill_running,
    reset_backfill_state,
)


def test_parse_days_all():
    assert parse_days("all") == ALL_DAYS


def test_parse_days_numeric():
    assert parse_days("120") == 120
    assert parse_days("365") == 365


def test_parse_days_invalid():
    with pytest.raises(ValueError):
        parse_days("999")
    with pytest.raises(ValueError):
        parse_days("")


def test_state_get_set_reset():
    reset_backfill_state()
    assert get_backfill_status() is None
    assert is_backfill_running() is False
    set_backfill_running(True)
    assert is_backfill_running() is True
    set_backfill_status({"state": "running", "window": "365"})
    assert get_backfill_status() == {"state": "running", "window": "365"}
    reset_backfill_state()
    assert get_backfill_status() is None
    assert is_backfill_running() is False
