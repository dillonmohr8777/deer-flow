"""Signed private-workspace calls. No credential values live in this module."""
import hashlib
import hmac
import json
import re

SERVER = "client_browser"
OWNER = "c95ca3f4-afaf-4aed-85cb-9b8d7d0d0a3f"
ORGANIZATION = "private-19b6c92174f3f603a2aaca833e32186dbd087dbda2136c75"


def valid_scope(scope):
    return (isinstance(scope, dict) and set(scope) == {"actor", "storage", "organization", "thread"}
            and scope["actor"] == OWNER and scope["storage"] == OWNER
            and scope["organization"] == ORGANIZATION
            and isinstance(scope["thread"], str)
            and re.fullmatch(r"[A-Za-z0-9_-]{1,128}", scope["thread"]) is not None)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def signature(secret, scope, nonce, issued, name, args):
    payload = canonical({"scope": scope, "nonce": nonce, "issued": issued, "name": name, "args": args})
    return hmac.new(secret.encode(), b"momo-client-browser-v1\0" + payload.encode(), hashlib.sha256).hexdigest()
