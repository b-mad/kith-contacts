# ADR-0016: Add keep-in-touch reminders and a presenting mode that withholds private details

- **Status:** Accepted (2026-10-03)
- **Date:** 2026-10-03
- **Deciders:** Bryan Madsen
- **Requirements affected:** C-15, C-16, C-17, S-11, P-01–P-07 added (Phase 7)

## Context

**Keep in touch.** §2 lists keep-in-touch reminders (Dex) as future work. Since
S-09 (ADR-0014) the activity log gives every contact a reliable last-contact
date, so reminders can be computed rather than maintained by hand.

**Presenting.** The app is used while sharing a screen in meetings. Cards and
results show notes, activity summaries, personal emails and phones, and tags or
lists the user would not want an audience to see (for example a confidential
"flight-risk" tag). Customer and vendor personal data on screen is also a
privacy exposure (§10). Products handle this two ways: blurring (Follow Up Boss
blurs phones and emails) or withholding (Metronome shows only public items;
Discord's Streamer Mode replaces identifiers and shows an on-screen bar).
Blurred text is still in the page — copy, find-in-page, zoom, screen readers
and a momentary unblur expose it. This app renders pages on the server
(ADR-0004, ADR-0008), so it can withhold values instead.

Mockups and the reviewed decisions: "Contact Manager UI Refresh" canvas
(Presenting mode, Settings › Privacy and presenting, Reconnect) and the
implementation plan (2026-10-03).

## Options considered

1. **Reminder cadence** — per list/tag with inheritance (flexible, harder to
   reason about) vs **per contact with a bulk action (chosen)**.
2. **Reminder delivery** — OS or email notifications (need a background
   process or third-party service, conflicts with N-04) vs **in-app only
   (chosen)**: a Reconnect page and a nav count.
3. **Presenting: remove or blur** — **remove on the server (chosen)**.
4. **Presenting scope** — per instance vs **every instance in the browser
   (chosen)**: one session cookie on `localhost` covers all ports, so switching
   tabs mid-meeting is safe.
5. **What is shown** — blocklist of private fields vs **allowlist of public
   fields (chosen)**: a field added later stays hidden until made public.

## Decision

### Keep-in-touch reminders (C-15, C-16, C-17, S-11)

1. A contact has an optional cadence: 2 weeks, 1 month, 3 months, 6 months or
   1 year (`contact.kit_interval`; null = off). Months are calendar months,
   clamped to the month's last day (Jan 31 + 1 month = Feb 28/29).
2. Due date = last interaction (meeting, call, email or message; notes don't
   count, as S-09) + cadence. With no interaction, the clock starts on the day
   the cadence was set (`kit_started_on`). The due date is computed in SQL, not
   stored.
3. Snooze moves only the current reminder to a date (`kit_snoozed_until`);
   logging an interaction clears it.
4. A **Reconnect** page lists overdue contacts (most overdue first), then those
   due within 7 days, each with Email, Log and Snooze. The nav shows the count;
   People gains a "Due to reconnect" filter; the card shows cadence and next
   date. "Keep in touch…" in the selection action bar sets a cadence for many.
5. After Email, Call or Compose from the app, a one-click prompt offers to log
   that interaction (C-17).
6. No notifications, emails or calendar entries (N-04).

### Presenting mode (P-01–P-07)

1. Turned on and off by a header button and ⇧P (outside text fields). A session
   cookie `cm_presenting` (Path=/, SameSite=Strict, HttpOnly; set and cleared
   by `POST /presenting`) applies to every instance in the browser.
   While on, a full-width bar says so and offers Stop presenting. It turns off
   when the browser closes by default; Settings also offers "after 2 hours" and
   "only when I turn it off".
2. `app/privacy.py` builds a presentable view of each contact from an allowlist
   of public fields; templates and fragments never receive private values.
   Hidden by default: notes; activity summaries (kind and date stay); emails
   and phones whose label is personal, home or mobile (labels configurable);
   extra fields marked private; private tags, lists and contacts.
3. Hidden items show a "hidden while presenting" placeholder by default;
   "leave no trace" is a setting. There is no peek: stop presenting to look.
4. Search still matches hidden fields but never quotes them ("Matched in
   Notes"); search by meaning drops its "why" text when the source is private.
   Private contacts are left out, with a count.
5. Copy emails and Compose use work addresses only and say how many were left out.
6. Import preview, duplicate merge, backup restore and exports show "Not
   available while presenting"; the JSON API applies the same redaction.
7. Per instance, presenting shows work details (default), names and companies
   only, or a lock screen (suggested for personal-prod).
8. New columns `is_private` on `contact`, `tag`, `contact_list` and
   `custom_field`; other settings in `app_setting` (ADR-0015).

## Consequences

- A canary test seeds a marker string into every private field, renders every
  GET page and fragment with presenting on, and fails if the marker appears.
- Every new template or field must go through the presentable view; the canary
  test catches misses.
- Reminders appear only when the app is open; an OS-level reminder would need a
  new ADR.
- Phase 7 depends on Phase 6 (`app_setting`, header layout).

## Requirements changes

| ID | Change | Old text (if changed) |
| --- | --- | --- |
| C-15 | Added (Should, Phase 7): keep-in-touch cadence per contact, on the card or for a selection. | — |
| C-16 | Added (Should, Phase 7): snooze a reminder; logging clears the snooze. | — |
| C-17 | Added (Could, Phase 7): offer to log after Email, Call or Compose. | — |
| S-11 | Added (Should, Phase 7): Reconnect page and Due filter, count in the nav. | — |
| P-01 | Added (Should, Phase 7): presenting mode toggle, bar, all instances, auto-off. | — |
| P-02 | Added (Must, Phase 7): private data never sent to the browser while presenting. | — |
| P-03 | Added (Should, Phase 7): mark items private; choose hidden fields and personal labels. | — |
| P-04 | Added (Should, Phase 7): search matches hidden fields without quoting; private contacts withheld with a count. | — |
| P-05 | Added (Should, Phase 7): raw-data pages and the JSON API do not expose private data. | — |
| P-06 | Added (Should, Phase 7): Copy and Compose use work addresses only. | — |
| P-07 | Added (Could, Phase 7): per-instance presenting view. | — |
