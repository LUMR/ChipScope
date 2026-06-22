import pandas as pd

from app.services.collector.tdx_client import _row_to_time, _parse_minute_df


def test_row_to_time_morning_first_and_last():
    assert _row_to_time(0) == "09:31"
    assert _row_to_time(119) == "11:30"


def test_row_to_time_afternoon_first_and_last():
    assert _row_to_time(120) == "13:01"
    assert _row_to_time(239) == "15:00"


def test_parse_minute_df_basic():
    df = pd.DataFrame(
        {"price": [1210.31, 1205.41], "vol": [1692, 1370], "volume": [1692, 1370]}
    )
    points = _parse_minute_df(df)
    assert points == [
        {"t": "09:31", "price": 1210.31, "vol": 1692},
        {"t": "09:32", "price": 1205.41, "vol": 1370},
    ]


def test_parse_minute_df_empty_or_none():
    assert _parse_minute_df(None) == []
    assert _parse_minute_df(pd.DataFrame()) == []
