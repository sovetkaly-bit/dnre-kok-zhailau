"""Сравнение пересчитанных таблиц v5 с эталонами и проверка ключевых чисел.

Использование: python scripts/compare_v5.py EXPECTED_DIR OUTPUT_DIR REPORT.md
Исходные CSV Meteo.Yerm не читаются.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

expected, output, report = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
lines, failed = [], False

def log(msg):
    lines.append(msg)
    print(msg)

names = sorted(p.name for p in expected.glob('*_v5.csv'))
log(f'Сравнение {len(names)} CSV: эталон {expected}, пересчёт {output}')
for name in names:
    new = output / name
    if not new.exists():
        log(f'- {name}: НЕТ В ПЕРЕСЧЁТЕ'); failed = True; continue
    if (expected / name).read_bytes() == new.read_bytes():
        log(f'- {name}: побайтово совпадает'); continue
    a, b = pd.read_csv(expected / name), pd.read_csv(new)
    if a.shape != b.shape or list(a.columns) != list(b.columns):
        log(f'- {name}: РАЗЛИЧАЕТСЯ форма {a.shape} vs {b.shape}'); failed = True; continue
    worst = (0.0, None)
    for col in a.columns:
        if pd.api.types.is_numeric_dtype(a[col]) and pd.api.types.is_numeric_dtype(b[col]):
            d = (a[col] - b[col]).abs()
            d = d.where(~(a[col].isna() & b[col].isna()), 0).fillna(np.inf)
            if len(d) and d.max() > worst[0]:
                worst = (float(d.max()), (int(d.idxmax()), col))
        else:
            bad = a[col].astype(str) != b[col].astype(str)
            if bad.any():
                worst = (np.inf, (int(bad.idxmax()), col))
    if worst[0] == 0:
        log(f'- {name}: совпадает по значениям, различается только запись байтов')
    else:
        row, col = worst[1]
        log(f'- {name}: РАЗЛИЧИЕ, строка {row}, колонка {col}, величина {worst[0]}'); failed = True

t = pd.read_csv(output / 'Rain_Snow_Interaction_v5.csv')
def pick(station, variant):
    return t[(t['Станция'] == station) & (t.variant == variant)].iloc[0]
checks = []
s = pick('Шымбулак', '3_all_months')
checks.append(('Шымбулак ОШ 0,945', round(s.odds_ratio, 3) == 0.945))
checks.append(('Шымбулак ДИ 0,758–1,177', (round(s.or_low, 3), round(s.or_high, 3)) == (0.758, 1.177)))
b = pick('Большое Алматинское озеро', '1_mar_apr')
checks.append(('БАО март–апрель ОШ 1,67 [1,04; 2,68]',
               (round(b.odds_ratio, 2), round(b.or_low, 2), round(b.or_high, 2)) == (1.67, 1.04, 2.68)))
checks.append(('Оценены 12 из 15 моделей', int((t.status == 'estimated').sum()) == 12 and len(t) == 15))
for station, expect in [('Большое Алматинское озеро', 2665), ('Мынжилки', 3866), ('Шымбулак', 744)]:
    r = pick(station, '3_all_months')
    total = int(r.likelihood_days + r.separated_nuisance_days)
    checks.append((f'{station}: разделённые уровни {expect}/6552',
                   int(r.separated_nuisance_days) == expect and total == 6552))
v = pd.read_csv(output / 'Interaction_Verdicts_v5.csv').set_index('Станция').verdict
checks.append(('Шымбулак: не подтверждён', v['Шымбулак'] == 'не подтверждён'))
checks.append(('БАО: различить нельзя', v['Большое Алматинское озеро'] == 'различить нельзя'))
log('Ключевые результаты:')
for text, ok in checks:
    log(f'- {"OK" if ok else "НЕ СОВПАЛО"}: {text}')
    failed |= not ok
report.write_text('\n'.join(lines) + '\n', encoding='utf-8')
sys.exit(1 if failed else 0)
