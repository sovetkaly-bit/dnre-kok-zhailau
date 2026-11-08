"""DNRE 2.0 / A5 (v1.3.1): устойчивость к прочтениям границы, два выхода.

A5a  Metric Robustness. Для метрики монографии (R1, I1) считается значение при каждом из трёх
     допустимых прочтений площади границы (заявленные 1002 га; точки 1–88; union контуров
     1–88 и 89–96), затем max/min и относительный разброс. Порогов и вердиктов здесь нет.

A5b  Verdict Robustness (Flip Rate). Только там, где есть обоснованный порог:

         R_flip = |{θ ∈ Θ_adm : v(d, θ) ≠ v(d, θ0)}| / |Θ_adm|,

     θ0 — базовое прочтение (по умолчанию 1002 га), Θ_adm включает θ0 (знаменатель 3, максимум
     при базовом 1002 га = 2/3). «Чувствителен» = вердикты на прочтениях не совпадают между собой.
     Если площадь меняет значение метрики, а порога нет, то R_flip = NA (TG), а не 0.
     Если домен вообще не использует площадь границы (вода, CCC, снегопроизводство, лавины, деревья),
     он не привязывается к ней искусственно: R_flip = 0 по построению, а не по устойчивости.

Это Verdict Robustness, а не VoI: вероятностей у прочтений нет. Вердикт даёт правило пакета
(dnre_core.margin / dnre_core.decision). Пороговые домены не придумываются: порог вводит
пользователь из документа, по умолчанию порога нет.
"""
from dataclasses import dataclass
from typing import Callable, Optional

import pandas as pd

import dnre_core as c
from gis_core import DECLARED_HA, load_contours, overlap_stats

VERDICTS = ("PASS", "FAIL", "INDETERMINATE")


# ---------------------------------------------------------------- прочтения границы
@dataclass(frozen=True)
class Reading:
    key: str
    area_ha: float
    source: str

    @property
    def label(self) -> str:
        return f"{self.area_ha:.2f}".replace(".", ",") + " га"


def boundary_readings() -> list[Reading]:
    """Три допустимых прочтения. Все 96 точек подряд (невалидный полигон) не используются."""
    gdf, _ = load_contours()
    r88 = gdf[gdf["name"] == "контур 1–88"].iloc[0]
    r96 = gdf[gdf["name"] == "все 96 точек"].iloc[0]
    if not bool(r88.valid):
        raise ValueError("Контур 1–88 невалиден: прочтение использовать нельзя")
    if bool(r96.valid):
        raise ValueError("Ожидался невалидный полигон «все 96 точек»; проверьте входные точки")
    ov = overlap_stats(gdf)
    return [
        Reading("declared", DECLARED_HA, "заявленные участки (площадь, полигона нет)"),
        Reading("points_1_88", float(r88.utm_ha), "точки 1–88"),
        Reading("union", float(ov["union_ha"]), "union контуров 1–88 и 89–96"),
    ]


# ---------------------------------------------------------------- домены
@dataclass(frozen=True)
class Result:
    verdict: str
    lo: Optional[float] = None   # нормированный запас, нижняя граница
    hi: Optional[float] = None   # нормированный запас, верхняя граница
    value: Optional[float] = None  # значение метрики (если домен — метрика)
    cause: Optional[str] = None   # "TG": обоснованного порога нет

    def signature(self):
        return (self.verdict, self.lo, self.hi, self.value)


@dataclass(frozen=True)
class Domain:
    name: str
    source: str                          # "пакет" | "сценарий"
    evaluate: Callable[[float], Result]  # площадь границы, га -> Result
    nd_note: str = ""                    # причина ND, если вердикт INDETERMINATE по построению


def _from_margin(R, B, L_lo, L_hi, applicable=True) -> Result:
    m1, m2 = c.margin(R, B, L_lo, "upper"), c.margin(R, B, L_hi, "upper")
    lo, hi = min(m1, m2), max(m1, m2)
    return Result(c.decision(lo, hi, applicable), lo, hi)


def water_domain(P: int) -> Domain:
    """Зимний водный приоритет: вердикт задан пакетом (INDETERMINATE; SPATIAL;DATA), площадь не используется."""
    def ev(area_ha: float) -> Result:
        return Result(c.winter_priority(P)["decision"])
    return Domain(f"Зимний водный приоритет, P={P} %", "пакет", ev,
                  "нет подтверждённого створа и фактического спроса (SPATIAL; DATA)")


def ccc_domain(density_limit: int) -> Domain:
    """Рекреационная нагрузка: запас по CCC на площадь трасс (143 га), не на границу."""
    def ev(area_ha: float) -> Result:
        _, rows = c.recreation(densities=(density_limit,))
        m = rows[0]["margin"]
        return Result(c.decision(m, m, True), m, m)
    return Domain(f"Рекреационная нагрузка (CCC), предел {density_limit} чел/га трасс", "пакет", ev)


# ---------------------------------------------------------------- A5a: метрики
@dataclass(frozen=True)
class Metric:
    code: str
    name: str
    unit: str
    source: str
    evaluate: Callable[[float], tuple]   # площадь границы, га -> (lo, hi)

    def mid(self, area_ha: float) -> float:
        lo, hi = self.evaluate(area_ha)
        return (lo + hi) / 2


DEFAULT_L_DAY = float(c.INP["day_visitors"])   # 15000 чел./сут, вход пакета
DEFAULT_A_DISTURBED = 300.0                    # га, публичная оценка (по сообщению автора), не измерение


def _interval(lo, hi, name):
    if lo < 0 or hi < lo:
        raise ValueError(f"{name}: нужно 0 <= нижняя <= верхняя")
    return lo, hi


def metric_r1(l_lo: float = DEFAULT_L_DAY, l_hi: Optional[float] = None) -> Metric:
    """R1 = L_сут / A, чел./(га·сут)."""
    l_hi = l_lo if l_hi is None else l_hi
    _interval(l_lo, l_hi, "L_сут")
    return Metric("R1", "R1 = L_сут / A", "чел./(га·сут)", "пакет: day_visitors; A — граница",
                  lambda A: (l_lo / A, l_hi / A))


def metric_i1(a_lo: float = DEFAULT_A_DISTURBED, a_hi: Optional[float] = None) -> Metric:
    """I1 = A_наруш / A × 100, %."""
    a_hi = a_lo if a_hi is None else a_hi
    _interval(a_lo, a_hi, "A_наруш")
    return Metric("I1", "I1 = A_наруш / A × 100", "%", "A_наруш — публичная оценка ≈300 га, не измерение",
                  lambda A: (100 * a_lo / A, 100 * a_hi / A))


def default_metrics(l_lo: float = DEFAULT_L_DAY, l_hi: Optional[float] = None,
                    a_lo: float = DEFAULT_A_DISTURBED, a_hi: Optional[float] = None) -> list[Metric]:
    return [metric_r1(l_lo, l_hi), metric_i1(a_lo, a_hi)]


@dataclass(frozen=True)
class MetricRow:
    code: str
    name: str
    unit: str
    source: str
    values: tuple          # середины интервалов по прочтениям
    intervals: tuple       # (lo, hi) по прочтениям
    ratio: float           # max/min
    spread_pct: float      # (max-min)/min × 100


def assess_metric(m: Metric, readings: list) -> MetricRow:
    if not readings:
        raise ValueError("Нет прочтений границы")
    for r in readings:
        if r.area_ha <= 0:
            raise ValueError("Площадь границы должна быть > 0")
    iv = tuple(m.evaluate(r.area_ha) for r in readings)
    vals = tuple((lo + hi) / 2 for lo, hi in iv)
    mn, mx = min(vals), max(vals)
    ratio = mx / mn if mn > 0 else float("inf")
    spread = (mx - mn) / mn * 100 if mn > 0 else float("inf")
    return MetricRow(m.code, m.name, m.unit, m.source, vals, iv, ratio, spread)


def metrics_dataframe(rows: list, readings: list) -> pd.DataFrame:
    recs = []
    for r in rows:
        rec = {"Метрика": r.name, "Единица": r.unit}
        for rd, v in zip(readings, r.values):
            rec[f"При {rd.label}"] = round(v, 2)
        rec["max/min"] = round(r.ratio, 4)
        rec["Разброс, %"] = round(r.spread_pct, 1)
        rec["Источник входа"] = r.source
        recs.append(rec)
    return pd.DataFrame(recs)


# ---------------------------------------------------------------- A5b: домены с порогом
def metric_threshold_domain(m: Metric, limit: Optional[float]) -> Domain:
    """Метрика против порога «не больше limit». Порога нет (None) -> INDETERMINATE, причина TG.
    Порог вводит пользователь из документа; здесь он не придумывается."""
    if limit is not None and limit <= 0:
        raise ValueError("Порог должен быть > 0")

    def ev(area_ha: float) -> Result:
        lo, hi = m.evaluate(area_ha)
        mid = (lo + hi) / 2
        if limit is None:
            return Result("INDETERMINATE", value=mid, cause="TG")
        r = _from_margin(0.0, limit, lo, hi)
        return Result(r.verdict, r.lo, r.hi, value=mid)
    return Domain(f"{m.code}: {m.name}, порог {'не задан' if limit is None else limit}",
                  "метрика", ev, "обоснованного порога нет (TG)")


NO_VERDICT = [
    ("Помесячный водный баланс", "в пакете нет вердикта (только недобор и сброс по месяцам), площадь границы не используется"),
]
NOT_BOUNDARY = ("вода, CCC, снегопроизводство, лавины, деревья",
                "не привязываются к общей площади границы: их основа — створ, площадь трасс, склоны, полигоны")


def default_domains(metrics: Optional[list] = None, limits: Optional[dict] = None) -> list[Domain]:
    """Домены пакета (не зависят от границы) + метрики с порогом (если задан) или TG."""
    limits = limits or {}
    out = [water_domain(p) for p in (25, 50, 75, 95)]
    out += [ccc_domain(d) for d in (10, 20, 30, 40)]
    for m in (metrics if metrics is not None else default_metrics()):
        out.append(metric_threshold_domain(m, limits.get(m.code)))
    return out


# ---------------------------------------------------------------- Flip Rate
@dataclass(frozen=True)
class Row:
    domain: str
    source: str
    verdicts: tuple
    r_flip: Optional[float]        # None = NA (TG)
    sensitive: Optional[bool]      # None = NA (TG)
    depends_on_boundary: bool
    na_tg: bool
    reason: str


def r_flip(verdicts, baseline: int = 0) -> float:
    if not 0 <= baseline < len(verdicts):
        raise ValueError("baseline вне диапазона прочтений")
    return sum(v != verdicts[baseline] for v in verdicts) / len(verdicts)


def assess(domain: Domain, readings: list, baseline: int = 0) -> Row:
    res = [domain.evaluate(r.area_ha) for r in readings]
    verdicts = tuple(x.verdict for x in res)
    for v in verdicts:
        if v not in VERDICTS:
            raise ValueError(f"Неизвестный вердикт {v!r} в домене {domain.name}")
    depends = len({x.signature() for x in res}) > 1
    na_tg = all(x.cause == "TG" for x in res)
    if na_tg:
        if depends:
            reason = ("Площадь влияет на значение, но обоснованного порога нет: R_flip = NA (TG), а не 0. "
                      "Вердикт не определён, пока порог не обоснован.")
        else:
            reason = "Порога нет и площадь не влияет на значение: R_flip = NA (TG)."
        return Row(domain.name, domain.source, verdicts, None, None, depends, True, reason)
    rf = r_flip(verdicts, baseline)
    sensitive = len(set(verdicts)) > 1
    if sensitive:
        path = " → ".join(f"{r.label}: {v}" for r, v in zip(readings, verdicts))
        reason = f"ЧУВСТВИТЕЛЕН: вердикт меняется между прочтениями ({path}). Нужна официальная граница."
    elif not depends:
        if set(verdicts) == {"INDETERMINATE"} and domain.nd_note:
            reason = (f"Не использует площадь границы; INDETERMINATE на всех прочтениях: {domain.nd_note}. "
                      "R_flip = 0 по построению, а не по устойчивости.")
        else:
            reason = "Не использует площадь границы; R_flip = 0 по построению, а не по устойчивости."
    elif set(verdicts) == {"INDETERMINATE"}:
        reason = "Зависит от площади, но на всех прочтениях INDETERMINATE (интервал запаса пересекает 0)."
    else:
        los = [x.lo for x in res if x.lo is not None]
        his = [x.hi for x in res if x.hi is not None]
        reason = (f"Зависит от площади, вердикт {verdicts[0]} на всех прочтениях "
                  f"(запас m от {min(los):.3f} до {max(his):.3f}); граница на этот домен не влияет.")
    return Row(domain.name, domain.source, verdicts, rf, sensitive, depends, False, reason)


def run_a5(domains: Optional[list] = None, readings: Optional[list] = None,
           baseline: int = 0, metrics: Optional[list] = None):
    """Возвращает (metric_rows, verdict_rows, readings)."""
    readings = readings or boundary_readings()
    metrics = metrics if metrics is not None else default_metrics()
    domains = domains if domains is not None else default_domains(metrics)
    mrows = [assess_metric(m, readings) for m in metrics]
    return mrows, [assess(d, readings, baseline) for d in domains], readings


def to_dataframe(rows: list, readings: list) -> pd.DataFrame:
    recs = []
    for r in rows:
        rec = {"Домен": r.domain, "Источник": r.source}
        for rd, v in zip(readings, r.verdicts):
            rec[f"Вердикт при {rd.label}"] = v
        rec["R_flip"] = "NA (TG)" if r.r_flip is None else round(r.r_flip, 3)
        rec["Чувствителен"] = "NA (TG)" if r.sensitive is None else ("да" if r.sensitive else "нет")
        rec["Зависит от границы"] = "да" if r.depends_on_boundary else "нет"
        rec["Причина"] = r.reason
        recs.append(rec)
    return pd.DataFrame(recs)


def summary(rows: list) -> dict:
    return dict(domains=len(rows),
                depend_on_boundary=sum(r.depends_on_boundary for r in rows),
                sensitive=sum(bool(r.sensitive) for r in rows),
                na_tg=sum(r.na_tg for r in rows),
                package_domains=sum(r.source == "пакет" for r in rows),
                package_depend=sum(r.source == "пакет" and r.depends_on_boundary for r in rows))
