# SSO / OIDC Authentication

DeerFlow supports single sign-on (SSO) via any OpenID Connect (OIDC) 2.0 compliant provider. This includes Keycloak, Google Workspace, Azure AD, Okta, and many others.

## Architecture

The OIDC flow uses the **Authorization Code flow** with PKCE (S256) and nonce validation for defense in depth:

```
Browser                      Gateway                    OIDC Provider
  │                             │                            │
  │  1. Click "Login with X"    │                            │
  │ ─────────────────────────▶  │                            │
  │                             │  2. Build auth URL         │
  │                             │     + state (signed cookie)│
  │                             │     + PKCE code_challenge  │
  │                             │     + nonce                │
  │                             │                            │
  │  3. Redirect to provider    │                            │
  │ ◀────────────────────────── │                            │
  │                             │                            │
  │  ──────────────────────────────────────────────────────▶ │
  │                             │   4. User authenticates    │
  │  ◀────────────────────────────────────────────────────── │
  │        5. Auth code + state │                            │
  │                             │                            │
  │  6. Callback → Gateway      │                            │
  │ ─────────────────────────▶  │                            │
  │                             │  7. Validate state cookie  │
  │                             │  8. Exchange code + PKCE   │
  │                             │     ─────────────────────▶ │
  │                             │     ◀──── tokens ──────────│
  │                             │  9. Validate ID token      │
  │                             │     (JWKS, iss, aud, nonce)│
  │                             │ 10. Fetch userinfo         │
  │                             │     ─────────────────────▶ │
  │                             │     ◀──── user claims ─────│
  │                             │ 11. Provision/link user    │
  │                             │ 12. Set session + CSRF     │
  │                             │     cookies                │
  │ ◀─ redirect to /auth/callback                            │
  │                             │                            │
  │ 13. Frontend detects auth   │                            │
  │     redirects to workspace  │                            │
```

**Key design decisions:**

- **State via signed cookie** — No server-side session store or Redis needed. The OIDC state (provider, nonce, code_verifier, next path) is signed with the JWT secret and stored in an HttpOnly cookie.
- **PKCE + nonce enabled by default** — Even though confidential clients could use `client_secret`, PKCE provides an extra layer of security.
- **No email auto-linking by default** — a pre-existing local (email/password) account is not linked to an SSO identity unless the provider sets `link_existing_accounts: true`. Otherwise an IdP-reported email that collides with an existing local account blocks the SSO login with a 409, so an SSO login can never seize a password account. See "Linking existing accounts" under Security Notes.
- **Existing DeerFlow JWT** — After successful OIDC authentication, DeerFlow creates its own JWT session cookie. The OIDC provider's tokens are never exposed to the browser.

## Configuration

### Step 1: Enable OIDC in `config.yaml`

```yaml
auth:
  oidc:
    enabled: true
    frontend_base_url: http://localhost:3000
    providers:
      keycloak:
        display_name: Keycloak
        issuer: http://localhost:8080/realms/deerflow
        client_id: deerflow
        client_secret: $KEYCLOAK_CLIENT_SECRET
        redirect_uri: http://localhost:8001/api/v1/auth/callback/keycloak
        scopes:
          - openid
          - email
          - profile
```

### Step 2: Set the client secret as an environment variable

```bash
export KEYCLOAK_CLIENT_SECRET="your-client-secret"
```

Or create a `.env` file in the `backend/` directory:

```
KEYCLOAK_CLIENT_SECRET=your-client-secret
```

### Step 3: Restart the backend

```bash
cd backend && make dev
```

## Provider Configuration

### Per-Provider Options

```yaml
providers:
  <provider-id>:
    display_name: "Display Name"    # Shown on the SSO button
    issuer: "https://..."           # OIDC issuer URL (must match the provider's .well-known/openid-configuration)
    client_id: "..."                # OAuth2 client ID
    client_secret: $SECRET          # OAuth2 client secret (supports $ENV_VAR)
    redirect_uri: "..."             # Optional: explicit callback URL
    scopes:                         # Default: ["openid", "email", "profile"]
      - openid
      - email
    token_endpoint_auth_method: "client_secret_post"  # client_secret_post, client_secret_basic, or none

    # User provisioning
    auto_create_users: true         # Auto-create DeerFlow account on first SSO login (default: true)
    auto_create_requires_invitation: false  # Auto-create only for a verified email with a pending workspace invitation (default: false)
    link_existing_accounts: false   # Link a first login to the one matching local account (default: false; see Security Notes)
    require_verified_email: true    # Reject logins without verified email (default: true)
    allowed_email_domains: []       # Restrict to specific domains (default: no restriction)
    admin_emails: []                # Auto-grant admin role to these emails (default: none)

    # Security features (both enabled by default)
    pkce_enabled: true
    nonce_enabled: true

    # Endpoint overrides (optional)
    # Use if the provider has non-standard endpoints.
    # authorization_endpoint: "https://..."
    # token_endpoint: "https://..."
    # userinfo_endpoint: "https://..."
    # jwks_uri: "https://..."
```

### Endpoint Overrides

Some providers don't return all endpoints from their `.well-known/openid-configuration`. You can override specific endpoints:

```yaml
providers:
  my-provider:
    display_name: "My Provider"
    issuer: "https://provider.example.com"
    client_id: "..."
    client_secret: $SECRET
    authorization_endpoint: "https://provider.example.com/oauth2/authorize"
    token_endpoint: "https://provider.example.com/oauth2/token"
    userinfo_endpoint: "https://provider.example.com/oauth2/userinfo"
    jwks_uri: "https://provider.example.com/oauth2/jwks"
```

## Local Keycloak Example

This section walks through setting up a local Keycloak instance with Podman or Docker for development.

### 1. Start Keycloak

```bash
# Using Podman
podman run -d \
  --name keycloak \
  -p 8080:8080 \
  -e KC_BOOTSTRAP_ADMIN_USERNAME=admin \
  -e KC_BOOTSTRAP_ADMIN_PASSWORD=admin \
  quay.io/keycloak/keycloak:26.1 \
  start-dev

# Using Docker
docker run -d \
  --name keycloak \
  -p 8080:8080 \
  -e KC_BOOTSTRAP_ADMIN_USERNAME=admin \
  -e KC_BOOTSTRAP_ADMIN_PASSWORD=admin \
  quay.io/keycloak/keycloak:26.1 \
  start-dev
```

### 2. Create a Realm and Client

1. Open the Keycloak admin console: http://localhost:8080
2. Log in with `admin` / `admin`
3. Create a new realm called `deerflow`
4. In the `deerflow` realm, go to **Clients** → **Create client**
5. Configure:
   - **Client ID**: `deerflow`
   - **Client authentication**: On (makes it a confidential client)
   - **Standard flow**: Enabled
   - **Valid redirect URIs**: `http://localhost:8001/api/v1/auth/callback/keycloak`
   - **Valid post logout redirect URIs**: `http://localhost:3000/*`
   - **Web origins**: `http://localhost:8001` (or `+` to allow all redirect URI origins)
6. After creating the client, go to the **Credentials** tab
7. Copy the **Client secret** — this is your `KEYCLOAK_CLIENT_SECRET`

### 3. Create a Test User

1. In the `deerflow` realm, go to **Users** → **Add user**
2. Set **Username**: `testuser`
3. Set **Email**: `testuser@example.com`
4. Set **Email verified**: On
5. Go to the **Credentials** tab
6. Set a password (e.g. `testpass123`)
7. Set **Temporary**: Off

### 4. Configure DeerFlow

Add to `config.yaml`:

```yaml
auth:
  oidc:
    enabled: true
    frontend_base_url: http://localhost:3000
    providers:
      keycloak:
        display_name: Keycloak
        issuer: http://localhost:8080/realms/deerflow
        client_id: deerflow
        client_secret: $KEYCLOAK_CLIENT_SECRET
        redirect_uri: http://localhost:8001/api/v1/auth/callback/keycloak
        scopes:
          - openid
          - email
          - profile
```

Set the secret:

```bash
export KEYCLOAK_CLIENT_SECRET="the-secret-from-step-2"
```

### 5. Restart and Test

```bash
cd backend && make dev
```

1. Open http://localhost:3000
2. On the login page, click **Login with Keycloak**
3. You'll be redirected to Keycloak's login page
4. Log in with `testuser` / `testpass123`
5. After successful authentication, you'll be redirected back to the DeerFlow workspace

## Account Settings for SSO Users

When a user logs in via SSO, the account settings page detects this (via the `oauth_provider` field returned by `/api/v1/auth/me`) and:

- Displays the SSO provider name (e.g. "Keycloak") in the profile section
- Replaces the password change form with an informational message
- Password changes must be done through the SSO provider, not DeerFlow

The backend also rejects password change requests for OAuth users:

```json
{
  "code": "invalid_credentials",
  "message": "OAuth users cannot change password"
}
```

## Public API Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /api/v1/auth/providers` | Returns list of enabled SSO providers (safe metadata only) |
| `GET /api/v1/auth/oauth/{provider}` | Initiates SSO login, redirects to the OIDC provider |
| `GET /api/v1/auth/callback/{provider}` | OIDC callback — exchanges code, creates session, redirects to frontend |

## Frontend Callback Flow

The frontend handles the post-SSO flow at `/auth/callback`:

1. After the backend processes the OIDC callback and sets cookies, it redirects to `{frontend_base_url}/auth/callback?next=...`
2. The callback page calls `GET /api/v1/auth/me`
3. On success: redirects to the workspace (or the original `next` path)
4. On failure: redirects to `/login?error=sso_failed`

## Security Notes

- **State cookies** are HttpOnly, SameSite=Lax, Max-Age=300 seconds, and signed with the JWT secret
- **PKCE** prevents authorization code interception attacks
- **Nonce** prevents ID token replay attacks
- **UserInfo sub check** ensures the UserInfo response matches the ID token subject
- **Reject alg=none** — ID tokens with algorithm "none" are always rejected
- **No email auto-linking by default** — an email collision with an existing local account blocks the SSO login (409) rather than merging the two.
- **Linking existing accounts (opt-in)**: with `link_existing_accounts: true` on a provider, a first SSO login links its subject onto the existing local account and signs into it, but only when all of these hold: the provider reports the email verified; the email is ASCII; `auth.local.allow_registration` is false (a self-registered account never proved it owns its email, so linking would share the real owner's account with whoever registered it); exactly one account matches the email case-insensitively; that account has no SSO identity yet, is not disabled and has no two-factor authentication (an SSO login skips the TOTP step); and the account was not created by accepting a workspace invitation issued by anyone other than a global admin (invitation acceptance creates a password account for the invited email even when `allow_registration` is false, and the inviter holds the token and sets the password, so the invited owner never proved the email; refused with reason `invitation_account`, matched on the email plus the account's `created_at` equalling the invitation's `consumed_at`). The write is one conditional UPDATE, so a concurrent link or disable is never overwritten. Every other case keeps the same 409 and public message. Each link is audited as `auth.oauth.linked`, each refusal as `auth.oauth.link_refused` with the reason and the provider subject. The registration check sees only the current setting, so enable it only if no account on the deployment was self-registered while registration was open (or after reviewing those accounts), and only for a provider that verifies email ownership, such as Google.
- **Admin link fallback**: `PUT /api/admin/users/{id}/oauth` (`{"provider", "subject"}`) links an identity the sign-in path refused, using the subject from the `auth.oauth.link_refused` event after checking with the person; `DELETE /api/admin/users/{id}/oauth` removes one. Both require a system admin on an interactive session, refuse the caller's own account, are audited (`admin.user.oauth_linked` / `admin.user.oauth_unlinked`), and end the user's sessions whenever an existing identity is replaced or removed. Each write is compare-and-set against the identity the admin read, so a sign-in that linked the account in between gets a 409 instead of being overwritten. The provider must be configured, and an identity another account holds is a 409. Unlink is for relinking, not for locking someone out: while `link_existing_accounts` is on, the next verified sign-in for that email links again, so disable the account to stop a person signing in.
- **Verified email requirement** — SSO users must have verified emails by default
- **Invite-only auto-create (opt-in)**: with `auto_create_requires_invitation: true`, a first SSO login creates an account only when the provider-verified email holds a pending workspace invitation (not consumed, not expired, issuer still an active owner/admin). Otherwise it gets the same 403 as `auto_create_users: false`. Existing linked accounts are unaffected. An email whose only pending invitations are `client` invitations is created with the `client` system role. A new account created this way joins the invited workspaces at sign-in (the provider verified the email, which is what the invitation token proves on the password path) and lands in the newest one.