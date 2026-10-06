# ADR-0029: Copy the selected contacts' Slack handles

- **Status:** Accepted (2026-10-06)
- **Date:** 2026-10-06
- **Deciders:** Bryan Madsen
- **Requirements affected:** M-07 added (Could, Phase 3); M-04, M-05 and C-04 unchanged

## Context

A selection can start a Teams group chat (M-05) because Teams accepts a list of email addresses in
one link. Slack has no equivalent: its links open one person (by Slack user ID) or one channel, and
the only way to create a group message from a list is the Slack API, which needs a Slack app and
token and a call to Slack's servers (N-04). The Slack handle on a contact is a display label, not
an ID (C-04), so nothing can resolve it. The owner still wants to tag several people in an
existing Slack chat, or start a group message, from a selection.

## Options considered

1. **Slack API (`conversations.open`).** Creates the group message for real. Needs a token and
   runtime calls to a third party: rejected by N-04.
2. **A link per person.** Opens many windows, not one chat.
3. **Copy the handles.** One action next to Copy emails: the handles go to the clipboard and the
   person pastes them into a Slack message (to tag) or into the New message box (to start a chat).

## Decision

Option 3. A "Copy Slack handles" button in the selection bar copies each selected contact's handle
with a leading `@`, in the order chosen and separated by a comma and a space, for example
`@Maria Lopez, @Dev Patel`. Contacts with no handle are skipped and named in the status line, as
Copy emails does. Identical handles are copied once. When the clipboard is not available the text
is shown ready to copy by hand (N-07). Rows carry the handle in `data-slack`; while presenting in
names-only view no handle is sent to the page (ADR-0016), and in the other views the handle is a
work field and is shown as on the card.

## Consequences

- Works with no Slack account details, no token and no network call.
- Slack decides what a pasted `@name` becomes. Typing `@` in a message box offers a mention picker
  and pasted text may stay plain text, so the person may still have to pick each name from
  Slack's list. This has not been tried against Slack itself.
- A handle that is not exactly the person's Slack display name will not match anyone.

## Requirements changes

| ID | Change | Old text (if changed) |
| --- | --- | --- |
| M-07 | Added: Copy Slack handles for the selected contacts (Could, Phase 3). | - |
