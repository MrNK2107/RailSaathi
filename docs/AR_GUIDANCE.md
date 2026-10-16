# AR guidance: model card

Real-time camera guidance inside MGR Chennai Central. This page covers how it works, what it sends where, what it cannot do, how it is evaluated, and the gate that has to pass before it is switched on in production.

**Status:** accuracy and latency are **not yet measured**. Until the evaluation below has been run and passes the gate, AR guidance must stay off in production and runs only in dev and staging.

## What it does

In the station wayfinder (Station Navigation → **Camera (AR)** tab), a passenger who has already picked a route points the phone's rear camera ahead. The app estimates where they are and which way they face, then shows:

- an arrow towards the next waypoint of their route;
- the next step's text, taken from the route API's `instructions[]`;
- the distance to the next waypoint, always marked as approximate.

The tab is offered only when all of these are true:

- the station is traced for routing (`routing_enabled`);
- `/api/client-config` lists it in `features.ar_guidance_stations`, which requires the station data's `ar_enabled`, the `AR_GUIDANCE_ENABLED` flag and a configured vision model;
- the page is a secure context;
- the device has a camera.

When the station data opts in (`features.ar_capable_stations`) but the flag or the vision model is missing, the tab
is shown disabled with the reason instead of being hidden. This is a discovery hint only: the localise endpoint keeps
its own gate, and production keeps AR off until the gate below passes.

Today only Chennai Central opts in.

## Method

### Localisation (server, `POST /api/navigation/localize`)

1. The app sends one still frame: the longest side is at most 768 px, it is JPEG, and it is at most 1.5 MB. Two priors go with it: the last fixed node and the node ids of the route being followed.
2. `GeminiVisionLocalizer` (Vertex AI, `GEMINI_MODEL`, temperature 0) receives the frame and a prompt. The prompt lists every mapped node of the station with its expected cues (signboard texts and features, from `station.json`).
3. Structured output constrains `node_id` and the candidates to an enum of the station's node ids, so the model cannot name a place that does not exist. It returns:
   - `node_id`;
   - `confidence`;
   - `facing_bearing_deg`: degrees clockwise from plan-up, in the station frame;
   - `matched_cues`;
   - up to 3 candidates.
4. `guard_result` drops unknown nodes and any cue text that is not in the station data, then clamps the numbers.
5. The answer is one of three:
   - confidence of at least `LOCALIZE_CONFIDENCE_THRESHOLD` (0.6) is a **fix**;
   - a lower confidence is **low_confidence**, with candidates;
   - an outage, a timeout or unusable output is **unavailable**. It is never a 500.

### Guidance (client, `frontend/src/ar/`)

- **Arrow bearing:**
  - *target*: the first heading of the route segment that leaves the fixed node, in plan pixels so a non-square plan does not skew it.
  - *facing*: the `facing_bearing_deg` at the fix.
  - *turn*: the phone's clockwise yaw change since the frame was taken.
  - **arrow = target − facing − turn.**
  - Target and facing are both station-frame bearings. The `geo_reference.rotation_deg` that would turn them into true bearings therefore cancels, and no true-north heading is ever needed.
- **Turn:**
  - It comes from the gyroscope through relative `deviceorientation` events: the rear-camera heading from alpha, beta and gamma, and only its change since the fix.
  - It wraps correctly (359° → 1° is +2°).
  - The magnetometer is never used: no `deviceorientationabsolute` and no `webkitCompassHeading`. Steel station roofs distort magnetic headings.
  - On iOS, motion permission is requested from the "Start camera" tap.
  - Without motion data, the arrow updates only after each fix, and the screen says so.
- **Off route:** the arrow points back to the nearest node of the route.
- **At the destination:** the app shows an arrival message.
- **Low confidence:** "Are you near…?" lists the candidates. The user's pick becomes the fix, but a pick has no facing bearing, so the app asks for a rescan before it shows an arrow.
- **Re-localisation:** automatic while guiding, on a "Scan again" tap, or after a turn of 60° or more. The client keeps within the server's budget of 20 fixes per session per 10 minutes (`frontend/src/ar/budget.ts`). That per-session budget is a courtesy limit, not a cost control: a caller that omits the session token gets a new session, and a fresh budget, on every call, so only the 120-per-IP tier binds it:
  - It keeps a sliding window of its own sends.
  - Automatic sends never use the last 4 slots, which are kept for taps and picks.
  - Automatic sends come at most every 8 s while at least 8 automatic slots are left, and are then paced across the rest of the window.
  - A 429 blocks every send until `Retry-After`.
  - Failures back off exponentially: 8 s, 16 s, 32 s and so on, up to 120 s.
  - Sustained, this is about one fix every 30 s. The 8 s cadence holds only for roughly the first minute of a walk.
- **WebXR (progressive enhancement):** when `navigator.xr.isSessionSupported('immersive-ar')` is true (Android Chrome), "Show the arrow on the floor" starts an immersive session with hit-test.
  - `dom-overlay` is a required feature, so the safety banner, the "Approximate" copy and the exit control stay visible over the immersive view. If the browser does not grant it, the session is ended at once and the camera overlay stays.
  - The arrow lies on the floor and is held in place by the device's 6DoF tracking.
  - WebXR gives no camera frames without raw-camera-access, so floor mode uses the last fix. Leaving floor mode resumes re-localisation.
  - The camera overlay is the default path. It also covers iOS.

## Privacy

- **Frames go to one place:** each frame is encoded in memory and sent once, only to `/api/navigation/localize`.
  - The app never writes it to localStorage, sessionStorage, IndexedDB or the Cache API, and never logs it. The canvas is cleared after encoding.
  - The backend keeps it in memory for the model call only (`del data` after the call). It never spools it to disk, logs it or stores it. The only thing logged is the status, the node id, the confidence and the latency.
- **Third party:** frames are processed by Google Vertex AI (Gemini) under the project's Google Cloud terms. The consent sheet says so before the camera opens. Declining returns to the text steps.
- **Bystanders:** passengers are asked not to point the camera at people. The model is asked only for a place, and the response schema has no free-text field that could describe a person.
- **Evaluation photos:** the about 40 labelled photos for the evaluation are kept in a private Cloud Storage bucket with faces blurred. They are never committed to git; `scripts/eval_localize.py` refuses an image set inside the repository.

## Limits

- **Schematic layout:**
  - The station plan is schematic: traced from a plan, not surveyed and not to scale. Positions are mapped nodes, not coordinates, and the arrow points along schematic geometry.
  - Every AR screen shows "Approximate — confirm with station signs" and the safety banner "Watch your step, look up at platform edges and stairs."
- **Cues:** they are the signage *expected* at each node, collected from published references, and not verified on site. Renamed, moved or covered signs reduce accuracy.
- **Conditions that defeat it:** crowds, glare, night lighting, a camera pointed at the floor and featureless corridors all lead to low confidence. The app then asks the user to pick a candidate or point at a sign.
- **Facing bearing:** it is the model's estimate from the view. It is coarser than a compass and can be wrong even when the node is right.
- **Gyroscope drift:** between fixes the arrow can drift a few degrees per minute. Re-localisation corrects it.
- **Levels:** levels are not distinguished visually beyond the cues. A fix on the wrong level is possible where levels look alike.
- **Re-localisation rate:** the backend budget limits it, as described above.
- **Coverage:** only Chennai Central has the data (`ar_enabled`, cues). Other stations can opt in later by authoring cues.

## Evaluation

`backend/scripts/eval_localize.py` runs a labelled image set through the same localizer, guard and threshold the API uses. Each image is first prepared the way the app sends it: longest side 768 px, JPEG.

**Manifest:** a JSON list, or JSON Lines, of `{"image": "<path relative to the manifest>", "true_node_id": "<node id>"}`.

**Running it:**

```
# copy the private set locally, outside the repository
gsutil -m cp -r gs://<private-bucket>/ar-eval/chennai_central /tmp/ar-eval
cd backend
LLM_PROVIDER=gemini GOOGLE_CLOUD_PROJECT=<project> uv run python scripts/eval_localize.py \
  --manifest /tmp/ar-eval/manifest.json --station chennai_central \
  --usd-per-mtok-input <current input price> --usd-per-mtok-output <current output price> \
  --out /tmp/ar-eval/results.json
```

`--dry-run` checks the wiring without credentials: a mock echoes the true node. Its numbers mean nothing, and its gate is always `not_applicable`.

**Reported metrics:**

- **Top-1 accuracy:** the predicted node is the true node, over all photos. An `unavailable` answer counts as wrong.
- **Accuracy at the threshold:** the same, over accepted fixes only, plus coverage (accepted fixes divided by all photos).
- **Latency p50 and p95:** of the localizer call (nearest rank). The upload time from the phone is not included.
- **Cost per fix:** from the token counts Gemini reports and the prices passed in. Every call is paid for, so the cost of rejected answers is spread over the accepted fixes.

### Results

| Metric | Value |
|---|---|
| Photos | not yet measured |
| Top-1 accuracy | not yet measured |
| Accuracy at threshold 0.6 | not yet measured |
| Coverage (accepted fixes) | not yet measured |
| Latency p50 / p95 | not yet measured |
| Cost per fix | not yet measured |
| Gate | not yet run |

Model, date and set version: to be filled in when the owner runs the evaluation. Paste the table the script prints.

## Production gate

`AR_GUIDANCE_ENABLED` may include `chennai_central` in production only when all of these hold:

- **Accuracy at the threshold** is at least **80 %**, measured on fixes the localiser accepts.
- **p95 latency** is **under 4 s**.
- The set has **at least 30 photos**. About 40 are planned, spread over the station's nodes.
- At least **20 accepted fixes**, so accuracy is not judged on a handful of answers.
- **Coverage** (accepted fixes divided by all photos) of at least **50 %**. A localiser that rarely commits does not guide anyone, however accurate its few fixes are.
- The verdict is judged only at the **production threshold** (`LOCALIZE_CONFIDENCE_THRESHOLD`, 0.6). A run with `--threshold` set to any other value reports the gate as `not_applicable`.

Until then:

- The flag stays unset in production, where unset means off.
- AR runs only in dev and staging, where unset means `*`.
- The virtual tour has no gate.

Re-run the evaluation, and update this page, whenever the model, the prompt, the threshold or the station's cues change.

## What has been tested, and what needs a device

**Unit tests (vitest):**

- bearing and yaw maths, including wrap-around;
- the arrow formula, and the rotation cancelling out;
- the guidance target (on route, off route, arrived);
- frame sizing;
- the budget and back-off, including a simulated hour that never exceeds the server limit;
- every transition of the state machine: denial, low confidence, unavailable, 429 and 404.

**Component tests (mocked camera):**

- the consent and safety copy;
- the arrow;
- gyro turns;
- early re-localisation after a large turn;
- the candidate pick;
- the fallbacks;
- keyboard exit;
- no storage writes.

**Playwright (Chromium fake camera):**

- the full flow with a mocked `/localize`;
- the real backend parsing the browser's multipart frame.

**Not testable without a real phone in the station:**

- localisation accuracy, which is what the evaluation measures;
- gyroscope behaviour on real hardware;
- the iOS motion-permission prompt;
- WebXR floor arrows: the hit-test and the arrow's placement and orientation;
- camera behaviour in low light.
