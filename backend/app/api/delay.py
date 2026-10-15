"""Delay estimate for a train at a station.

Answered by the container's DelayModel: a trained scikit-learn artifact, or the historical average when none is
loaded. The response carries `model_version`, `mae_minutes` (measured on held-out trains), `basis` and `provenance`.
Inference is CPU-bound and runs in the worker thread pool (`anyio.to_thread.run_sync` through `offload`)."""

from fastapi import APIRouter, HTTPException, Query, Request

from app.api.deps import offload
from app.delay.model import DelayPrediction

router = APIRouter(tags=["Delay Estimate"])

CODE_PATTERN = r"^[A-Za-z0-9]{1,8}$"
NO_DELAY = {"RT", "00:00", "RIGHT TIME", "--"}


def _delay_minutes(value: str | None) -> int:
    """Parse "RT", "00:20", "20" or "1:05" into minutes; anything unreadable counts as 0."""
    text = (value or "").strip().upper()
    if not text or text in NO_DELAY:
        return 0
    try:
        if ":" in text:
            hours, _, minutes = text.partition(":")
            return max(0, int(hours) * 60 + int(minutes))
        return max(0, int(text))
    except ValueError:
        return 0


@router.get("/api/predict/delay", response_model=DelayPrediction)
async def get_delay_prediction(
    request: Request,
    train_number: str = Query(..., pattern=CODE_PATTERN, description="Train number (e.g. 12952)"),
    destination: str = Query("DST", pattern=CODE_PATTERN, description="Station code the estimate is for"),
    train_name: str | None = Query(None, max_length=60, description="Ignored; kept for older clients"),
    train_type: str | None = Query(None, max_length=30, description="Ignored; the class is derived from the number"),
    current_delay: str | None = Query("RT", max_length=12, description="Reported delay such as 00:20 or RT"),
    hour: int | None = Query(None, ge=0, le=23, description="Hour of day, used only by models trained with it"),
    weekday: int | None = Query(None, ge=0, le=6, description="Weekday (Monday=0), same caveat"),
) -> DelayPrediction:
    model = request.app.state.container.delay_model
    if model is None:
        raise HTTPException(503, detail={"code": "delay_model_unavailable",
                                         "message": "The delay estimate is not set up."})
    return await offload(model.predict, train_number, destination, _delay_minutes(current_delay), hour, weekday)
