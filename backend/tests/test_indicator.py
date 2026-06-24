# backend/tests/test_indicator.py
import numpy as np
from numpy.testing import assert_array_almost_equal
from app.services.indicator import ema, sma, sma_tdx, hhv, llv


def test_ema_seed_and_recurrence():
    # EMA[0]=x[0]; α=2/3 → EMA[1]=2/3·1 + 1/3·10 = 4.0
    out = ema([10.0, 1.0], 2)
    assert_array_almost_equal(out, [10.0, 4.0])


def test_sma_simple_window():
    out = sma([1.0, 2.0, 3.0, 4.0], 2)
    assert np.isnan(out[0])
    assert_array_almost_equal(out[1:], [1.5, 2.5, 3.5])


def test_sma_n1_is_identity():
    assert_array_almost_equal(sma([1.0, 2.0, 3.0], 1), [1.0, 2.0, 3.0])


def test_sma_tdx_recurrence():
    # SMA[0]=x[0]; M=3 → SMA[1]=(10·2+1)/3=7
    out = sma_tdx([10.0, 1.0], 3)
    assert_array_almost_equal(out, [10.0, 7.0])


def test_hhv_llv_window_inclusive():
    h = hhv([1.0, 5.0, 3.0, 2.0], 2)   # 含当根的过去2根最大
    l = llv([1.0, 5.0, 3.0, 2.0], 2)
    assert_array_almost_equal(h[2:], [5.0, 3.0])  # i=2:max(5,3)=5; i=3:max(3,2)=3
    assert_array_almost_equal(l[2:], [3.0, 2.0])
