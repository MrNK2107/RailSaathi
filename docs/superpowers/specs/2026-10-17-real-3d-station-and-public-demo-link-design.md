# Real 3D Chennai Central tour, and a public demo link

Date: 2026-10-17. Status: approved in conversation, awaiting builder check.

## Why

RailSaathi is demoed at GDG DevFest on people's own phones. Two things get in the way today:

1. **Phones must share the laptop's Wi-Fi.** `python run.py` serves the app on the LAN only, behind a
   self-signed certificate that every phone warns about. At a venue, judges and visitors are on their own mobile
   data or on guest Wi-Fi that isolates devices, so the QR code does not work.
2. **The 3D tour (`#/tour`) does not look like a station.** Verified by screenshot on 2026-10-17 (desktop
   1280 px and phone 390 px, `chennai_central`):
   - it is the 2D plan image (`map.png`) laid flat and tilted, with dots and lines on top and a faint
     translucent box over the concourse; there are no platforms with height, no roof sheds, no trains, and no
     sign of the maroon heritage building or clock tower that people know as Chennai Central;
   - the start label "Start: Main Entrance (Wall Tax Road)" sits on the plan's printed "MAIN ENTRANCE
     (Jawaharlal Nehru Road)" marker (the source data contradicts itself; see Data facts);
   - the default camera crops the plan (station title cut off on the left, plan runs off the right) and leaves
     an empty band above the scene;
   - Street View shows nothing: no Maps key, no authored panoramas.

The user cannot provide a Google Maps API key and asked to "try scraping". **Scraping Google Maps, Street View or
3D Tiles is out**: it breaks Google's terms, and `frontend/src/tour/streetView.ts` already promises that Google
imagery is never read into our model. Open data replaces it.

Success: at the demo, someone scans a QR code on their own phone, on any network, opens `#/tour`, and
recognises Chennai Central: the maroon frontage and clock tower, the long platform sheds, numbered platforms and
tracks, the city around it. They then pick an entrance and a platform and watch the camera fly along the route.

## Goals

- `python run.py --public` prints one public `https://` link and its QR code that works from any phone on
  any network, with no certificate warning.
- `#/tour` for `chennai_central` **replaces** the current tilted-plan scene (the user chose replace, not a new
  page) with a real-geometry 3D model built from OpenStreetMap:
  - the station complex at true positions and scale: platforms 1–17 (with their numbers), tracks, roof sheds,
    the main building, the Moore Market suburban terminal;
  - the heritage main building with its four-faced clock tower, modelled by hand (OSM has only footprints);
  - surrounding city blocks extruded (from `building:levels` where present, a nominal height otherwise);
  - the existing walking route (same route API, same pickers) drawn on this model as a glowing path, with the
    existing fly-through, overview and motion-free step poses.
- Correct framing on phone (320–430 px wide) and desktop: the whole station in view on open, no empty band.
- OSM attribution visible on the scene: "© OpenStreetMap contributors" (ODbL requirement).
- The ticketing agent and the journey planner fall back from Gemini to a local model (gemma4 through Ollama)
  when Gemini is out, and run on gemma4 alone when no Gemini key is set, within the machine's memory.

## Non-goals

- Expo Go or any React Native port. (Answered in conversation: RailSaathi is a Vite + React PWA; Expo Go runs
  only React Native/Expo projects. The public link solves the demo problem instead.)
- Google Street View, Google 3D Tiles, or any Google imagery in the model.
- Real 3D for the other three stations (Egmore, KSR Bengaluru, Hyderabad Deccan). They keep today's scene.
- New routing data: no new nodes or pathways, no new step-free claims, no foot-over-bridge.
- A permanent hosted deployment (Cloud Run is possible later; not part of this).
- Photoreal textures or downloaded photos inside the model.

## Anti-goals (a failure even if it "works")

- Presenting the model as surveyed. OSM footprints are real-world positions, but the indoor route graph is still
  traced from a schematic plan, and heights are nominal. The honesty labels must say which is which.
- Any Google-derived geometry or imagery, or anything fetched from Google at runtime.
- Fetching OpenStreetMap (Overpass) at runtime from the browser or backend. The CSP is `connect-src 'self'`,
  the demo must work offline from the laptop's cache, and Overpass is a shared, rate-limited service.
- A phone demo that stutters or drains the battery: draw calls and triangles must stay modest
  (merge geometry per material).
- Breaking the bundle budget (`frontend/scripts/check-budget.mjs`: three.js chunk ≤ 200 kB, tour ≤ 270 kB gzip)
  or the existing tour tests, accessibility checks and Tamil string completeness.

## Constraints

- Frontend: React 18, three.js 0.172 via @react-three/fiber 8 and drei 9 (already used). Vite 6.4: the dev
  and preview servers reject unknown `Host` headers unless `allowedHosts` names them.
- Backend: FastAPI. Station data lives in `backend/data/stations/<id>/` and is served by
  `GET /api/stations/{id}/tour` (`backend/app/api/navigation.py`); stations are authored offline with
  `backend/scripts/stations.py` and the service never writes station data.
- Production CSP (`frontend/nginx/security-headers.conf`): everything from `'self'`; nothing new may be added
  for this feature.
- Every user-visible string in English and Tamil (`mobile/strings.ts`, checked by a completeness test).
- Provenance discipline from the README: every dataset carries its source; nothing estimated is shown as
  verified.
- Windows is the main dev machine; `cloudflared` is not installed (`scoop` and `winget` are available).

## Decisions made in conversation

- **Replace** the existing `#/tour` scene for Chennai Central (user).
- **No Google key, no scraping** of Google (user cannot provide a key; scraping declined). Use OpenStreetMap
  (ODbL) for geometry; openly licensed photos (for example Wikimedia Commons) may be used only as *reference*
  for hand-modelling the heritage frontage, not as textures.
- **Public demo link via a Cloudflare quick tunnel** behind `run.py --public` (proposed; user said "sounds
  good, proceed").
- **The AI features use a local model for now**: "for now, to test it use the local gemma4 model via ollama"
  (user). Ollama 0.30.8 is installed on the dev machine with `gemma4:latest` (9.6 GB) pulled. So the public
  link spends no cloud quota.

## Design

### Part A: public demo link (`run.py --public`)

- `--public` starts `cloudflared tunnel --url <local frontend URL>` after the frontend is up, reads the
  `https://<random>.trycloudflare.com` URL from its output, prints it, and prints its QR code with the existing
  `print_qr`. The tunnel process is stopped with the others on Ctrl+C or if either server stops.
- If `cloudflared` is not on PATH, exit with a one-line install hint (`winget install Cloudflare.cloudflared`,
  or `scoop install cloudflared`, or `brew install cloudflared`), mirroring `tool()`.
- `--public` implies plain HTTP locally (`--no-https` behaviour): Cloudflare terminates TLS with a real
  certificate, so camera, microphone and motion sensors work on the phone with no warning.
- Vite must accept the tunnel host: add `.trycloudflare.com` to `server.allowedHosts` (and
  `preview.allowedHosts`), only when the tunnel is in use (pass it through an env var set by `run.py`), so the
  default dev server keeps Vite's host check.
- The printout says plainly that the link is public while it runs, that anyone with it can use the app, and
  that it changes every run.
- **Per-visitor rate limits.** Through `cloudflared → vite → /api proxy` every visitor reaches the backend from
  127.0.0.1, so today all phones would share one rate-limit bucket (60/min, 20/min on LLM routes) and lock each
  other out. In `--public` mode only (an env var set by `run.py`), key rate limits on Cloudflare's
  `CF-Connecting-IP` header. Keep the limits themselves. Never trust that header outside `--public`, and never in
  production. *(Builder-check finding; my call.)*
- **The whole app is exposed, not only the tour**, which is intended for the demo. With Part C, the AI routes
  run on the local model, so the link costs nothing. If `LLM_PROVIDER` is `gemini` or `bedrock` when `--public`
  starts, print a warning that visitors will spend that quota.
- Builder's call: whether `--public` serves the dev server (simplest) or a production build through
  `vite preview` with the same `/api` proxy (fewer, smaller requests over the tunnel; better on mobile data).
  Measure first load of `#/tour` over the tunnel on a throttled phone profile and pick.

### Part B: the real 3D model

**Data, prepared offline.** A new subcommand, `uv run python scripts/stations.py osm chennai_central`:

- queries Overpass once for a bounding box that covers the whole complex including the north ends of the
  platforms (the 2026-10-17 probe, 13.0780–13.0870 N, 80.2690–80.2790 E, cut the platforms off at the top;
  widen northward), selecting `building=*`, `railway=rail|platform|station|subway`, `public_transport=platform`
  and `building=roof`;
- converts every coordinate to local metres (east, north) around a fixed origin, trims tags to what is drawn
  (kind, name, `ref`, `building:levels`, `height`, `layer`), simplifies tiny buildings, and writes
  `backend/data/stations/chennai_central/osm.json` with the OSM timestamp, the query, the bounding box and the
  licence/attribution text;
- is re-runnable and deterministic (sorted output) so diffs stay readable. The file is committed; nothing
  calls Overpass at runtime.

The 2026-10-17 probe returned 689 elements: 569 `building=yes`, 36 `building=roof` (platform sheds), 15
platform ways with refs (`1`, `1A`, `2;3`, `3;4`, `5;6`, `7;8`, `9;10`, `13;14`, `14;15`, `15;16`, `16;17`,
and unnumbered ones), 39 rail ways, 7 metro (`railway=subway`) ways, the station outline (way 217845073,
`railway=station`, ref MAS) and the suburban terminal (way 1115820281, ref MASS).

**Aligning the route graph to the real station.** The traced graph is in plan metres
(`metres_per_pixel` 0.17794) and is pinned to the world only by one coordinate with an expected error of 50 m
(`metadata.json` `geo_reference`). Fit a similarity transform (translation, rotation, uniform scale) from the
traced platform areas 7–12 to the matching OSM platform polygons. Validate it in `stations.py validate`
(residual under a threshold the builder picks and documents). If the fit residual is large, fall back to
translation only and say so.

*My call, after the builder check:* the fit is **additive**. It is stored as a new `world_alignment` block in
`metadata.json` (method, parameters, residual in metres, source, `verification: "pending"`), next to the
existing `geo_reference`, which stays unchanged. `metres_per_pixel`, the existing `position_m`, `geometry_m` and
`polygon_m` fields, distances, walking times, Maps links (`tour/mapsLinks.ts`), AR bearings (`ar/geometry.ts`)
and the `stations.py` panorama tooling keep their current inputs and behaviour. Only the new 3D scene applies
the fit, client-side or in the `world` block, so it never changes a number shown elsewhere.

**Platform numbers.** OSM numbers only some islands (`7;8`, `9;10`; 11 and 12 have no ref), and some refs
overlap (`2;3` and `3;4`). *My call:* label a platform with its OSM `ref` where it has one. For platforms 7–12,
which match the traced areas, take the number from the station plan, labelled as "number from the station plan".
Leave other unnumbered OSM platforms unlabelled. Never guess a number. The fit pairs traced platform areas with
OSM polygons by position after a coarse anchor-based placement, not by ref.

**Payload.** `GET /api/stations/{id}/tour` adds a `world` block when the station has `osm.json`: the OSM features
in local metres, the attribution text, the OSM timestamp, and the alignment. All existing fields are unchanged,
so `tourSpec.test.ts` fixtures stay valid. Stations without `osm.json` return no `world` block and keep today's
scene unchanged.

**Scene (frontend, pure spec + renderer, as today).** Extend `buildSceneSpec` (unit-tested, WebGL-free) to emit
world features; `TourScene` draws them:

- ground plane and roads area in neutral tones (no plan image as the floor for stations with a `world` block;
  the 2D plan stays available in the existing blueprint dialog);
- platforms as raised slabs (nominal 0.84 m) with their number labels; tracks as thin rails or dark beds;
  roof sheds as thin raised canopies on posts; the station and suburban terminal outlines as low buildings;
- city buildings extruded to `building:levels × 3.2 m` (or `height`), else a nominal 9 m, in one merged mesh
  with a muted palette, fading with distance;
- the heritage main building: a hand-built low-poly model (maroon walls, white trim, corner towers and the
  central four-faced clock tower at 41 m), placed on its OSM footprint. **Built in Blender** (user: "you can use
  the blender mcp if needed instead of relying entirely on three.js"). Blender 5.2 is installed. The Blender MCP
  server failed to connect in this session (connect timeout), so the builder uses it if it reconnects, and
  otherwise drives Blender headless with a committed Python script (`blender --background --python
  scripts/build_station_model.py`), which is reproducible either way. Export one `.glb`, about 2 MB or less, with
  no Draco: the Draco decoder loads from a CDN by default and the CSP is `'self'`-only. Prefer meshopt or plain
  quantised geometry, decoded locally. Serve it with the station data from the backend and load it with three.js'
  `GLTFLoader` lazily in the tour chunk, within the tour budget. Commit the `.blend` source and the export
  script. If the model fails to load, the scene shows the OSM footprint extruded with the same colours;
- the route: the existing route tube restyled as a glowing path, the pins kept for entrances, platforms and
  facilities, the start/destination labels kept;
- lighting: a warm sun with soft shadows only if the frame budget allows on a mid-range phone; otherwise
  ambient plus directional;
- default camera framed to the station complex bounds for the canvas's aspect ratio (fixes the cropping), with
  the empty band above the scene removed;
- an always-visible attribution chip "© OpenStreetMap contributors" next to the existing schematic chip.

**Honesty labels.** The schematic chip and notices stay, reworded where needed: buildings, platforms and
tracks are "from OpenStreetMap"; the walkways and route are "schematic, traced from a station plan, aligned to
the map approximately (within about N m)", where N is the fit residual; heights are nominal. Strings in English
and Tamil.

**Data facts to respect** (Wikipedia, "Chennai Central railway station", read 2026-10-17):

- Built 1873 to a design by George Harding; modified to Robert Fellowes Chisholm's design, completed 1900;
  Gothic Revival and Romanesque Revival; heritage building; painted maroon since 1873.
- The central clock tower is the tallest tower, has four faces, and is 136 ft (41 m) high.
- 17 bay platforms including five at the suburban terminal; platforms 1–11 average about 600 m.
- Main entrance on Poonamallee High Road; the eastern side opens onto Wall Tax Road; the western entrance leads
  to the suburban terminal (Moore Market Complex, opened 1986).
- The station's official name is Puratchi Thalaivar Dr. M.G. Ramachandran Central.
- **Known data conflict:** the traced node is named "Main Entrance (Wall Tax Road)" while the plan image prints
  "MAIN ENTRANCE (Jawaharlal Nehru Road)" at that spot, and Wikipedia puts the main entrance on Poonamallee
  High Road. Do not silently pick one: check against the OSM entrances and roads after alignment, record what
  was found in the station's `notes`, and rename only with a stated source.

**Street View and Google Maps links** stay as they are: outbound links and Google's own viewer, gated on a key
that is not configured. The "no Google" anti-goal covers the model's geometry and imagery, not these links.
*(My call, after the builder check.)*

### Part C: local AI model through Ollama, as Gemini's fallback

User, 2026-10-17: "use gemma4 if gemini goes out", and use the local gemma4 for testing now. So the chain is
**Gemini → gemma4 (Ollama) → rule-based**:

- `LLM_PROVIDER=gemini` plus a new `LLM_FALLBACK=ollama`: Gemini answers while it is healthy. When Gemini is
  not configured, or fails with a persistent error (`not_configured`, `auth_failed`, `access_denied`), or is
  `throttled`, it is marked out for a cooldown (builder picks it, around 60 s), and turns go to gemma4. A Gemini
  failure in the middle of a turn may retry on gemma4 only if enough deadline remains (builder sets the minimum
  from measured gemma4 latency). Otherwise that turn uses the rule-based answer, as today. `/api/health` reports
  which model is active and why.
- `LLM_PROVIDER=ollama` on its own (no Gemini key, as on this machine today) uses gemma4 directly, with the
  rule-based fallback.
- Each answer's provenance records which model produced it. The UI must not label a gemma4 answer as Gemini.

Details:

- Add `ollama` alongside `gemini` and `bedrock`, with `OLLAMA_URL` (default `http://127.0.0.1:11434`) and
  `OLLAMA_MODEL` (default `gemma4:latest`, 8B, Q4_K_M, supports tools and thinking).
- Provide both seams `container.py` already has:
  - an intent extractor for the planner (`build_llm`, like `BedrockIntentProvider`);
  - a `ChatLLM` for the ticketing agent (`build_chat_llm`, like `GeminiChatLLM`), using Ollama's `/api/chat`
    with tool calls.
- Reuse `Deadline`, `call_with_retries` and `LLMError` classification. Map connection refused and a missing
  model to `NOT_CONFIGURED`, so the app falls back to the rule-based agent and extractor exactly as it does
  today, and `/api/health` reports why.
- Vision and AR localisation stay Gemini-only; `ollama` leaves AR off.
- Dev-only: production refuses `LLM_PROVIDER=ollama` at startup, like demo data.
- `run.py` gains no hard dependency on Ollama. Document `LLM_PROVIDER=ollama` in `backend/.env.example` and the
  README. The existing answer-quality safeguards still apply to a local model: citations only from the
  knowledge base, fenced tool output and allowlisted links.
- **Latency:** generation on a laptop is slow and serial. The existing `llm_overall_deadline_seconds` (20 s)
  bounds every turn, and when it runs out the rule-based fallback answers. Send `think: false` (thinking
  doubles latency for no benefit here). Measure a typical ticketing question and a planner turn end to end and
  report them. If gemma4 routinely misses the deadline, say so rather than raising the deadline silently.
  `llama3.2:3b` (also pulled) is the documented lighter alternative.

**Memory management** (user: "manage the memory"). This machine has 15.8 GB RAM, about 6 GB free with the
usual apps open, and an RTX 5060 laptop GPU. The dev servers were killed for low memory once on 2026-10-17.
gemma4 occupies about 9.6 GB on disk and more when loaded with a context. So:

- Bounded requests: cap `num_ctx` (start at 8192; the model's 131072 default would balloon the KV cache) and
  `num_predict`.
- One model, one request at a time: document `OLLAMA_MAX_LOADED_MODELS=1` and `OLLAMA_NUM_PARALLEL=1` for the
  Ollama server (they are server settings; `run.py` does not start Ollama, so it checks `ollama ps` and warns if
  other models are loaded). The backend serialises its own Ollama calls. Never load `llama3.2:3b` and gemma4
  together.
- Lazy and released: never load the model at startup. Load it on the first turn that needs it (or on an explicit
  `run.py --warm-llm` before a demo, so the first visitor does not wait). Send `keep_alive` (builder picks it,
  around 10 min) so it unloads when idle.
- When Gemini is healthy, gemma4 should not be resident: fallback loads it on demand.
- `run.py` checks free RAM at start (using the standard library or a tiny platform call; no new heavy
  dependency). It warns, with numbers, when less than the model needs is free, and suggests closing apps or using
  `llama3.2:3b`.
- Lighter servers in `--public` mode: no uvicorn `--reload` (it spawns a watcher process). If the measurement
  in Part A favours `vite preview`, that also drops the dev server's memory.
- Verification records the peak RAM and VRAM of backend + frontend + Ollama during a demo run (tour open,
  two chat questions).

### Other stations and fallbacks

- Stations without `osm.json` render exactly as today.
- No WebGL, or a lost context: the existing 2D fallback (`SceneBoundary`) stays.
- Reduced motion: no fly-through, as today.

## Verification

- Unit tests for the OSM conversion (projection, trimming, determinism), the alignment fit (known transform
  recovered within tolerance), the payload's `world` block, and `buildSceneSpec` world features.
- `stations.py validate` passes for every station.
- `npm run build` passes the bundle budget; `npm test`, `npm run typecheck`, `npm run lint`, backend tests and
  the e2e/axe suites pass.
- Screenshots of `#/tour?station=chennai_central` at 320, 390 and 1280 px, on open and mid-fly-through,
  reviewed for: recognisable frontage and clock tower, numbered platforms, sheds, framing, labels, attribution.
- Frame rate checked with a mid-range phone profile (CPU throttling in Playwright/Chrome DevTools).
- `run.py --public` opened from a phone on mobile data: app loads with no certificate warning, `#/tour` works.
  Two phones at once do not share a rate-limit bucket.
- With `LLM_PROVIDER=ollama`: unit tests for the adapters (request shape, tool-call parsing, error mapping) with
  a fake HTTP server, and one manual end-to-end question to the ticketing agent and one to the planner with
  gemma4, with the timings recorded. With Ollama stopped, the app falls back to rule-based answers.
- Docs updated: `docs/STATION_NAVIGATION.md` (tour section, data sources, alignment), README quick start
  (`--public`), and `docs/DEMO_SCENARIOS.md`.

## Left to the builder

- Exact Overpass bounding box, simplification tolerance, and colour palette (match the app's tokens).
- Dev server versus `vite preview` for `--public` (measure, then decide).
- The heritage model's level of detail, within the performance budget.
- Whether shadows are on by default.
- The alignment residual threshold.
