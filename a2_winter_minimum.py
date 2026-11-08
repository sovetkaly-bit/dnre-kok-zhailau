"""DNRE 2.0 / A2: зимний минимум M(t) по межени (ребро «забор → межень»).

Для каждого месяца t:

    M(t) = (Q_nat − W_div − Q_min) / (Q_nat − Q_min),

это нормированный запас пакета dnre_core.margin(R, B, L, "lower") с R = Q_nat (естественный сток),
B = Q_min (минимально допустимый сток ниже забора), L = Q_nat − W_div (остаток после забора).
M = 1 без забора, M = 0 когда остаток равен Q_min, M < 0 когда остаток ниже Q_min.
Правило решения — dnre_core.decision: M_lo > 0 → PASS, M_hi < 0 → FAIL, иначе INDETERMINATE.

Вердикт блока — по зимним месяцам XI–III (dnre_core.WINTER): FAIL, если хотя бы один зимний месяц FAIL;
PASS, если все пять PASS; иначе INDETERMINATE.

Правила данных:
* Пустая ячейка = ND(DATA), а не 0. Нулевой забор вводится явно (0). Оценочные значения Q_nat, W_div, Q_min
  модуль не подставляет и не берёт из пакета (в пакете нет месячных рядов межени).
* Каждая величина может быть интервалом (колонки *_lo / *_hi); запас берётся по всем крайним комбинациям.
* Если Q_nat ≤ Q_min, нормировка не определена (естественный сток уже не выше нормы): INDETERMINATE, причина указана.
* Единицы: м³ за месяц. Перевод м³/с → м³/мес: m3s_to_month().
"""
import calendar
import itertools
from dataclasses import dataclass
from typing import Optional

import pandas as pd

import dnre_core as c

QUANT = ("Q_nat", "W_div", "Q_min")
COLS = ["month"] + [f"{q}_{s}" for q in QUANT for s in ("m3", "lo", "hi")]
TEMPLATE_COLS = ["month", "Q_nat_m3", "W_div_m3", "Q_min_m3", "Q_nat_lo", "Q_nat_hi",
                 "W_div_lo", "W_div_hi", "Q_min_lo", "Q_min_hi", "source", "note"]
MONTH_RU = {1: "I", 2: "II", 3: "III", 4: "IV", 5: "V", 6: "VI", 7: "VII", 8: "VIII", 9: "IX", 10: "X",
            11: "XI", 12: "XII"}


def m3s_to_month(q_m3s: float, month: int, year: int = 2025) -> float:
    """Расход м³/с -> объём за месяц, м³ (по числу суток месяца)."""
    if not 1 <= month <= 12:
        raise ValueError("month должен быть 1..12")
    if q_m3s < 0:
        raise ValueError("Расход не может быть отрицательным")
    return q_m3s * 86400 * calendar.monthrange(year, month)[1]


def template_dataframe() -> pd.DataFrame:
    """Пустой шаблон входных данных: 12 месяцев, значений нет (ND(DATA))."""
    df = pd.DataFrame({"month": range(1, 13)})
    for col in TEMPLATE_COLS[1:]:
        df[col] = ""
    return df[TEMPLATE_COLS]


@dataclass(frozen=True)
class MonthResult:
    month: int
    verdict: str
    lo: Optional[float]
    hi: Optional[float]
    cause: Optional[str]      # "DATA" | "NORM" | None
    note: str


def _num(v) -> Optional[float]:
    if v is None:
        return None
    if isinstance(v, str):
        v = v.strip().replace(",", ".").replace(" ", "")
        if v == "":
            return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        raise ValueError(f"Нечисловое значение: {v!r}")
    if x != x:           # NaN = пусто
        return None
    return x


def _range(row, q: str):
    """(lo, hi) величины q по строке: точное значение или интервал. None, если данных нет."""
    pt = _num(row.get(f"{q}_m3"))
    lo, hi = _num(row.get(f"{q}_lo")), _num(row.get(f"{q}_hi"))
    if lo is not None and hi is not None:
        if lo > hi:
            raise ValueError(f"{q}: нижняя граница больше верхней")
        if pt is not None and not lo <= pt <= hi:
            raise ValueError(f"{q}: значение вне интервала")
        lo_, hi_ = lo, hi
    elif lo is None and hi is None:
        if pt is None:
            return None
        lo_ = hi_ = pt
    else:
        raise ValueError(f"{q}: интервал задан наполовину (нужны обе границы)")
    if lo_ < 0:
        raise ValueError(f"{q}: объём не может быть отрицательным")
    return lo_, hi_


def month_margin(q_nat, w_div, q_min) -> tuple:
    """(lo, hi) нормированного запаса по интервалам; ValueError, если на какой-то комбинации Q_nat <= Q_min."""
    vals = []
    for qn, wd, qm in itertools.product(q_nat, w_div, q_min):
        vals.append(c.margin(qn, qm, qn - wd, "lower"))
    return min(vals), max(vals)


def assess_month(row) -> MonthResult:
    m = int(_num(row.get("month")))
    if not 1 <= m <= 12:
        raise ValueError("month должен быть 1..12")
    rng = {q: _range(row, q) for q in QUANT}
    missing = [q for q in QUANT if rng[q] is None]
    if missing:
        return MonthResult(m, "INDETERMINATE", None, None, "DATA", "ND(DATA): нет " + ", ".join(missing))
    try:
        lo, hi = month_margin(*(rng[q] for q in QUANT))
    except ValueError:
        return MonthResult(m, "INDETERMINATE", None, None, "NORM",
                           "Q_nat ≤ Q_min: нормировка не определена, естественный сток не выше нормы")
    return MonthResult(m, c.decision(lo, hi, True), lo, hi, None, "")


def assess(df: pd.DataFrame) -> tuple:
    """-> (список MonthResult по 12 месяцам, вердикт блока по XI–III, пояснение)."""
    if "month" not in df.columns:
        raise ValueError("В таблице нет колонки month")
    rows = {}
    for _, r in df.iterrows():
        res = assess_month(r.to_dict())
        if res.month in rows:
            raise ValueError(f"Месяц {res.month} указан дважды")
        rows[res.month] = res
    results = [rows.get(m) or MonthResult(m, "INDETERMINATE", None, None, "DATA", "ND(DATA): строки нет")
               for m in range(1, 13)]
    winter = [results[m - 1] for m in c.WINTER]
    fails = [r.month for r in winter if r.verdict == "FAIL"]
    if fails:
        verdict = "FAIL"
        why = "Остаток ниже Q_min в зимние месяцы: " + ", ".join(MONTH_RU[m] for m in fails)
    elif all(r.verdict == "PASS" for r in winter):
        verdict, why = "PASS", "Остаток выше Q_min во все зимние месяцы XI–III"
    else:
        verdict = "INDETERMINATE"
        nd = [r.month for r in winter if r.cause == "DATA"]
        why = ("ND(DATA) по зимним месяцам: " + ", ".join(MONTH_RU[m] for m in nd)) if nd else \
              "Интервал запаса пересекает 0 или норма неприменима хотя бы в одном зимнем месяце"
    return results, verdict, why


def to_dataframe(results: list) -> pd.DataFrame:
    recs = []
    for r in results:
        recs.append({"Месяц": MONTH_RU[r.month], "Зимний (XI–III)": "да" if r.month in c.WINTER else "нет",
                     "M(t), нижняя": None if r.lo is None else round(r.lo, 4),
                     "M(t), верхняя": None if r.hi is None else round(r.hi, 4),
                     "Вердикт": r.verdict, "Причина": r.note})
    return pd.DataFrame(recs)
