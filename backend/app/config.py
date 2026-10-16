"""Application configuration loaded from environment variables.

AWS credentials are never read here directly: boto3 resolves them through the
standard AWS credential chain (env vars, AWS_PROFILE, SSO, instance roles).
"""

from datetime import datetime
from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
BACKEND_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = BACKEND_ROOT / "data"
DB_PATH = DATA_DIR / "knowledge" / "railsaathi.db"
DELAYS_CSV_PATH = DATA_DIR / "ml" / "train_delays.csv"
DELAY_MODEL_PATH = DATA_DIR / "ml" / "model" / "model.joblib"
OBSERVATIONS_DIR = DATA_DIR / "ml" / "observations"
STATIONS_DIR = DATA_DIR / "stations"
LOCK_TTL_MARGIN_SECONDS = 10


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(BACKEND_ROOT / ".env"), env_file_encoding="utf-8", extra="ignore",
                                      populate_by_name=True)

    app_env: str = "development"
    api_version: str = "2.0.0"
    timezone: str = "Asia/Kolkata"
    # Freeze the application clock (ISO-8601, e.g. 2026-10-10T10:00:00+05:30) so end-to-end tests are
    # deterministic. Ignored when APP_ENV=production.
    fixed_now: datetime | None = None
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173,https://localhost:5173,https://127.0.0.1:5173"

    # Indoor station navigation. Station data (catalogue.json plus one folder per station) is a local directory
    # in development or gs://bucket/prefix in production, published by scripts/stations.py; the runtime only reads.
    stations_uri: str = str(STATIONS_DIR)
    # Lets anyone add what-if closures to a single route request (nothing is stored). Always off in production.
    public_disruption_simulation: bool = True
    disruption_ttl_seconds: int = Field(default=6 * 3600, ge=60, le=7 * 86_400)  # default disruption lifetime
    walking_speed_mps: float = 1.2

    # AR guidance (POST /api/navigation/localize) and the virtual tour. AR_GUIDANCE_ENABLED is a comma-separated
    # list of station ids, or "*" for every station whose data sets ar_enabled. Unset means "*" outside
    # production and none in production (AR stays off until its localisation evaluation passes).
    ar_guidance_enabled: str | None = None
    localize_confidence_threshold: float = Field(default=0.6, ge=0, le=1)  # below it: candidates, no fix
    localize_max_image_bytes: int = Field(default=1_500_000, ge=10_000, le=5_000_000)  # JPEG/WebP frame
    localize_rate_limit: int = Field(default=20, ge=1)  # per session per window
    localize_ip_rate_limit: int = Field(default=120, ge=1)  # per client IP per window (stops token farming)
    localize_rate_window_seconds: int = Field(default=600, ge=60)
    localize_deadline_seconds: float = Field(default=8.0, gt=0)
    # Public, referrer-restricted Maps JavaScript key for the tour's Street View (Secret Manager on Cloud Run).
    google_maps_browser_key: str | None = None

    # Knowledge & LLM. Gemini runs on Vertex AI (GOOGLE_CLOUD_PROJECT / GOOGLE_CLOUD_LOCATION) with the service
    # account's credentials. GEMINI_API_KEY is only honoured outside production when no project is set.
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.0-flash"
    gemini_timeout_seconds: float = Field(default=10.0, gt=0)  # per call; always clipped to the turn deadline
    gemini_max_retries: int = Field(default=2, ge=0, le=5)  # retries on 429 / 5xx / transport errors
    gemini_temperature: float = 0.3
    gemini_max_output_tokens: int = 2048
    max_agent_rounds: int = 4
    max_tool_calls: int = 6
    max_input_length: int = 2000
    max_history_messages: int = Field(default=20, ge=2)  # stored ticketing-chat messages per conversation
    # Knowledge SQLite: built by `python -m app.knowledge.ingest` at image-build time, opened read-only at runtime.
    # Outside production a missing or stale file is rebuilt at startup.
    knowledge_db_path: Path = DB_PATH

    # Planning policy
    max_passengers: int = Field(default=6, ge=1, le=20)
    max_planning_days: int = Field(default=60, ge=1)  # the Indian Railways advance reservation period
    min_transfer_minutes: int = Field(default=30, ge=0)
    session_ttl_minutes: int = Field(default=120, ge=1)
    recommendation_ttl_minutes: int = Field(default=30, ge=1)

    # Request hardening
    max_body_bytes: int = Field(default=16_384, ge=1024)
    max_message_chars: int = Field(default=1000, ge=50)
    rate_limit_per_minute: int = Field(default=60, ge=1)
    rate_limit_llm_per_minute: int = Field(default=20, ge=1)  # lower tier: chat / agent / planner-message routes
    rate_limit_max_keys: int = Field(default=10_000, ge=100)  # bound for the in-memory limiter

    # Shared state and session security
    redis_url: str | None = None
    redis_key_prefix: str = "rs"
    redis_socket_timeout_seconds: float = Field(default=2.0, gt=0)
    # The session lock is held across a whole request (LLM calls and RailRadar calls), so its TTL must outlive the
    # worst-case turn plus a margin (validated below); a turn that still outlives it cannot overwrite newer state,
    # because session saves are fenced on the lock token (sessions/redis_store.py).
    llm_overall_deadline_seconds: float = Field(default=20.0, gt=0)
    session_lock_ttl_ms: int = Field(default=45_000, ge=1000)
    session_lock_wait_seconds: float = Field(default=10.0, gt=0)
    # Number of trusted reverse proxies in front of the app, used to pick the client IP from X-Forwarded-For
    # counted from the right (0 = ignore the header, use the socket peer). Cloud Run: browser -> GFE -> nginx ->
    # GFE -> backend. nginx overwrites the header with the real client IP and the backend's GFE appends nginx's
    # egress IP, so the client is the 2nd entry from the right: 2.
    trusted_proxy_hops: int = Field(default=0, ge=0, le=10)
    # HMAC key for session tokens. Required when APP_ENV=production; a random per-process key is used otherwise.
    session_signing_key: SecretStr | None = None

    # Railway data source: "demo" (bundled simulated data), "ntes" (live NTES data through the unofficial
    # ntes-client package; run.py's local default) or "railradar" (live third-party API, needs a key).
    # Env var RAILWAY_DATA_MODE (preferred) or DATA_PROVIDER.
    data_provider: str = Field(default="demo", validation_alias=AliasChoices("RAILWAY_DATA_MODE", "DATA_PROVIDER",
                                                                           "data_provider"))
    railradar_api_key: SecretStr | None = None
    railradar_base_url: str = "https://api.railradar.in"
    railradar_timeout_seconds: float = Field(default=10.0, gt=0)
    # Hard bound on one batch of RailRadar calls (a journey search, or the live-status lookup for a plan's trains),
    # including queueing behind the concurrency gate and the retry. A planner turn makes at most two batches under
    # its session lock (reassess: live status, then a search), so this budget is part of the lock TTL check below.
    railradar_call_budget_seconds: float = Field(default=15.0, gt=0)
    railradar_cache_seconds: int = Field(default=300, ge=0)
    railradar_max_concurrency: int = Field(default=4, ge=1, le=10)
    railradar_requests_per_minute: int = Field(default=10, ge=1)  # observed limit of the current key
    # How long a cached RailRadar response may still be served (labelled STALE) when the quota is exhausted.
    railradar_stale_seconds: int = Field(default=21_600, ge=0)
    # Live departure boards: how many nearby catalogue stations are queried (one trains-between call each,
    # cached) and for how many of the listed trains running status is fetched (one call each, cached).
    # NTES through the unofficial ntes-client (RAILWAY_DATA_MODE=ntes). No key. The request budget is RailSaathi's
    # own politeness limit (NTES publishes none), shared by every instance through Redis when REDIS_URL is set.
    ntes_timeout_seconds: float = Field(default=10.0, gt=0)
    # Bound on one batch of NTES calls, like RAILRADAR_CALL_BUDGET_SECONDS (part of the lock TTL check below).
    ntes_call_budget_seconds: float = Field(default=15.0, gt=0)
    ntes_cache_seconds: int = Field(default=300, ge=0)  # timetable answers; live answers at most 60 s
    ntes_max_concurrency: int = Field(default=4, ge=1, le=10)
    ntes_requests_per_minute: int = Field(default=20, ge=1)
    ntes_stale_seconds: int = Field(default=21_600, ge=0)
    live_board_neighbours: int = Field(default=3, ge=1, le=6)
    live_board_status_limit: int = Field(default=3, ge=0, le=6)

    # Delay model: a local path or gs://bucket/object holding model.joblib (trained by scripts/train_delay_model.py).
    # A missing or unreadable artifact degrades to history_only and /readyz reports not ready, unless
    # DELAY_HISTORY_ONLY=true says that mode is intended.
    delay_model_uri: str | None = str(DELAY_MODEL_PATH)
    delay_history_only: bool = False

    # Observation collector (POST /internal/collect, called by Cloud Scheduler with a Cloud Run OIDC token).
    # Disabled (404) unless both the audience and the caller's service account are set.
    internal_oidc_audience: str | None = None  # the service URL the Scheduler job targets
    internal_oidc_service_account: str | None = None  # email of the Scheduler job's service account
    observations_uri: str = str(OBSERVATIONS_DIR)  # local directory (development) or gs://bucket/prefix
    observation_seen_ttl_seconds: int = Field(default=86_400, ge=60)  # "recently seen" window for trains
    observation_max_trains: int = Field(default=6, ge=1, le=50)  # live-status samples per collector run

    # LLM (optional). "gemini", "bedrock" or "none".
    llm_provider: str = "none"
    aws_region: str | None = None
    bedrock_model_id: str | None = None
    aws_profile: str | None = None
    bedrock_timeout_seconds: float = Field(default=15.0, gt=0)
    bedrock_max_retries: int = Field(default=2, ge=0, le=5)

    # Logging
    log_format: str = "json"  # "json" (Cloud Logging) or "text"
    gcp_project: str | None = Field(default=None, validation_alias=AliasChoices("GOOGLE_CLOUD_PROJECT", "GCP_PROJECT",
                                                                              "gcp_project"))
    gcp_location: str = Field(default="us-central1", validation_alias=AliasChoices("GOOGLE_CLOUD_LOCATION",
                                                                                "GCP_LOCATION", "gcp_location"))

    @property
    def call_budget_seconds(self) -> float:
        """The live data provider's per-batch budget: NTES_CALL_BUDGET_SECONDS in ntes mode, else RailRadar's."""
        if self.data_provider.lower() == "ntes":
            return self.ntes_call_budget_seconds
        return self.railradar_call_budget_seconds

    @property
    def planner_turn_budget_seconds(self) -> float:
        """Worst-case work under one session lock: a message turn (LLM deadline + one live data search) or a
        reassessment (live status + a search, no LLM)."""
        budget = self.call_budget_seconds
        return max(self.llm_overall_deadline_seconds + budget, 2 * budget)

    @model_validator(mode="after")
    def _lock_outlives_planner_turn(self) -> "Settings":
        needed = int((self.planner_turn_budget_seconds + LOCK_TTL_MARGIN_SECONDS) * 1000)
        if self.session_lock_ttl_ms < needed:
            raise ValueError(f"SESSION_LOCK_TTL_MS ({self.session_lock_ttl_ms}) must be at least the planner turn "
                             f"budget (LLM overall deadline and the live data call budget, RAILRADAR_CALL_BUDGET_SECONDS or "
                             f"NTES_CALL_BUDGET_SECONDS) plus "
                             f"{LOCK_TTL_MARGIN_SECONDS}s margin ({needed} ms)")
        return self

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() == "production"

    @property
    def disruption_simulation_enabled(self) -> bool:
        """Public what-if closures: only outside production, whatever PUBLIC_DISRUPTION_SIMULATION says."""
        return self.public_disruption_simulation and not self.is_production

    @property
    def localize_max_body_bytes(self) -> int:
        """Whole multipart body for /localize: the frame plus a small allowance for boundaries and form fields."""
        return self.localize_max_image_bytes + 16_384

    def ar_guidance_on(self, station_id: str) -> bool:
        raw = self.ar_guidance_enabled
        if raw is None:
            return not self.is_production
        ids = {part.strip() for part in raw.split(",") if part.strip()}
        return "*" in ids or station_id in ids

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def railradar_configured(self) -> bool:
        key = self.railradar_api_key.get_secret_value().strip() if self.railradar_api_key else ""
        return self.data_provider.lower() == "railradar" and bool(key)

    @property
    def gemini_configured(self) -> bool:
        if self.llm_provider.lower() != "gemini":
            return False
        return bool(self.gcp_project) or (bool(self.gemini_api_key) and not self.is_production)

    @property
    def llm_configured(self) -> bool:
        return self.gemini_configured or self.bedrock_configured

    @property
    def bedrock_configured(self) -> bool:
        return (
            self.llm_provider.lower() == "bedrock"
            and bool(self.aws_region)
            and bool(self.bedrock_model_id)
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
