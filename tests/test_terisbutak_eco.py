"""Тесты: единицы, баланс и пределы вычетов для сверки записки ASM-KGGALL-RPT-0003."""
import importlib.util
import sys
from pathlib import Path

import pytest

p = Path(__file__).resolve().parents[1] / "scripts" / "terisbutak_eco.py"
spec = importlib.util.spec_from_file_location("terisbutak_eco", p)
e = importlib.util.module_from_spec(spec)
sys.modules["terisbutak_eco"] = e
spec.loader.exec_module(e)


def test_task_arithmetic():
    assert e.m3s_to_m3d(0.164) == pytest.approx(14169.6)
    assert e.m3s_to_m3d(0.164) * 30 == pytest.approx(425088)
    assert e.winter_norm_total() == 220553
    assert all(c["ok"] for c in e.unit_checks())


@pytest.mark.parametrize("q,dem", [(0.164, 1250), (0.164, 1742), (0.164, 2700), (0.164, 4303), (0.022, 1250), (0.022, 2700)])
def test_balance_gross_equals_demand_plus_deductions_or_deficit(q, dem):
    gross, allowed, deficit = e.max_deductions(q, dem)
    assert gross + deficit == pytest.approx(dem + allowed)       # баланс при предельных вычетах
    assert allowed >= 0 and deficit >= 0
    assert not (allowed > 0 and deficit > 0)


def test_demand_above_inflow_gives_zero_deductions():
    gross, allowed, deficit = e.max_deductions(0.022, 2700)
    assert allowed == 0 and deficit == pytest.approx(2700 - 1900.8)


def test_deductions_decrease_as_demand_grows():
    vals = [e.max_deductions(0.164, d)[1] for d in (1250, 1742, 2700, 4303)]
    assert vals == sorted(vals, reverse=True)
    assert e.max_deductions(0.164, 4303)[1] == pytest.approx(14169.6 - 4303)


def test_bases_are_not_merged():
    rows = e.demand_scenarios()
    assert {r["flow_basis"][:5] for r in rows} == {"0,164", "0,022"}
    assert all(not r["can_merge"] for r in e.basis_comparison())


def test_mean_eco_reference_exceeds_winter_minimum_so_uniform_use_is_unsafe():
    assert e.W_ECO_ANNUAL / (365 * 86400) > e.Q_NOTE_30D
