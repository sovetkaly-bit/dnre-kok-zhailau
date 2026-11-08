"""ГИС-часть (геопандас/шэйпли/pyproj вместо десктопного QGIS): контуры по 96 координатам,
площади в UTM 43N и геодезическая, буферы. Порт gis_check.py пакета DNRE."""
from pathlib import Path
import pandas as pd
import geopandas as gpd
import plotly.graph_objects as go
from shapely.geometry import Polygon
from shapely.validation import explain_validity
from pyproj import Geod

HERE = Path(__file__).parent
CRS_UTM = 32643


def load_points():
    return pd.read_csv(HERE / "data" / "project_coordinates.csv")


def load_contours():
    df = load_points()
    xy = list(zip(df.longitude, df.latitude))
    parts = {"все 96 точек": xy, "контур 1–88": xy[:88], "контур 89–96": xy[88:]}
    geod = Geod(ellps="WGS84")
    recs = []
    for name, pts in parts.items():
        g = Polygon(pts)
        ga, _ = geod.geometry_area_perimeter(g)
        recs.append(dict(name=name, n=len(pts), geometry=g, geodesic_ha=abs(ga) / 1e4))
    gdf = gpd.GeoDataFrame(recs, crs=4326)
    gdf["utm_ha"] = gdf.to_crs(CRS_UTM).area / 1e4
    gdf["valid"] = gdf.to_crs(CRS_UTM).geometry.is_valid
    gdf["validity"] = [explain_validity(g) for g in gdf.to_crs(CRS_UTM).geometry]
    return gdf, recs


DECLARED_HA = 1002.0
LBL_PARCELS = "Неофициальная геометрия через OSMANOV.KZ; требует официального подтверждения"
LBL_ALL96 = "Все 96 точек подряд"
LBL_1_88 = "Контур по опубликованным координатам (точки 1–88); назначение и порядок соединения требуют уточнения"
LBL_89_96 = "Отдельная группа опубликованных точек (89–96); назначение не подтверждено"
LABELS = {"все 96 точек": LBL_ALL96, "контур 1–88": LBL_1_88, "контур 89–96": LBL_89_96}
M_GEOD = "геодезически: pyproj.Geod, эллипсоид WGS84, вход EPSG:4326"
M_UTM = "плоско: Shapely, UTM 43N (EPSG:32643)"


def geometry_control(gdf):
    """Контроль геометрии: validity, площади двумя методами, расхождение с заявленными 1002 га.
    Для invalid-полигона площади не интерпретируются (формальные значения — только диагностика).
    Геометрия не исправляется и не упрощается."""
    rows = []
    for _, r in gdf.iterrows():
        base = {"Вариант": LABELS[r["name"]]}
        if not r.valid:
            rows.append({**base, "Геометрия": "INVALID — самопересечение",
                         "Площадь геодезическая, га": "не интерпретируется",
                         "Площадь UTM 43N, га": "не интерпретируется",
                         "Отличие геодезической от 1002 га": "—", "Статус": "SPATIAL / INDETERMINATE",
                         "_формальная": f"геодезическая {r.geodesic_ha:.2f} га; UTM {r.utm_ha:.2f} га"})
        else:
            comparable = r.geodesic_ha > 100
            d = r.geodesic_ha - DECLARED_HA
            rows.append({**base, "Геометрия": "валидна",
                         "Площадь геодезическая, га": f"{r.geodesic_ha:.2f}",
                         "Площадь UTM 43N, га": f"{r.utm_ha:.2f}",
                         "Отличие геодезической от 1002 га": (f"{d:+,.1f} га ({r.geodesic_ha / DECLARED_HA:.2f}×)".replace(",", " ") if comparable else "не сопоставимо"),
                         "Статус": "SPATIAL / INDETERMINATE", "_формальная": ""})
    return pd.DataFrame(rows)


def overlap_stats(gdf):
    u = gdf.to_crs(CRS_UTM).set_index("name").geometry
    a, b = u["контур 1–88"], u["контур 89–96"]
    return dict(intersection_ha=a.intersection(b).area / 1e4, union_ha=a.union(b).area / 1e4)


def summary_table(gdf):
    return geometry_control(gdf).drop(columns="_формальная")


def buffer_ll(gdf, d):
    if d <= 0:
        return None
    row = gdf[gdf.name == "контур 1–88"].to_crs(CRS_UTM)
    return row.buffer(d, quad_segs=32).to_crs(4326).iloc[0]


def _xy(poly):
    x, y = poly.exterior.xy
    return list(x), list(y)


def contour_figure(gdf, buffer_m=300, parcels=None):
    fig = go.Figure()
    if parcels is not None:  # кадастровые полигоны (неофициальный источник), в WGS84
        for _, r in parcels.iterrows():
            for poly in getattr(r.geometry, "geoms", [r.geometry]):
                x, y = _xy(poly)
                fig.add_scatter(x=x, y=y, mode="lines", fill="toself", fillcolor="rgba(74,144,217,0.25)",
                                line=dict(color="#4a90d9", width=1), name="КН " + r.cadastral_number + ": " + LBL_PARCELS,
                                hoverinfo="name")
    colors = {"все 96 точек": "#999", "контур 1–88": "#e8730c", "контур 89–96": "#2b6"}
    for _, r in gdf.iterrows():
        x, y = _xy(r.geometry)
        fig.add_scatter(x=x, y=y, mode="lines", name=LABELS[r["name"]] + ("" if r.valid else ": INVALID (самопересечение)"), line=dict(color=colors[r["name"]], width=2, dash=("solid" if r.valid else "dash")))
    b = buffer_ll(gdf, buffer_m)
    if b is not None:
        x, y = _xy(b)
        fig.add_scatter(x=x, y=y, mode="lines", name=f"буфер {buffer_m} м",
                        line=dict(color="#4a90d9", dash="dot"))
    pts = load_points()
    fig.add_scatter(x=pts.longitude, y=pts.latitude, mode="markers", name="точки",
                    marker=dict(size=4, color="#333"), text=pts.point, hovertemplate="№%{text}")
    fig.update_layout(height=620, margin=dict(t=10), legend=dict(orientation="h", y=-0.18, font=dict(size=10)), xaxis_title="долгота", yaxis_title="широта",
                      yaxis_scaleanchor="x", yaxis_scaleratio=1.37)
    return fig
