### Auth frontend (MFA + SSO)

`src/app/(auth)/login/page.tsx` owns both login steps in one component:
`mfaChallenge` state gates which form renders (password vs. 6-digit/recovery
code), set from `login/local`'s `mfa_required` response and cleared by
"Back to sign in". The existing generic SSO button list
(`ssoProviders.map(...)`, driven by `GET /api/v1/auth/providers`) needed no
changes for Google: enabling a `google` OIDC provider in `config.yaml` is
enough, the button appears on its own.

`components/workspace/settings/security-settings-page.tsx` is the Settings
> Security tab (registered in `settings-dialog.tsx`'s section list): enroll
(QR via the already-installed `qrcode.react`, plus the raw `otpauth://` URI
and secret for manual entry), confirm, show the ten recovery codes once
with a copy button (`core/clipboard.ts`'s `writeTextToClipboard`), and
disable. Mirrors `account-settings-page.tsx`'s form conventions
(placeholder-driven `Input`, no separate `<label>`).

`User.mfa_enabled` (`types.ts`) is optional in the exported TS type even
though the zod schema defaults it at parse time, unlike `needs_setup` which
is required: dozens of existing test fixtures construct a `User` object
literal and predate this field, so making it required would have forced
touching all of them. `AuthProvider.refreshUser()` is what actually updates
it after an enroll/disable call; the settings page's own wizard step state
returns to idle independently of that.

UI copy: `core/i18n/locales/{en-US,zh-CN,types}.ts`, under `settings.security`
and `login.mfa*`. Follows the repo-wide no-dash punctuation rule; en-US uses
contractions.
