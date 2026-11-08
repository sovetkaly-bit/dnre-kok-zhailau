import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import a5_robustness as a5  # noqa: E402
import dnre_core as c  # noqa: E402


@pytest.fixture(scope="module")
def readings():
    return a5.boundary_readings()


def by_name(rows, start):
    return next(r for r in rows if r.domain.startswith(start))


# ---------------- прочтения
def test_three_readings_reproduce_panel_numbers(readings):
    areas = [r.area_ha for r in readings]
    assert areas[0] == 1002.0
    assert areas[1] == pytest.approx(2094.55, abs=0.01)
    assert areas[2] == pytest.approx(2101.48, abs=0.01)
    assert [r.label for r in readings] == ["1002,00 га", "2094,55 га", "2101,48 га"]


def test_union_is_not_a_sum(readings):
    # 2094.55 + 12.82 = 2107.37 — неверная сумма (двойной счёт пересечения 5.88 га)
    assert readings[2].area_ha < 2094.55 + 12.82
    assert all(abs(r.area_ha - 2107.37) > 1 for r in readings)
    # 2134.59 (все 96 точек подряд) — невалидный полигон, не используется
    assert all(abs(r.area_ha - 2134.59) > 1 for r in readings)


# ---------------- r_flip
def test_r_flip_formula_and_baseline():
    v = ("FAIL", "PASS", "PASS")
    assert a5.r_flip(v, 0) == pytest.approx(2 / 3)
    assert a5.r_flip(v, 1) == pytest.approx(1 / 3)
    assert a5.r_flip(("PASS",) * 3) == 0
    with pytest.raises(ValueError):
        a5.r_flip(v, 3)


# ---------------- домены пакета
def test_package_water_domain_constant_indeterminate(readings):
    for P in (25, 50, 75, 95):
        row = a5.assess(a5.water_domain(P), readings)
        assert row.verdicts == ("INDETERMINATE",) * 3
        assert row.r_flip == 0 and not row.sensitive and not row.depends_on_boundary   # внутренний ноль
        assert row.boundary_independent and not row.na_tg
        assert "not boundary-dependent" in row.reason


def test_package_ccc_independent_of_boundary(readings):
    rows = {d: a5.assess(a5.ccc_domain(d), readings) for d in (10, 20, 30, 40)}
    # те же знаки запаса, что в dnre_core.recreation
    _, rec = c.recreation()
    for r in rec:
        expect = "PASS" if r["margin"] > 0 else "FAIL"
        assert rows[r["density_limit"]].verdicts == (expect,) * 3
    assert not any(r.depends_on_boundary or r.sensitive for r in rows.values())
    assert all(r.boundary_independent for r in rows.values())


# ---------------- A5a: метрики
def test_a5a_r1_i1_values_and_ratio(readings):
    r1 = a5.assess_metric(a5.metric_r1(), readings)
    i1 = a5.assess_metric(a5.metric_i1(), readings)
    assert [round(v, 2) for v in r1.values] == [14.97, 7.16, 7.14]
    assert [round(v, 2) for v in i1.values] == [29.94, 14.32, 14.28]
    assert r1.ratio == pytest.approx(2.0973, abs=1e-3)
    assert i1.ratio == pytest.approx(2.0973, abs=1e-3)
    assert r1.spread_pct == pytest.approx(109.7, abs=0.1)


def test_a5a_interval_input(readings):
    row = a5.assess_metric(a5.metric_r1(10000, 20000), readings)
    assert row.intervals[0] == (pytest.approx(9.980, abs=1e-3), pytest.approx(19.960, abs=1e-3))
    assert row.values[0] == pytest.approx(14.970, abs=1e-3)


def test_a5a_invalid_inputs(readings):
    with pytest.raises(ValueError):
        a5.metric_r1(5000, 1000)
    with pytest.raises(ValueError):
        a5.metric_i1(-1)
    with pytest.raises(ValueError):
        a5.assess_metric(a5.metric_r1(), [])


def test_a5a_dataframe(readings):
    df = a5.metrics_dataframe([a5.assess_metric(m, readings) for m in a5.default_metrics()], readings)
    assert len(df) == 2 and {"max/min", "Разброс, %"} <= set(df.columns)


# ---------------- A5b: порог есть / нет
def test_no_threshold_gives_na_tg_not_zero(readings):
    for m in a5.default_metrics():
        row = a5.assess(a5.metric_threshold_domain(m, None), readings)
        assert row.r_flip is None and row.sensitive is None and row.na_tg
        assert row.depends_on_boundary            # площадь меняет значение
        assert row.verdicts == ("INDETERMINATE",) * 3
        assert "NA (TG)" in row.reason and "а не 0" in row.reason
    df = a5.to_dataframe([a5.assess(a5.metric_threshold_domain(a5.metric_r1(), None), readings)], readings)
    assert df["R_flip"].iloc[0] == "NA (TG)"


def test_user_threshold_flip(readings):
    # R1: 14.97 FAIL, 7.16 PASS, 7.14 PASS при пороге 10
    row = a5.assess(a5.metric_threshold_domain(a5.metric_r1(), 10.0), readings)
    assert row.verdicts == ("FAIL", "PASS", "PASS")
    assert row.sensitive and not row.na_tg and row.r_flip == pytest.approx(2 / 3)
    assert a5.assess(a5.metric_threshold_domain(a5.metric_r1(), 10.0), readings, baseline=1).r_flip == pytest.approx(1 / 3)


def test_threshold_robust_when_far(readings):
    row = a5.assess(a5.metric_threshold_domain(a5.metric_r1(), 100.0), readings)
    assert row.verdicts == ("PASS",) * 3 and not row.sensitive and row.r_flip == 0
    assert row.depends_on_boundary and "граница на этот домен не влияет" in row.reason


def test_interval_metric_with_threshold(readings):
    # L в [10000; 20000], порог 10: при 1002 га R1 в [9.98; 19.96] -> запас пересекает 0
    row = a5.assess(a5.metric_threshold_domain(a5.metric_r1(10000, 20000), 10.0), readings)
    assert row.verdicts[0] == "INDETERMINATE" and row.verdicts[1:] == ("PASS", "PASS")


def test_invalid_threshold():
    with pytest.raises(ValueError):
        a5.metric_threshold_domain(a5.metric_r1(), 0)
    with pytest.raises(ValueError):
        a5.metric_threshold_domain(a5.metric_i1(), -5)


def test_no_invented_threshold_domains():
    assert not hasattr(a5, "density_domain") and not hasattr(a5, "track_share_domain")


# ---------------- полный прогон
def test_run_default():
    mrows, rows, readings = a5.run_a5()
    s = a5.summary(rows)
    assert len(mrows) == 2 and s["domains"] == 10
    assert s["sensitive"] == 0 and s["na_tg"] == 2 and s["depend_on_boundary"] == 2
    assert s["na_independent"] == 8
    # домены пакета (вода, CCC) границу не используют
    assert s["package_domains"] == 8 and s["package_depend"] == 0
    df = a5.to_dataframe(rows, readings)
    assert {"R_flip", "Чувствителен", "Зависит от границы", "Причина"} <= set(df.columns)
    # снаружи: вода и CCC = N/A (not boundary-dependent), R1/I1 = NA (TG), числового 0 нет
    vals = dict(zip(df["Домен"], df["R_flip"]))
    na_ind = [v for k, v in vals.items() if k.startswith(("Зимний", "Рекреационная"))]
    assert len(na_ind) == 8 and set(na_ind) == {"N/A (not boundary-dependent)"}
    assert set(v for k, v in vals.items() if k.startswith(("R1", "I1"))) == {"NA (TG)"}
    assert 0 not in list(df["R_flip"])


def test_run_with_limits_finds_sensitive():
    mets = a5.default_metrics()
    _, rows, _ = a5.run_a5(a5.default_domains(mets, {"R1": 10.0, "I1": 20.0}), metrics=mets)
    s = a5.summary(rows)
    assert s["sensitive"] == 2 and s["na_tg"] == 0


def test_unknown_verdict_rejected(readings):
    bad = a5.Domain("x", "метрика", lambda a: a5.Result("MAYBE"))
    with pytest.raises(ValueError):
        a5.assess(bad, readings)


# ---------------- панель (streamlit/geopandas может отсутствовать в окружении)
def test_streamlit_app_runs_and_has_a5_tab():
    pytest.importorskip("streamlit")
    pytest.importorskip("geopandas")
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=120).run()
    assert not at.exception, [e.value for e in at.exception]
    assert len(at.tabs) >= 7
    assert any("A5" in t.label for t in at.tabs)


def test_a5a_numbers_unchanged(readings):
    r1 = a5.assess_metric(a5.metric_r1(), readings)
    i1 = a5.assess_metric(a5.metric_i1(), readings)
    assert [round(v, 2) for v in r1.values] == [14.97, 7.16, 7.14]
    assert [round(v, 2) for v in i1.values] == [29.94, 14.32, 14.28]
