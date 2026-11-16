"""Сверка показателей записки ASM-KGGALL-RPT-0003 с арифметикой и сценариями спроса.
Запуск: python scripts/terisbutak_eco.py OUTPUT_DIR
Ряды разных створов не объединяются: каждая основа расхода считается отдельно."""
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "terisbutak"
SEC_D = 86400.0

Q_NOTE_30D = 0.164        # м³/с, минимальный 30-суточный расход, 95 %, створ не назван
Q_NOTE_MEAN = 0.303       # м³/с, среднегодовой, 95 %, створ не назван
W_ECO_ANNUAL = 6.7e6      # м³/год, годовой экологический сток, 95 %, створ не назван
Q_HIST_ST1 = 0.022        # м³/с, суточный минимум 1968 г., створ №1 (расчёт по аналогии)
CATCH_MOUTH, CATCH_ST1 = 31.0, 4.79

WINTER_NORMS = {"XI": (1742, 30), "XII": (1480, 31), "I": (1521, 31), "II": (1304, 28), "III": (1250, 31)}
DEMANDS = [  # метка, м³/сут, источник
    ("норма III (минимум опубликованных)", 1250, "приложение gov.kz по тексту монографии"),
    ("норма XI (максимум опубликованных)", 1742, "приложение gov.kz по тексту монографии"),
    ("2 700 м³/сут", 2700, "ОоВВ с. 232–233"),
    ("проектный максимум 4 303 м³/сут", 4303, "ответы Департаменту экологии, водохозяйственный баланс"),
]


def m3s_to_m3d(q):
    return q * SEC_D


def m3d_to_m3s(v):
    return v / SEC_D


def winter_norm_total():
    return sum(v * d for v, d in WINTER_NORMS.values())


def max_deductions(q_m3s, demand_m3d):
    """Предельные суммарные вычеты (экологический попуск + действующие отборы), м³/сут, при которых спрос ещё покрывается.
    Остаётся не меньше спроса: Q·86400 − вычеты ≥ спрос. При спросе больше притока допустимые вычеты равны нулю, дефицит > 0."""
    gross = m3s_to_m3d(q_m3s)
    allowed = max(0.0, gross - demand_m3d)
    deficit = max(0.0, demand_m3d - gross)
    return gross, allowed, deficit


def write_csv(path, rows):
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def unit_checks():
    q = Q_NOTE_30D
    year = Q_NOTE_MEAN * 365 * SEC_D
    rows = [  # проверка, значение, ожидание, допуск
        ("0,164 м³/с в м³/сут", m3s_to_m3d(q), 14169.6, 1e-6),
        ("0,164 м³/с за 30 суток, м³", m3s_to_m3d(q) * 30, 425088.0, 1e-6),
        ("0,303 м³/с за год (365 сут), м³", year, 9555408.0, 1e-3),
        ("доля 6,7 млн м³ от годового объёма при 0,303 м³/с, %", W_ECO_ANNUAL / year * 100, 70.12, 0.01),
        ("остаток годового объёма после 6,7 млн м³, м³", year - W_ECO_ANNUAL, 2855408.0, 1e-3),
        ("6,7 млн м³/год в м³/с (справка о единицах; в сценариях не используется)", W_ECO_ANNUAL / (365 * SEC_D), 0.2125, 1e-4),
        ("4 303 м³/сут в м³/с", m3d_to_m3s(4303), 0.0498, 5e-5),
        ("зимние нормы XI–III, сумма за 151 сут, м³", winter_norm_total(), 220553.0, 1e-6),
        ("2 700 м³/сут × 151 сут, м³", 2700 * 151, 407700.0, 1e-6),
        ("отношение 0,164 к 0,022 (разные створы; единый ряд не строится)", Q_NOTE_30D / Q_HIST_ST1, 7.4545, 1e-3),
        ("0,164 м³/с, приведённое по площади к 4,79 км² при F=31 км² (ориентир, не наблюдение)", Q_NOTE_30D * CATCH_ST1 / CATCH_MOUTH, 0.0253, 5e-5),
    ]
    return [{"check": n, "value": round(v, 4), "expected": e, "ok": abs(v - e) <= t} for n, v, e, t in rows]


def demand_scenarios():
    rows = []
    for basis, q, stream in (("0,164 м³/с (записка, 30-сут минимум 95 %)", Q_NOTE_30D, "створ не назван"),
                             ("0,022 м³/с (исторический расчёт, створ №1)", Q_HIST_ST1, "створ №1 Терисбутак, расчёт по аналогии")):
        for label, dem, src in DEMANDS:
            gross, allowed, deficit = max_deductions(q, dem)
            rows.append({
                "flow_basis": basis, "stream_or_section": stream, "demand_label": label, "demand_m3d": dem, "demand_m3h": round(dem / 24, 3),
                "demand_source": src, "gross_m3d": round(gross, 1), "gross_30d_m3": round(gross * 30, 1), "demand_30d_m3": dem * 30,
                "required_remainder_after_deductions_m3d": dem,
                "max_total_deductions_m3d": round(allowed, 1), "max_total_deductions_m3s": round(m3d_to_m3s(allowed), 5),
                "max_deductions_share_of_gross": round(allowed / gross, 4), "deficit_m3d_if_no_deductions": round(deficit, 1),
                "covered_without_deductions": deficit == 0,
                "comment": "ряды разных створов не объединяются"})
    # помесячные нормы XI–III отдельной выборкой для основы 0,164
    return rows


def monthly_norms():
    rows = []
    for m, (v, d) in WINTER_NORMS.items():
        gross, allowed, deficit = max_deductions(Q_NOTE_30D, v)
        rows.append({"month": m, "days": d, "norm_m3d": v, "month_demand_m3": v * d,
                     "max_total_deductions_m3d_at_0.164": round(allowed, 1), "share_of_gross": round(allowed / gross, 4)})
    return rows


def basis_comparison():
    mouth_95 = 7.57e6 / (365 * SEC_D)
    return [{
        "item": "среднегодовой расход 95 %: записка 0,303 против устья по Чигринцу и Мазур (7,57 млн м³ = 0,240 м³/с)",
        "ratio": round(Q_NOTE_MEAN / mouth_95, 3), "can_merge": False,
        "reason": "створ в записке не назван; периоды разные (1994–2025 против 1947–2011); обе величины публикуются отдельно"},
        {"item": "0,164 м³/с (30-суточный минимум) против 0,022 м³/с (суточный минимум 1968 г., створ №1)",
         "ratio": round(Q_NOTE_30D / Q_HIST_ST1, 3), "can_merge": False,
         "reason": "разные показатели (30-суточный и суточный), разные створы и основания (записка и расчёт по аналогии); модуль 0,164/31 = 5,29 и 0,022/4,79 = 4,59 л/с·км² сопоставим только если 0,164 относится к площади около 31 км², что источником не подтверждено"},
        {"item": "6,7 млн м³ против 0,303 м³/с (9,55 млн м³)", "ratio": round(W_ECO_ANNUAL / (Q_NOTE_MEAN * 365 * SEC_D), 4), "can_merge": False,
         "reason": "если 6,7 — попуск, он составляет 70 % среднегодового стока при 95 %; если это объём стока, вычетом он не является; смысл источником не раскрыт"}]


def main(out):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "Eco_Source_Register.csv").write_text((DATA / "eco_source_register.csv").read_text(encoding="utf-8"), encoding="utf-8")
    uc = unit_checks()
    write_csv(out / "Eco_Unit_Checks.csv", uc)
    write_csv(out / "Eco_Demand_Scenarios.csv", demand_scenarios())
    write_csv(out / "Eco_Winter_Norms_Monthly.csv", monthly_norms())
    write_csv(out / "Eco_Basis_Comparison.csv", basis_comparison())
    bad = [c for c in uc if not c["ok"]]
    sc = [r for r in demand_scenarios() if r["flow_basis"].startswith("0,164")]
    lines = ["# Отчёт проверок: показатели записки и спрос", "", f"Проверок единиц: {len(uc) - len(bad)}/{len(uc)} верно.", "",
             "## Основа 0,164 м³/с (14 169,6 м³/сут; 425 088 м³ за 30 суток), створ не назван", "",
             "| спрос | м³/сут | предельные вычеты, м³/сут | то же, м³/с | доля от валового |", "|---|---|---|---|---|"]
    for r in sc:
        lines.append(f"| {r['demand_label']} | {r['demand_m3d']} | {r['max_total_deductions_m3d']} | {r['max_total_deductions_m3s']} | {r['max_deductions_share_of_gross']:.1%} |")
    (out / "Check_Report_Eco.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    for c in uc:
        print(("OK  " if c["ok"] else "FAIL"), c["check"], c["value"])
    if bad:
        sys.exit(1)


if __name__ == "__main__":
    main(sys.argv[1])
