# MomoBot first-login onboarding

Staff (`system_role` `user`, `exec` or `admin`) see a required three-step dialog the
first time they sign in. Clients never see it (the client route boundary denies
`/api/v1/auth/onboarding*`). Accounts that finished it get the old skippable
Easy/Medium/Hard chooser behaviour.

1. **Role and team.** Pre-filled from the person's own profile when one exists
   (see "People profiles"). Required.
2. **Daily tools.** The whole connectable catalog, searchable and grouped: the
   common tools pinned first (Slack, Gmail, Google Calendar, Google Drive,
   HubSpot, Google Ads, Meta Ads, GA4, Search Console), then every plugin in the
   capability catalog (`/api/capabilities/catalog`) and every enabled MCP server
   in `extensions_config.json`. Free text ("anything else") is recorded as a
   request. Required (at least one pick or free text).
3. **Connect.** Per tool: connected (a real per-user credential exists),
   "Request access" (recorded as `requested`), or "Skip" (recorded as `skipped`).
   Slack also offers "Link Slack DMs", the existing binding-code flow from
   `POST /api/channels/slack/connect`. Tools left untouched are recorded as
   skipped at completion.
4. **Finish.** Stores `onboarding_completed_at`, sets `experience_mode: easy` and
   `mode: flash`, and seeds the person's own memory once (role, team, clients,
   daily tools, working style).

State is stored in the owner-scoped `user_preferences` rows (`onboarding_profile`,
`daily_tools`, `onboarding_connections`, `onboarding_completed_at`).
`GET /api/v1/auth/onboarding/requests` (admin only) lists who requested which
tool so an operator can map credentials.

## What "connected" means

A tool is connected only when an existing per-user mechanism holds this
person's own credential:

| Tool | Mechanism | Self-serve today |
| --- | --- | --- |
| Google Ads, Meta Ads | `{DEER_FLOW_HOME}/users/<user_id>/integrations/ads/credentials.json` (see `community/ads/AGENTS.md`) | No, operator writes the file |
| Everything else (`<id>`) | An enabled MCP server named `<id>-user` (dashes for underscores, e.g. `slack-user`, `google-calendar-user`) or `<id>` with a `user_auth` block that maps this user id | No, operator maps the credential |
| An enabled MCP server with no `user_auth` | Shared server, shown as "Ready for everyone" | Already usable |

With no matching server the tool shows "Coming soon" and the request is
recorded. Nothing ever reports a connection that does not exist.

## Per-person Slack in chat

`extensions_config.example.json` ships a disabled `slack-user` entry. Each
person's runs call Slack with **their own user token** through `user_auth`
(`on_missing: deny`): an unmapped person gets a tool error, never the discovery
token, the bot token or someone else's token
(`backend/tests/test_slack_user_scoped_mcp.py`).

Read-only comes from the token's scopes, not from the MCP server. Steps:

1. In the existing workspace Slack app (or a new one), add **User Token Scopes**
   only: `search:read`, `channels:history`, `groups:history`, `channels:read`,
   `groups:read`, `users:read`. Do not add `chat:write` as a user scope.
   The bot side separately still lacks `users:read.email`, `im:write` and
   `files:read` for the DM channel features.
2. A Slack workspace admin approves the scope change and reinstalls the app.
3. Each person authorizes the app once (Slack's install/OAuth page) and the
   resulting `xoxp-` user token is stored as an env var on the host, for example
   `SLACK_USER_AUTH_ALICE="Bearer xoxp-..."`.
4. Map the person's MomoBot user id to it in the server's `user_auth.users`
   (`"<user-id>": "$SLACK_USER_AUTH_ALICE"`), set `SLACK_MCP_DISCOVERY_AUTH` to one
   staff member's own `Bearer xoxp-...` for tool discovery, point `url` at the
   Slack MCP endpoint you use, and enable the server. The denial message for an
   unmapped user prints the exact id to use.

A self-serve Slack OAuth callback that writes step 3-4 automatically is a
follow-up; it is a new OAuth surface and was deliberately not added here.

## People profiles

`MOMO_PEOPLE_DIR` points at a read-only folder of `<email>.md` files built
outside the repository:

```markdown
---
role: Account manager
team: Paid media
clients: Example Co, Sample LLC
tools: slack, gmail, google_ads
---
Prefers short morning updates.
```

The lookup key is the signed-in user's email, never a request parameter, so
each person only sees their own profile. Unknown tool names are ignored, files
over 64 KiB are ignored, and a missing folder or file simply means no pre-fill.
On EC2 the folder is `/opt/momobot/data/people` mounted at `/var/momo-people`
(`deploy/momentum/ec2/compose.ec2.yaml`).
