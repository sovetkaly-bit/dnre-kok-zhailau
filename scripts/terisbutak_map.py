"""Реестр точек, GeoJSON и карта PNG для Терисбутака.
Запуск: python scripts/terisbutak_map.py OUTPUT_DIR
Исходные суточные ряды не используются. Подложки нет (сеть недоступна): карта строится в метрах от точки отсчёта."""
import csv
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "data" / "terisbutak" / "points_registry.csv"
STATUSES = ("опубликованные координаты", "приближённая привязка по схеме", "точка не установлена")


def dms_to_deg(text):
    """43°07′39″ N -> 43.1275; E и N положительные, S и W отрицательные."""
    t = text.strip()
    hemi = t[-1].upper()
    nums = [float(x) for x in __import__("re").findall(r"\d+(?:\.\d+)?", t)]
    deg = nums[0] + (nums[1] if len(nums) > 1 else 0) / 60 + (nums[2] if len(nums) > 2 else 0) / 3600
    return -deg if hemi in "SW" else deg


def load_registry(path=REGISTRY):
    with open(path, encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        if r["status"] not in STATUSES:
            raise ValueError(f"{r['id']}: недопустимый статус {r['status']!r}")
        if r["lat_dms"]:
            r["lat_f"] = dms_to_deg(r["lat_dms"])
            r["lon_f"] = dms_to_deg(r["lon_dms"])
            if abs(r["lat_f"] - float(r["lat"])) > 1e-5 or abs(r["lon_f"] - float(r["lon"])) > 1e-5:
                raise ValueError(f"{r['id']}: десятичные координаты не совпадают с DMS")
        elif r["status"] != "точка не установлена":
            raise ValueError(f"{r['id']}: нет координат при статусе {r['status']}")
    return rows


def to_xy(lat, lon, lat0, lon0):
    """Локальная проекция в метрах (малые расстояния)."""
    return ((lon - lon0) * 111320.0 * math.cos(math.radians(lat0)), (lat - lat0) * 110574.0)


def distance_m(a, b):
    x, y = to_xy(b[0], b[1], a[0], a[1])
    return math.hypot(x, y)


def geojson(rows):
    feats = []
    for r in rows:
        geom = ({"type": "Point", "coordinates": [r["lon_f"], r["lat_f"]]} if r["lat_dms"] else None)
        props = {k: r[k] for k in ("id", "name", "status", "crs", "accuracy", "date", "source", "page", "note")}
        feats.append({"type": "Feature", "geometry": geom, "properties": props})
    return {"type": "FeatureCollection", "name": "terisbutak_points",
            "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"}}, "features": feats}


def make_map(rows, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    pts = [r for r in rows if r["lat_dms"]]
    lat0 = sum(r["lat_f"] for r in pts) / len(pts)
    lon0 = sum(r["lon_f"] for r in pts) / len(pts)
    xy = {r["id"]: to_xy(r["lat_f"], r["lon_f"], lat0, lon0) for r in pts}
    fig = plt.figure(figsize=(12, 8.2))
    ax = fig.add_axes([0.07, 0.45, 0.60, 0.46])
    colors = {"P1": "#1f6fb2", "P2": "#1f6fb2", "P3": "#c8501e", "P4": "#2c8a4b"}
    for r in pts:
        x, y = xy[r["id"]]
        ax.scatter(x, y, s=90, color=colors[r["id"]], edgecolor="black", zorder=3)
        q = r["name"].split("Q=")[1].split(" ")[0]
        dx, dy = {"P1": (-120, 110), "P2": (-220, -170), "P3": (-60, 90), "P4": (40, -120)}[r["id"]]
        ax.annotate(f"№{r['id'][1]}  Q={q} м³/с", (x, y), (x + dx, y + dy), fontsize=9,
                    arrowprops=dict(arrowstyle="-", color="gray"))
    ax.set_aspect("equal")
    xs = [v[0] for v in xy.values()]
    ys = [v[1] for v in xy.values()]
    ax.set_xlim(min(xs) - 300, max(xs) + 300)
    ax.set_ylim(min(ys) - 250, max(ys) + 300)
    ax.set_xlabel("Восток от точки отсчёта, м")
    ax.set_ylabel("Север от точки отсчёта, м")
    ax.grid(alpha=0.3)
    ax.set_title("Гидрометрические точки апреля 2026 г., р. Казачка (Терисбутак), WGS84\nбез картографической подложки; положение относительное", fontsize=11)
    x0 = min(xs) - 250
    y0 = min(ys) - 200
    ax.plot([x0, x0 + 500], [y0, y0], color="black", lw=4)
    ax.text(x0 + 250, y0 + 25, "500 м", ha="center", fontsize=9)
    ax.annotate("N", xy=(max(xs) + 230, max(ys) + 190), xytext=(max(xs) + 230, max(ys) + 60), ha="center",
                arrowprops=dict(arrowstyle="->", lw=1.5), fontsize=11)
    # врезка для близких точек 1 и 2
    ins = fig.add_axes([0.09, 0.07, 0.30, 0.28])
    cx = (xy["P1"][0] + xy["P2"][0]) / 2
    cy = (xy["P1"][1] + xy["P2"][1]) / 2
    for k in ("P1", "P2"):
        ins.scatter(*xy[k], s=90, color=colors[k], edgecolor="black", zorder=3)
        ins.annotate("№" + k[1], xy[k], (xy[k][0], xy[k][1] + 12), ha="center", fontsize=9)
    d12 = distance_m((pts[0]["lat_f"], pts[0]["lon_f"]), (pts[1]["lat_f"], pts[1]["lon_f"]))
    ins.set_xlim(cx - 70, cx + 70)
    ins.set_ylim(cy - 45, cy + 55)
    ins.set_aspect("equal")
    ins.plot([cx - 60, cx - 40], [cy - 38, cy - 38], color="black", lw=3)
    ins.text(cx - 50, cy - 33, "20 м", ha="center", fontsize=8)
    ins.set_title(f"Врезка: №1 и №2, расстояние ≈{d12:.0f} м (Q=0,356 м³/с в обеих)", fontsize=8)
    ax.text(0.99, 0.02, "Врезка с точками №1 и №2 — внизу слева", transform=ax.transAxes, ha="right", fontsize=8, color="gray")
    ins.tick_params(labelsize=7)
    ins.grid(alpha=0.3)
    ax.indicate_inset_zoom(ins, edgecolor="gray") if False else None
    # легенда и статусы
    lax = fig.add_axes([0.70, 0.08, 0.29, 0.84])
    lax.axis("off")
    lines = ["Легенда и статусы объектов", "",
             "● опубликованные координаты (WGS84):", "   №1, №2, №3, №4 — точки гидрометрии, апрель 2026", "",
             "Не нанесены — точка не установлена:"]
    for r in rows:
        if r["status"] == "точка не установлена":
            lines.extend(["   • " + w if i == 0 else "     " + w for i, w in enumerate(__import__("textwrap").wrap(r["name"], 40))])
    lines += ["", "Приближённой привязки по схеме нет;", "полигон площадки 12 га не строится:", "основания геопривязки не найдены.", "",
              "Створы №1 и №2 и пост № 14253 не считаются", "совпадающими с проектным створом:", "документального подтверждения нет.", "",
              "Точность координат — до 1″.", "Источник точек: gov.kz, PDF 2026-06-01", "(страница не проверена)."]
    lax.text(0, 1, "\n".join(lines), va="top", fontsize=8.6, family="DejaVu Sans")
    fig.savefig(path, dpi=160)
    plt.close(fig)


def main(out):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    rows = load_registry()
    (out / "Points_Registry.csv").write_text(REGISTRY.read_text(encoding="utf-8"), encoding="utf-8")
    (out / "Points.geojson").write_text(json.dumps(geojson(rows), ensure_ascii=False, indent=1), encoding="utf-8")
    make_map(rows, out / "Map_Points.png")
    n = sum(1 for r in rows if r["lat_dms"])
    print(f"объектов {len(rows)}, нанесено {n}")


if __name__ == "__main__":
    main(sys.argv[1])
