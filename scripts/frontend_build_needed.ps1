# Exit 1 when frontend/src is newer than the production build (or .next is missing).
# start.bat then runs `npm run build` so a CSS/TS drop actually reaches `next start`.

param(
    [Parameter(Mandatory = $true)]
    [string] $Root
)

$ErrorActionPreference = "Stop"
$src = Join-Path $Root "frontend\src"
$buildId = Join-Path $Root "frontend\.next\BUILD_ID"
if (-not (Test-Path -LiteralPath $src)) { exit 0 }
if (-not (Test-Path -LiteralPath $buildId)) { exit 1 }
$newest = Get-ChildItem -LiteralPath $src -Recurse -File -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTimeUtc -Descending |
    Select-Object -First 1
if (-not $newest) { exit 0 }
$built = Get-Item -LiteralPath $buildId
if ($newest.LastWriteTimeUtc -gt $built.LastWriteTimeUtc) { exit 1 }
exit 0
