"""Communication links (C-04, M-04, ADR-0007) — pure unit tests."""

from __future__ import annotations

import pytest

from app.links import (
    contact_teams_url,
    display_phone,
    mailto_url,
    normalize_phone,
    slack_handle_display,
    teams_chat_url,
    tel_url,
)


@pytest.mark.req("C-04")
def test_teams_link_generated_from_primary_email_when_blank() -> None:
    assert (
        contact_teams_url(None, "maria.lopez@acme.example")
        == "https://teams.microsoft.com/l/chat/0/0?users=maria.lopez@acme.example"
    )


@pytest.mark.req("C-04")
def test_explicit_teams_link_wins() -> None:
    explicit = "https://teams.microsoft.com/l/chat/0/0?users=other@acme.example"
    assert contact_teams_url(explicit, "maria@acme.example") == explicit


@pytest.mark.req("C-04")
def test_no_teams_link_without_email_or_url() -> None:
    assert contact_teams_url(None, None) is None
    assert teams_chat_url(["", "  "]) is None


def test_teams_group_chat_joins_users() -> None:
    assert teams_chat_url(["a@x.example", "b+tag@y.example"]) == (
        "https://teams.microsoft.com/l/chat/0/0?users=a@x.example,b%2Btag@y.example"
    )


@pytest.mark.req("M-04")
def test_mailto_link() -> None:
    assert mailto_url(["maria@acme.example"]) == "mailto:maria@acme.example"
    assert mailto_url(["a@x.example"], cc=["b@x.example"]) == "mailto:a@x.example?cc=b@x.example"
    assert mailto_url([]) is None


@pytest.mark.req("M-04")
@pytest.mark.parametrize(
    ("number", "expected"),
    [
        ("+1 (404) 555-0100", "tel:+14045550100"),
        ("404.555.0100 ext", "tel:4045550100"),
        ("44+20+7946", "tel:+44207946"),
    ],
)
def test_tel_link_keeps_digits_and_leading_plus(number: str, expected: str) -> None:
    assert tel_url(number) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("(404) 555-0123", "+14045550123"),
        ("+44 20 7946 0958", "+442079460958"),
        ("ext 42", "ext 42"),
        ("12", "12"),
    ],
)
def test_normalize_phone_to_e164_when_parseable(raw: str, expected: str) -> None:
    assert normalize_phone(raw, "US") == expected


def test_display_phone_formats_e164() -> None:
    assert display_phone("+14045550123") == "(404) 555-0123"
    assert display_phone("+442079460958") == "+44 20 7946 0958"
    assert display_phone("ext 42") == "ext 42"
    assert display_phone("+1") == "+1"


def test_slack_handle_display_adds_at() -> None:
    assert slack_handle_display("maria") == "@maria"
    assert slack_handle_display("@maria") == "@maria"
    assert slack_handle_display(None) is None
