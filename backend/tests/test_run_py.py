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


def parse(run, *argv):
    return run.make_parser().parse_args(list(argv))


def test_parse_tunnel_url():
    run = load_run()
    line = "2026-10-18T10:00:00Z INF |  https://quick-brown-fox-12.trycloudflare.com  |"
    assert run.parse_tunnel_url(line) == "https://quick-brown-fox-12.trycloudflare.com"
    assert run.parse_tunnel_url("INF Requesting new quick Tunnel on trycloudflare.com...") is None


def test_public_implies_http_and_env():
    run = load_run()
    env = run.build_env(parse(run, "--public"), {})
    assert env["PUBLIC_TUNNEL"] == "1"
    assert env["VITE_ALLOWED_HOSTS"] == ".trycloudflare.com"
    assert "VITE_HTTPS" not in env
    local = run.build_env(parse(run), {})
    assert local["VITE_HTTPS"] == "1" and "PUBLIC_TUNNEL" not in local


def test_backend_cmd_no_reload_in_public():
    run = load_run()
    assert "--reload" not in run.backend_cmd(parse(run, "--public"), "uv")
    assert "--reload" in run.backend_cmd(parse(run), "uv")


def test_free_ram_bytes_returns_int_or_none():
    run = load_run()
    value = run.free_ram_bytes()
    assert value is None or (isinstance(value, int) and value > 0)


def test_llm_settings_read_environment_then_backend_env(tmp_path):
    run = load_run()
    env = tmp_path / ".env"
    env.write_text("LLM_PROVIDER=ollama\nOLLAMA_MODEL=llama3.2:3b\n", encoding="utf-8")
    s = run.llm_settings({"LLM_FALLBACK": "none"}, env)
    assert s["LLM_PROVIDER"] == "ollama" and s["OLLAMA_MODEL"] == "llama3.2:3b"
    assert s["LLM_FALLBACK"] == "none" and s["OLLAMA_URL"] == "http://127.0.0.1:11434"


def test_loaded_ollama_models_is_empty_on_error():
    run = load_run()
    assert run.loaded_ollama_models("http://127.0.0.1:9") == []


def test_public_without_cloudflared_exits_with_install_guidance(monkeypatch):
    import pytest

    run = load_run()
    monkeypatch.setattr(run, "tool", lambda name: name)
    monkeypatch.setattr(run.shutil, "which", lambda name: None)
    monkeypatch.setattr(run.sys, "argv", ["run.py", "--public"])
    with pytest.raises(SystemExit) as exc:
        run.main()
    assert "winget install Cloudflare.cloudflared" in str(exc.value)
    assert "brew install cloudflared" in str(exc.value)


def test_start_tunnel_returns_the_public_url_from_stderr(monkeypatch):
    run = load_run()
    seen = {}

    class FakeProc:
        stderr = iter(["INF Starting\n", "INF |  https://calm-owl-7.trycloudflare.com  |\n"])

        def poll(self):
            return None

    def fake_popen(cmd, **kwargs):
        seen["cmd"] = cmd
        return FakeProc()

    monkeypatch.setattr(run.subprocess, "Popen", fake_popen)
    proc, url = run.start_tunnel("cloudflared", "http://127.0.0.1:5173")
    assert url == "https://calm-owl-7.trycloudflare.com"
    assert seen["cmd"][:4] == ["cloudflared", "tunnel", "--url", "http://127.0.0.1:5173"]


def test_llm_warnings_cover_quota_ram_and_loaded_models():
    run = load_run()
    gemini = {"LLM_PROVIDER": "gemini", "LLM_FALLBACK": "", "OLLAMA_MODEL": "gemma4:latest"}
    assert any("quota" in w for w in run.llm_warnings(gemini, True, None, []))
    assert run.llm_warnings(gemini, False, None, []) == []
    local = {"LLM_PROVIDER": "gemini", "LLM_FALLBACK": "ollama", "OLLAMA_MODEL": "gemma4:latest"}
    out = run.llm_warnings(local, True, 4 * 1024**3, ["a", "b"])
    assert any("OLLAMA_MODEL=llama3.2:3b" in w and "4.0 GB" in w for w in out)
    assert any("a, b" in w for w in out)
    assert not any("quota" in w for w in out)
