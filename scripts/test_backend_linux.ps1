<#
.SYNOPSIS
  Run the backend test suite on Linux against a committed git ref.

.DESCRIPTION
  Windows runs of this suite fail on file locking, MAX_PATH and subprocess lookup
  in ways Linux CI never sees. This runs a ref's committed tree inside the gateway
  image (Python 3.12 venv with dev deps), so results match CI.

  Examples:
    ./scripts/test_backend_linux.ps1
    ./scripts/test_backend_linux.ps1 -Ref my-branch -PytestArgs tests/test_uploads_router.py,-q
#>
param(
  [string]$Ref = 'HEAD',
  [string]$Image = 'deer-flow-gateway:momentum-branding-20260921',
  [string[]]$PytestArgs = @('-m', 'not live', '--ignore=tests/blocking_io', '-q', '-p', 'no:cacheprovider', '--timeout=300', 'tests/'),
  [string]$LogFile
)
$ErrorActionPreference = 'Stop'
$sha = (git rev-parse --short $Ref).Trim()
$tmp = Join-Path ([IO.Path]::GetTempPath()) "deerflow-test-$sha-$PID.tar"
git archive --format=tar -o $tmp $Ref
try {
  $quoted = ($PytestArgs | ForEach-Object { "'" + ($_ -replace "'", "'\''") + "'" }) -join ' '
  $script = @"
set -e
mkdir -p /tmp/src && tar -xf /src.tar -C /tmp/src
cd /app/backend && find . -mindepth 1 -maxdepth 1 ! -name .venv -exec rm -rf {} +
cp -a /tmp/src/. /app/
# Some tests resolve the repo root by its .git marker and diff against it.
# Makefile-contract tests shell out to make, as CI runners have it.
command -v git >/dev/null && command -v make >/dev/null || { apt-get update -qq && apt-get install -y -qq git make >/dev/null; }
cd /app && git init -q && git add -A && git -c user.email=t@t -c user.name=t commit -qm snapshot
cd /app/backend
uv sync --frozen --group dev -q >/dev/null 2>&1 || uv sync --group dev -q
uv pip install -q pytest-timeout >/dev/null
echo "ref $sha"
exec .venv/bin/python -m pytest $quoted
"@
  $cmd = @('run', '--rm', '--mount', "type=bind,source=$($tmp -replace '\\', '/'),target=/src.tar,readonly", '--entrypoint', 'sh', $Image, '-c', $script)
  if ($LogFile) { docker @cmd *> $LogFile } else { docker @cmd }
  exit $LASTEXITCODE
} finally {
  Remove-Item $tmp -ErrorAction SilentlyContinue
}
