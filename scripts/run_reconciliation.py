"""Сверка: 4 кадастровых полигона (неофициальная геометрия OSMANOV.KZ) ↔ 96 опубликованных точек.
Запуск: python scripts/run_reconciliation.py  ->  results/reconciliation.json, results/reconciliation_parcels.csv
Геометрия не исправляется и не упрощается."""
import json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import cadastre_check as cc
from gis_core import overlap_stats, load_contours, M_GEOD, M_UTM, DECLARED_HA, LBL_PARCELS, LBL_1_88, LBL_89_96

SRC = ROOT / "data" / "parcels_unofficial_osmanov.geojson"
parcels, _, field = cc.read_parcels(str(SRC))
tab, res = cc.check(parcels, 1.0)
gdf, _ = load_contours()
out = {
    "source": {"parcels": LBL_PARCELS, "file": SRC.name, "retrieved": "2026-11-08", "egkn_boundary_status": "ND"},
    "methods": {"geodesic": M_GEOD, "planar": M_UTM},
    "declared_sum_ha": DECLARED_HA,
    "parcels_geodesic_sum_ha": round(res["geodesic_sum_ha"], 6),
    "geodesic_diff_ha": round(res["geodesic_diff_ha"], 6),
    "geodesic_diff_pct": round(res["geodesic_diff_pct"], 6),
    "parcels_union_utm_ha": round(res["union_ha"], 6),
    "parcels_mutual_overlap_ha": round(res["overlaps_ha"], 6),
    "all_parcels_valid": bool(tab["Валиден"].all()),
    "points_1_88": {"label": LBL_1_88, **{k: (round(v, 4) if isinstance(v, float) else v) for k, v in res["контур 1–88"].items()}},
    "points_89_96": {"label": LBL_89_96, **{k: (round(v, 4) if isinstance(v, float) else v) for k, v in res["контур 89–96"].items()}},
    "contours": {r["name"]: {"valid": bool(r.valid), "geodesic_ha": round(r.geodesic_ha, 4), "utm_ha": round(r.utm_ha, 4)} for _, r in gdf.iterrows()},
    "overlap_89_96_with_1_88_utm_ha": round(overlap_stats(gdf)["intersection_ha"], 4),
    "union_89_96_and_1_88_utm_ha": round(overlap_stats(gdf)["union_ha"], 4),
}
(ROOT / "results").mkdir(exist_ok=True)
(ROOT / "results" / "reconciliation.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
tab.to_csv(ROOT / "results" / "reconciliation_parcels.csv", index=False, encoding="utf-8-sig")
print(json.dumps(out, ensure_ascii=False, indent=2))
