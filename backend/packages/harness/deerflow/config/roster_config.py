"""Slack account-manager roster and repo allow-list, plus the pure access resolver.

Config only: Slack user id -> role -> client ids, and repo full name -> client id
or ``"*"``. ``scope_for`` takes the Slack user id (never message text), so what a
user types cannot change what they can see. Unknown users get nothing, admin
gets ``"*"`` clients and every allow-listed repo, and a denied repo is never
visible to anyone.
"""

from typing import Literal, TypedDict

from pydantic import BaseModel, Field

Role = Literal["am", "expert", "admin"]
ALL = "*"


class RosterUser(BaseModel):
    role: Role
    clients: list[str] = Field(default_factory=list)
    email: str = Field(default="", description="Optional work email; Slack auto-link uses it first, so the bot needs no users:read.email scope")


class RosterConfig(BaseModel):
    """``roster`` section of config.yaml (empty by default: everyone denied)."""

    users: dict[str, RosterUser] = Field(default_factory=dict)
    repos: dict[str, str] = Field(default_factory=dict, description="repo full name -> client id, or '*' for every client")
    channel_clients: dict[str, str] = Field(default_factory=dict, description="Slack channel id -> client id; the client a '@MomoBot desktop' job in that channel is for")
    deny_repos: list[str] = Field(default_factory=list, description="personal repos that are never visible, even to admin")


class Scope(TypedDict):
    role: Role | None
    clients: list[str]  # ["*"] for admin
    repos: list[str]


def _norm(name: str) -> str:
    return name.strip().lower()


def scope_for(config: RosterConfig, slack_user_id: str) -> Scope:
    user = config.users.get(slack_user_id)
    if user is None:
        return {"role": None, "clients": [], "repos": []}
    denied = {_norm(r) for r in config.deny_repos}
    admin = user.role == "admin"
    repos = sorted(_norm(repo) for repo, client in config.repos.items() if _norm(repo) not in denied and (admin or client == ALL or client in user.clients))
    return {"role": user.role, "clients": [ALL] if admin else sorted(set(user.clients)), "repos": repos}


def client_allowed(scope: Scope, client_id: str) -> bool:
    return ALL in scope["clients"] or client_id in scope["clients"]
