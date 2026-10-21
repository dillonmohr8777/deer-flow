param(
    [Parameter(Mandatory=$true)][ValidatePattern('^0[1-7]-[a-z-]+$')][string]$Name,
    [Parameter(Mandatory=$true)][string]$TaskRoot,
    [Parameter(Mandatory=$true)][string]$FFmpegBin
)
$ErrorActionPreference = 'Continue'
$env:PATH = $FFmpegBin + ';C:\Program Files\nodejs;' + $env:PATH
$env:HYPERFRAMES_EXTRACT_CACHE_DIR = 'off'
$project = Join-Path $TaskRoot ('projects\' + $Name)
$available = (Get-PSDrive -Name ([IO.Path]::GetPathRoot($TaskRoot).Substring(0,1))).Free
if ($available -lt 3GB) { throw 'Insufficient worker disk headroom' }
Set-Location $project
& npx.cmd --yes hyperframes@0.8.61 check --snapshots 2>&1 | Out-File (Join-Path $TaskRoot ($Name + '-check.log')) -Encoding utf8
if ($LASTEXITCODE -ne 0) { throw 'HyperFrames check failed' }
# The accepted pilot establishes the visual treatment and preview. Each lesson
# still receives its own deterministic check, snapshots, export, and probe.
& npx.cmd --yes hyperframes@0.8.61 render --workers 4 --fps 15 --quality looks --no-best-effort --frames-cache-dir off --output (Join-Path $TaskRoot ($Name + '.mp4')) 2>&1 | Out-File (Join-Path $TaskRoot ($Name + '-render.log')) -Encoding utf8
if ($LASTEXITCODE -ne 0) { throw 'HyperFrames render failed' }
& ffprobe -v error -show_format -show_streams -of json (Join-Path $TaskRoot ($Name + '.mp4')) | Out-File (Join-Path $TaskRoot ($Name + '-probe.json')) -Encoding utf8
if ($LASTEXITCODE -ne 0) { throw 'Export probe failed' }
