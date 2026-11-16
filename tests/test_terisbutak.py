"""Тесты расчёта зимнего стока Терисбутака на синтетическом ряде (без исходных данных)."""
import importlib.util
import sys
from decimal import Decimal
from pathlib import Path

import pandas as pd

spec = importlib.util.spec_from_file_location(
    "terisbutak_winter", Path(__file__).resolve().parents[1] / "scripts" / "terisbutak_winter.py")
tw = importlib.util.module_from_spec(spec)
sys.modules["terisbutak_winter"] = tw
spec.loader.exec_module(tw)


def frame(value=lambda t: 0.5):
    dates = pd.date_range("2020-01-01", "2023-12-31", freq="D")
    q = [value(t) for t in dates]
    return pd.DataFrame({
        "Дата": dates, "Пост": 14253, "Расход, м³/с": q,
        "Исходная запись": [f"{v:.2f}_" for v in q], "Помета": "_",
        "Зимний сезон": [tw.season_of(t) if t.month in tw.WINTER_MONTHS else None for t in dates]})


def test_inputs_pass_and_season_split():
    d, checks = tw.prepare(frame())
    assert all(c["ok"] for c in checks), [c for c in checks if not c["ok"]]
    seasonal, monthly, incomplete, spread = tw.summaries(d)
    assert list(seasonal.days) == [151, 151, 151]
    assert list(incomplete.days) == [91, 61]
    assert len(monthly) == 15


def test_volume_is_exact_sum_times_86400():
    d, _ = tw.prepare(frame())
    seasonal, *_ = tw.summaries(d)
    assert int(seasonal.volume_m3.iloc[0]) == int(Decimal("0.5") * 151 * 86400)


def test_min7_uses_consecutive_days_and_first_minimum():
    def value(t):
        return 0.2 if pd.Timestamp("2021-01-10") <= t <= pd.Timestamp("2021-01-20") else 0.5
    d, _ = tw.prepare(frame(value))
    seasonal, *_ = tw.summaries(d)
    row = seasonal.iloc[0]
    assert row.min7_mean_m3s == 0.2
    assert str(row.min7_start) == "2021-01-10" and str(row.min7_end) == "2021-01-16"
    assert str(row.min_date) == "2021-01-10"


def test_duplicate_or_gap_fails_continuity():
    df = frame()
    bad = pd.concat([df.iloc[:100], df.iloc[101:]])
    _, checks = tw.prepare(bad)
    assert not next(c for c in checks if c["check"].startswith("непрерывность"))["ok"]


def test_reference_check_detects_difference():
    d, _ = tw.prepare(frame())
    seasonal, monthly, incomplete, spread = tw.summaries(d)
    ref = tw.reference_check(d, seasonal, incomplete)
    assert not ref.ok.all()  # синтетический ряд не равен эталону
