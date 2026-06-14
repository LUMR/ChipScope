from app.services.chip_pattern import recognize, recognize_trend


def test_single_peak_dense():
    r = recognize(concentration=0.12, peak_price=15.0, peak_ratio=0.45, current_price=15.0)
    assert r["name"] == "单峰密集"
    assert r["confidence"] > 0


def test_high_position_single_peak():
    # 现价 16 > 峰位 15×1.05=15.75 → 高位单峰
    r = recognize(concentration=0.12, peak_price=15.0, peak_ratio=0.45, current_price=16.0)
    assert r["name"] == "高位单峰"


def test_low_position_single_peak():
    # 现价 14 < 峰位 15×0.95=14.25 → 低位单峰
    r = recognize(concentration=0.12, peak_price=15.0, peak_ratio=0.45, current_price=14.0)
    assert r["name"] == "低位单峰"


def test_divergence():
    r = recognize(concentration=0.35, peak_price=15.0, peak_ratio=0.10, current_price=15.0)
    assert r["name"] == "筹码发散"


def test_no_pattern():
    r = recognize(concentration=0.20, peak_price=15.0, peak_ratio=0.20, current_price=15.0)
    assert r["name"] == "无明显形态"


def test_trend_down():
    series = [10.0 - i * 0.1 for i in range(30)]  # 单调降
    r = recognize_trend(series)
    assert r["name"] == "筹码下移"


def test_trend_up():
    series = [10.0 + i * 0.1 for i in range(30)]  # 单调升
    r = recognize_trend(series)
    assert r["name"] == "筹码上移"
