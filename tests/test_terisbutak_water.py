"""Тесты: единицы, баланс, ограничения водозабора, неотрицательность запаса, реестр точек."""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

SC = Path(__file__).resolve().parents[1] / "scripts"


def load(name):
    spec = importlib.util.spec_from_file_location(name, SC / f"{name}.py")
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


w = load("terisbutak_water")
mp = load("terisbutak_map")


def test_unit_conversions():
    assert w.m3s_to_m3h(0.022) == pytest.approx(79.2)
    assert w.m3s_to_m3d(0.022) == pytest.approx(1900.8)
    assert w.m3s_to_m3d(0.14) == pytest.approx(12096)
    assert w.m3h_to_m3s(w.m3s_to_m3h(0.072)) == pytest.approx(0.072)
    assert w.annual_m3_to_m3s(7.57) == pytest.approx(0.24, abs=1e-3)


def test_control_arithmetic_from_task():
    assert (100 - w.m3s_to_m3h(0.022)) * 24 == pytest.approx(499.2)
    assert all(c["ok"] for c in w.control_arithmetic())


@pytest.mark.parametrize("q,rate,hours,s0,eco,ex", [
    (0.022, 100, 168, 0, 0, 0), (0.022, 80, 24, 5000, 0.0066, 0.003), (0.05, 100, 48, 1000, 0, 0),
    (0.022, 100, 336, 234590, 0.011, 0.003)])
def test_water_balance_closes(q, rate, hours, s0, eco, ex):
    r = w.simulate(q, rate, hours, s0, w.CAP_STATED, eco, ex)
    assert r["river_intake_m3"] + r["storage_draw_m3"] + r["unmet_m3"] == pytest.approx(rate * hours)
    assert r["s_end_m3"] == pytest.approx(s0 + r["refilled_m3"] - r["storage_draw_m3"])


def test_river_intake_limited_by_inflow_minus_deductions():
    r = w.simulate(0.022, 100, 24, 0, w.CAP_STATED, eco=0.0066, existing=0.003)
    assert r["avail_m3h"] == pytest.approx((0.022 - 0.0066 - 0.003) * 3600)
    assert r["river_intake_m3"] == pytest.approx(r["avail_m3h"] * 24)
    big = w.simulate(0.022, 100, 24, 0, w.CAP_STATED, eco=0.05)   # вычеты больше притока
    assert big["avail_m3h"] == 0 and big["river_intake_m3"] == 0


def test_storage_never_negative_and_unmet_when_empty():
    r = w.simulate(0.022, 100, 24, 100, w.CAP_STATED)
    assert r["s_end_m3"] >= 0
    assert r["unmet_m3"] == pytest.approx(499.2 - 100)
    assert r["s_end_m3"] == 0


def test_surplus_refills_but_not_above_capacity():
    r = w.simulate(0.1, 80, 24, 900, 1000)
    assert r["s_end_m3"] == 1000
    assert r["unmet_m3"] == 0


def test_invalid_inputs_rejected():
    with pytest.raises(ValueError):
        w.simulate(-0.1, 80, 24, 0, 10)
    with pytest.raises(ValueError):
        w.simulate(0.022, 80, 24, 20, 10)


def test_all_scenarios_consistent():
    sc = w.scenarios()
    assert len(sc) == 3 * 2 * 6 * 4 * 2
    for r in sc:
        assert r["s_end_m3"] >= 0 and r["unmet_m3"] >= 0
        assert r["river_intake_m3"] + r["storage_draw_m3"] + r["unmet_m3"] == pytest.approx(r["demand_m3h"] * 24 * r["duration_days"], abs=0.1)
        assert r["allowable_river_intake_m3h"] <= r["demand_m3h"] + 1e-9


def test_published_hydrology_values():
    hyd = w.read_csv("hydrology_published.csv")
    assert [float(r["w95_mln_m3"]) for r in hyd] == [7.57, 1.17, 3.91]
    assert [float(r["qmin_1968_m3s"]) for r in hyd] == [0.140, 0.022, 0.072]
    t6 = {(r["object"], r["duration_days"]): r for r in w.read_csv("duration_table6_published.csv")}
    assert float(t6[("mouth", "365")]["y1968_p95"]) == 0.14 and float(t6[("station1", "365")]["y1968_p95"]) == 0.022
    assert float(t6[("station2", "365")]["y1968_p95"]) == 0.072


def test_registry_statuses_and_coordinates():
    rows = mp.load_registry()
    st = {r["id"]: r for r in rows}
    assert mp.dms_to_deg("43°07′39″ N") == pytest.approx(43.1275)
    assert st["P3"]["status"] == "опубликованные координаты" and st["H14253"]["status"] == "точка не установлена"
    assert st["A12"]["lat_dms"] == ""            # полигон 12 га не строится без основания
    d = mp.distance_m((st["P1"]["lat_f"], st["P1"]["lon_f"]), (st["P2"]["lat_f"], st["P2"]["lon_f"]))
    assert 85 < d < 95


def test_geojson_nulls_for_unlocated():
    g = mp.geojson(mp.load_registry())
    assert sum(1 for f in g["features"] if f["geometry"]) == 4
    assert json.dumps(g, ensure_ascii=False)


def test_storage_capacity_sources_sum_and_disagree():
    rows = w.read_csv("storage_capacity_sources.csv")
    for r in rows:
        assert float(r["lake_2_m3"]) + float(r["lake_5_m3"]) + float(r["lake_6_m3"]) == float(r["total_m3"])
    assert [float(r["total_m3"]) for r in rows] == [183900.0, 234590.0]
    assert 183900 - 118000 == 65900                      # остаток после цикла оснежения по ОПЗ
    assert 23923.2 / 183900 < 0.131                      # максимум сценарного запаса относительно меньшей ёмкости


def test_demand_register_confirms_rates_from_opz():
    reg = {r["value"]: r for r in w.demand_register()}
    assert reg["100 м³/ч"]["status"].startswith("подтверждено ОПЗ") and reg["80 м³/ч"]["status"].startswith("подтверждено ОПЗ")
