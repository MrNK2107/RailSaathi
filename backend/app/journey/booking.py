"""
RailSaathi AI — Booking Handoff Service

Generates verified official booking handoff links and metadata.
Strictly validates URLs against an allowlist of approved HTTPS official railway domains.
Never executes automated reservations or logs sensitive credentials.
"""

import logging
import urllib.parse
from datetime import date

from app.journey.models import BookingHandoff, TrainCandidate

logger = logging.getLogger("railsaathi.journey.booking")

# Strict allowlist of approved official and authorized railway domains
APPROVED_BOOKING_HOSTS = {
    "www.irctc.co.in",
    "irctc.co.in",
    "enquiry.indianrail.gov.in",
    "www.confirmtkt.com",
    "confirmtkt.com",
    "railmadad.indianrailways.gov.in",
}


def is_url_safe_and_allowlisted(url: str) -> bool:
    """Validate that a URL is well-formed, uses HTTPS, and has an approved hostname."""
    try:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme.lower() != "https":
            return False
        host = (parsed.hostname or "").lower()
        return host in APPROVED_BOOKING_HOSTS
    except Exception as e:
        logger.warning(f"URL validation failed for '{url}': {e}")
        return False


class BookingHandoffService:
    """Service to create safe, verified official booking handoff objects."""

    def create_booking_handoff(
        self,
        candidate: TrainCandidate,
        journey_date: date,
        recommended_class: str | None,
        recommended_fare: float | None = None,
    ) -> BookingHandoff:
        """Official IRCTC train-search link prefilled with the stations, date and (when known) class."""
        base_url = "https://www.irctc.co.in/nget/train-search"
        params = {
            "fromStation": candidate.origin_code,
            "toStation": candidate.destination_code,
            "journeyDate": journey_date.isoformat(),
        }
        if recommended_class:
            params["journeyClass"] = recommended_class
        full_booking_url = f"{base_url}?{urllib.parse.urlencode(params)}"
        if not is_url_safe_and_allowlisted(full_booking_url):
            full_booking_url = "https://www.irctc.co.in"

        return BookingHandoff(
            booking_url=full_booking_url,
            is_url_allowlisted=True,
            train_number=candidate.train_number,
            train_name=candidate.train_name,
            from_station_code=candidate.origin_code,
            to_station_code=candidate.destination_code,
            journey_date=journey_date,
            recommended_class=recommended_class,
            estimated_fare_inr=recommended_fare,
        )
