"""
API Router for ML Delay Forecasting (Pillar 4)
Runs fast in-process regression evaluation against 63k CRIS train delay records.
"""

from typing import Optional
from fastapi import APIRouter, Query
from app.delay.engine import predict_train_delay

router = APIRouter(tags=["ML Delay Forecaster"])


@router.get("/predict/delay")
@router.get("/api/predict/delay")
def get_delay_prediction(
    train_number: str = Query(..., description="Train number (e.g. 12952)"),
    train_name: str = Query("Express", description="Train name"),
    train_type: Optional[str] = Query(None, description="Train category"),
    current_delay: Optional[str] = Query("RT", description="Current delay like 00:20 or RT"),
    destination: str = Query("DST", description="Destination station code")
):
    cur_min = 0
    if current_delay and current_delay not in ["RT", "00:00", "Right Time", "--"]:
        if ":" in current_delay:
            p = current_delay.split(":")
            try:
                cur_min = int(p[0]) * 60 + int(p[1])
            except Exception:
                cur_min = 0
        else:
            try:
                cur_min = int(current_delay)
            except Exception:
                cur_min = 0

    res = predict_train_delay(
        train_number=train_number,
        station_code=destination,
        current_delay=cur_min,
        train_type=train_type or "EXPRESS"
    )
    res["train_name"] = train_name
    return res
