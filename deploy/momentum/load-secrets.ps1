# Loads the service-only credentials kept inside the gateway data volume into this
# process's environment. Creates them once if the volume has none. Never prints them.
param(
  [Parameter(Mandatory)][string]$Volume,
  [Parameter(Mandatory)][string]$GatewayImage
)
$py = @'
import json, os, secrets
from pathlib import Path
p = Path('/runtime/.deployment-secrets.json')
try:
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
except FileExistsError:
    pass
else:
    with os.fdopen(fd, 'w') as f:
        json.dump({'internal_auth': secrets.token_urlsafe(48), 'frontend_auth': secrets.token_urlsafe(48)}, f)
print(p.read_text())
'@
$json = docker run --rm --network none --read-only --mount "type=volume,source=$Volume,target=/runtime" --entrypoint python $GatewayImage -c $py
if ($LASTEXITCODE -ne 0) { throw "Cannot load service credentials from volume $Volume" }
$s = $json | ConvertFrom-Json
if (!$s.internal_auth -or !$s.frontend_auth) { throw 'Incomplete service credentials' }
$env:DEER_FLOW_INTERNAL_AUTH_TOKEN = $s.internal_auth
$env:BETTER_AUTH_SECRET = $s.frontend_auth
$json = $null; $s = $null
