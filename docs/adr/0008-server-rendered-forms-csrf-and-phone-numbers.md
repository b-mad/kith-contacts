# ADR-0008: Server-rendered forms, CSRF protection and phone number format

- **Status:** Accepted (2026-09-24)
- **Date:** 2026-09-24
- **Deciders:** Bryan Madsen
- **Requirements affected:** C-01–C-08, M-04, N-04, N-05 (implementation choices; no requirement text changed)

## Context

Phase 1 adds the first pages that change data. N-05 requires CSRF protection
on writes; N-04 forbids CDN assets; the data model says phones are stored in
E.164 "when parseable". The manager picker (C-07) needs search-as-you-type.

## Decision

1. **Forms are server-rendered and post back to the server** (Jinja). Validation
   errors re-render the form with the user's input kept. A small vanilla
   JavaScript file (`app/static/js/app.js`) adds the manager picker,
   add/remove email and phone rows, and auto-submitting filters. HTMX is not
   needed yet; it will be vendored (ADR-0004) when Phase 2's live search needs it.
2. **CSRF:** every form POST carries a double-submit token that must match an
   `HttpOnly`, `SameSite=Strict` cookie. JSON API writes require
   `Content-Type: application/json` (cross-site pages cannot send it without a
   CORS preflight, and no CORS is enabled). The CSP adds `form-action 'self'`.
3. **Links are https-only:** Slack and Teams links must start with `https://`,
   so a stored value can never become a `javascript:` link.
4. **Phone numbers** are normalized to E.164 with Google's `phonenumbers`
   library, using the instance's `PHONE_REGION` (default `US`) for numbers
   without a country code. Unparseable input (e.g. "ext 42") is stored as typed.
5. **Manager cycles** are rejected in the service layer by walking up the
   chain; the database also forbids a contact being its own manager.
6. A typed manager name that was not picked from the suggestions is an error,
   not a silently empty manager.

## Consequences

- The manager picker needs JavaScript; everything else works without it.
- `PHONE_REGION` is a new optional instance setting.
- New runtime dependencies: `email-validator`, `phonenumbers`, `python-multipart`.
