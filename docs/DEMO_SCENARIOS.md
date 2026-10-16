# Demo scenarios

Development and staging only. These run on the bundled demo dataset, which the service refuses when
`APP_ENV=production`.

Start both servers (see the README) and open http://localhost:5173. "Tomorrow"
is computed in Asia/Kolkata time, and all trains are fictional demo services.
These scenarios also run automatically in `backend/tests/test_harness.py` and
`frontend/e2e/planner.spec.ts`.

| # | Type in the chat | Expected |
|---|---|---|
| A | `I need to reach Chennai before 9 AM tomorrow.` → `Coimbatore` → `2` | Asks only for the origin, then the passenger count. Then shows options: D103 (best + cheapest) and D101 (fastest), with explanations. |
| B | `Find the cheapest option from Coimbatore to Chennai, but I must reach before 9 AM tomorrow. 2 passengers` | Lowest-cost card is D103 (₹590). A note explains that the cheaper D105 (₹540) is excluded because it arrives at 09:40. |
| C | `I am travelling with my mother, and she needs assistance.` → `from Madurai to Chennai tomorrow before 9 am` | 2 passengers inferred; assistance need kept; cards say "availability at Chennai Egmore has not been verified"; nothing claims assistance is booked. |
| D | After A, `Change my destination to Bengaluru.` | "Updated: destination." Origin, date, deadline and passengers are kept; options are recalculated for Bengaluru. |
| E | After B: select D103 → confirm → in *Disruption check* pick "D103 running 2 h 30 min late" → *Reassess* | Labelled SIMULATED. D103 now arrives at 09:15 and no longer qualifies. Alternatives are shown, the original confirmation stays on record, and a new confirmation is required. |
| F | Switch *Language* to தமிழ், type `நாளை காலை 9 மணிக்குள் கோவையிலிருந்து சென்னைக்கு, அம்மா உடன்` | Tamil replies; options shown. Switching back to English keeps the state. In Chrome/Edge, the mic fills the text box for review and never auto-sends. |
| G | `from Coimbatore to Chennai tomorrow, must reach before 4 am, 1 passenger` | "No option in the current data…", with the reason and a *Relax* button (or type `remove the deadline`). After relaxing, options appear. |

More things to try:

- `to Coimbatur` → asks "Did you mean 1) Coimbatore…"; reply `1`.
- `from Ooty to Chennai` → "not in the station list" plus the list of places.
- `I want a window seat` → "This planner can't handle: seat selection".
- `maximum 1200 rupees, direct trains only, AC 3 tier` → strict budget, class and direct filters.
- `confirm` before selecting anything → polite refusal; the state is unchanged.
