"""The backend deploy step of .github/workflows/deploy.yml, run with a stub `gcloud`: the optional Maps browser key
secret is mounted only when the MAPS_BROWSER_KEY_SECRET repository variable names it, so a project without that
secret still deploys."""

import re
import shutil
import subprocess
import textwrap

import pytest

from app.config import REPO_ROOT

DEPLOY = REPO_ROOT / ".github" / "workflows" / "deploy.yml"
BASE_SECRETS = "REDIS_URL=REDIS_URL:latest,SESSION_SIGNING_KEY=SESSION_SIGNING_KEY:latest"
RAILRADAR_SECRET = "RAILRADAR_API_KEY=RAILRADAR_API_KEY:latest"
MODE_EXPR = "${{ vars.RAILWAY_DATA_MODE || 'ntes' }}"
BASH = shutil.which("bash")


def _backend_step_script() -> str:
    text = DEPLOY.read_text(encoding="utf-8")
    step = text[text.index("- name: Deploy backend"):text.index("- name: Smoke test backend")]
    return textwrap.dedent(step[step.index("run: |") + len("run: |"):].strip("\n"))


def _deployed_secrets(tmp_path, maps_secret_var: str, mode: str = "ntes") -> str:
    script = _backend_step_script().replace("${{ vars.MAPS_BROWSER_KEY_SECRET || '' }}", maps_secret_var)
    script = script.replace(MODE_EXPR, mode)
    script = re.sub(r"\$\{\{[^}]*\}\}", "x", script)  # every other workflow expression
    args_file = tmp_path / "gcloud-args"
    stub = textwrap.dedent(f"""\
        gcloud() {{
          if [ "$1 $2" = "run deploy" ]; then printf '%s\\n' "$@" > '{args_file.as_posix()}'; else echo https://svc; fi
        }}
        export GITHUB_OUTPUT='{(tmp_path / "out").as_posix()}' BACKEND_SERVICE=svc REGION=r PROJECT_ID=p
        """)
    subprocess.run([BASH, "-c", stub + script], check=True, timeout=30)
    args = args_file.read_text(encoding="utf-8").splitlines()
    return args[args.index("--set-secrets") + 1]


@pytest.mark.skipif(BASH is None, reason="needs bash")
def test_deploy_works_without_the_maps_secret(tmp_path):
    assert _deployed_secrets(tmp_path, "") == BASE_SECRETS


@pytest.mark.skipif(BASH is None, reason="needs bash")
def test_deploy_mounts_the_maps_secret_when_the_variable_names_it(tmp_path):
    assert _deployed_secrets(tmp_path, "GOOGLE_MAPS_BROWSER_KEY") == (
        BASE_SECRETS + ",GOOGLE_MAPS_BROWSER_KEY=GOOGLE_MAPS_BROWSER_KEY:latest")


@pytest.mark.skipif(BASH is None, reason="needs bash")
def test_the_railradar_key_is_mounted_only_in_railradar_mode(tmp_path):
    assert RAILRADAR_SECRET not in _deployed_secrets(tmp_path, "", "ntes")
    assert _deployed_secrets(tmp_path, "", "railradar") == RAILRADAR_SECRET + "," + BASE_SECRETS


@pytest.mark.skipif(BASH is None, reason="needs bash")
def test_ntes_is_the_default_data_mode_and_the_variable_selects_another(tmp_path):
    def mode(args):
        value = args[args.index("--set-env-vars") + 1]
        return dict(item.split("=", 1) for item in value[3:].split("@"))["RAILWAY_DATA_MODE"]

    assert MODE_EXPR in _backend_step_script()
    assert mode(_deploy_args(tmp_path, {MODE_EXPR: "ntes"})) == "ntes"
    assert mode(_deploy_args(tmp_path, {MODE_EXPR: "railradar"})) == "railradar"


def test_maps_secret_is_never_mounted_unconditionally():
    script = _backend_step_script()
    assert "GOOGLE_MAPS_BROWSER_KEY" not in script.split("if [ -n")[0]


def _deploy_args(tmp_path, substitutions: dict[str, str]) -> list[str]:
    script = _backend_step_script()
    for expr, value in substitutions.items():
        script = script.replace(expr, value)
    script = re.sub(r"\$\{\{[^}]*\}\}", "x", script)
    args_file = tmp_path / "gcloud-args"
    stub = textwrap.dedent(f"""\
        gcloud() {{
          if [ "$1 $2" = "run deploy" ]; then printf '%s\n' "$@" > '{args_file.as_posix()}'; else echo https://svc; fi
        }}
        jq() {{ cat >/dev/null; echo https://candidate---svc; }}
        export GITHUB_OUTPUT='{(tmp_path / "out").as_posix()}' BACKEND_SERVICE=svc REGION=r PROJECT_ID=p
        """)
    subprocess.run([BASH, "-c", stub + script], check=True, timeout=30)
    return args_file.read_text(encoding="utf-8").splitlines()


@pytest.mark.skipif(BASH is None, reason="needs bash")
def test_comma_separated_env_values_survive_gcloud_delimiting(tmp_path):
    """AR_GUIDANCE_ENABLED and CORS_ORIGINS are comma lists; gcloud's default "," delimiter would split them."""
    args = _deploy_args(tmp_path, {"${{ vars.AR_GUIDANCE_ENABLED || '' }}": "chennai_central,mumbai_csmt",
                                   "${{ vars.FRONTEND_ORIGIN || '' }}": "https://a.example,https://b.example"})
    value = args[args.index("--set-env-vars") + 1]
    assert value.startswith("^@^")
    pairs = dict(item.split("=", 1) for item in value[3:].split("@"))
    assert pairs["AR_GUIDANCE_ENABLED"] == "chennai_central,mumbai_csmt"
    assert pairs["CORS_ORIGINS"] == "https://a.example,https://b.example"
    assert pairs["APP_ENV"] == "production"


@pytest.mark.skipif(BASH is None, reason="needs bash")
def test_backend_revision_gets_no_traffic_until_smoke_tested(tmp_path):
    args = _deploy_args(tmp_path, {})
    assert "--no-traffic" in args and args[args.index("--tag") + 1] == "candidate"
    outputs = (tmp_path / "out").read_text(encoding="utf-8")
    assert "candidate_url=https://candidate---svc" in outputs


def test_traffic_moves_only_after_the_candidate_smoke_test():
    text = DEPLOY.read_text(encoding="utf-8")
    smoke = text.index("- name: Smoke test backend")
    assert 'smoke.sh "${{ steps.backend.outputs.candidate_url }}"' in text[smoke:smoke + 300]
    promote = text.index("- name: Promote backend")
    assert smoke < promote < text.index("- name: Deploy frontend")
    assert "update-traffic" in text[promote:promote + 300] and "--to-latest" in text[promote:promote + 300]
    fe_smoke = text.index("- name: Smoke test frontend")
    assert "steps.frontend.outputs.candidate_url" in text[fe_smoke:fe_smoke + 400]
    assert fe_smoke < text.index("- name: Promote frontend")


def test_deploy_runs_only_after_ci_succeeds():
    import yaml

    doc = yaml.safe_load(DEPLOY.read_text(encoding="utf-8"))
    triggers = doc.get("on", doc.get(True))
    assert "push" not in triggers and "workflow_dispatch" in triggers
    assert triggers["workflow_run"] == {"workflows": ["CI"], "types": ["completed"], "branches": ["main"]}
    condition = doc["jobs"]["deploy"]["if"]
    assert "github.event.workflow_run.conclusion == 'success'" in condition
    assert "github.event.workflow_run.event == 'push'" in condition


def test_collected_observations_are_not_baked_into_the_image():
    ignored = (REPO_ROOT / "backend" / ".dockerignore").read_text(encoding="utf-8").split()
    assert "data/ml/observations/" in ignored
