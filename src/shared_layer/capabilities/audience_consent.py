"""audience.consent v1 — may this contact be reached on this channel? (D-9, D-17, D-25)

A lookup that fails closed: unknown contact, no flag for the channel, or
do-not-contact is `allowed: false`. An unknown channel never reaches this code:
`channel` is a closed enum, so the input schema rejects it (a protocol-level
error, D-14/D-25). Contacts are synthetic (example.com) in this repo.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from shared_layer.errors import ToolError
from shared_layer.storage import Database, now_iso

CAPABILITY = "audience.consent"
TOOL = "audience_consent"
VERSION = "1"
DESCRIPTION = (
    "Ask whether a contact may be reached on a channel. Give `contact_id` or `email` plus `channel`. "
    "Returns `allowed` with a reason. Fails closed: an unknown contact, a contact with no flag for the "
    "channel, or a do-not-contact flag is `allowed: false`. `channel` must be one of email|linkedin|sms|phone; "
    "any other value is rejected as invalid input before the check runs. Never returns the contact's "
    "details beyond the id."
)

Channel = Literal["email", "linkedin", "sms", "phone"]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal["1"] = "1"
    contact_id: str | None = None
    email: str | None = Field(default=None, description="Matched case-insensitively.")
    channel: Channel

    @model_validator(mode="after")
    def _one_of(self) -> Input:
        if not self.contact_id and not self.email:
            raise ValueError("give `contact_id` or `email`")
        return self


class Output(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal["1"] = "1"
    capability: Literal["audience.consent"] = "audience.consent"
    ok: bool = True
    error: ToolError | None = None
    allowed: bool = False
    reason: Literal["consented", "not_consented", "do_not_contact", "unknown_contact", "no_flag_for_channel"] | None = None
    contact_id: str | None = Field(default=None, description="The matched contact's id, or null when unknown.")
    channel: str = ""
    checked_at: str = ""


def run(db: Database, inp: Input) -> Output:
    if inp.contact_id:
        row = db.conn.execute("SELECT contact_id, do_not_contact FROM contacts WHERE contact_id = ?", (inp.contact_id,)).fetchone()
    else:
        row = db.conn.execute("SELECT contact_id, do_not_contact FROM contacts WHERE email = ?", (inp.email.strip().lower(),)).fetchone()  # type: ignore[union-attr]
    checked = now_iso()
    if row is None:
        return Output(allowed=False, reason="unknown_contact", contact_id=None, channel=inp.channel, checked_at=checked)
    if row["do_not_contact"]:
        return Output(allowed=False, reason="do_not_contact", contact_id=row["contact_id"], channel=inp.channel, checked_at=checked)
    flag = db.conn.execute("SELECT allowed FROM consent WHERE contact_id = ? AND channel = ?", (row["contact_id"], inp.channel)).fetchone()
    if flag is None:
        return Output(allowed=False, reason="no_flag_for_channel", contact_id=row["contact_id"], channel=inp.channel, checked_at=checked)
    allowed = bool(flag["allowed"])
    return Output(allowed=allowed, reason="consented" if allowed else "not_consented", contact_id=row["contact_id"], channel=inp.channel, checked_at=checked)
