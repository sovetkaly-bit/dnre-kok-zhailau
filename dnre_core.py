"""DNRE core: порт расчётов из пакета DNRE_calculation_package v1.0 (calc.py, Inputs.csv,
Water_inputs.csv, source_monthly_percent.csv). Логика сохранена; ND не заменяется нулём."""
import calendar

# --- Inputs.csv (значения как в пакете) ---
INP = dict(
    reservoir_m3=234590, snow_water_m3=355000, house_winter_m3_day=2700, house_other_m3_day=1350,
    winter_days=151, other_days=214, irrigation_m3=16520, fire_refill_m3=1961.28,
    track_area_ha=143, day_skiers=5000, open_hours=10, stay_hours=6,
    snow_peak_kw=9000, snow_peak_m3_h=2700, substation_kw=36000,
    day_visitors=15000, peak_arrival_fraction=0.25, shuttle_people_per_hour=180,
)
# --- Water_inputs.csv: P -> (natural, ecological) м3 ---
FLOWS = {25: (8_940_000, 7_190_000), 50: (7_190_000, 5_690_000),
         75: (5_690_000, 4_570_000), 95: (3_910_000, 3_590_000)}
# --- source_monthly_percent.csv: месяцы 1..12, % ---
SHARES = {
    25: [4.03, 3.68, 3.53, 9.11, 16.09, 21.05, 12.64, 7.57, 6.04, 5.94, 5.33, 4.99],
    50: [4.23, 4.0, 4.15, 8.33, 16.59, 21.56, 11.46, 7.34, 6.21, 6.05, 5.35, 4.74],
    75: [4.37, 3.99, 5.82, 11.11, 19.27, 14.95, 8.98, 7.84, 7.03, 6.01, 5.64, 4.99],
    95: [4.57, 4.17, 5.72, 10.91, 18.94, 14.69, 8.82, 7.71, 6.91, 6.36, 5.97, 5.22],
}
WINTER = [11, 12, 1, 2, 3]
OVOS_DAILY = 2481  # м3/сут, альтернативное основание спроса (winter_priority.csv)


def margin(R, B, L, direction):
    if direction == "upper":
        if not B > R:
            raise ValueError("upper requires B > R")
        return (B - L) / (B - R)
    if direction == "lower":
        if not R > B:
            raise ValueError("lower requires R > B")
        return (L - B) / (R - B)
    raise ValueError("unknown direction")


def decision(low, high, applicable=True):
    """Трёхзначное правило: PASS / FAIL / INDETERMINATE."""
    if not applicable or low is None or high is None:
        return "INDETERMINATE"
    if low > 0:
        return "PASS"
    if high < 0:
        return "FAIL"
    return "INDETERMINATE"


def winter_free(P, shares=None):
    """Свободный зимний сток XI–III (м3) = (естеств. − экол.) × доля XI–III."""
    nat, eco = FLOWS[P]
    s = (shares or SHARES)[P]
    return (nat - eco) * sum(s[m - 1] for m in WINTER) / sum(s)


def winter_priority(P, domestic_m3_day=None, snow_m3=None, storage=None, domestic_first=True, **kw):
    """Зимний приоритет: бытовое водопотребление обслуживается раньше снега (допущение автора,
    не юридический приоритет). Воспроизводит winter_priority.csv."""
    domestic_m3_day = INP["house_winter_m3_day"] if domestic_m3_day is None else domestic_m3_day
    snow_m3 = INP["snow_water_m3"] if snow_m3 is None else snow_m3
    storage = INP["reservoir_m3"] if storage is None else storage
    free = winter_free(P)
    dom = domestic_m3_day * INP["winter_days"]
    avail = free + storage
    if domestic_first:
        dom_served = min(dom, avail)
        snow_served = min(snow_m3, max(0.0, avail - dom_served))
    else:
        snow_served = min(snow_m3, avail)
        dom_served = min(dom, max(0.0, avail - snow_served))
    return dict(P=P, free_winter_m3=free, storage_m3=storage, domestic_m3=dom,
                domestic_served_m3=dom_served, domestic_unserved_m3=dom - dom_served,
                snow_m3=snow_m3, snow_served_m3=snow_served,
                snow_served_fraction=snow_served / snow_m3 if snow_m3 else None,
                decision="INDETERMINATE")  # SPATIAL;DATA — пока нет створа и фактического спроса


def monthly_balance(P, snow_m3=None, storage=None, domestic_winter=None, return_fraction=0.0):
    """Помесячный баланс XI–X (невисокосный цикл). return_fraction — доля возврата талой воды
    снежных пушек в накопитель (сценарий, в пакете задаётся в snow_return.csv)."""
    snow_m3 = INP["snow_water_m3"] if snow_m3 is None else snow_m3
    cap = INP["reservoir_m3"] if storage is None else storage
    dw = INP["house_winter_m3_day"] if domestic_winter is None else domestic_winter
    free = winter_free  # noqa
    nat, eco = FLOWS[P]
    fr = nat - eco
    s = SHARES[P]; ss = sum(s)
    S = cap
    rows = []
    for m in [11, 12, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10]:
        days = calendar.monthrange(2025 if m >= 11 else 2026, m)[1]
        domestic = days * (dw if m in WINTER else INP["house_other_m3_day"])
        snow = snow_m3 * {11: .375, 12: .375, 1: .125, 2: .125}.get(m, 0)
        irr = INP["irrigation_m3"] * {5: .05, 6: .1, 7: .25, 8: .5, 9: .1}.get(m, 0)
        fire = INP["fire_refill_m3"] if m == 10 else 0
        inflow = fr * s[m - 1] / ss
        ret = snow * return_fraction if m in (3, 4, 5) else 0  # возврат весной (допущение сценария)
        demand = domestic + snow + irr + fire
        net = S + inflow + ret - demand
        end = min(cap, max(0, net))
        rows.append(dict(month=m, storage_start=S, inflow=inflow, demand=demand,
                         unserved=max(0, -net), spill=max(0, net - cap), storage_end=end))
        S = end
    return rows


def recreation(day_skiers=None, stay_hours=None, open_hours=None, track_ha=None, densities=(10, 20, 30, 40)):
    day_skiers = INP["day_skiers"] if day_skiers is None else day_skiers
    stay_hours = INP["stay_hours"] if stay_hours is None else stay_hours
    open_hours = INP["open_hours"] if open_hours is None else open_hours
    track_ha = INP["track_area_ha"] if track_ha is None else track_ha
    N = day_skiers * stay_hours / open_hours
    out = []
    for d in densities:
        B = track_ha * d
        out.append(dict(density_limit=d, CCC=B, N=N, density_per_ha=N / track_ha,
                        margin=margin(0, B, N, "upper")))
    return N, out
