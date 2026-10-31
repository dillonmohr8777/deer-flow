param(
    [Parameter(Mandatory=$true)][ValidatePattern('^(0[0-9]|1[0-6])-[a-z-]+$')][string]$Name,
    [Parameter(Mandatory=$true)][string]$TaskRoot,
    [Parameter(Mandatory=$true)][string]$FFmpegBin
)
$ErrorActionPreference = 'Stop'
$env:PATH = $FFmpegBin + ';C:\Program Files\nodejs;' + $env:PATH
$env:HYPERFRAMES_EXTRACT_CACHE_DIR = 'off'
if (Test-Path (Join-Path $TaskRoot 'HOLD.json')) { throw 'Production is held' }
$project = Join-Path $TaskRoot ('projects\' + $Name)
if (!(Test-Path (Join-Path $project 'index.html') -PathType Leaf)) { throw 'Missing exact project index' }
if (!(Test-Path (Join-Path $project 'lesson.json') -PathType Leaf)) { throw 'Missing lesson contract' }
$lesson = Get-Content -Raw (Join-Path $project 'lesson.json') | ConvertFrom-Json
if ($lesson.course_stem -ne $Name -or $lesson.course -ne 'momentum-work') { throw 'Wrong project identity' }
$expected = [double]$lesson.duration
if ($Name.StartsWith('00-')) { if ($expected -lt 480 -or $expected -ge 600) { throw 'Tour duration gate' } }
elseif ($expected -lt 300 -or $expected -gt 360) { throw 'Lesson duration gate' }
$available = (Get-PSDrive -Name ([IO.Path]::GetPathRoot($TaskRoot).Substring(0,1))).Free
if ($available -lt 3GB) { throw 'Insufficient worker disk headroom' }
Set-Location -LiteralPath $project -ErrorAction Stop
if ((Get-Location).Path -ne (Resolve-Path $project).Path) { throw 'Wrong render directory' }
# PS5.1 treats ordinary native stderr as terminating errors under Stop. Capture
# each process through cmd redirection and check its explicit native exit status.
$checkLog = Join-Path $TaskRoot ($Name + '-check.log')
& cmd.exe /d /c "npx.cmd --yes hyperframes@0.8.61 check --snapshots > `"$checkLog`" 2>&1"
if ($LASTEXITCODE -ne 0) { throw 'HyperFrames check failed' }
if (Test-Path (Join-Path $TaskRoot 'HOLD.json')) { throw 'Production is held' }
$output = Join-Path $TaskRoot ($Name + '.mp4')
if (Test-Path $output) { throw 'Preserve existing export; reconcile its receipt before another render' }
$renderLog = Join-Path $TaskRoot ($Name + '-render.log')
& cmd.exe /d /c "npx.cmd --yes hyperframes@0.8.61 render --workers 4 --fps 30 --quality looks --no-best-effort --frames-cache-dir off --output `"$output`" > `"$renderLog`" 2>&1"
if ($LASTEXITCODE -ne 0) { throw 'HyperFrames render failed' }
$probeRaw = & ffprobe -v error -show_format -show_streams -of json $output
if ($LASTEXITCODE -ne 0) { throw 'Export probe failed' }
$probe = ($probeRaw -join "`n") | ConvertFrom-Json
$video = @($probe.streams | Where-Object codec_type -eq 'video')
$audio = @($probe.streams | Where-Object codec_type -eq 'audio')
if ($video.Count -ne 1 -or $audio.Count -ne 1) { throw 'Export must contain one video and one audio stream' }
if ([Math]::Abs([double]$probe.format.duration - $expected) -gt 0.2) { throw 'Export duration differs from narration' }
if ($video[0].width -lt 1280 -or $video[0].height -lt 720 -or $audio[0].codec_name -ne 'aac') { throw 'Export codec or resolution gate' }
$probeRaw | Out-File (Join-Path $TaskRoot ($Name + '-probe.json')) -Encoding utf8
