from enum import StrEnum


class WorkflowStatus(StrEnum):
    COLLECTING_DETAILS = "collecting_details"
    NEEDS_CLARIFICATION = "needs_clarification"
    VALIDATING_REQUEST = "validating_request"
    SEARCHING_OPTIONS = "searching_options"
    PRESENTING_RECOMMENDATIONS = "presenting_recommendations"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    CONFIRMED = "confirmed"
    NO_FEASIBLE_OPTIONS = "no_feasible_options"
    CANCELLED = "cancelled"
    ERROR = "error"


class Language(StrEnum):
    EN = "en"
    TA = "ta"


class DataMode(StrEnum):
    LIVE = "live"  # verified data from an authorised provider (not available in this prototype)
    DEMO = "demo"  # illustrative, simulated data
    UNKNOWN = "unknown"
    CACHED = "cached"  # a recent live response served from cache (still within its freshness window)
    STALE = "stale"  # a previously fetched live response served because a fresh one could not be fetched
    UNAVAILABLE = "unavailable"  # no data could be obtained
    FALLBACK = "fallback"  # a lower-fidelity substitute (e.g. rule-based/statistical) replaced the primary source


class TravelClass(StrEnum):
    SL = "SL"  # Sleeper
    THREE_A = "3A"  # AC 3 Tier
    TWO_A = "2A"  # AC 2 Tier
    CC = "CC"  # AC Chair Car
    EC = "EC"  # Executive Chair Car
    TWO_S = "2S"  # Second Sitting


class PassengerNeed(StrEnum):
    ASSISTANCE_REQUESTED = "assistance_requested"
    WHEELCHAIR = "wheelchair"
    REDUCED_WALKING = "reduced_walking"
    TRAVELLING_WITH_CHILDREN = "travelling_with_children"
    TRAVELLING_WITH_ELDERLY = "travelling_with_elderly"
    DAYTIME_DEPARTURE = "daytime_departure"
    LONGER_TRANSFER_BUFFER = "longer_transfer_buffer"


# Needs that depend on station facilities and therefore need verification.
ACCESSIBILITY_NEEDS = frozenset(
    {PassengerNeed.ASSISTANCE_REQUESTED, PassengerNeed.WHEELCHAIR, PassengerNeed.REDUCED_WALKING}
)


class Verification(StrEnum):
    VERIFIED_SUPPORTED = "verified_supported"
    NOT_SUPPORTED = "not_supported"
    UNKNOWN = "unknown"


class BudgetPriority(StrEnum):
    MINIMIZE_COST = "minimize_cost"
    MINIMIZE_TIME = "minimize_time"
    BALANCED = "balanced"


class TransferPreference(StrEnum):
    DIRECT_ONLY = "direct_only"
    ALLOW = "allow"


class DateAnchor(StrEnum):
    DEPARTURE = "departure"
    ARRIVAL = "arrival"


class FieldSource(StrEnum):
    EXPLICIT = "explicit"  # passenger stated it
    INFERRED = "inferred"  # derived with sufficient confidence (e.g. "with my mother" -> 2 passengers)
    EDITED = "edited"  # set through the manual edit form


class RecommendationCategory(StrEnum):
    BEST_OVERALL = "best_overall"
    LOWEST_COST = "lowest_cost"
    FASTEST = "fastest"


class CheckStatus(StrEnum):
    MET = "met"
    VIOLATED = "violated"
    UNVERIFIED = "unverified"
    NOT_APPLICABLE = "not_applicable"
