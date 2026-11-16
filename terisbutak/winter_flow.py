"""Зимняя водообеспеченность ручья Терисбутак (пост 14253, устье): показатели и сценарный баланс.

Режимы:
    python terisbutak/winter_flow.py --raw <файл.xlsx>   полный расчёт из суточного ряда (локально; ряд в репозиторий не входит)
    python terisbutak/winter_flow.py --verify            пересчёт итоговых таблиц из агрегатов results/Flow_Counts.csv

Расход хранится в сотых м³/с (целые числа), чтобы пересчёт был точным. Объём = сумма суточных расходов × 86 400 с.
Сценарный параметр R = Q_эко + q_забор (м³/с): заданные значения, не нормативы и не проектные числа.
Сутки дефицита: Q < R. Объём дефицита: сумма max(0, R − Q) × 86 400.
Пометы Казгидромета сохраняются как в источнике и не используются как критерий исключения.
"""
import argparse
import calendar
import hashlib
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "results"
WINTER = (11, 12, 1, 2, 3)
SCENARIOS = [round(x, 2) for x in np.arange(0.20, 0.601, 0.05)]  # R, м³/с
SHEET = "Суточные расходы"


def season_of(ts: pd.Timestamp):
    """Зимний сезон ноябрь–март, год = год окончания; вне зимы None."""
    if ts.month in (11, 12):
        return ts.year + 1
    if ts.month in (1, 2, 3):
        return ts.year
    return None


def season_expected(y: int) -> int:
    return sum(calendar.monthrange(yy, m)[1] for yy, m in ((y - 1, 11), (y - 1, 12), (y, 1), (y, 2), (y, 3)))


def load_raw(path: Path) -> pd.DataFrame:
    d = pd.read_excel(path, sheet_name=SHEET)
    d = d.rename(columns={"Дата": "date", "Расход, м³/с": "q", "Помета": "flag"})
    d["date"] = pd.to_datetime(d["date"])
    d["c"] = (d["q"] * 100).round().astype(int)
    d["flag"] = d["flag"].fillna("")
    assert d["date"].is_unique and d["q"].notna().all()
    d["season"] = d["date"].map(season_of)
    return d.sort_values("date").reset_index(drop=True)


def runs_below(dates, cents, r_cents):
    """Непрерывные последовательности суток с Q < R (даты подряд): [(начало, конец, суток, объём_м3)]."""
    out, cur = [], []
    prev = None
    for dt, c in zip(dates, cents):
        ok = c < r_cents and (prev is None or (dt - prev).days == 1 or not cur)
        if c < r_cents:
            if cur and (dt - cur[-1][0]).days != 1:
                out.append(cur)
                cur = []
            cur.append((dt, c))
        else:
            if cur:
                out.append(cur)
                cur = []
        prev = dt
    if cur:
        out.append(cur)
    return [(r[0][0], r[-1][0], len(r), sum(r_cents - x[1] for x in r) * 0.01 * 86400) for r in out]


def flow_counts(d):
    t = d.assign(month=d["date"].dt.strftime("%Y-%m")).groupby(["month", "c"]).size().reset_index(name="days")
    return t.rename(columns={"c": "q_cents"})


def month_table(d):
    rows = []
    for m, g in d.groupby(d["date"].dt.strftime("%Y-%m")):
        ts = g["date"].iloc[0]
        exp = calendar.monthrange(ts.year, ts.month)[1]
        i = g["c"].idxmin()
        rows.append(dict(month=m, winter_month=ts.month in WINTER, days=len(g), expected=exp, coverage=len(g) / exp,
                         mean_m3s=g["c"].mean() / 100, min_m3s=g["c"].min() / 100, min_date=d.loc[i, "date"].date(),
                         volume_m3=int(g["c"].sum()) * 0.01 * 86400))
    return pd.DataFrame(rows)


def season_table(d):
    rows = []
    for y, g in d[d["season"].notna()].groupby("season"):
        y = int(y)
        g = g.sort_values("date")
        exp = season_expected(y)
        i = g["c"].idxmin()
        c = g["c"].to_numpy()
        # 7 последовательных суток внутри сезона, без пропусков дат
        best, start = None, None
        for k in range(len(g) - 6):
            if (g["date"].iloc[k + 6] - g["date"].iloc[k]).days == 6:
                v = c[k:k + 7].mean() / 100
                if best is None or v < best:
                    best, start = v, g["date"].iloc[k].date()
        rows.append(dict(season=y, full_season=len(g) == exp, days=len(g), expected=exp, coverage=len(g) / exp,
                         start=g["date"].min().date(), end=g["date"].max().date(),
                         mean_m3s=c.mean() / 100, min_m3s=c.min() / 100, min_date=d.loc[i, "date"].date(),
                         min7_mean_m3s=best, min7_start=start, volume_m3=int(c.sum()) * 0.01 * 86400))
    return pd.DataFrame(rows)


def scenario_tables(d):
    bal, runs = [], []
    w = d[d["season"].notna()]
    for r in SCENARIOS:
        rc = int(round(r * 100))
        per = []
        for y, g in w.groupby("season"):
            y = int(y)
            g = g.sort_values("date")
            rr = runs_below(list(g["date"]), list(g["c"]), rc)
            per.append((y, len(g) == season_expected(y), len(g), rr, int(np.maximum(0, rc - g["c"]).sum()) * 0.01 * 86400,
                        int(g["c"].sum()) * 0.01 * 86400))
            for a, b, n, v in rr:
                runs.append(dict(R_m3s=r, season=y, full_season=len(g) == season_expected(y), start=a.date(), end=b.date(),
                                 days=n, deficit_volume_m3=v))
        for y, full, n, rr, vol, tot in per:
            longest = max(rr, key=lambda x: x[2]) if rr else None
            bal.append(dict(R_m3s=r, scope=str(y), full_season=full, days=n, deficit_days=sum(x[2] for x in rr),
                            longest_run_days=longest[2] if longest else 0,
                            longest_run_start=longest[0].date() if longest else "", longest_run_end=longest[1].date() if longest else "",
                            deficit_volume_m3=vol, season_volume_m3=tot))
        full = [p for p in per if p[1]]
        allr = [x for p in full for x in p[3]]
        longest = max(allr, key=lambda x: x[2]) if allr else None
        bal.append(dict(R_m3s=r, scope="full_seasons_pooled", full_season=True, days=sum(p[2] for p in full),
                        deficit_days=sum(x[2] for p in full for x in p[3]),
                        longest_run_days=longest[2] if longest else 0,
                        longest_run_start=longest[0].date() if longest else "", longest_run_end=longest[1].date() if longest else "",
                        deficit_volume_m3=sum(p[4] for p in full), season_volume_m3=sum(p[5] for p in full)))
    return pd.DataFrame(bal), pd.DataFrame(runs)


def flag_counts(d):
    t = d.assign(month=d["date"].dt.strftime("%Y-%m"), flag=d["flag"].replace("", "none"))
    return t.groupby(["month", "flag"]).size().reset_index(name="days")


def a2_input(month_df):
    """Заготовка входа для a2_winter_minimum: Q_nat по зимним месяцам (пост 14253, без переноса в створ), остальное ND."""
    w = month_df[month_df["winter_month"]].copy()
    w["cal"] = w["month"].str[-2:].astype(int)
    w = w[w["days"] == w["expected"]]  # только полные месяцы
    g = w.groupby("cal")["volume_m3"].agg(["mean", "min", "max", "count"]).reset_index()
    rows = []
    for m in range(1, 13):
        r = dict(month=m, Q_nat_m3="", W_div_m3="", Q_min_m3="", Q_nat_lo="", Q_nat_hi="", W_div_lo="", W_div_hi="", Q_min_lo="", Q_min_hi="", source="", note="")
        x = g[g["cal"] == m]
        if len(x):
            x = x.iloc[0]
            r.update(Q_nat_m3=round(x["mean"]), Q_nat_lo=round(x["min"]), Q_nat_hi=round(x["max"]),
                     source="Казгидромет, ЕДС, пост 14253 (устье), 2020-2023",
                     note=f"среднее и размах по {int(x['count'])} полным месяцам; без переноса в проектный створ; W_div и Q_min не заданы (ND)")
        rows.append(r)
    return pd.DataFrame(rows)


def write(df, name):
    df.to_csv(OUT / name, index=False, float_format="%.6f")


def from_counts(counts):
    """Пересчёт месячных и сезонных сумм и сценарных таблиц (кроме последовательностей) из агрегата Flow_Counts."""
    c = counts.copy()
    c["date_m"] = pd.to_datetime(c["month"] + "-01")
    c["season"] = c["date_m"].map(season_of)
    c["sum_c"] = c["q_cents"] * c["days"]
    return c


def verify():
    counts = pd.read_csv(OUT / "Flow_Counts.csv")
    c = from_counts(counts)
    mt, st = pd.read_csv(OUT / "Monthly_Metrics.csv"), pd.read_csv(OUT / "Season_Metrics.csv")
    bal, runs = pd.read_csv(OUT / "Scenario_Balance.csv"), pd.read_csv(OUT / "Deficit_Runs.csv")
    bad = []
    for _, r in mt.iterrows():
        g = c[c["month"] == r["month"]]
        if g["days"].sum() != r["days"]: bad.append(f"{r['month']} days")
        if not np.isclose(g["sum_c"].sum() * 0.01 * 86400, r["volume_m3"], rtol=0, atol=1e-6 * 1e6): bad.append(f"{r['month']} volume")
        if not np.isclose(g["sum_c"].sum() / g["days"].sum() / 100, r["mean_m3s"], atol=1e-6): bad.append(f"{r['month']} mean")
        if g["q_cents"].min() / 100 != r["min_m3s"]: bad.append(f"{r['month']} min")
    for _, r in st.iterrows():
        g = c[c["season"] == r["season"]]
        if g["days"].sum() != r["days"]: bad.append(f"season {r['season']} days")
        if not np.isclose(g["sum_c"].sum() * 0.01 * 86400, r["volume_m3"], atol=1.0): bad.append(f"season {r['season']} volume")
        if g["q_cents"].min() / 100 != r["min_m3s"]: bad.append(f"season {r['season']} min")
        if r["min7_mean_m3s"] < r["min_m3s"] - 1e-9: bad.append(f"season {r['season']} min7<min")
    for _, r in bal.iterrows():
        rc = int(round(r["R_m3s"] * 100))
        scope = c[c["season"].notna()]
        if r["scope"] == "full_seasons_pooled":
            seasons = set(st.loc[st["full_season"], "season"])
        else:
            seasons = {int(r["scope"])}
        g = scope[scope["season"].isin(seasons)]
        dd = int(g.loc[g["q_cents"] < rc, "days"].sum())
        vol = float(((rc - g["q_cents"]).clip(lower=0) * g["days"]).sum()) * 0.01 * 86400
        if dd != r["deficit_days"]: bad.append(f"balance R={r['R_m3s']} {r['scope']} deficit_days")
        if not np.isclose(vol, r["deficit_volume_m3"], atol=1.0): bad.append(f"balance R={r['R_m3s']} {r['scope']} volume")
        rr = runs[(np.isclose(runs["R_m3s"], r["R_m3s"]))]
        rr = rr[rr["full_season"]] if r["scope"] == "full_seasons_pooled" else rr[rr["season"] == int(r["scope"])]
        if rr["days"].sum() != dd: bad.append(f"balance R={r['R_m3s']} {r['scope']} run days != deficit days")
        if (rr["days"].max() if len(rr) else 0) != r["longest_run_days"]: bad.append(f"balance R={r['R_m3s']} {r['scope']} longest")
    print(f"checked months={len(mt)} seasons={len(st)} scenario rows={len(bal)} problems={len(bad)}")
    for b in bad: print(" -", b)
    return not bad


def run_raw(path: Path):
    d = load_raw(path)
    sha = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    OUT.mkdir(exist_ok=True)
    mt = month_table(d); write(mt, "Monthly_Metrics.csv")
    write(season_table(d), "Season_Metrics.csv")
    write(flow_counts(d), "Flow_Counts.csv")
    write(flag_counts(d), "Flag_Counts.csv")
    bal, runs = scenario_tables(d)
    write(bal, "Scenario_Balance.csv"); write(runs, "Deficit_Runs.csv")
    a2_input(mt).to_csv(OUT / "A2_input_post14253_winter.csv", index=False)
    (OUT / "Source_SHA256.txt").write_text(f"{sha}  {Path(path).name}\n")
    print("source sha256", sha, "| days", len(d))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw"); ap.add_argument("--verify", action="store_true")
    a = ap.parse_args()
    if a.raw: run_raw(Path(a.raw))
    if a.verify or not a.raw: raise SystemExit(0 if verify() else 1)
