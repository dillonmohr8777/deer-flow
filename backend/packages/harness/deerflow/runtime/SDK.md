# Optional offline Momentum SDK review

`__momentum_sdk_reviewer` is a server-owned run-scoped capability, carried only
through `RunContext` and injected/cleaned by the worker. It is stripped from
caller context/configurable. The offline factory is operator-only, defaults off,
and is not wired into public HTTP admission. Lead tool assembly requires the
capability and explicit `momentum_sdk` group; default/subagent paths deny it.
The tool checks scope and exact canonical identity, then delegates to an isolated
ScriptedModel-only SDK worker. No SDK dependency, global tracing setup, canonical
write, provider grant, or automatic production activation belongs in the Gateway.
See `examples/momentum-sdk-review/README.md` and `test_momentum_sdk_bridge.py`.
