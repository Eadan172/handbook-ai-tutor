# Download a local ffmpeg/ffprobe into tools\ffmpeg\bin.
# Called by start.bat. Does not touch the system PATH.
# Quiet on success; prints one line when it actually downloads.

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Dest = Join-Path $Root "tools\ffmpeg\bin"
$Ffmpeg = Join-Path $Dest "ffmpeg.exe"
if (Test-Path -LiteralPath $Ffmpeg) { exit 0 }

$Urls = @(
    "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip",
    "https://github.com/GyanD/codexffmpeg/releases/download/8.0/ffmpeg-8.0-essentials_build.zip"
)

$Tmp = Join-Path $env:TEMP ("handbook-ffmpeg-" + [guid]::NewGuid().ToString("n"))
New-Item -ItemType Directory -Path $Tmp | Out-Null
$Zip = Join-Path $Tmp "ffmpeg.zip"

try {
    $client = New-Object System.Net.WebClient
    $downloaded = $false
    foreach ($url in $Urls) {
        try {
            Write-Host "  [ffmpeg] downloading $url"
            $client.DownloadFile($url, $Zip)
            if ((Get-Item -LiteralPath $Zip).Length -gt 1000000) {
                $downloaded = $true
                break
            }
        } catch {
            Write-Host "  [ffmpeg] download failed: $($_.Exception.Message)"
        }
    }
    if (-not $downloaded) {
        Write-Host "  [ffmpeg] could not download. Put ffmpeg.exe and ffprobe.exe in $Dest"
        exit 1
    }
    Expand-Archive -LiteralPath $Zip -DestinationPath $Tmp -Force
    $found = Get-ChildItem -Path $Tmp -Recurse -Filter "ffmpeg.exe" | Select-Object -First 1
    if (-not $found) {
        Write-Host "  [ffmpeg] zip had no ffmpeg.exe"
        exit 1
    }
    New-Item -ItemType Directory -Path $Dest -Force | Out-Null
    Copy-Item -LiteralPath $found.FullName -Destination (Join-Path $Dest "ffmpeg.exe") -Force
    $probe = Join-Path $found.DirectoryName "ffprobe.exe"
    if (Test-Path -LiteralPath $probe) {
        Copy-Item -LiteralPath $probe -Destination (Join-Path $Dest "ffprobe.exe") -Force
    }
    Write-Host "  [ffmpeg] installed to $Dest"
    exit 0
} catch {
    Write-Host "  [ffmpeg] bootstrap failed: $($_.Exception.Message)"
    exit 1
} finally {
    Remove-Item -LiteralPath $Tmp -Recurse -Force -ErrorAction SilentlyContinue
}
