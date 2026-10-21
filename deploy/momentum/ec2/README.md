# MomoBot prod on AWS EC2

The Lightsail kit (`../lightsail/`) running on one EC2 instance, because the AWS account may not create a
Lightsail plan larger than the smallest sizes. Same compose layers, Caddy (automatic TLS) and nightly S3 backup.
EC2 adds three things:

- **Secrets in memory only.** The instance role (`momobot-ec2`) may read `/momobot/prod/*` in SSM Parameter Store
  and write the backup bucket, nothing else. `secrets.sh` runs before every start and writes `/run/momobot/.env`
  (tmpfs, root 600). Nothing secret is on disk, in git or in the backups.
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

## Not on the box (Mac-only, off in the cloud config)

Brain MCP (Mac bridge :8787), client_browser MCP (:8788), the Jevbox evidence tool (:4310) and the local
Ollama/oMLX models. Reaching them needs a tunnel back to the Mac. That is a follow-up, and MomoBot runs without them.
