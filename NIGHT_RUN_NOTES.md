# Night run 2026-10-20

Branch: `night-run/2026-10-20`, cut from `feat/real-3d-tour-public-link-local-llm`. Nothing pushed.

## What changed

1. **Snapshot of uncommitted work** (`chore: snapshot uncommitted work before night run`), committed unchanged.
   It is the follow-up to plan Task 11 step 3 (a stopped Ollama should still give a rule-based answer):
   - `container.py`: `_rules_rescue()` wraps any chain that includes the local model in
     `FallbackChatLLM(chain, KeywordChatLLM(), rescue_on=all error kinds, min_seconds=0)`. `chat_llm_status`
     keeps the build-time reason ahead of the runtime one.
   - `llm/fallback.py`: `rescue_on` and `min_seconds` options. `status()` now reports `reason`
     (`primary_<kind>`) and `cooldown_remaining_s`.
   - `intent/extractor.py`: health shows the fallback status. It no longer pauses on its own when the LLM is a
     fallback wrapper, because that wrapper already runs a cooldown.
   - Tests for all of the above. They pass as they were, so no fixes were needed.
2. **`.gitignore`**: added `.impeccable/` and `.playwright-mcp/`.
3. **Backend lint**: ruff F401, an unused `to_local` import in `scripts/stations.py`.
4. **Flaky frontend unit tests fixed.** The full `vitest run` failed 1 to 11 tests, and a different set each
   run. Every failing file passed when run alone. The cause was lazy-loaded screens on a cold module graph
   overrunning Testing Library's default 1 s `findBy`/`waitFor` timeout. `src/test/setup.ts` now sets
   `asyncUtilTimeout: 5000`. One AR test spies on `setTimeout(> 1 s)` to catch the auto re-localise timer, so it
   now skips Testing Library's own timeout (`getConfig().asyncUtilTimeout`).
5. **Accessibility**: the five text fields and selects that use `focus:outline-none` changed only a 1px border
   colour on focus. They now also get `focus:ring-2 focus:ring-brand-600/30` (wayfinder pickers, endpoint
   picker, station navigation, coach position, tour).

## 3D tour review

Tasks 1 to 11 of `docs/superpowers/plans/2026-10-18-real-3d-station-public-link-local-llm.md` were already
committed on the feature branch: the OSM world, alignment, heritage model, scene, copy and measurements. The only
open piece was the uncommitted rules-rescue work above, and it is now committed and green. Build and budget gate
pass. The tour and a11y e2e specs pass.

## How to run / test

```
cd backend;  .venv/Scripts/python -m pytest -q -o addopts=""   # uv-managed venv; ../venv lacks redis
cd frontend; npm run lint; npm run typecheck; npx vitest run; npm run build
cd frontend; npx playwright test        # starts backend (uv) + vite itself
python run.py                            # full app
```

## Verified status (this run)

- Backend pytest: **1345 passed**. ruff clean.
- Frontend: lint ok, typecheck ok, vitest **437/437** (full run twice in a row after the fix), build + budget ok.
- e2e (Playwright, Chromium): tour + a11y **7 passed**; mobile + ar + viewport **20 passed**.

## Left / ideas

- The root `venv/` is stale: no `redis`, so the backend suite fails to import there. Use `backend/.venv`
  (`uv sync`), or delete the root venv to avoid confusion.
- Starlette warns that `httpx` in TestClient is deprecated (wants `httpx2`). Harmless for now.
- The plan's manual steps were not re-done here: the phone check over `--public` and the Ollama-stopped check.
- Merge the feature branch to main once it has had a human look.
