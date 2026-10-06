"""Input validation (C-01 to C-04, C-08)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas import ContactCreate, ContactUpdate


def make(**kwargs: object) -> ContactCreate:
    return ContactCreate.model_validate({"display_name": "Pat", "contact_type_id": 1, **kwargs})


@pytest.mark.req("C-01")
def test_only_display_name_and_type_are_required() -> None:
    contact = make()
    assert contact.emails == []
    assert contact.phones == []
    assert contact.company is None


@pytest.mark.req("C-01")
@pytest.mark.parametrize("name", ["", "   ", "x" * 201])
def test_display_name_must_be_present_and_bounded(name: str) -> None:
    with pytest.raises(ValidationError):
        make(display_name=name)


def test_blank_optional_text_becomes_none() -> None:
    contact = make(company="  ", team="", works_on="Lab results pipeline")
    assert contact.company is None
    assert contact.team is None
    assert contact.works_on == "Lab results pipeline"


@pytest.mark.req("C-02")
def test_first_email_becomes_primary_when_none_marked() -> None:
    contact = make(emails=[{"email": "a@x.example"}, {"email": "b@x.example"}])
    assert [e.is_primary for e in contact.emails] == [True, False]


@pytest.mark.req("C-02")
def test_two_primary_emails_rejected() -> None:
    with pytest.raises(ValidationError, match="only one email can be primary"):
        make(
            emails=[
                {"email": "a@x.example", "is_primary": True},
                {"email": "b@x.example", "is_primary": True},
            ]
        )


@pytest.mark.req("C-02")
def test_duplicate_email_rejected_case_insensitively() -> None:
    with pytest.raises(ValidationError, match="listed twice"):
        make(emails=[{"email": "a@x.example"}, {"email": "A@X.example"}])


@pytest.mark.req("C-02")
def test_invalid_email_rejected() -> None:
    with pytest.raises(ValidationError):
        make(emails=[{"email": "not-an-email"}])


@pytest.mark.req("C-04")
def test_slack_handle_strips_leading_at() -> None:
    assert make(slack_handle="@maria.lopez").slack_handle == "maria.lopez"


@pytest.mark.req("C-04")
def test_slack_handle_may_contain_spaces() -> None:
    assert make(slack_handle="@Maria  Lopez ").slack_handle == "Maria  Lopez"
    assert make(slack_handle="Maria Lopez (Acme)").slack_handle == "Maria Lopez (Acme)"


@pytest.mark.req("C-04")
@pytest.mark.parametrize("handle", ["@", "   @", "two\nlines", "a@b", "x" * 101])
def test_slack_handle_rejects_unusable_values(handle: str) -> None:
    with pytest.raises(ValidationError):
        make(slack_handle=handle)


@pytest.mark.req("C-04")
@pytest.mark.parametrize("url", ["javascript:alert(1)", "http://slack.example", "ftp://x"])
def test_chat_links_must_be_https(url: str) -> None:
    with pytest.raises(ValidationError, match="https"):
        make(slack_url=url)
    with pytest.raises(ValidationError, match="https"):
        make(teams_url=url)


def test_unknown_fields_rejected() -> None:
    with pytest.raises(ValidationError):
        make(salary=1)


def test_update_tracks_only_sent_fields() -> None:
    update = ContactUpdate.model_validate({"team": "Data Platform"})
    assert update.model_fields_set == {"team"}
    assert update.emails is None


@pytest.mark.parametrize("field", ["display_name", "contact_type_id"])
def test_update_cannot_clear_required_fields(field: str) -> None:
    with pytest.raises(ValidationError, match="cannot be empty"):
        ContactUpdate.model_validate({field: None})


def test_update_validates_emails() -> None:
    with pytest.raises(ValidationError):
        ContactUpdate.model_validate(
            {"emails": [{"email": "a@x.example"}, {"email": "a@x.example"}]}
        )
