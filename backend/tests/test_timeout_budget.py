"""The timeouts of a planner turn must nest: backend work < browser client timeout < Cloud Run request timeout.

A turn may wait for the session lock, spend the whole LLM budget (then degrade to rules and still return 200) and
run the journey search (RailRadar has its own timeout). The frontend planner timeout must outlast that, and Cloud
Run must not cut the request first."""

import re

from app.config import REPO_ROOT, Settings

DEPLOY = REPO_ROOT / ".github" / "workflows" / "deploy.yml"
CLIENT = REPO_ROOT / "frontend" / "src" / "api" / "client.ts"


def _cloud_run_backend_timeout() -> int:
    text = DEPLOY.read_text(encoding="utf-8")
    step = text[text.index("- name: Deploy backend"):text.index("- name: Smoke test backend")]
    return int(re.search(r"--timeout (\d+)", step).group(1))


def _client_ms(name: str) -> int:
    match = re.search(rf"export const {name} = ([\d_]+)", CLIENT.read_text(encoding="utf-8"))
    return int(match.group(1).replace("_", ""))


def test_planner_turn_budget_nests_inside_client_and_cloud_run_timeouts():
    s = Settings(_env_file=None)
    backend_turn = s.session_lock_wait_seconds + s.planner_turn_budget_seconds
    client = _client_ms("PLANNER_TIMEOUT_MS") / 1000
    cloud_run = _cloud_run_backend_timeout()
    assert backend_turn <= client < cloud_run, (backend_turn, client, cloud_run)


def test_plain_read_timeout_is_not_longer_than_planner_timeout():
    assert _client_ms("READ_TIMEOUT_MS") <= _client_ms("PLANNER_TIMEOUT_MS")


def test_smoke_planner_message_timeout_outlasts_the_backend_turn():
    smoke = (REPO_ROOT / "backend" / "scripts" / "smoke.sh").read_text(encoding="utf-8")
    planner_call = smoke[smoke.index('REPLY="$(curl'):]
    max_time = int(re.search(r"--max-time (\d+)", planner_call).group(1))
    s = Settings(_env_file=None)
    assert max_time > s.session_lock_wait_seconds + s.planner_turn_budget_seconds
    assert max_time < _cloud_run_backend_timeout()
