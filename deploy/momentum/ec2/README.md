# MomoBot prod on AWS EC2

The Lightsail kit (`../lightsail/`) running on one EC2 instance, because the AWS account may not create a
Lightsail plan larger than the smallest sizes. Same compose layers, Caddy (automatic TLS) and nightly S3 backup.
EC2 adds three things:

- **Secrets in memory only.** The instance role (`momobot-ec2`) may read `/momobot/prod/*` in SSM Parameter Store
  and write the backup bucket, nothing else. `secrets.sh` runs before every start and writes `/run/momobot/.env`
  (tmpfs, root 600). These environment credentials stay out of git and backups;
  the private gateway backup still contains its JWT signing secret and user data.
- **The gateway's extra mounts** (`compose.ec2.yaml`): skills, admission, lobby notes, brand kit, evals and the
  two browser guard modules, from `/opt/momobot/data` and `/opt/momobot/code`.
- **systemd drop-ins** (`systemd/`) that point the kit's units at the tmpfs env file and the EC2 layer.

## Layout on the box

```
/opt/momobot/src              git checkout (this repo)
/opt/momobot/config.yaml      gateway config (cloud copy: no Mac-only models, tools or MCP servers)
/opt/momobot/extensions_config.json
/opt/momobot/frontend.env     MOMO_DAILY_CLOUD_OWNER_USER_ID only
/opt/momobot/settings.env     non-secret: MOMOBOT_DOMAIN, MOMOBOT_ACME_EMAIL, image tags, GATEWAY_ENABLE_DOCS
/opt/momobot/data/{skills,admission,lobby-notes,brand,evals}
/opt/momobot/code/{momo_guard.py,momo_protocol.py}
```

## Operate

```bash
sudo systemctl restart momobot          # fetch secrets, then lightsail/up.sh
sudo systemctl start momobot-backup     # backup now; prints the s3:// object
sudo MOMOBOT_ENV_FILE=/run/momobot/.env MOMOBOT_EXTRA_COMPOSE=/opt/momobot/src/deploy/momentum/ec2/compose.ec2.yaml \
  /opt/momobot/src/deploy/momentum/lightsail/up.sh compose logs -f gateway
```

Release: build `deer-flow-{gateway,frontend}:main-<sha8>` on the box from the merged commit, set both tags in
`settings.env`, then `systemctl restart momobot`. Rollback: put the previous tags back and restart.

## Nightly recovery contents

The existing backup timer includes the consistent gateway SQLite snapshot, config and MCP settings,
a Redis-native RDB snapshot verified by `redis-check-rdb`, and the seven EC2 bind mounts listed above.
`ec2-recovery.json` carries only the known non-secret image/domain/frontend-owner settings needed to
recreate `settings.env` and `frontend.env`. Environment files remain excluded; reload credentials
from SSM. The gateway snapshot contains private user data and its JWT signing secret, so keep the
S3 bucket private and encrypted.

For a replacement host, install the merged source and EC2 kit, verify every `MANIFEST.sha256` entry,
restore `gateway-data.tgz` into an empty gateway volume, and restore `ec2-mounts.tgz` under
`/opt/momobot`. Recreate the two non-secret env files from `ec2-recovery.json`. With Redis stopped
and an empty Redis volume, install `redis.rdb` as `dump.rdb` with the image's Redis ownership;
start Redis once without AOF so it loads the snapshot, then enable AOF before starting the stack.
Never overwrite a populated live volume. Snapshot checks are per service, not one atomic cross-service
transaction. A failed Redis or required EC2 mount snapshot fails the backup before its success stamp.

## Not on the box (Mac-only, off in the cloud config)

Brain MCP (Mac bridge :8787), client_browser MCP (:8788), the Jevbox evidence tool (:4310) and the local
Ollama/oMLX models. Reaching them needs a tunnel back to the Mac. That is a follow-up, and MomoBot runs without them.
