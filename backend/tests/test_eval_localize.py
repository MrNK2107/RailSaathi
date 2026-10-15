"""`scripts/eval_localize.py`: the localisation evaluation that gates AR guidance in production.

Runs on generated images in a temp folder (never real photos) with the MockVisionLocalizer and a fake genai client.
"""

import io
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import eval_localize as ev  # noqa: E402

from app.llm.base import LLMError, LLMErrorKind  # noqa: E402
from app.llm.mock import MockVisionLocalizer  # noqa: E402
from app.llm.vision import GeminiVisionLocalizer, LocalizeCandidate, LocalizeResult  # noqa: E402

STATION = ev.load_station("chennai_central")


def _image_set(folder: Path, truths: list[str], size=(1600, 900)) -> Path:
    rows = []
    for i, node in enumerate(truths):
        name = f"frame_{i}.png"
        Image.new("RGB", size, (i * 20 % 255, 80, 140)).save(folder / name)
        rows.append({"image": name, "true_node_id": node})
    manifest = folder / "manifest.json"
    manifest.write_text(json.dumps(rows), encoding="utf-8")
    return manifest


class Ticker:
    """A monotonic clock that advances by scripted latencies (seconds) per localizer call."""

    def __init__(self, latencies: list[float]) -> None:
        self.t = 0.0
        self.pending = list(latencies)
        self.started = False

    def __call__(self) -> float:
        if self.started:
            self.t += self.pending.pop(0)
        self.started = not self.started
        return self.t


def test_prepare_image_downscales_to_768_jpeg(tmp_path):
    Image.new("RGB", (2000, 1000)).save(tmp_path / "big.png")
    data, mime = ev.prepare_image(tmp_path / "big.png")
    assert mime == "image/jpeg" and data[:3] == b"\xff\xd8\xff"
    with Image.open(io.BytesIO(data)) as img:
        assert img.size == (768, 384)


def test_small_images_are_not_upscaled(tmp_path):
    Image.new("RGB", (400, 300)).save(tmp_path / "small.png")
    data, _ = ev.prepare_image(tmp_path / "small.png")
    with Image.open(io.BytesIO(data)) as img:
        assert img.size == (400, 300)


def test_manifest_accepts_json_lines_and_rejects_bad_rows(tmp_path):
    (tmp_path / "m.jsonl").write_text('{"image": "a.jpg", "true_node_id": "cj_north"}\n\n'
                                      '{"image": "b.jpg", "true_node_id": "nj_west"}\n', encoding="utf-8")
    samples = ev.load_manifest(tmp_path / "m.jsonl")
    assert [s.true_node_id for s in samples] == ["cj_north", "nj_west"]
    assert samples[0].image == (tmp_path / "a.jpg").resolve()
    (tmp_path / "bad.json").write_text('[{"image": "a.jpg"}]', encoding="utf-8")
    with pytest.raises(ValueError, match="true_node_id"):
        ev.load_manifest(tmp_path / "bad.json")


def test_percentile_is_nearest_rank():
    values = [float(v) for v in range(1, 21)]  # 1..20
    assert ev.percentile(values, 50) == 10
    assert ev.percentile(values, 95) == 19
    assert ev.percentile([], 95) is None


def test_metrics_from_mock_localizer(tmp_path):
    truths = ["cj_north", "nj_west", "wa_north", "platform_10"]
    manifest = _image_set(tmp_path, truths)
    script = [
        LocalizeResult(node_id="cj_north", confidence=0.9),                  # accepted, correct
        LocalizeResult(node_id="cj_south", confidence=0.8),                  # accepted, wrong
        LocalizeResult(node_id="wa_north", confidence=0.4,                   # correct but below threshold
                       candidates=(LocalizeCandidate("nj_west", 0.3),)),
        LLMError(LLMErrorKind.TIMEOUT),                                      # unavailable counts as wrong
    ]
    mock = MockVisionLocalizer(script)
    outcomes = ev.run(mock, STATION, ev.load_manifest(manifest), 0.6, 8.0, clock=Ticker([1.0, 2.0, 3.0, 5.0]))
    report = ev.summarise("chennai_central", "mock", 0.6, outcomes)

    assert [o.status for o in outcomes] == ["fix", "fix", "low_confidence", "unavailable"]
    assert report.top1_accuracy == 0.5          # cj_north and wa_north
    assert report.accepted == 2 and report.coverage == 0.5
    assert report.accuracy_at_threshold == 0.5  # 1 of 2 accepted
    assert report.latency_p50_ms == 2000.0 and report.latency_p95_ms == 5000.0
    assert report.unavailable == 1
    assert report.cost_usd_per_fix is None      # the mock reports no tokens
    assert report.gate == "insufficient_data"
    # The localizer saw the app's frame format, and the outcomes name images by file name only.
    assert all(call["mime_type"] == "image/jpeg" for call in mock.calls)
    assert all(o.image.startswith("frame_") and "/" not in o.image and "\\" not in o.image for o in outcomes)


def test_unknown_true_node_is_rejected(tmp_path):
    manifest = _image_set(tmp_path, ["not_a_node"])
    with pytest.raises(ValueError, match="not a node"):
        ev.run(MockVisionLocalizer([]), STATION, ev.load_manifest(manifest), 0.6, 8.0)


def _outcome(correct: bool, status: str = "fix", latency: float = 1000.0) -> ev.Outcome:
    return ev.Outcome("x.jpg", "a", "a" if correct else "b", 0.9, status, latency, correct)


def test_gate_passes_only_with_enough_accurate_fast_fixes():
    good = [_outcome(True)] * 32 + [_outcome(False)] * 8  # 80 % at threshold
    assert ev.summarise("s", "m", 0.6, good).gate == "pass"
    slow = [_outcome(True, latency=4000.0)] * 40
    report = ev.summarise("s", "m", 0.6, slow)
    assert report.gate == "fail" and "p95" in report.gate_reasons[0]
    inaccurate = [_outcome(True)] * 31 + [_outcome(False)] * 9
    assert ev.summarise("s", "m", 0.6, inaccurate).gate == "fail"
    none_accepted = [_outcome(False, status="low_confidence")] * 40
    assert ev.summarise("s", "m", 0.6, none_accepted).gate == "fail"
    assert ev.summarise("s", "m", 0.6, good, dry_run=True).gate == "not_applicable"


def test_cost_per_fix_spreads_every_call_over_accepted_fixes():
    outcomes = [ev.Outcome("x.jpg", "a", "a", 0.9, "fix", 900.0, True, 1000, 100),
                ev.Outcome("y.jpg", "a", None, 0.0, "low_confidence", 900.0, False, 1000, 100)]
    report = ev.summarise("s", "m", 0.6, outcomes, usd_per_mtok_input=0.1, usd_per_mtok_output=0.4)
    assert report.input_tokens == 2000 and report.output_tokens == 200
    assert report.cost_usd_total == pytest.approx(0.00028)
    assert report.cost_usd_per_fix == pytest.approx(0.00028)  # two calls paid, one fix


def test_gemini_path_records_token_usage(tmp_path):
    manifest = _image_set(tmp_path, ["cj_north"])

    class FakeModels:
        async def generate_content(self, **kwargs):
            assert kwargs["contents"][0].parts[0].inline_data.mime_type == "image/jpeg"
            text = json.dumps({"node_id": "cj_north", "confidence": 0.85, "facing_bearing_deg": 180,
                               "matched_cues": [], "candidates": []})
            return SimpleNamespace(text=text, usage_metadata=SimpleNamespace(
                prompt_token_count=1800, candidates_token_count=60, thoughts_token_count=None))

    fake = SimpleNamespace(aio=SimpleNamespace(models=FakeModels()))
    usage = ev.UsageRecorder(fake)
    settings = ev.Settings(_env_file=None, llm_provider="gemini", gcp_project="p")
    localizer = GeminiVisionLocalizer(settings, client=usage)
    outcomes = ev.run(localizer, STATION, ev.load_manifest(manifest), 0.6, 8.0, usage=usage)
    assert outcomes[0].status == "fix" and outcomes[0].correct
    assert (outcomes[0].input_tokens, outcomes[0].output_tokens) == (1800, 60)


def test_cli_dry_run_writes_report_and_never_image_bytes(tmp_path, capsys):
    manifest = _image_set(tmp_path, ["cj_north", "nj_west"])
    out = tmp_path / "results.json"
    assert ev.main(["--manifest", str(manifest), "--dry-run", "--out", str(out)]) == 0
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["dry_run"] is True and report["gate"] == "not_applicable"
    assert report["top1_accuracy"] == 1.0 and report["samples"] == 2
    printed = capsys.readouterr().out
    assert "| Gate | not_applicable |" in printed
    assert "JFIF" not in out.read_text(encoding="utf-8") and "JFIF" not in printed


def test_cli_refuses_an_image_set_inside_the_repository(tmp_path, capsys):
    rows = [{"image": str(ev.REPO_ROOT / "frontend" / "public" / "x.jpg"), "true_node_id": "cj_north"}]
    (tmp_path / "manifest.json").write_text(json.dumps(rows), encoding="utf-8")
    assert ev.main(["--manifest", str(tmp_path / "manifest.json"), "--dry-run"]) == 2
    assert "inside the git checkout" in capsys.readouterr().err


def test_cli_without_gemini_configuration_explains(tmp_path, capsys, monkeypatch):
    manifest = _image_set(tmp_path, ["cj_north"])
    real = ev.Settings
    monkeypatch.setattr(ev, "Settings", lambda: real(_env_file=None, llm_provider="gemini", gcp_project=None,
                                                     gemini_api_key=""))
    assert ev.main(["--manifest", str(manifest)]) == 2
    assert "not configured" in capsys.readouterr().err
