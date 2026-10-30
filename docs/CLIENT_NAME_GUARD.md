# Client-name guard

This repository is public. Examples, tests, docs and deploy files must use synthetic
names (for example "Acme Dental", "Northwind Events"), never a real client, contact or
account name.

`scripts/client_name_guard.py check` fails when any tracked file, or any tracked file
path, contains a deny-listed name. CI runs it on every pull request and push
(`.github/workflows/client-name-guard.yml`). Output gives `path:line` only, never the
matched text.

## How the deny-list stays private

`scripts/client_name_denylist.json` holds only salted SHA-256 hashes. Each name is
normalised (camelCase split, lowercased, runs of letters and digits joined by one space)
and hashed as `sha256(salt + ":" + phrase)`. At check time every 1 to N token window of
every line and path is hashed the same way and looked up. Consequences:

- `Acme Dental`, `ACME-DENTAL`, `acme_dental` and `AcmeDental` all match; the joined
  spelling `acmedental` is added automatically.
- A name that is a common English word or acronym is deliberately not on the list (it
  would block unrelated text). Use a multi-word form of the name instead.
- Lockfiles, vendored directories, minified assets and binary files are skipped.
- The salt and a plain SHA-256 hide names from a casual reader and from `git grep`. They are not
  secrecy against someone who already has a candidate list: anyone can hash a guess and compare
  it. Keep the plaintext list out of the repo and out of history.
- Windows run across line breaks, so a name wrapped over two lines is found. A name glued
  into a longer lowercase word with no case change (for example `fooacmedentalbar`) is not.
- Not scanned: lockfiles, `vendor`, `vendored`, `third_party` and `node_modules` directories,
  minified assets, fonts, files over 5 MB, binary files (including UTF-16 text), and the
  target content of symlinks (the link path is still checked). Names inside images are never seen.

## Refreshing the list

Keep `names.txt` (one name or alias per line) outside the repository, then:

```
python scripts/client_name_guard.py build --salt "$(python -c "import json;print(json.load(open('scripts/client_name_denylist.json'))['salt'])")" < names.txt > /tmp/new.json
mv /tmp/new.json scripts/client_name_denylist.json
python scripts/client_name_guard.py check
```

To add names without the old plaintext list, merge them into the committed one. The salt and every existing hash are kept:

```
python scripts/client_name_guard.py build --merge scripts/client_name_denylist.json < new_names.txt > /tmp/merged.json
mv /tmp/merged.json scripts/client_name_denylist.json
python scripts/client_name_guard.py check
```

The deny-list covers staff names as well as client names. A name written in camelCase (`McName`) is split into two tokens, so also add the plain lowercase spelling as its own line. Role placeholders (`sales-lead`, `agency-principal`) stand in for staff in profiles, fixtures and tests; the real staff roster for the Momentum Daily page is build-time config (`NEXT_PUBLIC_MOMENTUM_STAFF`), never code.

Generate `names.txt` from the client registry (display names and aliases of non-internal
records) plus any extras. Review which single-word names would collide with ordinary words
before adding them.

## Browserbase fleet exception

`browserbase_fleet.py` refuses jobs for one historical client id. That id is stored as a
salted hash (`_HISTORICAL_CLIENT_HASHES`) so the file doesn't name the client; the check is
an exact match, same behavior as before.

Tests: `backend/tests/test_client_name_guard.py`.
