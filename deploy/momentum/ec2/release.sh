#!/usr/bin/env bash
# One-command MomoBot prod release on the EC2 box. Run from an operator checkout (git push + gh signed in):
#
#   deploy/momentum/ec2/release.sh <sha>      release a commit that is on origin/main
#   deploy/momentum/ec2/release.sh rollback   put the previous release's source and image tags back
#
# A release, under /run/momobot-release.lock on the box: check out <sha> in /opt/momobot/src, build
# deer-flow-{gateway,frontend}:main-<sha8> unless the box already has them, swap both tags in
# settings.env, `systemctl restart momobot`, wait for /health/ready, smoke (running images, public API
# and UI). Any failure after the swap restores the previous source and tags on its own. On success the
# operator side tags momobot-prod-YYYYMMDD-<sha8>, pushes the tag and opens a PR that adds the release to
# docs/MOMOBOT_CHANGELOG.md. Every attempt appends a line to /var/log/momobot/releases.jsonl on the box.
#
# Env: MOMOBOT_SSH (ssh destination, default ubuntu@momobot.needmomentum.com), MOMOBOT_SSH_KEY (optional).
# The box half is this same file piped to `sudo bash -s`, so the box checkout need not carry it yet.
# Everything is in functions and `main` runs on the last line, so commands reading stdin cannot eat
# the rest of the piped script.
set -euo pipefail

# Box paths; the env overrides exist for the offline test (backend/tests/test_ec2_release_script.py).
DEPLOY="${MOMOBOT_DEPLOY_DIR:-/opt/momobot}"
SRC="$DEPLOY/src"
SETTINGS="$DEPLOY/settings.env"
PREV="$DEPLOY/release-prev.env"
ENV_FILE="${MOMOBOT_ENV_FILE:-/run/momobot/.env}"
LEDGER="${MOMOBOT_RELEASE_LEDGER:-/var/log/momobot/releases.jsonl}"
LOCK="${MOMOBOT_RELEASE_LOCK:-/run/momobot-release.lock}"
CHANGELOG=docs/MOMOBOT_CHANGELOG.md

die() { echo "release: $*" >&2; exit 1; }

# ---------------------------------------------------------------- box half (root, on EC2)

setting() { "$SRC/deploy/momentum/vps/dotenv-get.sh" "$SETTINGS" "$1"; }

set_setting() {
  grep -q "^$1=" "$SETTINGS" || die "$1 is missing from $SETTINGS"
  sed -i.bak "s|^$1=.*|$1=$2|" "$SETTINGS"   # .bak keeps the last value by hand too
}

ledger() {  # <action> <sha> <gateway> <frontend> <ok>
  mkdir -p "$(dirname "$LEDGER")"
  printf '{"at":"%s","action":"%s","sha":"%s","gateway":"%s","frontend":"%s","ok":%s}\n' \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$@" >>"$LEDGER"
}

ready() {
  local code=000 deadline=$((SECONDS + 180))
  while ((SECONDS < deadline)); do
    code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 http://127.0.0.1:2026/health/ready || true)"
    [[ "$code" == 200 ]] && return 0
    sleep 3
  done
  echo "release: /health/ready answered $code for 180 s" >&2
  return 1
}

smoke() {  # <gateway image> <frontend image>
  local name want got domain url code
  # up.sh's compose project names the containers (compose.funnel.yaml: <project>-gateway).
  local project="${MOMOBOT_PROJECT:-momobot-prod}"
  for name in gateway frontend; do
    [[ "$name" == gateway ]] && want="$1" || want="$2"
    got="$(docker inspect -f '{{.Config.Image}}' "$project-$name" 2>/dev/null || true)"
    [[ "$got" == "$want" ]] || { echo "release: $project-$name runs '$got', expected $want" >&2; return 1; }
  done
  domain="$("$SRC/deploy/momentum/vps/dotenv-get.sh" "$ENV_FILE" MOMOBOT_DOMAIN)"
  [[ -n "$domain" ]] || { echo "release: MOMOBOT_DOMAIN missing from $ENV_FILE" >&2; return 1; }
  for url in "https://$domain/health" "https://$domain/"; do
    code="$(curl -s --location -o /dev/null -w '%{http_code}' --max-time 15 "$url" || true)"
    [[ "$code" == 200 ]] || { echo "release: smoke $url answered $code" >&2; return 1; }
  done
}

apply() {  # <source sha> <gateway image> <frontend image>: switch, restart, wait, smoke
  git -C "$SRC" checkout -q --detach "$1"
  set_setting MOMENTUM_GATEWAY_IMAGE "$2"
  set_setting MOMENTUM_FRONTEND_IMAGE "$3"
  systemctl restart momobot && ready && smoke "$2" "$3"
}

take_lock() {
  exec 9>"$LOCK"
  flock -n 9 || die "another release holds $LOCK"
}

box_release() {
  local sha="$1" sha8 gw fe prev_src prev_gw prev_fe free_kib
  take_lock
  [[ -z "$(git -C "$SRC" status --porcelain --untracked-files=no)" ]] || die "$SRC has local changes; resolve them first"
  git -C "$SRC" fetch -q origin main
  sha="$(git -C "$SRC" rev-parse --verify --quiet "$sha^{commit}")" || die "unknown commit $1"
  git -C "$SRC" merge-base --is-ancestor "$sha" origin/main || die "$sha is not on origin/main"
  free_kib="$(df -Pk "$DEPLOY" | awk 'NR == 2 {print $4}')"
  ((free_kib >= 10 * 1024 * 1024)) || die "under 10 GiB free on $DEPLOY; recover headroom first (see README)"

  sha8="${sha:0:8}"
  gw="deer-flow-gateway:main-$sha8"
  fe="deer-flow-frontend:main-$sha8"
  prev_src="$(git -C "$SRC" rev-parse HEAD)"
  prev_gw="$(setting MOMENTUM_GATEWAY_IMAGE)"
  prev_fe="$(setting MOMENTUM_FRONTEND_IMAGE)"
  [[ -n "$prev_gw" && -n "$prev_fe" ]] || die "current image tags missing from $SETTINGS"

  git -C "$SRC" checkout -q --detach "$sha"
  if ! docker image inspect "$gw" "$fe" >/dev/null 2>&1; then
    echo "release: building $gw and $fe"
    if ! MOMENTUM_GATEWAY_IMAGE="$gw" MOMENTUM_FRONTEND_IMAGE="$fe" MOMOBOT_ENV_FILE="$ENV_FILE" \
      MOMOBOT_EXTRA_COMPOSE="$SRC/deploy/momentum/ec2/compose.ec2.yaml" \
      "$SRC/deploy/momentum/lightsail/up.sh" build; then
      git -C "$SRC" checkout -q --detach "$prev_src"
      ledger build "$sha" "$gw" "$fe" false
      die "build failed; nothing was restarted"
    fi
  fi

  if ! apply "$sha" "$gw" "$fe"; then
    echo "release: rolling back to $prev_gw and $prev_fe" >&2
    ledger release "$sha" "$gw" "$fe" false
    if apply "$prev_src" "$prev_gw" "$prev_fe"; then
      ledger auto-rollback "$prev_src" "$prev_gw" "$prev_fe" true
      die "release failed and was rolled back"
    fi
    ledger auto-rollback "$prev_src" "$prev_gw" "$prev_fe" false
    die "release failed AND the rollback is unhealthy; look now"
  fi
  printf 'PREV_SRC=%s\nPREV_GATEWAY=%s\nPREV_FRONTEND=%s\n' "$prev_src" "$prev_gw" "$prev_fe" >"$PREV"
  ledger release "$sha" "$gw" "$fe" true
  echo "release: live on $gw and $fe (previous: $prev_gw, $prev_fe)"
}

box_rollback() {
  local src gw fe
  take_lock
  [[ -f "$PREV" ]] || die "no $PREV; no release to roll back"
  src="$("$SRC/deploy/momentum/vps/dotenv-get.sh" "$PREV" PREV_SRC)"
  gw="$("$SRC/deploy/momentum/vps/dotenv-get.sh" "$PREV" PREV_GATEWAY)"
  fe="$("$SRC/deploy/momentum/vps/dotenv-get.sh" "$PREV" PREV_FRONTEND)"
  if ! apply "$src" "$gw" "$fe"; then
    ledger rollback "$src" "$gw" "$fe" false
    die "rollback to $gw and $fe is unhealthy; look now"
  fi
  ledger rollback "$src" "$gw" "$fe" true
  echo "release: rolled back to $gw and $fe"
}

# ---------------------------------------------------------------- operator half (local checkout)

on_box() {
  # `bash <(git show ...)` leaves BASH_SOURCE an already-read pipe, so the box would get an empty
  # script, exit 0, and the operator half would tag a release that never deployed.
  [[ -f "${BASH_SOURCE[0]}" ]] || die "run release.sh from a file (e.g. git show origin/main:deploy/momentum/ec2/release.sh > /tmp/release.sh), not bash <(...)"
  local ssh=(ssh)
  [[ -n "${MOMOBOT_SSH_KEY:-}" ]] && ssh+=(-i "$MOMOBOT_SSH_KEY")
  "${ssh[@]}" "${MOMOBOT_SSH:-ubuntu@momobot.needmomentum.com}" "sudo bash -s -- $*" <"${BASH_SOURCE[0]}"
}

changelog_section() {  # <range> <heading>: keep-a-changelog section from first-parent PR merges
  local subject title changed="" fixed="" security="" re='^Merge pull request #([0-9]+)'
  # Bash 3.2 (macOS) compatible: no associative arrays.
  while IFS=$'\t' read -r subject title; do
    [[ "$subject" =~ $re ]] || continue
    title="- ${title:-$subject} (#${BASH_REMATCH[1]})"$'\n'
    shopt -s nocasematch
    if [[ "$title" =~ secur|secret|credential|auth|token|redact|permission ]]; then
      security+="$title"
    elif [[ "$title" =~ fix|flak|repair|restore|broken|crash|race ]]; then
      fixed+="$title"
    else
      changed+="$title"
    fi
    shopt -u nocasematch
  done < <(git log --first-parent --merges --format='%s%x09%b' "$1" | grep '^Merge pull request')
  printf '%s\n' "$2"
  [[ -z "$changed" ]] || printf '\n### Changed\n\n%s' "$changed"
  [[ -z "$fixed" ]] || printf '\n### Fixed\n\n%s' "$fixed"
  [[ -z "$security" ]] || printf '\n### Security\n\n%s' "$security"
}

changelog_pr() {  # <tag> <sha> <previous tag or empty>
  local tag="$1" sha="$2" prev="$3" wt section
  wt="$(mktemp -d)"
  git worktree add -q -b "release/$tag-changelog" "$wt" origin/main
  section="$(changelog_section "${prev:+$prev..}$sha" "## [$tag] - $(date +%Y-%m-%d)")"
  # The new release goes right under [Unreleased], whose bullets it supersedes.
  SECTION="$section" awk '
    /^## \[Unreleased\]/ { print; print ""; print ENVIRON["SECTION"]; print ""; skip = 1; next }
    skip && /^## \[/ { skip = 0 }
    !skip
  ' "$wt/$CHANGELOG" >"$wt/$CHANGELOG.new"
  mv "$wt/$CHANGELOG.new" "$wt/$CHANGELOG"
  git -C "$wt" commit -q -am "Add $tag to the MomoBot changelog"
  git -C "$wt" push -q -u origin "release/$tag-changelog"
  (cd "$wt" && gh pr create --fill --title "MomoBot changelog $tag, $(date '+%b %-d')" \
    --body "Intent: record prod release $tag ($sha) in docs/MOMOBOT_CHANGELOG.md. Risk class: trivial (docs). Verified: generated by release.sh after /health/ready and smoke passed. Not verified: entry categories are keyword guesses from PR titles.")
  git worktree remove "$wt"
}

release() {
  local sha tag prev
  git fetch -q origin main --tags
  sha="$(git rev-parse --verify --quiet "$1^{commit}")" || die "unknown commit $1"
  git merge-base --is-ancestor "$sha" origin/main || die "$sha is not on origin/main"
  prev="$(git describe --tags --abbrev=0 --match 'momobot-prod-*' "$sha^" 2>/dev/null || true)"
  on_box box-release "$sha"
  tag="momobot-prod-$(date +%Y%m%d)-${sha:0:8}"
  if ! git rev-parse -q --verify "refs/tags/$tag" >/dev/null; then
    git tag -a "$tag" "$sha" -m "MomoBot prod release ${sha:0:8}: /health/ready and smoke passed"
    git push -q origin "$tag"
  fi
  changelog_pr "$tag" "$sha" "$prev"
  echo "release: $tag is live and tagged"
}

main() {
  case "${1:-}" in
    box-release) box_release "${2:?sha}" ;;
    box-rollback) box_rollback ;;
    changelog) changelog_section "${2:?range}" "${3:-## [Unreleased]}" ;;
    rollback) on_box box-rollback ;;
    "" | -h | --help) sed -n '2,20p' "${BASH_SOURCE[0]}" ;;
    *) release "$1" ;;
  esac
}

main "$@"
exit
