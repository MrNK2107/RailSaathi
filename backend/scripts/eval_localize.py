"""Evaluate camera localisation against labelled photos. Its numbers gate turning AR guidance on in production.

Usage (from backend/):
    uv run python scripts/eval_localize.py --manifest /path/to/set/manifest.json [--station chennai_central]
        [--threshold 0.6] [--usd-per-mtok-input X --usd-per-mtok-output Y] [--out results.json] [--dry-run]

The manifest is a JSON list (or JSON Lines) of `{"image": "<path relative to the manifest>", "true_node_id": "..."}`.
Each image is prepared the way the app sends it (longest side 768 px, JPEG) and run through the same localizer
the API uses (`GeminiVisionLocalizer`, built from the usual GOOGLE_CLOUD_PROJECT / GEMINI_MODEL settings), with
`guard_result` applied and the API's fix rule (`confidence >= threshold`).

Reported:
- top-1 accuracy: the predicted node equals the true node, over every photo (an unavailable answer counts as wrong);
- accuracy at the threshold: the same over accepted fixes only, plus coverage (accepted / all);
- p50 and p95 latency of the localizer call;
- cost per accepted fix, from the token counts Gemini reports and the prices passed on the command line (prices
  change, so none are built in). Every call is paid for, so the cost of rejected answers is spread over the fixes.

Gate (docs/AR_GUIDANCE.md): AR may be enabled for a station in production only when accuracy at the threshold is
at least 80 %, p95 latency is under 4 s, the set has at least MIN_SAMPLES photos, at least MIN_ACCEPTED_FIXES of them
are accepted fixes and coverage (accepted / all) is at least MIN_COVERAGE. The verdict applies only to the production
threshold (LOCALIZE_CONFIDENCE_THRESHOLD): a run with `--threshold` set to anything else reports "not_applicable".

Privacy: the photos are real people's surroundings. Keep them in the private bucket, blur faces before use, and
never put them in this repository: the script refuses an image set inside the git checkout. It never prints,
logs or saves image bytes; the results file names images by file name only.
`--dry-run` swaps in a mock that echoes the true node, to check the wiring without credentials; its numbers mean
nothing and its gate is always "not_applicable".
"""

from __future__ import annotations

import argparse
import io
import json
import math
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import STATIONS_DIR, Settings  # noqa: E402
from app.llm.base import Deadline, LLMError  # noqa: E402
from app.llm.vision import LocalizeHint, LocalizeResult, VisionLocalizer, guard_result  # noqa: E402
from app.navigation.models.station import Station  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
MAX_SIDE_PX = 768  # same as the app (frontend/src/ar/frame.ts)
JPEG_QUALITY = 80
GATE_MIN_ACCURACY = 0.80
GATE_MAX_P95_MS = 4000
MIN_SAMPLES = 30
MIN_ACCEPTED_FIXES = 20  # accuracy over 1-2 accepted fixes proves nothing
MIN_COVERAGE = 0.5  # a localiser that rarely commits is not useful guidance, however accurate its few fixes


@dataclass(frozen=True)
class Sample:
    image: Path
    true_node_id: str


@dataclass
class Outcome:
    image: str  # file name only
    true_node_id: str
    predicted_node_id: str | None
    confidence: float
    status: str  # fix | low_confidence | unavailable
    latency_ms: float
    correct: bool
    input_tokens: int | None = None
    output_tokens: int | None = None


@dataclass
class Report:
    station_id: str
    model: str
    threshold: float
    samples: int
    unavailable: int
    top1_accuracy: float | None
    accepted: int
    coverage: float | None
    accuracy_at_threshold: float | None
    latency_p50_ms: float | None
    latency_p95_ms: float | None
    input_tokens: int | None
    output_tokens: int | None
    cost_usd_total: float | None
    cost_usd_per_fix: float | None
    gate: str  # pass | fail | insufficient_data | not_applicable
    production_threshold: float | None = None
    gate_reasons: list[str] = field(default_factory=list)
    dry_run: bool = False
    outcomes: list[Outcome] = field(default_factory=list)


# ---- inputs ---------------------------------------------------------------------------------------------------

def load_manifest(path: Path) -> list[Sample]:
    text = path.read_text(encoding="utf-8")
    try:
        rows = json.loads(text)
    except ValueError:
        rows = [json.loads(line) for line in text.splitlines() if line.strip()]
    if not isinstance(rows, list) or not rows:
        raise ValueError("the manifest must be a non-empty JSON list or JSON Lines file")
    samples = []
    for i, row in enumerate(rows):
        if not isinstance(row, dict) or not isinstance(row.get("image"), str) or not isinstance(
                row.get("true_node_id"), str):
            raise ValueError(f"manifest row {i} needs string fields 'image' and 'true_node_id'")
        samples.append(Sample((path.parent / row["image"]).resolve(), row["true_node_id"]))
    return samples


def inside_repo(path: Path, repo_root: Path = REPO_ROOT) -> bool:
    try:
        path.resolve().relative_to(repo_root.resolve())
        return True
    except ValueError:
        return False


def prepare_image(path: Path, max_side: int = MAX_SIDE_PX, quality: int = JPEG_QUALITY) -> tuple[bytes, str]:
    """Downscale to `max_side` on the longest side and encode as JPEG, like the app does before upload."""
    from PIL import Image

    with Image.open(path) as img:
        img = img.convert("RGB")
        scale = min(1.0, max_side / max(img.size))
        if scale < 1.0:
            img = img.resize((max(1, round(img.width * scale)), max(1, round(img.height * scale))))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality)
    return buf.getvalue(), "image/jpeg"


def load_station(station_id: str, root: Path = STATIONS_DIR) -> Station:
    return Station.model_validate_json((root / station_id / "station.json").read_text(encoding="utf-8"))


# ---- metrics --------------------------------------------------------------------------------------------------

def percentile(values: Sequence[float], q: float) -> float | None:
    """Nearest-rank percentile (q in 0..100); None for no values."""
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(q / 100 * len(ordered)))
    return ordered[rank - 1]


def _ratio(num: int, den: int) -> float | None:
    return round(num / den, 4) if den else None


def summarise(station_id: str, model: str, threshold: float, outcomes: list[Outcome],
              usd_per_mtok_input: float | None = None, usd_per_mtok_output: float | None = None,
              dry_run: bool = False, production_threshold: float | None = None) -> Report:
    n = len(outcomes)
    accepted = [o for o in outcomes if o.status == "fix"]
    latencies = [o.latency_ms for o in outcomes]
    have_tokens = n > 0 and all(o.input_tokens is not None and o.output_tokens is not None for o in outcomes)
    tokens_in = sum(o.input_tokens or 0 for o in outcomes) if have_tokens else None
    tokens_out = sum(o.output_tokens or 0 for o in outcomes) if have_tokens else None
    cost = None
    if have_tokens and usd_per_mtok_input is not None and usd_per_mtok_output is not None:
        cost = round((tokens_in * usd_per_mtok_input + tokens_out * usd_per_mtok_output) / 1_000_000, 6)
    report = Report(
        station_id=station_id, model=model, threshold=threshold, samples=n,
        unavailable=sum(o.status == "unavailable" for o in outcomes),
        top1_accuracy=_ratio(sum(o.correct for o in outcomes), n),
        accepted=len(accepted), coverage=_ratio(len(accepted), n),
        accuracy_at_threshold=_ratio(sum(o.correct for o in accepted), len(accepted)),
        latency_p50_ms=percentile(latencies, 50), latency_p95_ms=percentile(latencies, 95),
        input_tokens=tokens_in, output_tokens=tokens_out, cost_usd_total=cost,
        cost_usd_per_fix=round(cost / len(accepted), 6) if cost is not None and accepted else None,
        gate="not_applicable", production_threshold=production_threshold, dry_run=dry_run, outcomes=outcomes,
    )
    report.gate, report.gate_reasons = gate(report)
    return report


def gate(report: Report) -> tuple[str, list[str]]:
    if report.dry_run:
        return "not_applicable", ["dry run: the mock echoes the true node, so the numbers mean nothing"]
    if report.production_threshold is None or abs(report.threshold - report.production_threshold) > 1e-9:
        return "not_applicable", [f"threshold {report.threshold} is not the production threshold "
                                  f"{report.production_threshold}; the gate is judged at the production threshold only"]
    if report.samples < MIN_SAMPLES:
        return "insufficient_data", [f"{report.samples} photos; at least {MIN_SAMPLES} are needed"]
    reasons = []
    if report.accepted < MIN_ACCEPTED_FIXES:
        reasons.append(f"{report.accepted} accepted fixes; at least {MIN_ACCEPTED_FIXES} are needed")
    if report.coverage is None or report.coverage < MIN_COVERAGE:
        reasons.append(f"coverage {report.coverage} is below {MIN_COVERAGE}")
    if report.accuracy_at_threshold is None or report.accuracy_at_threshold < GATE_MIN_ACCURACY:
        reasons.append(f"accuracy at threshold {report.accuracy_at_threshold} is below {GATE_MIN_ACCURACY}")
    if report.latency_p95_ms is None or report.latency_p95_ms >= GATE_MAX_P95_MS:
        reasons.append(f"p95 latency {report.latency_p95_ms} ms is not under {GATE_MAX_P95_MS} ms")
    return ("fail", reasons) if reasons else ("pass", [])


# ---- running --------------------------------------------------------------------------------------------------

class UsageRecorder:
    """Wraps a google-genai client and keeps the token counts of the last call (`usage_metadata`)."""

    def __init__(self, client: Any) -> None:
        self._client = client
        self.last: tuple[int, int] | None = None
        recorder = self

        class _Models:
            async def generate_content(self, **kwargs: Any) -> Any:
                response = await client.aio.models.generate_content(**kwargs)
                usage = getattr(response, "usage_metadata", None)
                if usage is not None:
                    recorder.last = (int(getattr(usage, "prompt_token_count", 0) or 0),
                                     int(getattr(usage, "candidates_token_count", 0) or 0)
                                     + int(getattr(usage, "thoughts_token_count", 0) or 0))
                return response

        class _Aio:
            models = _Models()

        self.aio = _Aio()


def run(localizer: VisionLocalizer, station: Station, samples: Sequence[Sample], threshold: float,
        deadline_seconds: float, prepare: Callable[[Path], tuple[bytes, str]] = prepare_image,
        usage: UsageRecorder | None = None, clock: Callable[[], float] = time.monotonic) -> list[Outcome]:
    node_ids = {n.id for n in station.nodes}
    outcomes = []
    for sample in samples:
        if sample.true_node_id not in node_ids:
            raise ValueError(f"{sample.image.name}: true_node_id {sample.true_node_id!r} is not a node of "
                             f"{station.station_id}")
        data, mime = prepare(sample.image)
        if usage is not None:
            usage.last = None
        started = clock()
        try:
            result: LocalizeResult | None = guard_result(
                localizer.localize(data, mime, station, LocalizeHint(), Deadline(deadline_seconds)), station)
        except LLMError:
            result = None
        except Exception:  # noqa: BLE001 - the API answers `unavailable` for any failure; so does the eval
            result = None
        latency_ms = round((clock() - started) * 1000, 1)
        del data
        if result is None:
            status, node, confidence = "unavailable", None, 0.0
        else:
            node, confidence = result.node_id, result.confidence
            status = "fix" if node is not None and confidence >= threshold else "low_confidence"
        tokens = usage.last if usage is not None else None
        outcomes.append(Outcome(
            image=sample.image.name, true_node_id=sample.true_node_id, predicted_node_id=node,
            confidence=round(confidence, 3), status=status, latency_ms=latency_ms,
            correct=node == sample.true_node_id,
            input_tokens=tokens[0] if tokens else None, output_tokens=tokens[1] if tokens else None))
    return outcomes


def markdown_rows(report: Report) -> str:
    def fmt(value: Any, suffix: str = "") -> str:
        return "not measured" if value is None else f"{value}{suffix}"

    pct = (lambda v: None if v is None else f"{v * 100:.1f} %")  # noqa: E731
    return "\n".join([
        "| Metric | Value |", "|---|---|",
        f"| Photos | {report.samples} |",
        f"| Top-1 accuracy | {fmt(pct(report.top1_accuracy))} |",
        f"| Accuracy at threshold {report.threshold} | {fmt(pct(report.accuracy_at_threshold))} |",
        f"| Coverage (accepted fixes) | {fmt(pct(report.coverage))} |",
        f"| Latency p50 / p95 | {fmt(report.latency_p50_ms, ' ms')} / {fmt(report.latency_p95_ms, ' ms')} |",
        f"| Cost per fix | {fmt(report.cost_usd_per_fix, ' USD')} |",
        f"| Gate | {report.gate} |",
    ])


def build_localizer(args: argparse.Namespace, settings: Settings, samples: Sequence[Sample]
                    ) -> tuple[VisionLocalizer, UsageRecorder | None, str]:
    if args.dry_run:
        from app.llm.mock import MockVisionLocalizer

        return (MockVisionLocalizer([LocalizeResult(node_id=s.true_node_id, confidence=0.9) for s in samples]),
                None, "mock-vision (dry run)")
    from app.llm.gemini import build_genai_client
    from app.llm.vision import GeminiVisionLocalizer

    usage = UsageRecorder(build_genai_client(settings))
    return GeminiVisionLocalizer(settings, client=usage), usage, settings.gemini_model


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--manifest", required=True, type=Path)
    p.add_argument("--station", default="chennai_central")
    p.add_argument("--threshold", type=float, default=None, help="default: LOCALIZE_CONFIDENCE_THRESHOLD")
    p.add_argument("--usd-per-mtok-input", type=float, default=None)
    p.add_argument("--usd-per-mtok-output", type=float, default=None)
    p.add_argument("--out", type=Path, default=None, help="write the full JSON report here")
    p.add_argument("--dry-run", action="store_true", help="mock localizer, no credentials, meaningless numbers")
    args = p.parse_args(argv)

    samples = load_manifest(args.manifest)
    in_repo = [s.image.name for s in samples if inside_repo(s.image)] + (
        [args.manifest.name] if inside_repo(args.manifest) else [])
    if in_repo:
        print("Refusing: the image set is inside the git checkout. Keep photos in the private bucket and run "
              "from a local copy outside the repository.", file=sys.stderr)
        return 2
    missing = [s.image.name for s in samples if not s.image.is_file()]
    if missing:
        print(f"Missing images: {', '.join(missing)}", file=sys.stderr)
        return 2
    settings = Settings()
    threshold = settings.localize_confidence_threshold if args.threshold is None else args.threshold
    station = load_station(args.station)
    try:
        localizer, usage, model = build_localizer(args, settings, samples)
    except LLMError:
        print("Gemini is not configured: set LLM_PROVIDER=gemini and GOOGLE_CLOUD_PROJECT (Application Default "
              "Credentials), or use --dry-run.", file=sys.stderr)
        return 2
    outcomes = run(localizer, station, samples, threshold, settings.localize_deadline_seconds, usage=usage)
    report = summarise(args.station, model, threshold, outcomes, args.usd_per_mtok_input,
                       args.usd_per_mtok_output, dry_run=args.dry_run,
                       production_threshold=settings.localize_confidence_threshold)
    if args.out:
        args.out.write_text(json.dumps(asdict(report), indent=2) + "\n", encoding="utf-8")
    print(markdown_rows(report))
    for reason in report.gate_reasons:
        print(f"- {reason}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
