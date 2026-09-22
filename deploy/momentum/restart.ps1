<#
.SYNOPSIS
  Start or restart the Momentum DeerFlow stack from this repo.

.DESCRIPTION
  Replaces Codex/2026-09-20/.../Restart-DeerFlow-Workspace.ps1, which broke once
  its deploy worktree and secrets image were removed. Everything it needs is in
  the repo except .env (API keys) and the gateway data volume.

  -WhatIfOnly renders the merged compose config and changes nothing.
  --no-build is deliberate: only verified image tags run here.
#>
[CmdletBinding()]
param(
  [string]$ProjectName = 'deer-flow',
  [string]$ConfigPath,
  [string]$EnvFile,
  [string]$ExtensionsConfigPath,
  [string]$TailnetHost,
  [string[]]$ExtraComposeFile = @(),
  [int]$Port = 2026,
  [switch]$WhatIfOnly
)
$ErrorActionPreference = 'Stop'
$Repo = (Resolve-Path "$PSScriptRoot/../..").Path -replace '\\', '/'
if (!$ConfigPath) { $ConfigPath = "$Repo/deploy/momentum/workspace.config.yaml" }
if (!$EnvFile) { $EnvFile = "$Repo/.env" }
if (!$ExtensionsConfigPath) { $ExtensionsConfigPath = "$Repo/extensions_config.json" }
if (!$TailnetHost) {
  $ts = Get-Command tailscale -ErrorAction SilentlyContinue
  $TailnetHost = if ($ts) { (tailscale ip -4 2>$null | Select-Object -First 1) } else { '' }
  if (!$TailnetHost) { $TailnetHost = '127.0.0.1' }
}

docker info 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) { Write-Error 'Docker engine not reachable. Start Docker Desktop and re-run.'; exit 2 }

$env:COMPOSE_PROJECT_NAME = $ProjectName
$env:PORT = "$Port"
$env:MOMENTUM_TAILNET_HOST = $TailnetHost
$env:DEER_FLOW_CONFIG_PATH = $ConfigPath -replace '\\', '/'
$env:DEER_FLOW_EXTENSIONS_CONFIG_PATH = $ExtensionsConfigPath -replace '\\', '/'
$env:DEER_FLOW_HOME = "$Repo/backend/.deer-flow"

$base = @('compose', '--env-file', $EnvFile, '-p', $ProjectName,
  '-f', "$Repo/docker/docker-compose.yaml",
  '-f', "$Repo/docker/docker-compose.dood.yaml",
  '-f', "$Repo/deploy/momentum/compose.momentum.yaml")
foreach ($f in $ExtraComposeFile) { $base += @('-f', $f) }

if ($WhatIfOnly) { docker @base config; exit $LASTEXITCODE }

$gatewayImage = (docker @base config --images | Select-String 'deer-flow-gateway' | Select-Object -First 1).ToString().Trim()
. "$PSScriptRoot/load-secrets.ps1" -Volume "${ProjectName}_gateway-data" -GatewayImage $gatewayImage

docker @base up -d --no-build --wait --wait-timeout 180 gateway frontend nginx redis
if ($LASTEXITCODE -ne 0) { Write-Error "Stack not ready. Check: docker compose -p $ProjectName ps"; exit $LASTEXITCODE }

$deadline = (Get-Date).AddSeconds(120)
do {
  try { $code = (Invoke-WebRequest "http://127.0.0.1:$Port/" -UseBasicParsing -TimeoutSec 10).StatusCode } catch { $code = $null }
  if ($code -eq 200) { break }
  Start-Sleep 2
} while ((Get-Date) -lt $deadline)
if ($code -ne 200) { Write-Error "http://127.0.0.1:$Port/ did not return 200"; exit 3 }
Write-Output "UI http://127.0.0.1:$Port/ -> 200 (tailnet listener: ${TailnetHost}:$Port)"
