"""Проверка зимних показателей Терисбутака из агрегатов (суточный ряд в репозитории отсутствует)."""
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "terisbutak"))
import winter_flow as wf  # noqa: E402


def test_aggregates_reproduce_tables():
    assert wf.verify()


def test_full_seasons_and_minima():
    st = pd.read_csv(wf.OUT / "Season_Metrics.csv").set_index("season")
    assert list(st.index[st["full_season"]]) == [2021, 2022, 2023]
    assert st.loc[[2021, 2022, 2023], "min_m3s"].round(2).tolist() == [0.36, 0.48, 0.21]
    assert not st.loc[[2020, 2024], "full_season"].any()


def test_source_hash_recorded():
    assert (wf.OUT / "Source_SHA256.txt").read_text().startswith("8d4dfbcc0c39de382c6ca2c520dd7f693662c1dfaf38ca2d152d515b780c99ba")
