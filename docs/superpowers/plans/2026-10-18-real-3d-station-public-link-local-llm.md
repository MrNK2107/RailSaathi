# Real 3D Chennai Central, public demo link and local LLM fallback: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the tilted-plan `#/tour` scene for Chennai Central with a real-geometry 3D model (OpenStreetMap + a
Blender-built heritage building), make the app reachable from any phone through `run.py --public`, and fall back
from Gemini to a local gemma4 (Ollama) within the machine's memory.

**Architecture:** Three independent parts. **C** (backend LLM): an Ollama adapter for both LLM seams in
`container.py`, wrapped in a fallback that prefers Gemini and cools it down on persistent or throttling errors.
**A** (`run.py`): a Cloudflare quick tunnel, per-visitor rate limiting from `CF-Connecting-IP` in public mode
only, memory checks. **B** (tour): OSM features are fetched offline into `osm.json`, aligned to the traced graph by
a similarity fit stored in `world_alignment`, served as a `world` block on the tour payload, turned into a pure
scene spec, and drawn with merged three.js meshes plus a `.glb` heritage model.

**Tech Stack:** FastAPI, Pydantic settings, httpx (already a dependency), pytest; React 18, three 0.172,
@react-three/fiber 8, drei 9, Vitest, Playwright; Blender 5.2 (headless Python); Ollama 0.30.8 (`gemma4:latest`);
`cloudflared`.

**Spec:** `docs/superpowers/specs/2026-10-17-real-3d-station-and-public-demo-link-design.md`

## Global Constraints

- No Google imagery or geometry in the model; nothing fetched from Google or Overpass at runtime.
- Production CSP stays `'self'`-only for scripts, data and models; nothing new added to `security-headers.conf`.
- No Draco. The `.glb` is plain (low-poly, ≤ 2 MB) and loaded with `GLTFLoader` from `three/examples/jsm`.
- Bundle budget (`frontend/scripts/check-budget.mjs`): three chunk ≤ 200 kB, tour ≤ 270 kB, other chunks ≤ 40 kB
  gzip. Do not raise budgets.
- Every new user-visible string in English **and** Tamil in `frontend/src/mobile/strings.ts`.
- OSM attribution text, verbatim: `© OpenStreetMap contributors`.
- Existing tour payload fields, `geo_reference`, `metres_per_pixel`, distances, `mapsLinks.ts`, `ar/geometry.ts`
  and the `stations.py` panorama tooling keep their current behaviour.
- Dev-only features follow the existing pattern: a settings property that is False when `is_production`.
- Ollama defaults: `OLLAMA_URL=http://127.0.0.1:11434`, `OLLAMA_MODEL=gemma4:latest`, `num_ctx` 8192,
  `think: false`, `keep_alive` "10m". Never load the model at startup.
- `llm_overall_deadline_seconds` stays 20 s.
- Commit messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Backend tests: `cd backend && uv run pytest <path> -q`. Frontend: `cd frontend && npx vitest run <path>`.

## Review Focus

1. **Ollama not running or model not pulled**: the chat and planner answer rule-based, with no 500 and no 20 s
   hang. Covered by Task 1 (`test_connection_refused_is_not_configured`, `test_missing_model_is_not_configured`).
2. **Gemini answers mid-conversation after a gemma4 turn** (history carries Gemini `provider_state` into Ollama, or
   the reverse): the turn still works. Covered by Task 3 (`test_ollama_ignores_foreign_provider_state`).
3. **`CF-Connecting-IP` sent by a LAN client when not in public mode**: it must be ignored. Covered by Task 4
   (`test_cf_header_ignored_without_public_mode`).
4. **A station without `osm.json`, or a broken/missing `.glb`**: today's scene, or the extruded-footprint
   fallback, with no blank canvas. Covered by Task 8 (`buildSceneSpec without world`) and Task 9
   (`model load failure shows footprint`).
5. **320 px phone opening `#/tour` over the tunnel**: the whole station framed, labels not overlapping the chips.
   Covered by Task 10 screenshots at 320/390/1280.

---

## Part C: local LLM fallback

### Task 1: Ollama chat adapter and settings

**Files:**
- Create: `backend/app/llm/ollama.py`
- Modify: `backend/app/config.py` (LLM block near line 152; properties near line 220)
- Modify: `backend/.env.example` (document the new variables)
- Test: `backend/tests/test_llm_ollama.py`

**Interfaces:**
- Produces:
  - Settings fields `ollama_url: str = "http://127.0.0.1:11434"`, `ollama_model: str = "gemma4:latest"`,
    `ollama_num_ctx: int = Field(8192, ge=1024, le=32768)`, `ollama_keep_alive: str = "10m"`,
    `ollama_timeout_seconds: float = Field(18.0, gt=0)`, `llm_fallback: str = "none"` ("ollama" or "none").
  - Property `ollama_configured -> bool`: True when (`llm_provider == "ollama"` or `llm_fallback == "ollama"`)
    and not `is_production`.
  - `class OllamaCaller(settings, transport: httpx.BaseTransport | None = None)` with
    `chat(payload: dict, deadline: Deadline) -> dict`. It POSTs `/api/chat` with `stream: false`,
    `think: false`, `keep_alive`, `options: {num_ctx}`. It is serialised with a module-level `threading.Lock`, so
    one request runs at a time.
  - `classify(exc) -> tuple[LLMError, bool]`:
    - `httpx.ConnectError` → `NOT_CONFIGURED`, not retryable;
    - HTTP 404 → `NOT_CONFIGURED`;
    - timeout → `TIMEOUT`, retryable;
    - 5xx → `MODEL_ERROR`, retryable;
    - 429 → `THROTTLED`.
  - `class OllamaChatLLM(settings, transport=None, system_instruction: str | None = None)`, with `name = "gemma4"`
    (derived as `settings.ollama_model.split(":")[0]`) and
    `generate(messages, tools, deadline) -> LLMTurn`.
    - Maps `ChatMessage` to Ollama messages: the system message first; tool results become role `tool` with the
      JSON content.
    - `ToolSpec` becomes `{"type": "function", "function": {name, description, parameters}}`.
    - `message.tool_calls[].function.{name, arguments}` becomes a `ToolCall`.
    - Ignores `provider_state`.

- [ ] **Step 1: Write failing tests** in `tests/test_llm_ollama.py`, using `httpx.MockTransport`:
  - `test_request_shape`: the posted JSON has `model == "gemma4:latest"`, `stream is False`, `think is False`,
    `options["num_ctx"] == 8192`, `keep_alive == "10m"`, and `tools[0]["function"]["name"] == "search_ticketing_guidance"`.
  - `test_text_reply`: `{"message": {"role": "assistant", "content": "RAC means..."}}` gives
    `LLMTurn.text == "RAC means..."` and no tool calls.
  - `test_tool_call_reply`: `tool_calls: [{"function": {"name": "search_ticketing_guidance", "arguments": {"query": "RAC"}}}]`
    gives `turn.tool_calls[0] == ToolCall(name="search_ticketing_guidance", args={"query": "RAC"})`.
  - `test_connection_refused_is_not_configured`: a transport raising `httpx.ConnectError` makes `generate` raise
    `LLMError` with `kind == NOT_CONFIGURED` within 1 s.
  - `test_missing_model_is_not_configured`: a 404 response gives `NOT_CONFIGURED`.
  - `test_ollama_ignores_foreign_provider_state`: a history containing `ChatMessage(role="assistant", provider_state=object())`
    serialises without error.
  - `test_ollama_configured_false_in_production`: `Settings(_env_file=None, app_env="production", llm_provider="ollama").ollama_configured is False`.
- [ ] **Step 2:** Run `uv run pytest tests/test_llm_ollama.py -q`. Expected: FAIL (module missing).
- [ ] **Step 3:** Implement the settings and `app/llm/ollama.py`, reusing `call_with_retries` and
  `run_blocking_with_deadline` from `app/llm/base.py` the way `GeminiCaller` does. The per-call timeout is
  `deadline.clip(ollama_timeout_seconds)`.
- [ ] **Step 4:** Run `uv run pytest tests/test_llm_ollama.py tests/test_llm_gemini.py -q`. Expected: PASS.
- [ ] **Step 5:** Commit `feat(llm): Ollama chat adapter for a local model (dev only)`.

### Task 2: Ollama intent provider

**Files:**
- Create: `backend/app/intent/ollama.py`
- Test: `backend/tests/test_llm_ollama.py` (append)

**Interfaces:**
- Consumes: `OllamaCaller` (Task 1); `JSON_SYSTEM_PROMPT`, `TOOL_SCHEMA`, `parse_json_text`, `user_payload` and
  `validate_intent` from `app/intent/prompt.py`.
- Produces: `class OllamaIntentProvider(settings, transport=None)`, with `name` the same as the chat adapter's
  and `extract_intent(message, context) -> IntentUpdate`. It sends `format: TOOL_SCHEMA`, `temperature: 0` and
  `num_predict: 800`.

- [ ] **Step 1: Failing tests:**
  - `test_intent_uses_json_schema_format`: the posted `format == TOOL_SCHEMA`.
  - `test_intent_parses_reply`: reply content `{"intent":"provide_details","origin_text":"Chennai"}` gives
    `update.origin_text == "Chennai"`.
  - `test_intent_invalid_json_is_invalid_output`: content `"not json"` raises `LLMError(INVALID_OUTPUT)`.
- [ ] **Step 2:** Run the tests. Expected: FAIL.
- [ ] **Step 3:** Implement, mirroring `app/intent/gemini.py`.
- [ ] **Step 4:** Run the tests. Expected: PASS.
- [ ] **Step 5:** Commit `feat(intent): planner intent extraction on Ollama`.

### Task 3: Gemini → gemma4 fallback, wiring, provenance and health

**Files:**
- Create: `backend/app/llm/fallback.py`
- Modify: `backend/app/llm/base.py` (`LLMTurn` gains `model: str | None = None`)
- Modify: `backend/app/container.py` (`build_llm`, `build_chat_llm`)
- Modify: `backend/app/agent/controller.py:199` and `:264` (record and label the model that answered)
- Modify: `backend/app/llm/gemini.py` and `backend/app/llm/ollama.py` (set `LLMTurn.model`)
- Test: `backend/tests/test_llm_fallback.py`

**Interfaces:**
- Consumes: `OllamaChatLLM`, `OllamaIntentProvider`, `GeminiChatLLM`, `GeminiIntentProvider`, `PERSISTENT_ERRORS`.
- Produces:
  - `COOLDOWN_SECONDS = 60`.
  - `FALLBACK_ERRORS = PERSISTENT_ERRORS | {THROTTLED}`.
  - `MIN_FALLBACK_SECONDS = 8.0`: a mid-turn retry on the secondary model happens only if the deadline has at
    least this much left. Adjust it after the Task 11 measurement.
  - `class FallbackChatLLM(primary: ChatLLM, secondary: ChatLLM, clock=time.monotonic)`:
    - `name` is the primary's name;
    - `generate` uses the secondary while the primary is cooling down;
    - on an `LLMError` in `FALLBACK_ERRORS` from the primary, it starts the cooldown and retries on the secondary
      if `deadline.remaining() >= MIN_FALLBACK_SECONDS`, otherwise it re-raises;
    - `status() -> dict` returns `{"active": <name>, "primary_cooling_until": float | None}`.
  - `class FallbackIntentLLM(primary: IntentLLM, secondary: IntentLLM, clock=...)`: the same policy. Its result
    source name is the provider that answered.
  - `build_chat_llm` / `build_llm` behaviour:
    - `llm_provider="ollama"`: Ollama alone.
    - `llm_provider="gemini"` and `llm_fallback="ollama"`: `Fallback*(gemini, ollama)` when Gemini is configured,
      otherwise Ollama alone with the reason `"gemini_not_configured_using_ollama"`.
    - Production with `ollama`: as today (`llm_disabled` or Gemini only).
  - The agent's provenance source uses the `LLMTurn.model` of the final turn. Example:
    `"gemma4 (local) over the RailSaathi knowledge base (curated …)"` for Ollama, unchanged for Gemini.
  - `chat_llm_status` includes the fallback `status()` when present.

- [ ] **Step 1: Failing tests**, using fake `ChatLLM`s that return or raise:
  - `test_primary_used_when_healthy`.
  - `test_auth_error_falls_back_and_cools_down`: the first call raises `AUTH`, and the turn is answered by the
    secondary. The second call within 60 s goes straight to the secondary. After a clock advance of 61 s, the
    primary is tried again.
  - `test_timeout_does_not_cool_down`: `TIMEOUT` from the primary re-raises and does not start a cooldown.
  - `test_no_fallback_when_deadline_short`: with `deadline.remaining() == 3` and `THROTTLED`, it re-raises.
  - `test_build_chat_llm_ollama_only`: `Settings(llm_provider="ollama")` gives an `OllamaChatLLM` and reason `None`.
  - `test_build_chat_llm_gemini_unconfigured_uses_ollama`: `llm_provider="gemini"`, `llm_fallback="ollama"`, no
    project, gives `OllamaChatLLM` and reason `"gemini_not_configured_using_ollama"`.
  - `test_provenance_names_local_model`: an `AgentController` with a fake Ollama turn (`model="gemma4"`) has a
    provenance `source` that starts with `"gemma4 (local)"`.
  - `test_health_reports_active_model`: `GET /api/health` with the fallback wired includes `chat.active`.
- [ ] **Step 2:** Run the tests. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run `uv run pytest tests/test_llm_fallback.py tests/test_llm_gemini.py tests/test_ticketing_agent.py tests/test_health.py -q`.
  Expected: PASS.
- [ ] **Step 5:** Commit `feat(llm): fall back from Gemini to the local model; answers name the model`.

## Part A: public demo link

### Task 4: Per-visitor rate limits in public mode

**Files:**
- Modify: `backend/app/api/middleware.py:37` (`client_ip`) and where it is called, around line 113
- Modify: `backend/app/config.py` (new `public_tunnel: bool = False`; property `trust_cf_connecting_ip` that is
  `public_tunnel and not is_production`)
- Modify: `backend/app/main.py:56`
- Test: `backend/tests/test_rate_limit.py` (append)

**Interfaces:**
- Produces: `client_ip(headers, scope, trusted_hops=0, trust_cf: bool = False) -> str`. When `trust_cf` is set
  and the `cf-connecting-ip` header is present, it returns the header value truncated to 64 characters. Otherwise
  the behaviour is unchanged. `run.py` sets the env var `PUBLIC_TUNNEL=1`.

- [ ] **Step 1: Failing tests:**
  - `test_cf_header_keys_buckets_in_public_mode`: two clients with different `CF-Connecting-IP` values, both from
    127.0.0.1, get separate buckets. 60 requests from A do not 429 B.
  - `test_cf_header_ignored_without_public_mode`.
  - `test_cf_header_ignored_in_production`: `app_env="production"`, `public_tunnel=True`.
- [ ] **Step 2:** Run the tests. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run `uv run pytest tests/test_rate_limit.py tests/test_limits.py -q`. Expected: PASS.
- [ ] **Step 5:** Commit `feat(api): per-visitor rate limits behind the demo tunnel`.

### Task 5: `run.py --public`, `--warm-llm` and memory checks

**Files:**
- Modify: `run.py`
- Modify: `frontend/vite.config.ts` (`server.allowedHosts` and `preview.allowedHosts` read from
  `process.env.VITE_ALLOWED_HOSTS`, a comma list; unset keeps Vite's default)
- Modify: `README.md` (quick start), `docs/DEMO_SCENARIOS.md`
- Test: `backend/tests/test_run_py.py` (append; it loads `run.py` with importlib)

**Interfaces:**
- Produces, in `run.py`:
  - `parse_tunnel_url(line: str) -> str | None`: matches `https://[a-z0-9-]+\.trycloudflare\.com`.
  - `start_tunnel(cloudflared: str, local_url: str) -> tuple[subprocess.Popen, str]`: reads stderr lines until a
    URL appears, with a 30 s timeout.
  - `free_ram_bytes() -> int | None`: Windows uses `ctypes` `GlobalMemoryStatusEx`; Linux reads `/proc/meminfo`;
    macOS returns `None`.
  - `loaded_ollama_models(url: str) -> list[str]`: `GET /api/ps` with a 2 s timeout; returns `[]` on any error.
  - `warm_llm(url: str, model: str) -> float`: POSTs `/api/generate` with `{"model", "prompt": "", "keep_alive": "10m"}`
    and returns the seconds taken.
  - Flags: `--public` (implies `--no-https`, sets `PUBLIC_TUNNEL=1` and `VITE_ALLOWED_HOSTS=.trycloudflare.com`,
    and runs uvicorn without `--reload`) and `--warm-llm`.
  - Messages printed:
    - missing `cloudflared`: `cloudflared was not found. Install it: winget install Cloudflare.cloudflared (Windows), brew install cloudflared (macOS).`
    - `--public` with `LLM_PROVIDER` gemini/bedrock and no Ollama fallback: a quota warning.
    - free RAM below 10 GB while Ollama is the provider or fallback: the free and needed GB, plus the hint
      `OLLAMA_MODEL=llama3.2:3b`.
    - more than one model loaded in Ollama: a warning listing them.
    - always in `--public`: `This link is public while RailSaathi runs: anyone with it can use the app. It changes every run.`
  - The tunnel process is stopped with the others.
- Builder decision, recorded in the README: dev server versus `vite preview` for `--public`. Measure the first
  load of `#/tour` over the tunnel with Playwright on the Fast 3G profile, and pick the faster.

- [ ] **Step 1: Failing tests:**
  - `test_parse_tunnel_url` (a real cloudflared log line, and a non-matching line → `None`);
  - `test_public_implies_http_and_env`: the env built by a factored `build_env(args)` has
    `PUBLIC_TUNNEL == "1"` and no `VITE_HTTPS`;
  - `test_backend_cmd_no_reload_in_public`;
  - `test_free_ram_bytes_returns_int_or_none`.
- [ ] **Step 2:** Run `uv run pytest tests/test_run_py.py -q`. Expected: FAIL.
- [ ] **Step 3:** Implement, factoring `build_env(args)` and `backend_cmd(args)` out of `main()`.
- [ ] **Step 4:** Run the tests. Expected: PASS. Then manual: install cloudflared, run `python run.py --public`,
  and open the printed link on a phone on mobile data. It loads with no certificate warning.
- [ ] **Step 5:** Commit `feat(run): --public Cloudflare tunnel link, --warm-llm, memory warnings`.

## Part B: real 3D Chennai Central

### Task 6: OSM world data, offline

**Files:**
- Create: `backend/app/navigation/world.py` (pure: projection, trimming, loading)
- Modify: `backend/scripts/stations.py` (new `osm` subcommand next to `panoramas`, around line 436)
- Create: `backend/data/stations/chennai_central/osm.json` (generated, committed)
- Test: `backend/tests/test_world.py`

**Interfaces:**
- Produces:
  - `ORIGIN` of a world file: its `origin: {"lat", "lon"}`. For Chennai Central, use the OSM station node
    2481969291.
  - `to_local(lat, lon, origin_lat, origin_lon) -> tuple[float, float]`: east and north metres, equirectangular,
    rounded to 0.01.
  - `WorldFeature` TypedDict: `{"id": str, "kind": "building"|"roof"|"platform"|"rail"|"subway"|"station"|"heritage",
    "name": str|None, "ref": str|None, "levels": int|None, "height_m": float|None, "layer": int|None,
    "points": list[list[float]]}`. `points` is an open ring for areas and a polyline for rails, in [east, north]
    metres.
  - `elements_to_features(overpass_json: dict, origin) -> list[WorldFeature]`: sorted by `id`. Drops buildings
    under 12 m². Simplifies with Douglas–Peucker at a 0.5 m tolerance.
  - `load_world(station_dir: Path) -> dict | None`, the `osm.json` schema:
    `{"source": "OpenStreetMap", "attribution": "© OpenStreetMap contributors", "licence": "ODbL-1.0",
    "osm_timestamp": str, "bbox": [s, w, n, e], "query": str, "origin": {...}, "features": [...]}`.
  - The heritage main building's feature has `kind = "heritage"`. Pick the footprint by checking the OSM
    building ways that face Poonamallee High Road and recording the chosen way id in the file.
  - CLI: `uv run python scripts/stations.py osm chennai_central [--bbox s,w,n,e] [--input saved.json]`. The
    default bbox is `13.0780,80.2690,13.0905,80.2790` (widened north so platforms 1–11, about 600 m long, fit).
    It sends a User-Agent and `Accept: application/json` (the default curl agent got a 406).

- [ ] **Step 1: Failing tests:**
  - `test_to_local_origin_is_zero`;
  - `test_to_local_100m_north` (lat + 0.000899 → north ≈ 100 ± 0.5);
  - `test_elements_to_features_kinds`: a small Overpass fixture with one building, one `building=roof`, one
    platform `ref "7;8"` and one rail gives four features with the right kinds and ref;
  - `test_deterministic_output` (same input → identical JSON);
  - `test_drops_tiny_buildings`;
  - `test_load_world_missing_returns_none`.
- [ ] **Step 2:** Run `uv run pytest tests/test_world.py -q`. Expected: FAIL.
- [ ] **Step 3:** Implement. Run the CLI once and commit `osm.json`. Check that it contains platform refs `7;8`
  and `9;10`, and that the gzipped file is ≤ 120 kB (report the size).
- [ ] **Step 4:** Run the tests and `uv run python scripts/stations.py validate`. Expected: PASS.
- [ ] **Step 5:** Commit `feat(stations): OpenStreetMap world data for Chennai Central (offline, ODbL)`.

### Task 7: Align the traced graph to OSM (`world_alignment`) and resolve the entrance name

**Files:**
- Create: `backend/app/navigation/alignment.py`
- Modify: `backend/scripts/stations.py` (an `align` subcommand; `validate` checks the residual)
- Modify: `backend/data/stations/chennai_central/metadata.json` (adds `world_alignment`; `geo_reference`
  untouched)
- Possibly modify: `station.json` / `info.json` notes for the entrance name (see Step 3)
- Test: `backend/tests/test_alignment.py`

**Interfaces:**
- Produces:
  - `fit_similarity(src: list[tuple[float,float]], dst: list[tuple[float,float]]) -> Similarity`: Umeyama/Procrustes
    with no reflection.
  - `Similarity` dataclass: `scale: float`, `rotation_deg: float`, `tx: float`, `ty: float`,
    `residual_m: float` (RMS), and `apply(x, y) -> (east, north)`.
  - Input frame: plan metres (`position_m`; y points down the plan, so negate y before fitting).
  - Pairs: the centroid of each traced platform area 7–12 (the `areas` of kind `platform` in `station.json`)
    matched to the nearest OSM platform centroid after a coarse placement with `geo_reference.anchor`.
  - `RESIDUAL_LIMIT_M = 15.0`. Above it, `fit_translation` is used instead, and that is recorded.
  - `metadata.json` `world_alignment` contains `method` ("similarity" or "translation"), scale, rotation_deg, tx,
    ty, residual_m, pairs (the area ids and OSM way ids), `source`, and `verification: "pending"`.
  - Platform labels: the OSM `ref` where present. For the matched platforms 7–12, the number comes from the
    traced area name, with `label_source: "station_plan"`.

- [ ] **Step 1: Failing tests:**
  - `test_fit_recovers_known_transform` (scale 1.03, rotation 12°, shift (40, −25), plus noise ±0.3 m →
    within 0.5° and 1 m);
  - `test_fit_rejects_reflection`;
  - `test_large_residual_falls_back_to_translation`;
  - `test_validate_flags_residual_over_limit` (via the validate check function);
  - `test_geo_reference_unchanged` (the committed metadata still has `method == "anchor_scale_rotation"`).
- [ ] **Step 2:** Run the tests. Expected: FAIL.
- [ ] **Step 3:** Implement and run `scripts/stations.py align chennai_central`. Report the residual. Then check
  the entrance-name conflict:
  - The node "Main Entrance (Wall Tax Road)" sits on the plan's "MAIN ENTRANCE (Jawaharlal Nehru Road)" label.
    Wikipedia says the main entrance is on Poonamallee High Road and the east side is on Wall Tax Road.
  - With the aligned position, look up the nearest OSM road names and entrances.
  - Record the finding and the sources in `metadata.json` `notes`.
  - Rename the node only if OSM and Wikipedia agree. Otherwise leave it and note the conflict.
- [ ] **Step 4:** Run `uv run pytest tests/test_alignment.py tests/test_station_validate.py -q` and
  `scripts/stations.py validate`. Expected: PASS.
- [ ] **Step 5:** Commit `feat(stations): fit the traced graph to OpenStreetMap (world_alignment)`.

### Task 8: Heritage building model (Blender) and `world` block on the tour payload

**Files:**
- Create: `backend/scripts/build_station_model.py` (Blender Python; run as
  `blender --background --python scripts/build_station_model.py -- --footprint <osm.json> --out <glb>`)
- Create: `backend/data/stations/chennai_central/heritage.blend`, `heritage.glb`
- Modify: `backend/app/api/navigation.py` (`get_station_tour` adds `world`; new
  `GET /api/stations/{station_id}/model.glb`, served with `model/gltf-binary`, cached like `/map`)
- Modify: `frontend/src/api/types.ts` (`StationTour.world?: TourWorld | null`)
- Test: `backend/tests/test_tour_api.py` (append)

**Interfaces:**
- Produces, in the payload:
  `world: {"attribution", "licence", "osm_timestamp", "features": WorldFeature[], "alignment": {...world_alignment},
  "model": {"url": "/api/stations/chennai_central/model.glb", "feature_id": <heritage id>, "height_m": 41} | null}`,
  or `null` without `osm.json`.
- TS: `TourWorld`, `TourWorldFeature` (snake_case, mirroring the JSON above).
- Model content (Blender script, low-poly, ≤ 2 MB, origin at the footprint centroid, +Y up, metres):
  - maroon walls `#7a1f1f`, white trim `#f3efe6`;
  - two-storey arcaded frontage on the footprint;
  - corner towers with caps;
  - a central four-faced clock tower 41 m tall with clock faces on four sides.
  - Use the Blender MCP if it connects; otherwise run headless. The script is the source of truth either way.

- [ ] **Step 1: Failing tests:**
  - `test_tour_world_block_for_chennai_central`: `world.attribution == "© OpenStreetMap contributors"`,
    `world.features` non-empty, `world.model.url` ends with `model.glb`;
  - `test_tour_world_null_for_egmore`;
  - `test_model_glb_served`: status 200, content type `model/gltf-binary`, body starts with `b"glTF"`, size
    ≤ 2_000_000;
  - `test_existing_tour_fields_unchanged`: `geo_reference.method == "anchor_scale_rotation"`, and the first
    node's `position_m` equals the value before this change.
- [ ] **Step 2:** Run `uv run pytest tests/test_tour_api.py -q`. Expected: FAIL.
- [ ] **Step 3:** Build the model with Blender. Check it by rendering a PNG preview from the same script
  (`--preview out.png`) and looking at it. Then implement the endpoint and the payload.
- [ ] **Step 4:** Run `uv run pytest tests/test_tour_api.py tests/test_navigation_api.py -q`. Expected: PASS.
- [ ] **Step 5:** Commit `feat(tour): world block and heritage model for Chennai Central`.

### Task 9: Scene spec and renderer for the world

**Files:**
- Create: `frontend/src/tour/worldSpec.ts` (pure)
- Modify: `frontend/src/tour/sceneSpec.ts` (`buildSceneSpec` adds `world: WorldSpec | null`; with a world, the
  graph is transformed by the alignment, there is no plan-image floor, and the camera frames the world bounds)
- Create: `frontend/src/tour/WorldLayer.tsx` (merged meshes, `GLTFLoader` lazy, attribution handled by the screen)
- Modify: `frontend/src/tour/TourScene.tsx` (renders `WorldLayer` when `spec.world`; the route tube becomes a
  glowing path: emissive, slightly wider, with an animated dash or pulse that is off under reduced motion)
- Test: `frontend/src/test/worldSpec.test.ts`; `frontend/src/test/tourSpec.test.ts` (append)

**Interfaces:**
- Consumes: `TourWorld` (Task 8).
- Produces:
  - `planToWorld(alignment, [xPlan, yPlan]) -> Vec2`. The world frame stays the three.js convention:
    x = east, z = −north.
  - `WorldSpec`:
    `{buildings: {outline: Vec2[], height: number}[], roofs: ..., platforms: {outline, label: string|null, labelSource: "osm"|"station_plan"|null}[],
    rails: Vec2[][], heritage: {outline, modelUrl: string|null, height: 41} | null, bounds: {minX,maxX,minZ,maxZ}, attribution: string}`.
  - Heights: `levels × 3.2`, else `height_m`, else 9. Platforms 0.84. Roofs at 6.5 m, 0.3 m thick, on posts
    drawn as one instanced mesh.
  - `frameBounds(bounds, aspect: number, fovDeg = 50) -> CameraPose`: the whole complex in view at a 55°
    pitch from the south (the frontage faces the camera on open).
  - `WorldLayer`:
    - buildings merged into one `BufferGeometry` (`mergeGeometries` from `three/examples/jsm/utils/BufferGeometryUtils.js`),
      one material, colour `#cbd2dc`;
    - platforms `#e7e2d6`, rails `#4b5563`, roofs `#9fb3c8` at 0.85 opacity, ground `#eef1f4`;
    - platform labels as drei `Html` only for labelled platforms;
    - the heritage model via `GLTFLoader` (no Draco loader set). On error, the heritage footprint is extruded to
      18 m in `#7a1f1f`.
  - Performance target: draw calls under 40 for the world, and 55+ fps at 4× CPU throttling in Chromium.

- [ ] **Step 1: Failing tests:**
  - `worldSpec.test.ts`:
    - `planToWorld applies similarity`;
    - `building height from levels` (levels 5 → 16);
    - `default building height 9`;
    - `platform label prefers osm ref`;
    - `station_plan label for traced platforms`;
    - `frameBounds fits a 320x480 canvas` (all corners project inside the frustum);
    - `buildSceneSpec without world` (the spec equals today's output for an Egmore fixture);
  - `tourSpec.test.ts`: `with world, route points are in world frame` (the first route point equals
    `planToWorld` of the traced start node).
  - A component test in `tour.test.tsx`: `model load failure shows footprint` (mock `GLTFLoader` to error and
    assert that the fallback mesh is rendered, using the existing test pattern for `TourScene`).
- [ ] **Step 2:** Run `npx vitest run src/test/worldSpec.test.ts src/test/tourSpec.test.ts src/test/tour.test.tsx`.
  Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run the same tests, plus `npm run typecheck`. Expected: PASS.
- [ ] **Step 5:** Commit `feat(tour): draw Chennai Central from OpenStreetMap with the heritage model`.

### Task 10: Tour screen copy, honesty labels, framing and visual verification

**Files:**
- Modify: `frontend/src/mobile/screens/StationTour.tsx` (attribution chip next to the schematic chip; no empty
  band above the canvas; the intro text depends on whether there is a world)
- Modify: `frontend/src/mobile/strings.ts` (EN and TA under `tour`)
- Modify: `docs/STATION_NAVIGATION.md` (the tour section: data sources, alignment, model, Blender script, CLI)
- Test: `frontend/src/test/tour.test.tsx` (append); e2e/axe spec for `#/tour` if one exists under `frontend/e2e`

**Interfaces:**
- New strings: `tour.osmAttribution`, `tour.introWorld`, `tour.worldNote`, `tour.platformFromPlan`, as exact
  English copy. The Tamil translations are written by the implementer and flagged as awaiting native review,
  like the existing ones.
  - `tour.osmAttribution`: `© OpenStreetMap contributors`
  - `tour.introWorld`: `A 3D model of the station from OpenStreetMap, with the walking routes from the station plan.`
  - `tour.worldNote`: `Buildings, platforms and tracks are from OpenStreetMap. Walkways and routes are schematic, traced from a station plan and placed on the map approximately (within about {residual} m). Heights are nominal.`
  - `tour.platformFromPlan`: `Platform number from the station plan`

- [ ] **Step 1: Failing tests:** `shows OSM attribution when world present`; `worldNote interpolates residual`;
  `no attribution for stations without world`; the strings completeness test (existing) covers the Tamil keys.
- [ ] **Step 2:** Run `npx vitest run src/test/tour.test.tsx`. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run `npm test`, `npm run lint`, `npm run typecheck` and `npm run build` (budget gate).
  Expected: all pass, and the budget lines print under their ceilings.
- [ ] **Step 5: Visual check.** Run `python run.py --skip-install --no-https`. Screenshot
  `#/tour?station=chennai_central` at 320, 390 and 1280 px:
  - on open;
  - after choosing Main Entrance → Platform 9;
  - mid-fly-through.

  Use the SwiftShader Playwright flags from the earlier probe. Look at every image and confirm:
  - the frontage and clock tower are recognisable;
  - platforms are numbered;
  - the sheds and tracks are visible;
  - the whole complex is framed, with no empty band;
  - the labels are readable;
  - the attribution is visible.

  Fix anything that fails and re-shoot.
- [ ] **Step 6:** Commit `feat(tour): world copy in English and Tamil, attribution, framing`.

### Task 11: End-to-end verification and measurements

**Files:**
- Modify: `docs/STATION_NAVIGATION.md`, `README.md`, `docs/LIMITATIONS.md` (record the measurements)

- [ ] **Step 1:** Run the full backend suite `uv run pytest -q` and the frontend
  `npm test && npm run e2e`. Expected: PASS.
- [ ] **Step 2:** Set `LLM_PROVIDER=ollama`, run `python run.py --warm-llm`, then ask the ticketing agent "What is
  RAC?" and send the planner "Chennai to Bengaluru tomorrow morning". Record the seconds each takes and the
  provenance source (it must name gemma4 (local)). If a turn exceeds 20 s, record that, and test `llama3.2:3b`
  for comparison.
- [ ] **Step 3:** Stop Ollama and repeat one question. The answer is rule-based, with no error.
- [ ] **Step 4:** During steps 2 and 5, record peak RAM (Task Manager or `Get-Process`) and VRAM (`nvidia-smi`)
  for backend + vite + Ollama.
- [ ] **Step 5:** Run `python run.py --public`, open the link on a phone on mobile data and a second phone, and
  check the tour, the chat, and that there's no certificate warning. Record the frame-rate impression and the
  first-load time.
- [ ] **Step 6:** Write the numbers into the docs and commit `docs: measured local model latency, memory and demo link`.
