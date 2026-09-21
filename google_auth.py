"""
Google Sign-In — required for feedback only.

WHY ONLY FOR FEEDBACK
---------------------
Anyone can search without an account. Asking people to sign in before they
can look up a hadith would turn away exactly the casual visitor this site
is for, and there is nothing to protect: searching costs a fraction of a
penny and reveals nothing.

Feedback is different. It is written into a file a human reads and acts on,
so it needs to be costly enough to abuse that nobody bothers. A sign-in
does that without a CAPTCHA.

WHAT IS STORED
--------------
A salted hash of the Google account id. Nothing else -- no email, no name,
no profile picture. Google tells us who you are; we deliberately forget it
and keep only enough to recognise the same person twice, which is all that
rate-limiting and de-duplication need.

The salt lives in HADITH_ID_SALT. If it is not set, one is derived from the
client id, which is stable but not secret -- fine for a trial, worth setting
properly before launch so the hashes cannot be recomputed by anyone who
knows a Google account id.

Both values are read lazily rather than at import, so they can come from
.env like everything else.
"""
import hashlib
import os

# Read lazily, not at import time. .env is loaded when the server starts,
# which happens AFTER this module is imported -- reading the environment
# here at import would capture it before .env had been applied, and the
# Client ID would silently appear unset no matter what the file said.
def _env(name):
    from env_config import load_env
    load_env()
    return os.environ.get(name, "").strip()


def client_id():
    return _env("GOOGLE_CLIENT_ID")


def configured():
    return bool(client_id())


def _salt():
    return _env("HADITH_ID_SALT") or ("derived:" + client_id())


def anonymous_id(google_sub):
    """Google's account id -> an opaque token we can store."""
    return hashlib.sha256((_salt() + "|" + google_sub).encode()).hexdigest()[:24]


def verify(credential):
    """
    Check a Google ID token and return an opaque user id, or None.

    Raises nothing: a bad token is simply not a signed-in user.
    """
    if not configured() or not credential:
        return None
    try:
        from google.auth.transport import requests as g_requests
        from google.oauth2 import id_token as g_id_token
        info = g_id_token.verify_oauth2_token(
            credential, g_requests.Request(), client_id()
        )
        # verify_oauth2_token already checks signature, audience and expiry.
        if info.get("iss") not in ("accounts.google.com",
                                   "https://accounts.google.com"):
            return None
        sub = info.get("sub")
        return anonymous_id(sub) if sub else None
    except Exception:
        return None
