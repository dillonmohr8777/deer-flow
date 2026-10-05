#!/usr/bin/env bash
# Point the Mac stack's Google sign-in at a new public host. Default is a dry run
# (prints the diff). --apply backs up $DEPLOY/{config.yaml,.env} first and edits
# them; it does NOT restart anything. Restart with ../restart.sh afterward.
# Rollback: ./set-public-host.sh dillons-mac-mini.tailade026.ts.net --apply
set -euo pipefail
host="${1:?usage: set-public-host.sh <host> [--apply]}"; mode="${2:-}"
D="${MOMOBOT_DEPLOY_DIR:-$HOME/momobot-prod}"
[[ "$host" =~ ^[a-z0-9.-]+$ ]] || { echo "bad host" >&2; exit 2; }
python3 - "$D" "$host" "$mode" <<'PY'
import sys,re,shutil,difflib,time
D,host,mode=sys.argv[1:4]
edits={
 f"{D}/config.yaml":[(r"(frontend_base_url:\s*)https://\S+",rf"\1https://{host}"),
                      (r"(redirect_uri:\s*)https://[^/\s]+(/api/v1/auth/callback/google)",rf"\1https://{host}\2")],
 f"{D}/.env":[(r"(?m)^(MOMOBOT_DOMAIN=).*$",rf"\g<1>{host}")],
}
for p,subs in edits.items():
    old=open(p).read(); new=old
    for pat,rep in subs: new=re.sub(pat,rep,new)
    if new==old: print(f"{p}: already {host}"); continue
    if p.endswith(".env"): print(f"{p}: MOMOBOT_DOMAIN -> {host}")  # never echo .env content
    else: sys.stdout.writelines(difflib.unified_diff(old.splitlines(1),new.splitlines(1),p,p))
    if mode=="--apply":
        shutil.copy2(p,f"{p}.bak-{time.strftime('%Y%m%d-%H%M%S')}"); open(p,"w").write(new)
print("applied" if mode=="--apply" else "dry run (add --apply)")
PY
