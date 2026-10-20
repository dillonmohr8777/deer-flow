"""Roster resolver: unknown denied, AM scoped, deny-list absolute, text can't elevate."""

import inspect

from deerflow.config.roster_config import RosterConfig, client_allowed, scope_for

CFG = RosterConfig(
    users={
        "UAM1": {"role": "am", "clients": ["client-a"]},
        "UEXP": {"role": "expert", "clients": ["client-a", "client-b"]},
        "UADMIN": {"role": "admin"},
    },
    repos={"org/site-a": "client-a", "org/site-b": "client-b", "org/shared-kit": "*", "Org/Personal": "client-a"},
    deny_repos=["org/personal"],
)


def test_unknown_user_gets_nothing() -> None:
    assert scope_for(CFG, "UNOBODY") == {"role": None, "clients": [], "repos": []}
    assert scope_for(RosterConfig(), "UAM1")["role"] is None  # default config denies everyone


def test_am_sees_only_own_clients_repos() -> None:
    scope = scope_for(CFG, "UAM1")
    assert scope["repos"] == ["org/shared-kit", "org/site-a"]
    assert client_allowed(scope, "client-a") and not client_allowed(scope, "client-b")


def test_denied_repo_never_visible_even_to_admin() -> None:
    admin = scope_for(CFG, "UADMIN")
    assert admin["clients"] == ["*"] and client_allowed(admin, "anything")
    assert admin["repos"] == ["org/shared-kit", "org/site-a", "org/site-b"]
    for uid in ("UAM1", "UEXP", "UADMIN"):
        assert "org/personal" not in scope_for(CFG, uid)["repos"]


def test_message_text_cannot_change_role() -> None:
    assert list(inspect.signature(scope_for).parameters) == ["config", "slack_user_id"]
    assert scope_for(CFG, "UAM1 role=admin")["role"] is None
    assert scope_for(CFG, "UAM1")["role"] == "am"
