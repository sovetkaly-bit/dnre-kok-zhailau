#!/usr/bin/env python3
"""Зимний сток ручья Терисбутак (пост 14253, устье): воспроизводимый расчёт.

Использование: python scripts/terisbutak_winter.py WORKBOOK.xlsx OUTPUT_DIR
Исходный файл в репозиторий не добавляется. Пропуски не заполняются.
Код возврата 1, если не прошла проверка входа или сверка с эталоном.
"""
import argparse
import calendar
import hashlib
import re
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

import numpy as np
import pandas as pd

EXPECTED_SHA256 = '8d4dfbcc0c39de382c6ca2c520dd7f693662c1dfaf38ca2d152d515b780c99ba'
POST = 14253
SHEET = 'Суточные расходы'
HEADERS = ['Дата', 'Пост', 'Расход, м³/с', 'Исходная запись', 'Помета']
WINTER_MONTHS = (11, 12, 1, 2, 3)
FULL_SEASONS = (2021, 2022, 2023)  # годом окончания: 2020/21, 2021/22, 2022/23
SECONDS_PER_DAY = 86400
# Эталон: сутки, минимум м³/с, объём м³.
REFERENCE = {2021: (151, '0.36', 5422464),
             2022: (151, '0.48', 6848064),
             2023: (151, '0.21', 4171392)}
RAW = re.compile(r'^\s*([0-9]+(?:\.[0-9]+)?)\s*(\D*?)\s*$')
MONTH_NAMES = {1: 'январь', 2: 'февраль', 3: 'март', 11: 'ноябрь', 12: 'декабрь'}


def season_of(ts):
    return ts.year + 1 if ts.month >= 11 else ts.year


def season_label(s):
    return f'{s - 1}/{str(s)[2:]}'


def expected_days(s):
    feb = 29 if calendar.isleap(s) else 28
    return 30 + 31 + 31 + feb + 31


def load(path):
    df = pd.read_excel(path, sheet_name=SHEET, engine='openpyxl')
    return df


def prepare(df):
    """Проверки входа. Возвращает (таблица, список проверок)."""
    checks = []

    def check(name, ok, detail=''):
        checks.append({'check': name, 'ok': bool(ok), 'detail': detail})

    check('заголовки листа', list(df.columns[:5]) == HEADERS, ' | '.join(map(str, df.columns[:5])))
    check('единицы м³/с в заголовке расхода', 'м³/с' in str(df.columns[2]), str(df.columns[2]))
    d = pd.DataFrame({'date': pd.to_datetime(df['Дата']), 'post': df['Пост'],
                      'raw': df['Исходная запись'].astype(str), 'mark': df['Помета']})
    check('код поста 14253 во всех строках', (d.post == POST).all(), f'уникальные: {sorted(int(x) for x in d.post.unique())}')
    check('дублей дат нет', d.date.is_unique, f'строк {len(d)}')
    full = pd.date_range('2020-01-01', '2023-12-31', freq='D')
    check('непрерывность 1461 даты 01.01.2020–31.12.2023',
          len(d) == 1461 and list(d.date.sort_values()) == list(full),
          f'строк {len(d)}, первая {d.date.min().date()}, последняя {d.date.max().date()}')
    values, parsed_marks, ok_parse = [], [], True
    for raw in d.raw:
        m = RAW.match(raw)
        if not m:
            ok_parse = False
            values.append(None); parsed_marks.append('')
        else:
            values.append(Decimal(m.group(1))); parsed_marks.append(m.group(2))
    check('исходные записи разобраны без потерь', ok_parse)
    d['q'] = values
    num = pd.to_numeric(df['Расход, м³/с'])
    check('числовая колонка совпадает с исходной записью',
          all(float(v) == float(n) for v, n in zip(d.q, num)))
    check('пометы совпадают с символами исходной записи',
          all((p or '') == (str(m) if pd.notna(m) else '') for p, m in zip(parsed_marks, d.mark)))
    check('пропусков значений нет', d.q.notna().all() and num.notna().all())
    check('значения неотрицательны', all(v >= 0 for v in d.q))
    d = d.sort_values('date').reset_index(drop=True)
    d['month'] = d.date.dt.month
    d['winter'] = d.month.isin(WINTER_MONTHS)
    d['season'] = [season_of(t) if w else None for t, w in zip(d.date, d.winter)]
    if 'Зимний сезон' in df.columns:
        book = df.sort_values('Дата')['Зимний сезон'].reset_index(drop=True)
        mine = d.season.astype('float')
        same = ((book.isna() & mine.isna()) | (book == mine)).all()
        check('сезон ноябрь–март (год окончания) совпадает с колонкой книги', same)
    return d, checks


def dec_sum(vals):
    total = Decimal(0)
    for v in vals:
        total += v
    return total


def volume_m3(vals):
    return dec_sum(vals) * SECONDS_PER_DAY


def stats(g):
    qs = list(g.q)
    mn = min(qs)
    first_min = g.loc[g.q == mn].iloc[0]
    return {'days': len(g), 'first_date': g.date.min().date(), 'last_date': g.date.max().date(),
            'mean_m3s': float(dec_sum(qs) / len(qs)), 'median_m3s': float(np.median([float(v) for v in qs])),
            'min_m3s': float(mn), 'min_date': first_min.date.date(), 'min_day_raw': first_min.raw,
            'volume_m3': int(volume_m3(qs))}


def min_7day(g):
    g = g.sort_values('date').reset_index(drop=True)
    dates = list(g.date)
    best = None
    for i in range(len(g) - 6):
        if (dates[i + 6] - dates[i]).days != 6:  # только 7 последовательных суток
            continue
        s = dec_sum(g.q[i:i + 7])
        if best is None or s < best[0]:
            best = (s, dates[i].date(), dates[i + 6].date())
    if best is None:
        return {'min7_mean_m3s': np.nan, 'min7_start': None, 'min7_end': None}
    return {'min7_mean_m3s': float(best[0] / 7), 'min7_start': best[1], 'min7_end': best[2]}


def summaries(d):
    w = d[d.winter]
    seasonal, monthly, incomplete = [], [], []
    for s, g in w.groupby('season'):
        s = int(s)
        full = s in FULL_SEASONS
        row = {'season': season_label(s), 'season_end_year': s, 'full': full,
               'expected_days': expected_days(s)}
        row.update(stats(g)); row.update(min_7day(g))
        (seasonal if full else incomplete).append(row)
        if full:
            for m, gm in g.groupby('month'):
                r = {'season': season_label(s), 'month': int(m), 'month_name': MONTH_NAMES[int(m)]}
                r.update(stats(gm))
                monthly.append(r)
    seasonal = pd.DataFrame(seasonal)
    monthly = pd.DataFrame(monthly)
    order = {11: 0, 12: 1, 1: 2, 2: 3, 3: 4}
    monthly = monthly.sort_values(['season', 'month'], key=lambda c: c.map(order) if c.name == 'month' else c)
    incomplete = pd.DataFrame(incomplete)
    spread = []
    for label, col in [('объём стока за сезон, м³', 'volume_m3'),
                       ('суточный минимум, м³/с', 'min_m3s'),
                       ('семисуточный минимум (среднее за 7 суток), м³/с', 'min7_mean_m3s')]:
        v = seasonal[col].astype(float)
        spread.append({'metric': label, 'min': v.min(), 'max': v.max(), 'range': v.max() - v.min(),
                       'max_to_min_ratio': v.max() / v.min(), 'mean': v.mean(),
                       'sd_n_minus_1': v.std(ddof=1), 'cv_percent': 100 * v.std(ddof=1) / v.mean(),
                       'n_winters': len(v)})
    return seasonal, monthly, incomplete, pd.DataFrame(spread)


def reference_check(d, seasonal, incomplete):
    rows = []
    for s, (days, mn, vol) in REFERENCE.items():
        r = seasonal[seasonal.season_end_year == s].iloc[0]
        ok = (int(r.days) == days and Decimal(str(r.min_m3s)) == Decimal(mn) and int(r.volume_m3) == vol)
        rows.append({'season': season_label(s), 'days_ref': days, 'days_calc': int(r.days),
                     'min_ref_m3s': float(mn), 'min_calc_m3s': r.min_m3s,
                     'volume_ref_m3': vol, 'volume_calc_m3': int(r.volume_m3), 'ok': ok, 'note': ''})
    p = incomplete[incomplete.season_end_year == 2024].iloc[0]
    months = sorted(set(d[(d.season == 2024)].month))
    ok = (Decimal(str(p.min_m3s)) == Decimal('0.18') and months == [11, 12]
          and str(p.first_date) == '2023-11-01' and str(p.last_date) == '2023-12-31')
    rows.append({'season': '2023/24 (неполный)', 'days_ref': None, 'days_calc': int(p.days),
                 'min_ref_m3s': 0.18, 'min_calc_m3s': p.min_m3s, 'volume_ref_m3': None,
                 'volume_calc_m3': int(p.volume_m3), 'ok': ok,
                 'note': f'покрытие {p.first_date} – {p.last_date}, месяцы {months}: только ноябрь–декабрь 2023 года'})
    return pd.DataFrame(rows)


def marks_table(d):
    w = d[d.winter].copy()
    w['mark'] = w.mark.fillna('(нет)')
    w['season'] = w.season.astype(int).map(season_label)
    return w.pivot_table(index='season', columns='mark', values='q', aggfunc='size', fill_value=0).reset_index()


def make_plot(d, seasonal, out):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(len(FULL_SEASONS), 1, figsize=(10, 9.5), sharey=True, layout='constrained')
    for ax, s in zip(axes, FULL_SEASONS):
        g = d[d.season == s].sort_values('date').reset_index(drop=True)
        q = g.q.astype(float)
        roll = q.rolling(7).mean()
        ax.step(g.date, q, where='mid', lw=1.1, color='#1f77b4', label='суточный расход')
        ax.plot(g.date, roll, lw=2.0, color='#d62728', label='семисуточное среднее (по концу окна)')
        r = seasonal[seasonal.season_end_year == s].iloc[0]
        ax.axvspan(pd.Timestamp(r.min7_start), pd.Timestamp(r.min7_end), color='#d62728', alpha=0.18,
                   label=f'минимальные 7 суток: {r.min7_start:%d.%m}–{r.min7_end:%d.%m}, {r.min7_mean_m3s:.3f} м³/с')
        ax.scatter([pd.Timestamp(r.min_date)], [r.min_m3s], color='black', zorder=5,
                   label=f'суточный минимум {r.min_m3s:.2f} м³/с, {r.min_date:%d.%m.%Y}')
        ax.set_title(f'Зима {season_label(s)}: {int(r.days)} сут., объём {r.volume_m3 / 1e6:.3f} млн м³')
        ax.set_ylabel('Q, м³/с'); ax.grid(alpha=0.3); ax.set_ylim(0.15, 1.0)
        ax.legend(fontsize=8, loc='upper center', ncol=2, frameon=False)
    axes[-1].set_xlabel('Дата')
    fig.suptitle('Терисбутак — устье (пост 14253): зимний сток, ноябрь–март', fontsize=13)
    fig.savefig(out, dpi=150)
    plt.close(fig)


def conclusion(seasonal, spread, incomplete, ref):
    def f(x, n=2):
        return f'{x:,.{n}f}'.replace(',', ' ').replace('.', ',')
    s = {int(r.season_end_year): r for r in seasonal.itertuples()}
    sp = {r.metric: r for r in spread.itertuples()}
    v, dm, m7 = (sp['объём стока за сезон, м³'], sp['суточный минимум, м³/с'],
                 sp['семисуточный минимум (среднее за 7 суток), м³/с'])
    inc = {int(r.season_end_year): r for r in incomplete.itertuples()}
    lines = ['# Зимний сток Терисбутака по посту 14253: вывод для монографии', '',
             'По данным среднесуточных расходов Казгидромета за 2020–2023 годы измерен сток ручья Терисбутак '
             'в устье (пост 14253). Три полные зимы (ноябрь–март, год обозначен годом окончания) дали такой разброс. '
             f'Объём стока за сезон: {f(s[2021].volume_m3 / 1e6, 3)} млн м³ (2020/21), {f(s[2022].volume_m3 / 1e6, 3)} млн м³ (2021/22) '
             f'и {f(s[2023].volume_m3 / 1e6, 3)} млн м³ (2022/23), размах {f(v.range / 1e6, 3)} млн м³, отношение наибольшего к наименьшему '
             f'{f(v.max_to_min_ratio)}. Суточный минимум: {f(s[2021].min_m3s)}, {f(s[2022].min_m3s)} и {f(s[2023].min_m3s)} м³/с, '
             f'размах {f(dm.range)} м³/с. Минимальный средний расход за семь последовательных суток: '
             f'{f(s[2021].min7_mean_m3s, 3)} м³/с ({s[2021].min7_start:%d.%m.%Y}–{s[2021].min7_end:%d.%m.%Y}), '
             f'{f(s[2022].min7_mean_m3s, 3)} м³/с ({s[2022].min7_start:%d.%m.%Y}–{s[2022].min7_end:%d.%m.%Y}) и '
             f'{f(s[2023].min7_mean_m3s, 3)} м³/с ({s[2023].min7_start:%d.%m.%Y}–{s[2023].min7_end:%d.%m.%Y}), '
             f'размах {f(m7.range, 3)} м³/с.', '',
             f'Неполные сезоны показаны отдельно и в сводку по трём зимам не входят. Сезон 2019/20 покрыт с {inc[2020].first_date:%d.%m.%Y} '
             f'по {inc[2020].last_date:%d.%m.%Y} ({int(inc[2020].days)} из {int(inc[2020].expected_days)} суток). Сезон 2023/24 покрыт с '
             f'{inc[2024].first_date:%d.%m.%Y} по {inc[2024].last_date:%d.%m.%Y} ({int(inc[2024].days)} из {int(inc[2024].expected_days)} суток), '
             f'суточный минимум {f(inc[2024].min_m3s)} м³/с достигнут {inc[2024].min_date:%d.%m.%Y}. Этот фрагмент охватывает только '
             'ноябрь–декабрь 2023 года, поэтому с полными зимами его сравнивать нельзя.', '',
             'Границы применимости. Измерен сток в устье Терисбутака. Оценка воды, доступной для оснежения, требует отдельного '
             'расчёта в проектном створе с учётом экологического расхода и действующих водозаборов. Три зимы позволяют описать '
             'наблюдавшийся разброс, но их недостаточно для оценки многолетней обеспеченности.', '',
             f'Контрольная сверка с эталоном: {"пройдена" if ref.ok.all() else "НЕ ПРОЙДЕНА"}.']
    return '\n'.join(lines) + '\n'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('workbook', type=Path)
    ap.add_argument('output', type=Path)
    ap.add_argument('--sha256', default=EXPECTED_SHA256)
    a = ap.parse_args()
    a.output.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(a.workbook.read_bytes()).hexdigest()
    sha_ok = digest == a.sha256
    d, checks = prepare(load(a.workbook))
    checks.insert(0, {'check': 'SHA-256 входного файла', 'ok': sha_ok, 'detail': digest})
    seasonal, monthly, incomplete, spread = summaries(d)
    ref = reference_check(d, seasonal, incomplete)
    for name, tab in [('Input_Checks', pd.DataFrame(checks)), ('Seasonal_Summary', seasonal),
                      ('Monthly_Summary', monthly), ('Incomplete_Seasons', incomplete),
                      ('Spread_Three_Winters', spread), ('Reference_Check', ref),
                      ('Marks_By_Season', marks_table(d))]:
        tab.to_csv(a.output / f'{name}.csv', index=False)
    make_plot(d, seasonal, a.output / 'Winter_Flow.png')
    (a.output / 'Conclusion_Monograph.md').write_text(conclusion(seasonal, spread, incomplete, ref), encoding='utf-8')
    ok = all(c['ok'] for c in checks) and bool(ref.ok.all())
    report = ['Проверки входа:'] + [f'- {"OK" if c["ok"] else "ОШИБКА"}: {c["check"]} ({c["detail"]})' for c in checks]
    report += ['Сверка с эталоном:'] + [f'- {"OK" if r.ok else "ОШИБКА"}: {r.season}: сутки {r.days_calc}, '
                                        f'минимум {r.min_calc_m3s}, объём {r.volume_calc_m3} {r.note}' for r in ref.itertuples()]
    report.append('ИТОГ: ' + ('все проверки пройдены' if ok else 'ЕСТЬ РАСХОЖДЕНИЯ'))
    (a.output / 'Check_Report.md').write_text('\n'.join(report) + '\n', encoding='utf-8')
    print('\n'.join(report))
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
