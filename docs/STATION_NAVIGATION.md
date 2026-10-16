# Station navigation

Indoor wayfinding at four stations. It has five parts:

- a station map with step-by-step routes;
- an accessibility preference;
- current and what-if closures;
- an optional camera (AR) mode;
- a 3D virtual tour.

This page describes what the mobile app does, which API it uses, and where the data stops being trustworthy.

**Design credit:** the station navigation screen, like the rest of the mobile UI, is the design of the team lead,
PaulShervin (`origin/worktree-station-navigation-ui`, commit `d44f49b`). It was ported by hand onto RailSaathi's
API client and contracts. That branch's separate backend navigation module, its admin station editor,
`/api/admin/status` and its stored public disruptions were **not** integrated, and none of them exist in this
release.

## The stations

| Station | `station_id` | Code | Routing | AR | Layout |
|---|---|---|---|---|---|
| MGR Chennai Central | `chennai_central` | MAS | **Yes** | Opted in; off in production (see [AR_GUIDANCE.md](AR_GUIDANCE.md)) | Schematic, traced from a plan image of platforms 7 to 12 and the main concourse |
| Chennai Egmore | `chennai_egmore` | MS | No (`routing_unavailable`) | No | Generic schematic, not traced |
| KSR Bengaluru City Junction | `ksr_bengaluru` | SBC | No | No | Generic schematic, not traced |
| Hyderabad Deccan (Nampally) | `hyderabad_deccan` | HYB | No | No | Generic schematic, not traced |

**Every layout is schematic: not surveyed and not to scale.** The responses say so in
`provenance.note` and `layout_basis`, and the app shows a "Schematic layout" notice on every station.

- **Chennai Central** is the only station whose graph was traced from a source, so it is the only one that gives
  routes.
- **The other three** serve their plan image, station facts, amenities and national helplines, with no pickers
  and no route. A route request there gets 503 `routing_unavailable`.

**Step-free status is `unknown` on every pathway.** No pathway has been verified on site. A request with
`require_verified_accessibility: true` therefore excludes every pathway and returns `no_route`.
`avoid_stairs` avoids pathways recorded as stairs or with steps. `wheelchair` also avoids escalators. Their
routes report `accessibility_confidence: "unverified"`, because a pathway without recorded steps is not proof that
it is step-free. Helplines are national numbers only (for example 139 Rail Madad and
112), each with its source.

## The screen (`#/navigation`)

`frontend/src/mobile/screens/StationNavigation.tsx`, with its parts in `mobile/screens/navigation/` and the data
hook `src/navigation/useStationNav.ts`.

| Part | What it does | API |
|---|---|---|
| Station choice | Matches the journey's boarding station (then the last leg's arrival station) to `station_code` in the station list. With a journey but no match, it says RailSaathi has no floor plan for that station. With no journey, it shows the first station, and the picker always overrides | `GET /api/stations` |
| Banner and notice | The station name and the schematic notice with a provenance badge. The banner photo is shown only for Chennai Central, the station it depicts | `GET /api/stations/{id}`, `GET /api/stations/{id}/info` (`layout_note`) |
| From / To picker, swap, preferences | Picks any two nodes. The preference chips (avoid stairs, wheelchair, verified accessibility only) re-route automatically. Each request can be cancelled, and a late answer never overwrites a newer one | `POST /api/navigation/route` |
| Map and Steps tabs | An SVG route over the plan image with zoom. The step list comes from the route's `instructions[]`, with distances (`distance_basis`), step-free labels and warnings. Distances and times are estimates from the map scale | `GET /api/stations/{id}/map` |
| Summary tiles, Along the way, Go here | Distance, time and accessibility confidence. Facilities passed on the route, each of which can become the new destination | (route response) |
| No route | The reason, the blocking pathways and chips to relax a preference | (route response) |
| Active closures | Closures stored by operators, listed and drawn on the map. Routes avoid them (`apply_disruptions`). If the store is down, a notice says closures may not be reflected | `GET /api/disruptions/{id}` |
| Closure simulator | "What if this pathway were closed?" It closes a pathway of the shown route for **this request only** (`simulate_closures` plus `previous_edge_ids`, so the answer can explain the re-route) and shows the old route dashed. **Nothing is stored.** It appears only when `GET /api/client-config` returns `features.simulate_closures: true`, which is the same flag the backend uses to answer 403 `simulation_disabled`. Off in production. Labelled "simulated" in English and Tamil | `POST /api/navigation/route` |
| Camera (AR) tab | Offered only when the station is in `features.ar_guidance_stations` and the device has a camera and a secure context | `POST /api/navigation/localize` |
| Coach position | Where your coach stops, **only from a composition you enter**. There is no live rake data, so without one the answer is "unknown" | `GET /api/trains/rake-position` |
| Blueprint and tour links | The plan image in a dialog, and the 3D tour (`#/tour?station=…`) | `GET /api/stations/{id}/tour` |

Every string is in English and Tamil (`mobile/strings.ts`, checked by a completeness test). The Tamil strings are
awaiting review by a native speaker.

## Closures (station disruptions)

There are two kinds of closure:

- **Stored closures** are written only through the OIDC-protected internal endpoints
  (`POST/DELETE /internal/stations/{station_id}/disruptions`, see [API.md](API.md)). They live in Redis with a TTL
  (`DISRUPTION_TTL_SECONDS`, default 6 h). In production, `simulated: true` closures are refused. Nothing in the
  public API can write one.
- **What-if closures** (`simulate_closures`) affect one route request and are never stored. They are allowed only
  when `PUBLIC_DISRUPTION_SIMULATION=true` and `APP_ENV` is not `production`.

## The 3D virtual tour (`#/tour`)

A schematic three.js model built from `GET /api/stations/{id}/tour`: levels, areas, nodes and edges in metres from
the plan scale. It has a route fly-through.

Street View panoramas appear only where nodes have them **and** a Maps browser key is configured
(`GOOGLE_MAPS_BROWSER_KEY`, optional). Without the key, the tour links out to Google Maps. **No panoramas are
authored yet.** The owner finds them with `uv run python scripts/stations.py panoramas chennai_central`, which needs a
server-side Maps key with the Street View Static API in `GOOGLE_MAPS_API_KEY` (or the variable named by `--key-env`). Street View under the production Content-Security-Policy has not been tested yet, because there is no Maps
key.

## Authoring stations

Stations are authored and published with a CLI. The service never writes station data.

```bash
cd backend
uv run python scripts/stations.py validate                      # every station: connectivity, edges, exits, image bounds
uv run python scripts/stations.py preview chennai_central --from ent_wall_tax --to platform_9 --step-free
uv run python scripts/stations.py catalogue                     # rewrite catalogue.json from the station folders
uv run python scripts/stations.py publish chennai_central --dest gs://<bucket>/stations   # versioned folder
uv run python scripts/stations.py --help
```

At runtime, `STATIONS_URI` (a local directory, or `gs://bucket/prefix`) is read once at startup. Production must
set it to the published `gs://` location, or it serves the stations baked into the image. A station that fails
validation is skipped and reported under `/readyz` `degraded`.

## Making a station routable

Routing is enabled only for layouts traced from a real plan or a survey (`"routing": true` in `metadata.json`; a
missing field means no routing). To enable another station:

1. Trace its graph from a source.
2. Record `layout_basis` and the source in `info.json` and `metadata.json`.
3. Run `validate` and publish.

Mark a pathway's `step_free` as verified only after an on-site check, and record who checked it and when.
