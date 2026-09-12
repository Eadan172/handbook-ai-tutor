# Fingerprint of launcher-relevant files so start.bat can tell a code/config
# drop from the process that is already listening on :8000 / :3000.
# Prints one hex line to stdout. Does not touch the system PATH.

param(
    [Parameter(Mandatory = $true)]
    [string] $Root
)

$ErrorActionPreference = "Stop"
$parts = New-Object System.Collections.Generic.List[string]

function Add-PathStamp([string] $rel) {
    $full = Join-Path $Root $rel
    if (-not (Test-Path -LiteralPath $full)) { return }
    $item = Get-Item -LiteralPath $full
    if ($item.PSIsContainer) {
        Get-ChildItem -LiteralPath $full -Recurse -File -ErrorAction SilentlyContinue |
            Sort-Object FullName |
            ForEach-Object {
                $parts.Add("$($_.FullName)|$($_.Length)|$($_.LastWriteTimeUtc.Ticks)")
            }
    } else {
        $parts.Add("$($item.FullName)|$($item.Length)|$($item.LastWriteTimeUtc.Ticks)")
    }
}

Add-PathStamp "start.bat"
Add-PathStamp ".env"
Add-PathStamp "backend\app"
Add-PathStamp "frontend\src"
Add-PathStamp "frontend\.next\BUILD_ID"

$sha = [System.Security.Cryptography.SHA256]::Create()
$bytes = [System.Text.Encoding]::UTF8.GetBytes(($parts -join "`n"))
$hash = [System.BitConverter]::ToString($sha.ComputeHash($bytes)).Replace("-", "").ToLowerInvariant()
Write-Output $hash
