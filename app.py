"""DNRE — интерактивная панель (Streamlit). Запуск: streamlit run app.py
Расчёты — порт пакета DNRE_calculation_package v1.0 (Zenodo 10.5281/zenodo.23107585).
Это сценарный инструмент, а не независимая валидация метода."""
import pandas as pd
import streamlit as st
import plotly.graph_objects as go
import dnre_core as c
from gis_core import (load_contours, geometry_control, overlap_stats, contour_figure, LABELS, LBL_PARCELS,
                      M_GEOD, M_UTM)

st.set_page_config(page_title="DNRE · Кок-Жайлау", layout="wide")
st.title("DNRE · Кок-Жайлау")
st.caption("Динамическое природно-рекреационное равновесие — сценарная панель. "
           "Результат PASS/FAIL/INDETERMINATE зависит от допущений, а не от измерений.")

tab1, tab2, tab3, tab4, tab5, tab6, tab7, tab8 = st.tabs(
    ["Зимний водный приоритет", "Помесячный баланс", "Рекреационная нагрузка (CCC)",
     "Запас и решение", "Контур на карте", "Кадастр ↔ точки", "DNRE 2.0 / A5 Robustness", "DNRE 2.0 / A2 Winter minimum"])

# ---------- 1. зимний приоритет ----------
with tab1:
    c1, c2 = st.columns([1, 2])
    with c1:
        P = st.select_slider("Обеспеченность стока P, %", options=[25, 50, 75, 95], value=75, key="p1")
        basis = st.radio("Основание бытового спроса", ["Календарь: 2700 м³/сут", "ОВОС: 2481 м³/сут", "Своё"])
        dom = {"Календарь: 2700 м³/сут": 2700, "ОВОС: 2481 м³/сут": 2481}.get(basis)
        if dom is None:
            dom = st.number_input("Бытовой спрос зимой, м³/сут", 0, 10000, 2700, 50)
        snow_k = st.slider("Доля заявленного снегового спроса (355 000 м³)", 0.0, 1.5, 1.0, 0.05)
        stor = st.slider("Полезный запас накопителей, м³ (номинал 234 590)", 0, 234590, 234590, 5000)
        dfirst = st.checkbox("Бытовое водопотребление раньше снега (допущение автора)", True)
    r = c.winter_priority(P, dom, c.INP["snow_water_m3"] * snow_k, stor, dfirst)
    with c2:
        m1, m2, m3 = st.columns(3)
        m1.metric("Свободный сток XI–III", f"{r['free_winter_m3']:,.0f} м³".replace(",", " "))
        m2.metric("Снег обслужен", f"{(r['snow_served_fraction'] or 0) * 100:.0f} %")
        m3.metric("Бытовой недобор", f"{r['domestic_unserved_m3']:,.0f} м³".replace(",", " "))
        fig = go.Figure(go.Bar(
            x=["Бытовой спрос", "Бытовой обслужен", "Снег спрос", "Снег обслужен"],
            y=[r["domestic_m3"], r["domestic_served_m3"], r["snow_m3"], r["snow_served_m3"]],
            marker_color=["#bbb", "#2b6", "#bbb", "#e8730c"]))
        fig.update_layout(yaxis_title="м³ за XI–III", height=360, margin=dict(t=10))
        st.plotly_chart(fig, width="stretch")
        st.info(f"Решение: **{r['decision']}** — нет подтверждённого створа и фактического "
                "спроса (причины SPATIAL; DATA в пакете).")
    # сводка по всем P
    rows = []
    for p in (25, 50, 75, 95):
        x = c.winter_priority(p, dom, c.INP["snow_water_m3"] * snow_k, stor, dfirst)
        rows.append({"P, %": p, "Свободный сток, м³": round(x["free_winter_m3"]),
                     "Бытовой недобор, м³": round(x["domestic_unserved_m3"]),
                     "Снег обслужен, %": round((x["snow_served_fraction"] or 0) * 100, 1)})
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")

# ---------- 2. помесячный баланс ----------
with tab2:
    c1, c2 = st.columns([1, 2])
    with c1:
        P2 = st.select_slider("Обеспеченность P, %", options=[25, 50, 75, 95], value=95, key="p2")
        ret = st.slider("Доля возврата воды снегопушек весной", 0.0, 1.0, 0.0, 0.25,
                        help="Сценарий. В пакете snow_return.csv — 0 / 0,5 / 1.")
        snow2 = st.slider("Снеговой спрос, м³", 0, 500000, 355000, 5000)
    rows = c.monthly_balance(P2, snow2, return_fraction=ret)
    df = pd.DataFrame(rows)
    names = {11: "XI", 12: "XII", 1: "I", 2: "II", 3: "III", 4: "IV", 5: "V", 6: "VI",
             7: "VII", 8: "VIII", 9: "IX", 10: "X"}
    df["Месяц"] = df["month"].map(names)
    with c2:
        fig = go.Figure()
        fig.add_bar(x=df["Месяц"], y=df["inflow"], name="Приток", marker_color="#4a90d9")
        fig.add_bar(x=df["Месяц"], y=-df["demand"], name="Спрос", marker_color="#e8730c")
        fig.add_scatter(x=df["Месяц"], y=df["storage_end"], name="Запас на конец месяца",
                        mode="lines+markers", line=dict(color="#222"))
        fig.update_layout(barmode="relative", height=400, yaxis_title="м³", margin=dict(t=10))
        st.plotly_chart(fig, width="stretch")
        un = df["unserved"].sum()
        st.metric("Недоданная вода за цикл XI–X", f"{un:,.0f} м³".replace(",", " "))
    st.dataframe(df.rename(columns={"storage_start": "Запас на начало", "inflow": "Приток",
                                    "demand": "Спрос", "unserved": "Недобор", "spill": "Сброс",
                                    "storage_end": "Запас на конец"}).drop(columns="month").round(0),
                 hide_index=True, width="stretch")

# ---------- 3. CCC ----------
with tab3:
    c1, c2 = st.columns([1, 2])
    with c1:
        sk = st.slider("Лыжников в сутки", 1000, 15000, 5000, 500)
        stay = st.slider("Время катания, ч", 1, 10, 6)
        opn = st.slider("Часы работы, ч", 6, 12, 10)
        trk = st.slider("Площадь трасс, га", 50, 300, 143)
    N, rec = c.recreation(sk, stay, opn, trk)
    with c2:
        st.metric("Средняя одновременная нагрузка N", f"{N:,.0f} чел.".replace(",", " "),
                  help="N = суточные × время катания / часы работы. Среднее, не пик.")
        dfr = pd.DataFrame(rec)
        fig = go.Figure(go.Bar(x=[f"{d} чел/га" for d in dfr["density_limit"]], y=dfr["CCC"],
                               marker_color=["#2b6" if v > 0 else "#d33" for v in dfr["margin"]]))
        fig.add_hline(y=N, line_dash="dash", annotation_text="N")
        fig.update_layout(height=360, yaxis_title="CCC, чел.", margin=dict(t=10))
        st.plotly_chart(fig, width="stretch")
        st.dataframe(dfr.rename(columns={"density_limit": "Предел плотности, чел/га",
                                         "density_per_ha": "Плотность, чел/га", "margin": "Запас"}).round(2),
                     hide_index=True, width="stretch")
        st.caption("Пределы плотности — чувствительность, не локальные нормы. "
                   "Распределение по классам трасс и пик в пакете = ND.")

# ---------- 4. запас и решение ----------
with tab4:
    st.write("Нормированный запас и трёхзначное решение: PASS / FAIL / INDETERMINATE.")
    c1, c2 = st.columns(2)
    with c1:
        direction = st.radio("Направление показателя", ["upper (нагрузка ограничена сверху)",
                                                         "lower (нужно не меньше порога)"])
        direction = direction.split()[0]
        R = st.number_input("R — ориентир/фон", value=0.0)
        B = st.number_input("B — предел", value=100.0)
    with c2:
        Llo = st.number_input("L, нижняя граница нагрузки", value=40.0)
        Lhi = st.number_input("L, верхняя граница нагрузки", value=70.0)
        applicable = st.checkbox("Показатель применим к объекту (пространственно подтверждён)", True)
    try:
        m_a, m_b = c.margin(R, B, Llo, direction), c.margin(R, B, Lhi, direction)
        lo, hi = min(m_a, m_b), max(m_a, m_b)
        d = c.decision(lo, hi, applicable)
        st.metric("Запас m (интервал)", f"[{lo:.3f}; {hi:.3f}]")
        {"PASS": st.success, "FAIL": st.error, "INDETERMINATE": st.warning}[d](f"Решение: {d}")
    except ValueError as e:
        st.error(str(e))

# ---------- 5. карта ----------
with tab5:
    gdf, rows = load_contours()
    show_cad = st.checkbox("Показать 4 кадастровых полигона. " + LBL_PARCELS, False)
    import cadastre_check as _cc
    _par = _cc.read_parcels(str(__import__("pathlib").Path(__file__).parent / "data" / "parcels_unofficial_osmanov.geojson"))[0].to_crs(4326) if show_cad else None
    st.plotly_chart(contour_figure(gdf, st.slider("Буфер, м", 0, 1000, 300, 100), _par), width="stretch")
    st.subheader("Контроль геометрии")
    ctl = geometry_control(gdf)
    st.dataframe(ctl.drop(columns="_формальная"), hide_index=True, width="stretch")
    st.caption(f"Методы: геодезическая площадь — {M_GEOD}; плоская — {M_UTM}. Геометрия не исправляется и не упрощается.")
    ov = overlap_stats(gdf)
    k1, k2, k3 = st.columns(3)
    k1.metric("Пересечение 89–96 с 1–88", f"{ov['intersection_ha']:.2f} га")
    k2.metric("Объединение двух контуров", f"{ov['union_ha']:.2f} га")
    k3.metric("Заявлено", "1002 га")
    st.caption("Контуры 1–88 и 89–96 пересекаются, складывать их нельзя.")
    with st.expander("Диагностика: формальная площадь invalid-полигона"):
        bad = ctl[ctl["Геометрия"].str.startswith("INVALID")]
        for _, r in bad.iterrows():
            st.write(f"{r['Вариант']}: {r['_формальная']} — результат вычисления для "
                     "самопересекающейся геометрии, не площадь территории.")
    st.caption("Диагностическая реконструкция по опубликованным точкам; не кадастровая граница. "
               "Разбиение точек на четыре кадастровых участка (136,53 + 178,058 + 228,21 + 459,202 = 1002 га) "
               "в документах не раскрыто; подбирать фрагменты под 1002 га нельзя. Статус: SPATIAL / INDETERMINATE.")

# ---------- 6. кадастр ----------
with tab6:
    import cadastre_check as cc, tempfile, os
    st.write("Четыре заявленных участка (сумма 1002,0000 га). Границы нужно загрузить из ПКК/ЕГКН "
             "(GeoJSON, KML, GPKG или zip со SHP) — в пакет они не входят.")
    st.dataframe(cc.declared(), hide_index=True, width="stretch")
    use_bundled = st.checkbox("Использовать набор из пакета (получен 08.11.2026). " + LBL_PARCELS, False)
    up = st.file_uploader("Файл с полигонами участков", type=["geojson", "json", "kml", "gpkg", "zip"])
    tol = st.number_input("Допуск расхождения площади, %", 0.0, 10.0, 1.0, 0.5)
    if up is not None or use_bundled:
        try:
            if use_bundled and up is None:
                src = os.path.join(os.path.dirname(__file__), "data", "parcels_unofficial_osmanov.geojson")
                st.warning("Неофициальный источник. Статус границ в ЕГКН: ND.")
            else:
                path = os.path.join(tempfile.mkdtemp(), up.name)
                open(path, "wb").write(up.getvalue())
                src = "zip://" + path if up.name.endswith(".zip") else path
            parcels, cols, used = cc.read_parcels(src)
            if cols:
                pick = st.selectbox("Поле с кадастровым номером (определено автоматически)", cols,
                                    index=cols.index(used) if used in cols else 0)
                if pick != used:
                    parcels, _, _ = cc.read_parcels(src, field=pick)
            tab, res = cc.check(parcels, tol)
            if tab is not None:
                st.dataframe(tab, hide_index=True, width="stretch")
            if "stop" in res:
                st.error(res["stop"])
            else:
                m1, m2 = st.columns(2)
                m1.metric("Сумма площадей, геодезически (WGS84, pyproj.Geod)", f"{res['geodesic_sum_ha']:.6f} га",
                          f"{res['geodesic_diff_ha']:+.6f} га / {res['geodesic_diff_pct']:+.6f} % к 1002")
                m2.metric("Объединение, плоско (UTM 43N, EPSG:32643)", f"{res['union_ha']:.6f} га",
                          f"{res['union_vs_1002_ha']:+.6f} га к 1002")
                st.caption(f"Взаимные наложения участков: {res['overlaps_ha']:.4f} га. Заявленная сумма: 1002,0000 га. "
                           "Официальный статус установления границ в ЕГКН: ND.")
                for n in ("контур 1–88", "контур 89–96"):
                    r = res[n]
                    st.write(f"**{LABELS[n]}**: точек внутри кадастровых участков {r['points_inside']} из {r['points_total']}; "
                             f"площадь контура {r['area_ha']:.2f} га, внутри {r['inside_ha']:.2f} га "
                             f"({r['share_inside_pct']:.1f} %), вне {r['outside_ha']:.2f} га.")
                if res["found"] < 4:
                    st.warning(f"Идентифицировано {res['found']}/4 участков — вывод неполный (ND).")
        except Exception as e:
            st.error(f"Не удалось прочитать файл: {e}")
    else:
        st.info("Файл не загружен: сверка не выполняется, статус SPATIAL / INDETERMINATE сохраняется.")

# ---------- 7. DNRE 2.0 / A5: устойчивость к прочтениям границы (A5a метрики, A5b вердикты) ----------
with tab7:
    import a5_robustness as a5
    rd = a5.boundary_readings()
    st.subheader("A5a. Metric Robustness")
    st.write("Значение метрики при трёх допустимых прочтениях площади границы. Порогов и вердиктов здесь нет.")
    c1, c2 = st.columns(2)
    with c1:
        l_day = st.number_input("L_сут, чел./сут (R1)", 1.0, 1_000_000.0, float(a5.DEFAULT_L_DAY), 500.0)
    with c2:
        a_dist = st.number_input("A_наруш, га (I1; публичная оценка ≈300, не измерение)",
                                 0.1, 5000.0, float(a5.DEFAULT_A_DISTURBED), 10.0)
    mets = a5.default_metrics(l_day, None, a_dist, None)
    mrows = [a5.assess_metric(m, rd) for m in mets]
    st.dataframe(a5.metrics_dataframe(mrows, rd), hide_index=True, width="stretch")
    st.caption("Все 96 точек подряд (2134,59 га) — невалидный полигон, в набор не входит. "
               "Сумма контуров 2107,37 га неверна: пересечение 5,88 га считается дважды.")

    st.subheader("A5b. Verdict Robustness")
    st.write("Вердикт и R_flip считаются только там, где есть обоснованный порог. "
             "Нет порога, но площадь меняет значение: R_flip = NA (TG), а не 0. "
             "Это не VoI: у прочтений нет вероятностей.")
    limits = {}
    for m in mets:
        on = st.checkbox(f"Ввести порог для {m.code} (из документа; по умолчанию порога нет)", False, key=f"lim_on_{m.code}")
        if on:
            limits[m.code] = st.number_input(f"Порог {m.code}, не больше, {m.unit}", 0.01, 1_000_000.0,
                                             10.0, 0.5, key=f"lim_{m.code}")
    base = st.selectbox("Базовое прочтение θ0", range(len(rd)),
                        format_func=lambda i: f"{rd[i].label} — {rd[i].source}")
    doms = a5.default_domains(mets, limits)
    rows7 = [a5.assess(d, rd, base) for d in doms]
    s7 = a5.summary(rows7)
    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("Доменов", s7["domains"])
    k2.metric("Зависят от границы", s7["depend_on_boundary"])
    k3.metric("Чувствительны", s7["sensitive"])
    k4.metric("R_flip = NA (TG)", s7["na_tg"])
    k5.metric("N/A (не зависят от границы)", s7["na_independent"])
    df7 = a5.to_dataframe(rows7, rd)
    st.dataframe(df7, hide_index=True, width="stretch")
    if s7["package_depend"] == 0:
        st.info("Домены пакета (вода, CCC) не используют площадь границы, R_flip = N/A (not boundary-dependent), "
                "это не доказательство устойчивости. " + a5.NOT_BOUNDARY[0].capitalize() + ": "
                + a5.NOT_BOUNDARY[1] + ".")
    for name, why in a5.NO_VERDICT:
        st.caption(f"Без вердикта в пакете: {name} — {why}.")
    st.caption("Отложено до официальных полигонов: S2 (сохранённый свободный доступ, A_своб,P1 / A_своб,M0) "
               "и пространственные индикаторы A3.")
    st.download_button("Скачать A5b (CSV)", df7.to_csv(index=False).encode("utf-8-sig"),
                       "a5b_verdict_robustness.csv", "text/csv")
    st.download_button("Скачать A5a (CSV)", a5.metrics_dataframe(mrows, rd).to_csv(index=False).encode("utf-8-sig"),
                       "a5a_metric_robustness.csv", "text/csv")

# ---------- 8. DNRE 2.0 / A2: зимний минимум M(t) по межени ----------
with tab8:
    import io
    import a2_winter_minimum as a2
    st.write("Зимний минимум M(t) = (Q_nat − W_div − Q_min) / (Q_nat − Q_min) по месяцам, вердикт блока по XI–III. "
             "Пустая ячейка = ND(DATA), а не 0. Оценочные значения не подставляются. "
             "Единицы: м³ за месяц; интервал задаётся колонками *_lo и *_hi.")
    st.download_button("Скачать пустой шаблон (CSV)",
                       a2.template_dataframe().to_csv(index=False).encode("utf-8-sig"),
                       "a2_winter_minimum_template.csv", "text/csv")
    up2 = st.file_uploader("Заполненный шаблон (CSV)", type=["csv"], key="a2_csv")
    try:
        if up2 is not None:
            df2 = pd.read_csv(io.BytesIO(up2.getvalue()), dtype=str, keep_default_na=False)
        else:
            df2 = a2.template_dataframe()
            st.info("Файл не загружен: данных по Q_nat, W_div, Q_min нет, статус ND(DATA) / INDETERMINATE. "
                    "Запросы к KTD, Казгидромету и Казгидрогеологии отправлены, ответы ожидаются.")
        res2, verdict2, why2 = a2.assess(df2)
        st.metric("Вердикт блока A2 (XI–III)", verdict2)
        st.caption(why2)
        st.dataframe(a2.to_dataframe(res2), hide_index=True, width="stretch")
    except ValueError as e:
        st.error(f"Ошибка во входных данных: {e}")
