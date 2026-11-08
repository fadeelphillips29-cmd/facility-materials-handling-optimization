"""Smoke tests of the Streamlit dashboard (Streamlit AppTest)."""

from __future__ import annotations

from pathlib import Path

import pytest

AppTest = pytest.importorskip("streamlit.testing.v1").AppTest
APP = str(Path(__file__).resolve().parents[1] / "app" / "dashboard.py")


def test_dashboard_loads():
    at = AppTest.from_file(APP, default_timeout=60).run()
    assert not at.exception
    assert any("Illustrative" in w.value for w in at.warning)


def test_dashboard_runs_small_simulation():
    at = AppTest.from_file(APP, default_timeout=240).run()
    at.slider(key="reps").set_value(5)
    at.slider(key="weeks").set_value(10)
    at.slider(key="workers").set_value(1)
    at.slider(key="crew").set_value(3)
    at.button(key="run").click().run()
    assert not at.exception
    labels = [m.label for m in at.metric]
    assert "Order lead time" in labels and "Bottleneck" in labels
