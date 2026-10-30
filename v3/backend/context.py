"""
Who is asking?

current_user is a context variable: the API sets it for the duration of one request, and the
tools read it to decide what that person may see. It is empty by default, and an empty value
means NO access (never admin), so a code path that forgets to set it fails closed.
"""

from contextvars import ContextVar
from dataclasses import dataclass


@dataclass(frozen=True)
class UserContext:
    username: str
    role: str                          # "admin" or "user"
    display_name: str
    consumer_type: str | None = None   # "LT", "HT", or None for admins
    consumer_ref: str | None = None    # SCNO for LT, CONS_NUMBER for HT
    cons_id: int | None = None         # lt_consumer_master.ID (links to lt_meter_data)
    ukscno: str | None = None          # links to smart_meters_install_m
    dtr_code: str | None = None        # the transformer the consumer hangs off
    meter_sno: str | None = None       # smart meter serial, None if non-smart
    phase: str | None = None

    @property
    def is_admin(self):
        return self.role == "admin"


current_user = ContextVar("current_user", default=None)


class NotSignedIn(Exception):
    pass


def require_user():
    user = current_user.get()
    if user is None:
        raise NotSignedIn("Not signed in.")
    return user
