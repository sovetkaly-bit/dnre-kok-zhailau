"""v1.2: сверка официальных кадастровых полигонов с опубликованными 96 точками.
Вход: GeoJSON/KML/SHP/GPKG. Ничего не подгоняется и не «чинится»: невалидные официальные
полигоны не исправляются (make_valid не применяется), сверка в этом случае прекращается."""
import re
import pandas as pd
import geopandas as gpd
from shapely.geometry import Point
from pyproj import Geod
from gis_core import HERE, CRS_UTM, load_contours, load_points, DECLARED_HA, LBL_1_88, LBL_89_96, M_GEOD, M_UTM

_GEOD = Geod(ellps="WGS84")


def geodesic_ha(geom_wgs84):
    """Абсолютная геодезическая площадь (га) геометрии в EPSG:4326 на эллипсоиде WGS84."""
    return abs(_GEOD.geometry_area_perimeter(geom_wgs84)[0]) / 1e4

KN_RE = re.compile(r"\d\d:\d\d\d:\d\d\d:\d+")
FALLBACK = ["cadastral_number", "cadastral_no", "kn", "cadnum", "cad_num", "cn", "name", "id"]


def declared():
    return pd.read_csv(HERE / "data" / "cadastre_declared.csv", dtype={"cadastral_number": str})


def _read_raw(path):
    p = str(path)
    if p.lower().endswith((".geojson", ".json")):
        # GDAL принимает 20:315:057:032 за время (20:31:00) -> GeoJSON читаем напрямую, строками
        import json
        from shapely.geometry import shape
        fc = json.load(open(p, encoding="utf-8"))
        feats = fc["features"] if fc.get("type") == "FeatureCollection" else [fc]
        g = gpd.GeoDataFrame([{**f.get("properties", {}), "geometry": shape(f["geometry"]) if f.get("geometry") else None} for f in feats], crs=4326)
    else:
        g = gpd.read_file(p)
    return g.set_crs(4326) if g.crs is None else g


def text_columns(g):
    return [c for c in g.columns if c != "geometry" and (g[c].dtype == object or pd.api.types.is_string_dtype(g[c]))]


def guess_field(g):
    """Сначала ищем колонку, значения которой похожи на кадастровый номер; потом name/id."""
    best, score = None, 0
    for c in text_columns(g):
        n = g[c].astype(str).str.contains(KN_RE).sum()
        if n > score:
            best, score = c, n
    if best:
        return best
    return next((k for k in FALLBACK if k in g.columns), None)


def read_parcels(path, field=None):
    """Возвращает (GeoDataFrame в UTM, список колонок, использованная колонка)."""
    g = _read_raw(path)
    cols = text_columns(g)
    key = field or guess_field(g)
    if key is None:
        raise ValueError("Не найдено поле с кадастровым номером; выберите его вручную")
    n_null = int(g.geometry.isna().sum())
    g = g.rename(columns={key: "cadastral_number"})
    g = g[g.geometry.notna() & ~g.geometry.is_empty]
    if g.empty:
        raise ValueError(f"Во всех записях ({n_null}) геометрия пустая (geometry: null) — границы не получены, статус ND / SPATIAL")
    g["cadastral_number"] = g["cadastral_number"].astype(str).str.strip()
    return g[["cadastral_number", "geometry"]].to_crs(CRS_UTM), cols, key


def check(parcels_utm, tol_pct=1.0):
    dec = declared()
    nums = set(dec.cadastral_number)
    found = parcels_utm[parcels_utm.cadastral_number.isin(nums)]
    n_found = found.cadastral_number.nunique()
    if n_found == 0:
        return None, dict(stop=f"0/4 участков идентифицировано → ND / SPATIAL; проверьте поле кадастрового номера.")
    bad = [kn for kn, grp in found.groupby("cadastral_number") if not grp.geometry.union_all().is_valid]
    rows = []
    for _, d in dec.iterrows():
        m = found[found.cadastral_number == d.cadastral_number]
        if m.empty:
            rows.append({"КН": d.cadastral_number, "Заявлено, га": d.declared_area_ha, "Полигон": "не загружен",
                         "Геодезическая, га": "—", "Откл. геод., %": "—", "UTM 43N, га": "—", "Откл. UTM, %": "—",
                         "Валиден": "—", "Статус": "ND"}); continue
        geom = m.geometry.union_all()
        a = geom.area / 1e4
        gw = m.to_crs(4326).geometry.union_all()
        ag = geodesic_ha(gw)
        pct_g = 100 * (ag - d.declared_area_ha) / d.declared_area_ha
        pct = 100 * (a - d.declared_area_ha) / d.declared_area_ha
        rows.append({"КН": d.cadastral_number, "Заявлено, га": d.declared_area_ha, "Полигон": "загружен",
                     "Геодезическая, га": f"{ag:.6f}", "Откл. геод., %": f"{pct_g:+.4f}",
                     "UTM 43N, га": f"{a:.6f}", "Откл. UTM, %": f"{pct:+.4f}", "Валиден": bool(geom.is_valid),
                     "Статус": "INVALID" if not geom.is_valid else ("согласуется" if abs(pct_g) <= tol_pct else "РАСХОЖДЕНИЕ")})
    tab = pd.DataFrame(rows)
    if bad:
        return tab, dict(stop="Невалидная геометрия официального полигона: " + ", ".join(bad) +
                         ". Пространственная сверка остановлена; полигон не исправлялся (make_valid не применяется).")
    cad = found.geometry.union_all()
    cad_ha = cad.area / 1e4
    gsum = sum(geodesic_ha(found[found.cadastral_number == kn].to_crs(4326).geometry.union_all()) for kn in nums if kn in set(found.cadastral_number))
    res = {"union_ha": cad_ha, "union_vs_1002_ha": cad_ha - DECLARED_HA, "found": n_found,
           "geodesic_sum_ha": gsum, "geodesic_diff_ha": gsum - DECLARED_HA,
           "geodesic_diff_pct": 100 * (gsum - DECLARED_HA) / DECLARED_HA,
           "overlaps_ha": sum(a.intersection(b).area for i, a in enumerate(found.geometry.tolist()) for b in found.geometry.tolist()[i + 1:]) / 1e4}
    pts = load_points()
    pg = gpd.GeoDataFrame(pts, geometry=[Point(x, y) for x, y in zip(pts.longitude, pts.latitude)], crs=4326).to_crs(CRS_UTM)
    inside = pg.geometry.within(cad) | pg.geometry.touches(cad)
    groups = {"контур 1–88": pg.point.between(1, 88), "контур 89–96": pg.point.between(89, 96)}  # ключи внутренние
    cont, _ = load_contours()
    u = cont.to_crs(CRS_UTM).set_index("name").geometry
    for name, mask in groups.items():
        g = u[name]
        inter = g.intersection(cad).area / 1e4
        res[name] = dict(points_total=int(mask.sum()), points_inside=int((inside & mask).sum()),
                         area_ha=g.area / 1e4, inside_ha=inter, outside_ha=g.area / 1e4 - inter,
                         share_inside_pct=100 * inter / (g.area / 1e4))
    return tab, res
