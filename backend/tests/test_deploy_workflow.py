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
BASE_SECRETS = ("RAILRADAR_API_KEY=RAILRADAR_API_KEY:latest,REDIS_URL=REDIS_URL:latest,"
                "SESSION_SIGNING_KEY=SESSION_SIGNING_KEY:latest")
BASH = shutil.which("bash")


def _backend_step_script() -> str:
    text = DEPLOY.read_text(encoding="utf-8")
    step = text[text.index("- name: Deploy backend"):text.index("- name: Smoke test backend")]
    return textwrap.dedent(step[step.index("run: |") + len("run: |"):].strip("\n"))


def _deployed_secrets(tmp_path, maps_secret_var: str) -> str:
    script = _backend_step_script().replace("${{ vars.MAPS_BROWSER_KEY_SECRET || '' }}", maps_secret_var)
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


def test_maps_secret_is_never_mounted_unconditionally():
    script = _backend_step_script()
    assert "GOOGLE_MAPS_BROWSER_KEY" not in script.split("if [ -n")[0]
