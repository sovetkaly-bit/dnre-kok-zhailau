"""Тесты A2. Все числа ниже СИНТЕТИЧЕСКИЕ (проверка кода), к Кок-Жайлау отношения не имеют."""
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import a2_winter_minimum as a2  # noqa: E402
import dnre_core as c  # noqa: E402


def synth(q_nat=100.0, w_div=0.0, q_min=40.0, over=None):
    """СИНТЕТИКА: 12 месяцев с одинаковыми значениями; over = {месяц: dict(поле=значение)}."""
    over = over or {}
    rows = []
    for m in range(1, 13):
        r = dict(month=m, Q_nat_m3=q_nat, W_div_m3=w_div, Q_min_m3=q_min)
        r.update(over.get(m, {}))
        rows.append(r)
    return pd.DataFrame(rows)


def test_template_is_empty_and_gives_nd_data():
    df = a2.template_dataframe()
    assert len(df) == 12 and list(df.columns) == a2.TEMPLATE_COLS
    res, verdict, why = a2.assess(df)
    assert verdict == "INDETERMINATE" and all(r.cause == "DATA" for r in res)
    assert "ND(DATA)" in why
    # файл шаблона в репозитории совпадает с функцией и не содержит значений
    f = pd.read_csv(ROOT / "data" / "templates" / "a2_winter_minimum_template.csv", dtype=str).fillna("")
    assert (f.drop(columns="month") == "").all().all()


def test_margin_matches_core_formula():
    # Q_nat=100, W=30, Q_min=40 -> (100-30-40)/(100-40) = 0.5 = dnre_core.margin(100, 40, 70, "lower")
    res, verdict, _ = a2.assess(synth(w_div=30))
    assert res[0].lo == res[0].hi == pytest.approx(0.5)
    assert res[0].lo == pytest.approx(c.margin(100, 40, 70, "lower"))
    assert verdict == "PASS"


def test_missing_diversion_is_not_zero():
    df = synth(over={12: dict(W_div_m3="")})
    res, verdict, why = a2.assess(df)
    assert res[11].verdict == "INDETERMINATE" and res[11].cause == "DATA"
    assert verdict == "INDETERMINATE"           # не PASS: пустой забор не считается нулём
    assert "XII" in why
    res0, v0, _ = a2.assess(synth(over={12: dict(W_div_m3=0)}))
    assert res0[11].verdict == "PASS" and v0 == "PASS"   # явный ноль допустим


def test_winter_fail_gives_block_fail():
    res, verdict, why = a2.assess(synth(w_div=0, over={12: dict(W_div_m3=70)}))   # остаток 30 < Q_min 40
    assert res[11].verdict == "FAIL" and res[11].lo < 0
    assert verdict == "FAIL" and "XII" in why


def test_non_winter_fail_does_not_decide_block():
    res, verdict, _ = a2.assess(synth(over={7: dict(W_div_m3=70)}))
    assert res[6].verdict == "FAIL" and verdict == "PASS"      # июль не входит в XI–III


def test_interval_crossing_zero_is_indeterminate():
    # W_div в [20; 70]: запас от (100-70-40)/60 < 0 до (100-20-40)/60 > 0
    res, verdict, _ = a2.assess(synth(over={1: dict(W_div_m3="", W_div_lo=20, W_div_hi=70)}))
    assert res[0].verdict == "INDETERMINATE" and res[0].lo < 0 < res[0].hi
    assert verdict == "INDETERMINATE"


def test_interval_corners_monotone():
    lo, hi = a2.month_margin((90, 110), (10, 20), (30, 50))
    assert lo == pytest.approx(c.margin(90, 50, 70, "lower"))
    assert hi == pytest.approx(c.margin(110, 30, 100, "lower"))


def test_natural_flow_not_above_norm():
    res, verdict, _ = a2.assess(synth(q_nat=40, q_min=40))
    assert all(r.cause == "NORM" for r in res) and verdict == "INDETERMINATE"


def test_invalid_inputs():
    with pytest.raises(ValueError):
        a2.assess(synth(over={1: dict(W_div_m3=-1)}))
    with pytest.raises(ValueError):
        a2.assess(synth(over={1: dict(Q_nat_lo=100)}))                      # интервал наполовину
    with pytest.raises(ValueError):
        a2.assess(synth(over={1: dict(Q_nat_lo=120, Q_nat_hi=90)}))
    with pytest.raises(ValueError):
        a2.assess(synth(over={1: dict(Q_nat_m3="abc")}))
    with pytest.raises(ValueError):
        a2.assess(pd.concat([synth(), synth().iloc[[0]]]))                  # месяц дважды
    with pytest.raises(ValueError):
        a2.assess(pd.DataFrame({"x": [1]}))


def test_missing_months_are_nd():
    res, verdict, _ = a2.assess(synth().iloc[:6])
    assert [r.cause for r in res[6:]] == ["DATA"] * 6 and verdict == "INDETERMINATE"


def test_decimal_comma_and_conversion():
    res, _, _ = a2.assess(synth(over={1: dict(Q_nat_m3="100,0")}))
    assert res[0].verdict == "PASS"
    assert a2.m3s_to_month(1.0, 1) == 86400 * 31
    assert a2.m3s_to_month(1.0, 2) == 86400 * 28
    with pytest.raises(ValueError):
        a2.m3s_to_month(1.0, 13)


def test_dataframe_columns():
    res, _, _ = a2.assess(synth())
    df = a2.to_dataframe(res)
    assert len(df) == 12 and {"Месяц", "Вердикт", "Причина"} <= set(df.columns)


def test_streamlit_a2_tab_default_nd():
    pytest.importorskip("streamlit")
    pytest.importorskip("geopandas")
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=120).run()
    assert not at.exception, [e.value for e in at.exception]
    assert any("A2" in t.label for t in at.tabs)
    assert any(m.label.startswith("Вердикт блока A2") and m.value == "INDETERMINATE" for m in at.metric)
