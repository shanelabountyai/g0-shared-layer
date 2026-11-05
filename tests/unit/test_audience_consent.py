"""C5: audience.consent (D-9, D-17)."""

from __future__ import annotations

import pytest

from shared_layer.capabilities import audience_consent as cap


def run(db, **kw):
    return cap.run(db, cap.Input(**kw))


def test_fixture_flags_are_honoured(db):
    # ct-001 consents everywhere; ct-002 email only; ct-003 linkedin only
    assert run(db, contact_id="ct-001", channel="sms").allowed is True
    out = run(db, contact_id="ct-002", channel="email")
    assert out.allowed and out.reason == "consented" and out.contact_id == "ct-002"
    out = run(db, contact_id="ct-002", channel="linkedin")
    assert not out.allowed and out.reason == "not_consented"
    assert run(db, contact_id="ct-003", channel="linkedin").allowed
    assert not run(db, contact_id="ct-003", channel="email").allowed


def test_lookup_by_email_is_case_insensitive(db):
    out = run(db, email="  ADA.Test01@Example.COM ", channel="phone")
    assert out.allowed and out.contact_id == "ct-001"


def test_do_not_contact_blocks_every_channel(db):
    for ch in ("email", "linkedin", "sms", "phone"):
        out = run(db, contact_id="ct-007", channel=ch)
        assert not out.allowed and out.reason == "do_not_contact"


def test_unknown_contact_fails_closed_and_leaks_nothing(db):
    out = run(db, email="nobody@example.com", channel="email")
    assert out.ok and not out.allowed and out.reason == "unknown_contact" and out.contact_id is None


def test_missing_flag_for_a_channel_fails_closed(db):
    with db.conn:
        db.conn.execute("DELETE FROM consent WHERE contact_id='ct-001' AND channel='sms'")
    out = run(db, contact_id="ct-001", channel="sms")
    assert not out.allowed and out.reason == "no_flag_for_channel"


def test_input_requires_an_identifier():
    with pytest.raises(ValueError):
        cap.Input(channel="email")


def test_output_never_carries_name_or_email(db):
    out = run(db, contact_id="ct-001", channel="email")
    dumped = out.model_dump_json()
    assert "Testperson" not in dumped and "@example.com" not in dumped
