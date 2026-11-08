"""Запуск: python -m pytest -q   (или python tests/test_core.py)"""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import dnre_core as c
import cadastre_check as cc


def close(a, b, tol=0.01):
    assert abs(a - b) < tol, (a, b)


def test_winter_priority_reference():  # значения winter_priority.csv пакета DNRE v1.0
    ref = {25: (377300.0, 204190.0, 0.0), 50: (337016.298, 163906.298, 0.0),
           75: (277872.0, 104762.0, 0.0), 95: (82088.209, 0.0, 91021.791)}
    for P, (free, snow, unserved) in ref.items():
        r = c.winter_priority(P)
        close(r["free_winter_m3"], free); close(r["snow_served_m3"], snow); close(r["domestic_unserved_m3"], unserved)
    close(c.winter_priority(25, domestic_m3_day=2481)["snow_served_fraction"], 0.6683352112676056, 1e-9)


def test_decision_rule():
    assert c.decision(0.1, 0.2) == "PASS" and c.decision(-0.2, -0.1) == "FAIL"
    assert c.decision(-0.1, 0.1) == "INDETERMINATE" and c.decision(0.1, 0.2, False) == "INDETERMINATE"


def test_cadastre_reconciliation():
    P, _, _ = cc.read_parcels(str(ROOT / "data" / "parcels_unofficial_osmanov.geojson"))
    tab, res = cc.check(P, 1.0)
    assert res["found"] == 4 and tab["Валиден"].all()
    close(res["geodesic_sum_ha"], 1001.625664, 1e-5)
    close(res["geodesic_diff_ha"], -0.374336, 1e-5)
    close(res["geodesic_diff_pct"], -0.037359, 1e-5)
    assert res["overlaps_ha"] == 0


def test_96_points_geometry():
    from gis_core import load_contours
    g, _ = load_contours()
    d = g.set_index("name")
    assert not d.loc["все 96 точек", "valid"] and d.loc["контур 1–88", "valid"] and d.loc["контур 89–96", "valid"]
    close(d.loc["контур 1–88", "utm_ha"], 2094.55, 0.01); close(d.loc["контур 89–96", "utm_ha"], 12.82, 0.01)


if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            f(); print("OK", n)
