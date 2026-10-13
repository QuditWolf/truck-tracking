# paddy2026 — Design

Fleet event reporting for the paddy harvest. Successor to `02_truck_fleet` (2026 wheat season).

## Principles

- **Web form is the source of truth.** Structured input → deterministic event. No LLM on this path.
- **WhatsApp is a mirror.** Web events are relayed to the fleet + control groups. Free-text WA
  messages are parsed (LLM, phase 3) into the *same* report shape.
- **One rule for free text:** complete (truck + verb + site resolved) → commit + echo.
  Incomplete/ambiguous → ask in the control group. No confidence thresholds.
- **Never invent events.** Gaps, duplicates and odd orderings are flagged and *explained*; counts
  that rely on inference are shown separately (`Loaded 14 (2 inf)`) with a one-line reason each.
- **Everything recomputed on read.** Trips, flags, counts and shift membership are derived from
  the event list every time. Edits, deletes, backdating and shift changes need no repair logic.
- **Everything audited.** Every create / edit / delete / merge / setting change writes before/after.
- **All times IST**, minute precision for events and shifts.
- **Bot text is compact, no emojis.**

## Data model

```
users          google identity + name + phone. Admin = email in ADMIN_EMAILS. Anyone may sign up.
registry       ONE table for trucks, sites, verbs (kind, code, label, site_type, merged_into, active)
reports        one submission: verb, site, event_time, remarks, user, source (web|wa), deleted
report_trucks  report ↔ trucks (multi-truck: "A,B LS KN4")
shifts         started_at, ended_at, default_site
audit          who, when, action, before, after
outbox         pending WhatsApp sends (phase 2 drains it)
settings       fleet_mode, summary_interval_min, shift_stale_hours
```

### Aliases, merge, delete (trucks + sites only)

- An alias is a registry row with `merged_into` → canonical row. Creating an alias = creating a row
  born merged. Merging two entries = setting the pointer. Unmerge = clearing it.
- Reports store the id *as reported*; reads resolve through the pointer. Renames, merges and
  unmerges never touch report rows, so nothing is ever orphaned and every step is reversible.
- Delete: hard delete only when nothing references the row; otherwise deactivate (hidden from
  dropdowns, no longer matches new input, still resolves for history).
- Unknown values typed on the web become new entries (admin sets the site type / merges later).
  Unknown values in WhatsApp text → bot asks in the control group: alias of X, or new?

## Trip engine (`backend/app/trips.py`)

Each cycle verb maps to a slot (ENTER/LEFT side decided by site type, guessed if unknown):

```
0 ENTER@L  1 LS  2 LO  3 LEFT@L  4 ENTER@U  5 US  6 UO  7 LEFT@U
```

Per truck, per shift, events in time order:

- slot already filled in the current trip within 20 min → **duplicate** (shown, not counted)
- slot ≤ last slot of current trip                     → **new trip** (previous one closes)
- otherwise                                            → same trip; skipped slots are inferred

Only LS / LO / US / UO gaps are flagged (ENTER/LEFT are optional in practice).

Counting per trip:

| | reported | inferred when |
|---|---|---|
| loaded | LO | any unloading-phase slot; or LS and the trip closed (next trip / shift end); or trip starts at unloading with no carried load |
| reached | — | any slot ≥ ENTER@U |
| unloaded | UO | LEFT@U; or US and trip closed; or loaded and the truck started a new trip |

Load attributed to the shift + loading site where it happened; unload likewise.

### Shifts

- Membership by time: event in `[start, end)`. Never stored on events.
- One open shift. Starting a new one ends the open one at the new start. No overlaps (rejected).
- Trips are cut at shift end. A loaded-not-unloaded truck carries into the next shift: its first
  trip there counts the unload but not the load again.
- Events outside any shift are flagged; the web form warns before sending.
- Shift open longer than `shift_stale_hours` → warning (not auto-closed).

## Summaries

- WhatsApp (compact): loaded per site, reached, unloaded per site, truck positions, inferred notes.
- Web Summary tab: shift / day / season; counts, per-site, per-truck trips + durations
  (loading, haul, unloading, cycle), inferred notes, flags, trip timelines.
- Sent: every N min during an open shift, on demand, at shift end; day/season on the web.

## WhatsApp (phase 2)

Baileys runs in the same container as the API (second process, session on the /data volume).

```
A,B LS KN4 14:32 Ravi
- wet paddy, slow

edit (reply to original):  A,B ~LS~ LO KN4 14:32 Ravi
delete (reply):            ~A,B LS KN4 14:32 Ravi~ deleted
```

Modes (admin setting, no redeploy):

- `silent` — fleet group gets relays only; confirmations, questions, summaries → control group
- `full`   — confirmations and summaries also go to the fleet group

## Phases

1. Backend + Svelte PWA — **done**
2. Baileys relay (outbox → both groups, edit/delete replies, periodic + end-of-shift summaries,
   control-group commands: shift start/end, summary)
3. LLM parse of free-text WA messages (OpenAI-compatible endpoint), same report shape
4. Flutter app on the same API
