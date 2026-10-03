# ADR-0014: Find people by when you last interacted (filter, sort and time phrases)

- **Status:** Accepted (2026-10-03)
- **Date:** 2026-10-03
- **Deciders:** Bryan Madsen
- **Requirements affected:** S-09 and S-10 added (Phase 5)

## Context

Searching "who have I interacted with recently" found no one, although a contact
had a message logged that week. Search by meaning (S-08, ADR-0013) compares the
meaning of words; it has no notion of dates, so "recently" carries no signal
(similarity ≈ 0.12, far below the 0.40 floor). The activity log (C-13) already
records the date and kind of every interaction, and cards show "last contact",
but neither could be searched or sorted.

## Options considered

1. **A filter and a sort only** — predictable and combinable, but the question
   as typed still finds no one.
2. **Time phrases in the search box only** — answers the question, but hides the
   capability; nothing to click.
3. **Both (chosen)** — a filter, a sort and a column for everyday use, and the
   search box understands common time phrases and turns them into the same
   filter, shown as a removable chip.
4. **Let a language model interpret the query** — rejected: heavier, slower,
   less predictable, and the phrases people use for time are a small, known set.

## Decision

1. **What counts as an interaction:** an activity of kind meeting, call, email or
   message. Notes are not interactions (consistent with "last contact", C-13).
2. **S-09 filter, sort, column.** A **Contacted** filter (any time, last 7, 30, 90
   or 365 days) combines with the other filters; a **Last contact** column shows
   each result's latest interaction date and sorts by it (newest first, people
   never contacted last). The filter is a URL parameter (`contacted=30`), so it
   can be saved in a saved search and stays relative ("last 30 days" moves
   with time). The JSON search API accepts the same `contacted` parameter.
3. **S-10 time phrases.** The search box recognises, case-insensitively:
   `today`, `yesterday`; `this/last week` (weeks start Monday), `this/last
   month`, `this/last quarter`, `this/last year` (calendar periods); `past
   week/month/year` and `in the last/past N days/weeks/months/years` (rolling);
   `recently` and `lately` (= last 30 days); `in <month> [year]` and `during
   <month>` (a future month means last year's); `since <month> [day] [year]` and
   `since YYYY-MM-DD`. Only the first phrase is used.
4. **Kinds from verbs.** With a time phrase present, `met`/`meeting(s)`,
   `called`/`phoned`, `emailed`, `messaged`/`texted` narrow the activity kind
   ("who did I meet last week" → meetings only).
5. **The rest of the query.** Filler words (who, I, have, did, talked, spoke,
   interacted, with, to, about, people, …) are dropped; any remaining words are
   searched as usual (keywords and meaning) within the people who had an
   interaction in that period. With no remaining words, the results are
   everyone with an interaction in the period, most recent first.
6. **Showing why.** While a time filter is active, each result shows its latest
   interaction in that period ("Message · Oct 2: Sent the Q4 schedule"). A chip
   such as "Interacted: recently (last 30 days)" names the period; removing it
   searches the remaining words without the time limit.

## Consequences

- "Who have I interacted with recently", "who did I meet last week" and "who did
  I talk to about contracts in September" work as typed.
- Phrases outside the list are not understood; the words are then searched as
  text (no worse than before). New phrases are easy to add to `app/timephrase.py`.
- Dates use the computer's local date.

## Requirements changes

| ID | Change | Old text (if changed) |
| --- | --- | --- |
| S-09 | Added (Should, Phase 5): filter by recent interaction and sort by last contact. | — |
| S-10 | Added (Could, Phase 5): time phrases in the search box. | — |
