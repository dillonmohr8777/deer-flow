"""Per-instance auth cookie naming (DEER_FLOW_AUTH_COOKIE_PREFIX).

Two DeerFlow deployments reachable on the same hostname but different ports
(e.g. a private workspace beside the main site) share one browser cookie jar,
because cookies are host-scoped, not port-scoped. Without a per-instance
cookie name, logging into one instance silently clobbers the other's session,
and a token issued by one instance's JWT secret gets sent to the other
instance, which rejects it — the "login succeeds, then the next request 401s"
bug. Setting DEER_FLOW_AUTH_COOKIE_PREFIX per instance keeps their cookies
(and therefore their sessions) independent, while leaving deployments that
don't set it unchanged.
"""

import importlib


def _reload_session_cookie():
    from app.gateway.auth import session_cookie

    return importlib.reload(session_cookie)


def test_default_cookie_names_unchanged(monkeypatch):
    monkeypatch.delenv("DEER_FLOW_AUTH_COOKIE_PREFIX", raising=False)
    module = _reload_session_cookie()
    assert module.ACCESS_TOKEN_COOKIE_NAME == "access_token"
    assert module.SESSION_PERSISTENCE_COOKIE_NAME == "deerflow_session_persistent"


def test_prefix_env_var_namespaces_cookie_names(monkeypatch):
    monkeypatch.setenv("DEER_FLOW_AUTH_COOKIE_PREFIX", "dillon_workspace_")
    module = _reload_session_cookie()
    try:
        assert module.ACCESS_TOKEN_COOKIE_NAME == "dillon_workspace_access_token"
        assert module.SESSION_PERSISTENCE_COOKIE_NAME == "dillon_workspace_deerflow_session_persistent"
        # Distinct from the unprefixed names an unrelated instance on the
        # same hostname would use — this is the property that prevents the
        # cross-instance session collision.
        assert module.ACCESS_TOKEN_COOKIE_NAME != "access_token"
    finally:
        monkeypatch.delenv("DEER_FLOW_AUTH_COOKIE_PREFIX", raising=False)
        _reload_session_cookie()  # restore defaults for later tests in this process
