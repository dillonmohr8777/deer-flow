<#
.SYNOPSIS
  Daily and at-logon health check for the Momentum stack. Repairs the one known
  failure it can fix safely, appends a receipt, and exits 1 if anything is wrong.

.DESCRIPTION
  Checks: Docker reachable; the main UI and /health/ready on -Port; the newest
  offsite backup receipt is younger than -MaxBackupAgeHours. The rehearsal port is
  recorded but does not fail the check, since rehearsal is often down on purpose.

  Repair: after an unclean shutdown Docker Desktop can restart the nginx container
  before Tailscale has its 100.x address. The tailnet binding in
  compose.momentum.yaml then fails, Docker drops the whole publish, and nginx runs
  with no host port at all (seen 2026-09-24 10:56). If the main port is down and
  nginx has no published port, restart that one container once. Nothing else is
  touched: no rebuild, no compose up, no volume change.
#>
param(
  [int]$Port = 2026,
  [int]$RehearsalPort = 2027,
  [string]$Nginx = 'deer-flow-nginx',
  [string]$BackupDir = "$env:USERPROFILE\OneDrive\MomoBot-Backups",
  [int]$MaxBackupAgeHours = 26,
  [string]$Log = "$env:LOCALAPPDATA\MomoBot\health.jsonl"
)
function Probe($url) { try { (Invoke-WebRequest $url -UseBasicParsing -TimeoutSec 10).StatusCode } catch { 0 } }

$r = [ordered]@{ at = (Get-Date).ToString('o'); docker = $false; main = 0; ready = 0; rehearsal = 0; repaired = $false; backupAgeHours = $null; ok = $false }
docker info *> $null
$r.docker = ($LASTEXITCODE -eq 0)
if ($r.docker) {
  $r.main = Probe "http://127.0.0.1:$Port/"
  if ($r.main -ne 200 -and -not (docker port $Nginx 2>$null)) {
    docker restart $Nginx *> $null
    Start-Sleep 8
    $r.repaired = $true
    $r.main = Probe "http://127.0.0.1:$Port/"
  }
  $r.ready = Probe "http://127.0.0.1:$Port/health/ready"
  $r.rehearsal = Probe "http://127.0.0.1:$RehearsalPort/"
}
$newest = Get-ChildItem $BackupDir -Filter '*.receipt.json' -ErrorAction SilentlyContinue |
  Sort-Object LastWriteTime -Descending | Select-Object -First 1
if ($newest) { $r.backupAgeHours = [math]::Round(((Get-Date) - $newest.LastWriteTime).TotalHours, 1) }
$r.ok = $r.docker -and $r.main -eq 200 -and $r.ready -eq 200 -and
  $null -ne $r.backupAgeHours -and $r.backupAgeHours -le $MaxBackupAgeHours

New-Item -ItemType Directory -Force (Split-Path $Log) | Out-Null
($r | ConvertTo-Json -Compress) | Add-Content $Log
$r | ConvertTo-Json
exit ([int](-not $r.ok))
