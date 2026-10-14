"""Composition root: wires providers, services and the optional LLM adapter."""

import logging
from dataclasses import dataclass
from zoneinfo import ZoneInfo

from redis import Redis

from app.audit.log import AuditLog
from app.clock import Clock, FixedClock, SystemClock
from app.config import Settings
from app.disruption.service import DisruptionService
from app.harness.engine import WorkflowEngine
from app.harness.merge import JourneyMerger
from app.harness.planner import PlannerService
from app.intent.extractor import IntentExtractor
from app.intent.llm import IntentLLM, LLMError
from app.llm.base import ChatLLM
from app.intent.rules import RuleBasedExtractor
from app.journey.plan_store import InMemoryPlanStore, PlanStore, RedisPlanStore
from app.journey.planner import GoalPlanner
from app.journey.venues import load_venues
from app.providers.base import DisruptionSource, JourneyProvider
from app.providers.demo import DemoDisruptionSource, DemoJourneyProvider
from app.providers.railradar import RailRadarDisruptionSource, RailRadarJourneyProvider, UnconfiguredLiveProvider
from app.providers.railradar_client import RailRadarClient
from app.providers.railradar_shared import RedisQuotaGate, RedisResponseCache
from app.ranking.recommender import Recommender
from app.infra.redis import build_redis
from app.security.tokens import SessionTokenSigner, build_signer
from app.sessions.redis_store import RedisSessionStore
from app.sessions.store import InMemorySessionStore, SessionStore
from app.stations.resolver import StationResolver

log = logging.getLogger("railsaathi")


@dataclass
class Container:
    settings: Settings
    clock: Clock
    provider: JourneyProvider
    disruptions: DisruptionSource
    resolver: StationResolver
    extractor: IntentExtractor
    audit: AuditLog
    planner: PlannerService
    data_provider_status: dict
    redis: Redis | None = None  # shared client; None when REDIS_URL is unset
    signer: SessionTokenSigner | None = None
    chat_llm: ChatLLM | None = None  # ticketing agent LLM; None -> rule-based KeywordChatLLM
    chat_llm_reason: str | None = None
    goal_planner: GoalPlanner | None = None
    plan_store: PlanStore | None = None

    @property
    def agent_llm(self) -> ChatLLM:
        if self.chat_llm is not None:
            return self.chat_llm
        from app.agent.keyword_llm import KeywordChatLLM

        return KeywordChatLLM()

    @property
    def chat_llm_status(self) -> dict:
        return {"provider": self.agent_llm.name, "llm": self.chat_llm is not None,
                "reason": self.chat_llm_reason}


def build_clock(settings: Settings) -> Clock:
    """System clock, or a frozen clock when FIXED_NOW is set outside production (for deterministic e2e runs)."""
    if settings.fixed_now is None or settings.is_production:
        if settings.fixed_now is not None:
            log.warning("FIXED_NOW is ignored because APP_ENV=production")
        return SystemClock(settings.timezone)
    fixed = settings.fixed_now
    if fixed.tzinfo is None:
        fixed = fixed.replace(tzinfo=ZoneInfo(settings.timezone))
    log.warning("Application clock frozen at %s (FIXED_NOW)", fixed.isoformat())
    return FixedClock(fixed)


def build_llm(settings: Settings) -> tuple[IntentLLM | None, str | None]:
    """Planner intent extraction LLM: (provider, reason_if_unavailable). Never contacts AWS or Google here;
    any failure degrades to rule-based extraction."""
    choice = settings.llm_provider.lower()
    if choice == "gemini":
        if not settings.gemini_configured:
            log.warning("LLM_PROVIDER=gemini but GOOGLE_CLOUD_PROJECT is missing; using rule-based extraction")
            return None, "gemini_not_configured"
        try:
            from app.intent.gemini import GeminiIntentProvider

            return GeminiIntentProvider(settings), None
        except LLMError as err:
            log.warning("Gemini unavailable (%s); using rule-based extraction", err.kind.value)
            return None, f"gemini_{err.kind.value}"
    if choice != "bedrock":
        return None, "llm_disabled"
    if not settings.bedrock_configured:
        log.warning("LLM_PROVIDER=bedrock but AWS_REGION/BEDROCK_MODEL_ID missing; using rule-based extraction")
        return None, "bedrock_not_configured"
    try:
        from app.intent.bedrock import BedrockIntentProvider

        return BedrockIntentProvider(settings), None
    except LLMError as err:
        log.warning("Bedrock unavailable (%s); using rule-based extraction", err.kind.value)
        return None, f"bedrock_{err.kind.value}"


def build_chat_llm(settings: Settings) -> tuple[ChatLLM | None, str | None]:
    """Ticketing agent LLM: (llm, reason_if_unavailable). Only Gemini has a chat adapter; anything else (or a
    construction failure) returns None and the agent uses the rule-based KeywordChatLLM. Never contacts Google."""
    choice = settings.llm_provider.lower()
    if choice == "bedrock":
        return None, "chat_bedrock_not_supported"
    if choice != "gemini":
        return None, "llm_disabled"
    if not settings.gemini_configured:
        return None, "gemini_not_configured"
    try:
        from app.agent.prompt import SYSTEM_INSTRUCTION
        from app.llm.gemini import GeminiChatLLM

        return GeminiChatLLM(settings, system_instruction=SYSTEM_INSTRUCTION), None
    except Exception as exc:  # noqa: BLE001 - degrade, never fail startup
        log.warning("Gemini chat unavailable (%s); using the rule-based agent", type(exc).__name__)
        return None, "gemini_unavailable"


def build_data_sources(settings: Settings, redis: Redis | None = None) -> tuple[JourneyProvider, DisruptionSource, dict]:
    """Choose demo or RailRadar (RAILWAY_DATA_MODE). Never contacts RailRadar here.

    Live mode without a key does NOT fall back to demo journeys: searches fail with a
    clear "not configured" message and /api/health reports the reason."""
    requested = settings.data_provider.lower()
    if requested == "railradar" and settings.railradar_configured:
        api_key = settings.railradar_api_key.get_secret_value().strip()
        shared = {}
        if redis is not None:  # one quota and one cache across every instance
            shared = {
                "quota": RedisQuotaGate(redis, api_key, settings.railradar_requests_per_minute,
                                        settings.redis_key_prefix),
                "cache": RedisResponseCache(redis, api_key, settings.railradar_stale_seconds,
                                            settings.redis_key_prefix),
            }
        client = RailRadarClient(
            settings.railradar_base_url, api_key,
            settings.railradar_timeout_seconds, settings.railradar_cache_seconds,
            requests_per_minute=settings.railradar_requests_per_minute,
            stale_seconds=settings.railradar_stale_seconds, **shared,
        )
        provider = RailRadarJourneyProvider(client, settings.timezone, settings.railradar_max_concurrency)
        return provider, RailRadarDisruptionSource(client, settings.timezone), {
            "requested": requested, "active": "railradar", "configured": True, "reason": None}
    if requested == "railradar":
        log.error("RAILWAY_DATA_MODE=railradar but RAILRADAR_API_KEY is empty; live searches will fail (no demo fallback)")
        unconfigured = UnconfiguredLiveProvider("RailRadar API key is not configured (set RAILRADAR_API_KEY)",
                                                settings.timezone)
        return unconfigured, unconfigured, {
            "requested": requested, "active": "railradar", "configured": False,
            "reason": "railradar_api_key_missing"}
    if requested != "demo":
        raise ValueError(f"Unknown RAILWAY_DATA_MODE '{settings.data_provider}' (use 'demo' or 'railradar')")
    if settings.is_production:
        # Simulated data is never served in production: searches fail honestly and /readyz reports not ready.
        log.error("RAILWAY_DATA_MODE=demo is refused when APP_ENV=production; configure RailRadar")
        refused = UnconfiguredLiveProvider("Demo data is disabled in production and live data is not configured",
                                           settings.timezone)
        return refused, refused, {
            "requested": requested, "active": "none", "configured": False, "reason": "demo_refused_in_production"}
    return DemoJourneyProvider(settings.timezone), DemoDisruptionSource(), {
        "requested": requested, "active": "demo", "configured": True, "reason": None}


def build_session_store(settings: Settings, clock: Clock, redis: Redis | None) -> SessionStore:
    if redis is not None:
        return RedisSessionStore(redis, settings.session_ttl_minutes * 60, settings.redis_key_prefix,
                                 settings.session_lock_ttl_ms, settings.session_lock_wait_seconds)
    return InMemorySessionStore(clock, settings.session_ttl_minutes)


def build_plan_store(settings: Settings, redis: Redis | None) -> PlanStore:
    ttl = settings.session_ttl_minutes * 60
    if redis is not None:
        return RedisPlanStore(redis, ttl, settings.redis_key_prefix)
    return InMemoryPlanStore(ttl)


def build_container(settings: Settings, clock: Clock | None = None,
                    llm: IntentLLM | None = None, use_configured_llm: bool = True,
                    redis: Redis | None = None, chat_llm: ChatLLM | None = None) -> Container:
    """`redis` lets tests inject fakeredis; otherwise a client is built from REDIS_URL (or None)."""
    clock = clock or build_clock(settings)
    redis = redis if redis is not None else build_redis(settings)
    signer = build_signer(settings)
    provider, disruptions, data_status = build_data_sources(settings, redis)
    resolver = StationResolver(provider)
    reason = None
    if llm is None and use_configured_llm:
        llm, reason = build_llm(settings)
    chat_reason = None
    if chat_llm is None and use_configured_llm:
        chat_llm, chat_reason = build_chat_llm(settings)
    elif chat_llm is None:
        chat_reason = "llm_disabled"
    extractor = IntentExtractor(RuleBasedExtractor(resolver), llm, reason or ("llm_disabled" if llm is None else None))
    audit = AuditLog()
    recommender = Recommender(provider, settings.min_transfer_minutes)
    engine = WorkflowEngine(settings, clock, audit, recommender, resolver)
    planner = PlannerService(
        engine=engine,
        store=build_session_store(settings, clock, redis),
        extractor=extractor,
        merger=JourneyMerger(resolver),
        disruption=DisruptionService(disruptions, recommender),
        data_mode=provider.data_mode,
    )
    goal_planner = GoalPlanner(provider, resolver, load_venues(), clock, settings.timezone,
                               settings.max_planning_days)
    return Container(settings, clock, provider, disruptions, resolver, extractor, audit, planner, data_status, redis, signer,
                     chat_llm, chat_reason, goal_planner, build_plan_store(settings, redis))
