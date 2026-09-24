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
)


def anonymize(session: Session) -> None:
    for statement in _STATEMENTS:
        session.execute(text(statement))
    refresh_all(session)
