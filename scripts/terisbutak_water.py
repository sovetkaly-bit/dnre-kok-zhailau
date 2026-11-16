"""Историческая гидрология, водозабор и накопители Терисбутака.
Запуск: python scripts/terisbutak_water.py OUTPUT_DIR
Данные: только опубликованные таблицы (data/terisbutak) и агрегаты по календарным годам; суточный ряд не используется."""
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "terisbutak"
SEC_H = 3600.0
SEC_D = 86400.0

# --- единицы и баланс ---------------------------------------------------------------

def m3s_to_m3h(q):
    return q * SEC_H


def m3s_to_m3d(q):
    return q * SEC_D


def m3h_to_m3s(v):
    return v / SEC_H


def annual_m3_to_m3s(w_mln_m3, days=365.0):
    return w_mln_m3 * 1e6 / (days * SEC_D)


def simulate(q_in, demand_m3h, hours, s0, cap, eco=0.0, existing=0.0, refill=True):
    """Почасовой баланс при постоянном притоке q_in (м³/с).
    Забор из реки = min(спрос, приток − экорасход − существующие отборы), не меньше нуля.
    Недостаток подаётся из накопителя, но не больше текущего запаса; остаток — необеспеченный объём.
    Если река даёт больше спроса, излишек пополняет накопитель до ёмкости cap."""
    if min(q_in, demand_m3h, hours, s0, cap, eco, existing) < 0:
        raise ValueError("отрицательные входные данные")
    if s0 > cap:
        raise ValueError("начальный запас больше ёмкости")
    avail = max(0.0, (q_in - eco - existing) * SEC_H)
    s = float(s0)
    river = draw = unmet = refilled = 0.0
    for _ in range(int(round(hours))):
        take = min(demand_m3h, avail)
        deficit = demand_m3h - take
        use = min(deficit, s)
        s -= use
        unmet += deficit - use
        river += take
        draw += use
        if refill and avail > take:
            add = min(avail - take, cap - s)
            s += add
            refilled += add
    return {"avail_m3h": avail, "river_intake_m3": river, "storage_draw_m3": draw, "unmet_m3": unmet,
            "refilled_m3": refilled, "s_end_m3": s, "demand_total_m3": demand_m3h * hours}


# --- чтение опубликованных таблиц -----------------------------------------------------

def read_csv(name):
    with open(DATA / name, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path, rows, fields=None):
    fields = fields or list(rows[0].keys())
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def exceedance_position(w, table2_row):
    """Ориентировочная позиция годового объёма по табл. 2 (линейная интерполяция между опубликованными квантилями)."""
    pts = [(25, float(table2_row["p25"])), (50, float(table2_row["p50"])), (75, float(table2_row["p75"])),
           (80, float(table2_row["p80"])), (90, float(table2_row["p90"])), (95, float(table2_row["p95"])),
           (97, float(table2_row["p97"])), (99, float(table2_row["p99"]))]
    if w > pts[0][1]:
        return "<25 % (выше верхнего опубликованного квантиля)"
    if w < pts[-1][1]:
        return ">99 %"
    for (p1, w1), (p2, w2) in zip(pts, pts[1:]):
        if w2 <= w <= w1:
            return f"{p1 + (w1 - w) / (w1 - w2) * (p2 - p1):.1f} %"
    return "н/д"


# --- 2. историческая гидрология -------------------------------------------------------

def hydrology_check():
    hyd = read_csv("hydrology_published.csv")
    obs = read_csv("observed_14253_annual_aggregates.csv")
    obs_min_all = min(float(r["min_m3s"]) for r in obs)
    mouth_f = float(hyd[0]["catchment_km2"])
    rows = []
    for r in hyd:
        q = float(r["qmin_1968_m3s"])
        f = float(r["catchment_km2"])
        w = float(r["w95_mln_m3"])
        scaled = obs_min_all * f / mouth_f
        rows.append({
            "object": r["object"], "catchment_km2": f, "basis": r["basis"],
            "w95_mln_m3": w, "w95_mean_m3s": round(annual_m3_to_m3s(w), 4),
            "w95_module_mln_m3_per_km2": round(w / f, 4),
            "qmin_1968_m3s": q, "qmin_1968_m3h": round(m3s_to_m3h(q), 1), "qmin_1968_m3d": round(m3s_to_m3d(q), 1),
            "observed_min_mouth_2020_2023_m3s": obs_min_all,
            "observed_min_scaled_by_area_m3s": round(scaled, 4),
            "ratio_scaled_obs_to_qmin_1968": round(scaled / q, 3),
            "note": ("опубликованные наблюдения поста-аналога 1947–2011; в 2020–2023 минимум сопоставим по данным поста № 14253"
                     if r["basis"] == "наблюдения" else
                     "расходы восстановлены по гидрологической аналогии; наблюдений на створе нет; пересчёт минимума поста по площади — ориентир, не наблюдение"),
        })
    t2 = {r["object"]: r for r in read_csv("table2_annual_published.csv")}["mouth"]
    ann = []
    for r in obs:
        w = int(r["volume_m3"]) / 1e6
        ann.append({"year": r["year"], "days": r["days"], "coverage": f"01.01.{r['year']}–31.12.{r['year']}",
                    "volume_mln_m3": round(w, 3), "min_m3s": r["min_m3s"], "min_date": r["min_date"],
                    "position_in_table2": exceedance_position(w, t2),
                    "note": "агрегат по календарному году, без заполнения пропусков; позиция по табл. 2 ориентировочная, не оценка обеспеченности"})
    return rows, ann


def duration_conversions():
    rows = []
    for r in read_csv("duration_table6_published.csv"):
        q = float(r["y1968_p95"])
        rows.append({"object": r["object"], "duration_days": r["duration_days"], "q_1968_m3s": q,
                     "q_1968_m3h": round(m3s_to_m3h(q), 1), "q_1968_m3d": round(m3s_to_m3d(q), 1)})
    return rows


# --- 3. водозабор и накопители --------------------------------------------------------

CAP_STATED = 234590.0          # №2 116 250 + №5 28 100 + №6 90 240, ОоВВ с. 229; тип ёмкости в источнике не указан
LAKES = {"№2": 116250.0, "№5": 28100.0, "№6": 90240.0}
Q_ST1 = 0.022                  # м³/с, Qmin 1968 г., створ №1, табл. 6 с. 109
DURATIONS_D = (1, 7, 14)
RATES_M3H = (80, 100)
S0_GRID = (0.0, 5000.0, 20000.0, 50000.0, 100000.0, CAP_STATED)
ECO_FRAC = (0.0, 0.1, 0.3, 0.5)    # доля притока, параметрический допуск
EXISTING_M3S = (0.0, 0.003)        # существующие отборы, допуск


def scenarios(q=Q_ST1, cap=CAP_STATED):
    rows = []
    for d in DURATIONS_D:
        for rate in RATES_M3H:
            for s0 in S0_GRID:
                for ef in ECO_FRAC:
                    for ex in EXISTING_M3S:
                        eco = q * ef
                        res = simulate(q, rate, 24 * d, s0, cap, eco, ex)
                        need = max(0.0, rate * 24 * d - res["river_intake_m3"])
                        rows.append({
                            "duration_days": d, "demand_m3h": rate, "s0_m3": s0, "s0_share_of_cap": round(s0 / cap, 3),
                            "q_in_m3s": q, "q_in_m3h": round(m3s_to_m3h(q), 3),
                            "eco_m3s": round(eco, 5), "eco_share_of_q": ef, "existing_m3s": ex,
                            "avail_river_m3h": round(res["avail_m3h"], 3),
                            "allowable_river_intake_m3h": round(min(res["avail_m3h"], rate), 3),
                            "river_intake_m3": round(res["river_intake_m3"], 2),
                            "storage_draw_m3": round(res["storage_draw_m3"], 2),
                            "min_storage_to_cover_m3": round(need, 2),
                            "unmet_m3": round(res["unmet_m3"], 2),
                            "unmet_share": round(res["unmet_m3"] / res["demand_total_m3"], 4),
                            "s_end_m3": round(res["s_end_m3"], 2),
                            "covered": res["unmet_m3"] < 1e-6})
    return rows


def control_arithmetic():
    q = m3s_to_m3h(Q_ST1)
    return [
        {"item": "0,022 м³/с в м³/ч", "value": round(q, 3), "expected": 79.2, "ok": abs(q - 79.2) < 1e-9},
        {"item": "разница при 100 м³/ч за 24 ч до вычетов, м³", "value": round((100 - q) * 24, 3), "expected": 499.2,
         "ok": abs((100 - q) * 24 - 499.2) < 1e-9},
        {"item": "разница при 80 м³/ч за 24 ч до вычетов, м³", "value": round((80 - q) * 24, 3),
         "expected": 19.2, "ok": abs((80 - q) * 24 - 19.2) < 1e-9},
        {"item": "сумма ёмкостей озёр №2+№5+№6, м³", "value": sum(LAKES.values()), "expected": 234590.0, "ok": sum(LAKES.values()) == 234590.0},
        {"item": "общее водопотребление 905 565+1 961,28+16 520+355 000, м³/год", "value": round(905565 + 1961.28 + 16520 + 355000, 2),
         "expected": 1279046.28, "ok": abs(905565 + 1961.28 + 16520 + 355000 - 1279046.28) < 1e-6},
        {"item": "89 000 м³/мес в л/с при месяце 365/12 сут", "value": round(89000 / (365 / 12 * SEC_D) * 1000, 2), "expected": 33.9,
         "ok": abs(89000 / (365 / 12 * SEC_D) * 1000 - 33.9) < 0.05},
        {"item": "2 700 м³/сут в м³/ч", "value": 2700 / 24, "expected": 112.5, "ok": 2700 / 24 == 112.5},
    ]


def demand_register():
    """Сверка значений спроса и водозабора с первичным документом (ОоВВ Almaty Superski, LoadFile/280880)."""
    src = "ОоВВ LoadFile/280880"
    return [
        {"value": "100 м³/ч", "unit": "м³/ч", "purpose": "водозабор (по заданию)", "source": "не найдено", "page": "—", "status": "не подтверждено первичным документом", "note": "в доступных фрагментах ОоВВ значения нет; сценарий параметрический"},
        {"value": "80 м³/ч", "unit": "м³/ч", "purpose": "водозабор (по заданию)", "source": "не найдено", "page": "—", "status": "не подтверждено первичным документом", "note": "в доступных фрагментах ОоВВ значения нет; сценарий параметрический"},
        {"value": "2 700 м³/сут (=112,5 м³/ч)", "unit": "м³/сут", "purpose": "хозяйственно-питьевое водоснабжение, ноябрь–март", "source": src, "page": "232–233", "status": "подтверждено", "note": "1 350 м³/сут в остальное время; не совпадает ни с 100, ни с 80 м³/ч"},
        {"value": "355 000 м³/год", "unit": "м³/год", "purpose": "оснежение (90,7 га)", "source": src, "page": "5; 229; 235", "status": "подтверждено", "note": "доли XI и XII по 37,5 %; для I и II в тексте «46154» (повреждено)"},
        {"value": "41–137 тыс. м³/мес, в среднем 89 тыс. м³ (33,9 л/с)", "unit": "м³/мес", "purpose": "водоотбор из р. Казачка", "source": src, "page": "232–233", "status": "подтверждено", "note": "помесячной разбивки в источнике нет; 33,9 л/с соответствует месяцу 365/12 сут"},
        {"value": "116 250 / 28 100 / 90 240 м³ (озёра №2/№5/№6), итого 234 590 м³", "unit": "м³", "purpose": "искусственные озёра-накопители", "source": src, "page": "229", "status": "подтверждено; тип ёмкости не указан", "note": "в тексте нет различия полный/полезный/номинальный; озёра №1, №3, №4 не упомянуты"},
        {"value": "1 279 046,28 м³/год", "unit": "м³/год", "purpose": "общее водопотребление", "source": src, "page": "229", "status": "подтверждено арифметикой", "note": "905 565 + 1 961,28 + 16 520 + 355 000"},
        {"value": "220 553 м³ за ноябрь–март", "unit": "м³", "purpose": "зимний спрос (по заданию)", "source": "не найдено", "page": "—", "status": "не воспроизведено", "note": "из доступных чисел не получается: хозяйственно-питьевое за 151 сут = 407 700 м³; оснежение XI+XII = 266 250 м³"},
        {"value": "экологический попуск", "unit": "—", "purpose": "требование к водозабору", "source": src, "page": "229; 232", "status": "числовое значение не приведено", "note": "сценарии с долей 0/10/30/50 % притока — допущение"},
        {"value": "существующие водозаборы", "unit": "—", "purpose": "—", "source": src, "page": "54", "status": "оросительные каналы ниже по р. Большая Алматинка; на участке других нет", "note": "величина отбора на створе №1 неизвестна; допущение 0 и 0,003 м³/с"},
    ]


def winter_demand_components():
    days = 151
    dom = 2700 * days
    sn = 355000
    rows = [
        {"component": "хозяйственно-питьевое (2 700 м³/сут × 151 сут)", "m3": dom, "basis": "ОоВВ с. 232, расчёт", "double_count_risk": "нет"},
        {"component": "оснежение, ноябрь (37,5 % от 355 000)", "m3": sn * 0.375, "basis": "ОоВВ с. 229", "double_count_risk": "берётся из озёр; наполнение озёр отдельно не складывать"},
        {"component": "оснежение, декабрь (37,5 % от 355 000)", "m3": sn * 0.375, "basis": "ОоВВ с. 229", "double_count_risk": "то же"},
        {"component": "оснежение, январь–март (остаток 25 %)", "m3": sn * 0.25, "basis": "допущение: в источнике «46154»", "double_count_risk": "то же"},
        {"component": "наполнение озёр", "m3": 0.0, "basis": "не добавляется: это перенос воды, а не потребление", "double_count_risk": "исключено"},
    ]
    rows.append({"component": "итого без наполнения (проверка, не эталон 220 553)", "m3": sum(r["m3"] for r in rows), "basis": "сумма", "double_count_risk": "—"})
    return rows


def main(out):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    hyd, ann = hydrology_check()
    write_csv(out / "Hydrology_Check.csv", hyd)
    write_csv(out / "Observed_Annual_Mouth_14253.csv", ann)
    write_csv(out / "Q1968_Duration_Converted.csv", duration_conversions())
    write_csv(out / "Demand_Source_Register.csv", demand_register())
    write_csv(out / "Winter_Demand_Components.csv", winter_demand_components())
    ctl = control_arithmetic()
    write_csv(out / "Control_Arithmetic.csv", ctl)
    sc = scenarios()
    write_csv(out / "Scenarios_Station1.csv", sc)
    short = [r for r in sc if r["s0_share_of_cap"] == 0 or r["s0_m3"] in (5000.0, 20000.0)]
    deficit = [r for r in sc if not r["covered"]]
    base = [r for r in sc if r["eco_share_of_q"] == 0.0 and r["existing_m3s"] == 0.0 and r["s0_m3"] == 0.0]
    write_csv(out / "Scenarios_Station1_NoStorage_NoDeductions.csv", base)
    bad = [c for c in ctl if not c["ok"]]
    lines = ["# Отчёт проверок: гидрология и сценарии", "",
             f"Сценариев: {len(sc)}; с необеспеченным объёмом: {len(deficit)}; контрольная арифметика: {len(ctl) - len(bad)}/{len(ctl)} верно.", "",
             "## Сценарии при нулевом запасе, без экорасхода и отборов (Q = 0,022 м³/с = 79,2 м³/ч)", "",
             "| сут | спрос, м³/ч | забор из реки, м³ | необеспечено, м³ | мин. запас, м³ |", "|---|---|---|---|---|"]
    for r in base:
        lines.append(f"| {r['duration_days']} | {r['demand_m3h']} | {r['river_intake_m3']:.1f} | {r['unmet_m3']:.1f} | {r['min_storage_to_cover_m3']:.1f} |")
    (out / "Check_Report_Scenarios.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    for c in ctl:
        print(("OK  " if c["ok"] else "FAIL"), c["item"], c["value"])
    print(f"сценариев {len(sc)}, дефицит в {len(deficit)}")
    if bad:
        sys.exit(1)


if __name__ == "__main__":
    main(sys.argv[1])
