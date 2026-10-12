"""
RailSathi AI — Booking Handoff Service

Generates verified official booking handoff links and metadata.
Strictly validates URLs against an allowlist of approved HTTPS official railway domains.
Never executes automated reservations or logs sensitive credentials.
"""

import logging
import urllib.parse
from app.journey.models import BookingHandoff, TrainService

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
        train: TrainService,
        journey_date: str,
        recommended_class: str,
        recommended_fare: float | None = None,
    ) -> BookingHandoff:
        """
        Create a booking handoff object with official IRCTC link.
        """
        # Official IRCTC main booking portal with pre-formatted search path
        # Official safe URL: https://www.irctc.co.in/nget/train-search
        base_url = "https://www.irctc.co.in/nget/train-search"

        # Build query parameters safely
        params = {
            "fromStation": train.origin_station_code,
            "toStation": train.destination_station_code,
            "journeyDate": journey_date,
            "journeyClass": recommended_class,
        }
        encoded_query = urllib.parse.urlencode(params)
        full_booking_url = f"{base_url}?{encoded_query}"

        # Allowlist check
        safe = is_url_safe_and_allowlisted(full_booking_url)
        if not safe:
            full_booking_url = "https://www.irctc.co.in"

        return BookingHandoff(
            official_provider="IRCTC Official Railway Reservation",
            booking_url=full_booking_url,
            is_url_allowlisted=True,
            train_number=train.train_number,
            train_name=train.train_name,
            from_station_code=train.origin_station_code,
            to_station_code=train.destination_station_code,
            journey_date=journey_date,
            recommended_class=recommended_class,
            estimated_fare_inr=recommended_fare,
            disclaimer=(
                "RailSathi AI provides booking guidance. Clicking this link redirects you to the official "
                "IRCTC portal to complete your reservation. No automated transactions are performed."
            ),
        )
