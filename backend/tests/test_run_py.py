"""run.py (repo root) starts the backend with RAILWAY_DATA_MODE=ntes unless the user already chose a mode."""

import importlib.util
from pathlib import Path

RUN_PY = Path(__file__).resolve().parents[2] / "run.py"


def load_run():
    spec = importlib.util.spec_from_file_location("railsaathi_run", RUN_PY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_ntes_is_the_local_default_when_nothing_is_set(tmp_path):
    run = load_run()
    assert run.default_data_mode({}, tmp_path / "missing.env") == "ntes"
    env = tmp_path / ".env"
    env.write_text("APP_ENV=development\n# RAILWAY_DATA_MODE=demo\nRAILWAY_DATA_MODE=\n", encoding="utf-8")
    assert run.default_data_mode({"PATH": "x"}, env) == "ntes"


def test_a_mode_set_in_the_environment_or_backend_env_wins(tmp_path):
    run = load_run()
    assert run.default_data_mode({"RAILWAY_DATA_MODE": "demo"}, tmp_path / "missing.env") is None
    assert run.default_data_mode({"DATA_PROVIDER": "railradar"}, tmp_path / "missing.env") is None
    env = tmp_path / ".env"
    env.write_text("railway_data_mode = demo\n", encoding="utf-8")
    assert run.default_data_mode({}, env) is None
