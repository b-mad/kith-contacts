"""Anonymize a copied database for development (I-07).

Keeps the shape of the data (types, companies, teams, titles, manager chains,
tags, lists, works-on) so issues reproduce, but removes what identifies people.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.search import refresh_all

_STATEMENTS = (
    """UPDATE contact SET display_name = 'Contact ' || id, first_name = NULL, last_name = NULL,
         nickname = NULL, notes = NULL, pronunciation = NULL, slack_handle = NULL,
         slack_url = NULL, teams_url = NULL, location = NULL""",
    """UPDATE contact_email
         SET email = 'contact' || contact_id || '-' || id || '@example.invalid'""",
    "DELETE FROM contact_phone",
    "DELETE FROM contact_photo",
    # Phase 4 free text can name people too (C-11, C-12, C-13).
    "UPDATE activity SET summary = initcap(kind) || ' ' || id",
    "UPDATE custom_field SET value = 'Value ' || id",
    "DELETE FROM contact_merge",
    # Embeddings are derived from the real text: rebuild them from the anonymized copy (S-08).
    "DELETE FROM semantic_chunk",
    "DELETE FROM semantic_doc",
)


def anonymize(session: Session) -> None:
    for statement in _STATEMENTS:
        session.execute(text(statement))
    refresh_all(session)
