# Demo scenarios

Development and staging only. These run on the bundled demo dataset, which the service refuses when
`APP_ENV=production`.

Start both servers with demo data (`RAILWAY_DATA_MODE=demo`; `python run.py` uses live NTES data unless you set
it, see the README) and open the app. "Tomorrow" is computed in Asia/Kolkata time, and all trains are fictional
demo services. The scenarios run automatically in `backend/tests/test_harness.py`; the mobile flow (plan, options,
details, confirm) runs in `frontend/e2e/mobile.spec.ts`.

To demo on phones that are not on your Wi-Fi, run `python run.py --public` (needs cloudflared, see the README) and
share the printed link or QR code. With a local model as the fallback, run `python run.py --warm-llm` a few minutes
before the demo so the first answer is not slow, and close other apps (about 10 GB of free RAM is needed).

Type each request in the AI planner (*Plan Your Journey* on the home screen).

| # | Type in the chat | Expected |
|---|---|---|
| A | `I need to reach Chennai before 9 AM tomorrow.` → `Coimbatore` → `2` | Asks only for the origin, then the passenger count. Then shows options: D103 (best + cheapest) and D101 (fastest), with explanations. |
| B | `Find the cheapest option from Coimbatore to Chennai, but I must reach before 9 AM tomorrow. 2 passengers` | Lowest-cost card is D103 (₹590). A note explains that the cheaper D105 (₹540) is excluded because it arrives at 09:40. |
| C | `I am travelling with my mother, and she needs assistance.` → `from Madurai to Chennai tomorrow before 9 am` | 2 passengers inferred; assistance need kept; cards say "availability at Chennai Egmore has not been verified"; nothing claims assistance is booked. |
| D | After A, `Change my destination to Bengaluru.` | "Updated: destination." Origin, date, deadline and passengers are kept; options are recalculated for Bengaluru. |
| E | After B: open D103 → *Confirm* → on the confirmation screen tap *Check live status* | The simulated "D103 running 2 h 30 min late" event is applied, labelled SIMULATED. D103 now arrives at 09:15 and no longer qualifies. The re-ranked options are shown, the original confirmation stays on record, and a new confirmation is required. |
| F | Switch the language to தமிழ் on the home screen, then type `நாளை காலை 9 மணிக்குள் கோவையிலிருந்து சென்னைக்கு, அம்மா உடன்` | The greeting and the replies are in Tamil; options shown. Switching back to English keeps the state. In Chrome/Edge, the mic fills the text box for review and never auto-sends. |
| G | `from Coimbatore to Chennai tomorrow, must reach before 4 am, 1 passenger` | "No option in the current data…", with the reason and a relax suggestion on the options screen (or type `remove the deadline`). After relaxing, options appear. |

More things to try:

- `to Coimbatur` → asks "Did you mean 1) Coimbatore…"; reply `1`.
- `from Ooty to Chennai` → "not in the station list" plus the list of places.
- `I want a window seat` → "This planner can't handle: seat selection".
- `maximum 1200 rupees, direct trains only, AC 3 tier` → strict budget, class and direct filters.
- `confirm` before selecting anything → polite refusal; the state is unchanged.
