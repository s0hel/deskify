# Builds bot/appPackage/deskify-teams.zip for upload to Teams.
# Reads TEAMS_APP_ID, CLIENT_ID and DESKIFY_BOT_PUBLIC_URL from .env at the repo root.
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$cfg = @{}
Get-Content (Join-Path $root '.env') | ForEach-Object {
    if ($_ -match '^\s*([A-Z_]+)\s*=\s*(.*?)\s*$') { $cfg[$Matches[1]] = $Matches[2].Trim('"') }
}
foreach ($k in 'TEAMS_APP_ID', 'CLIENT_ID', 'DESKIFY_BOT_PUBLIC_URL') {
    if (-not $cfg[$k]) { throw "$k is missing from .env" }
}
$domain = ([Uri]$cfg['DESKIFY_BOT_PUBLIC_URL']).Host
$src = Join-Path $PSScriptRoot 'appPackage'
$tmp = Join-Path ([IO.Path]::GetTempPath()) 'deskify-teams-package'
Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory $tmp | Out-Null
(Get-Content (Join-Path $src 'manifest.json') -Raw).
    Replace('${{TEAMS_APP_ID}}', $cfg['TEAMS_APP_ID']).
    Replace('${{BOT_ID}}', $cfg['CLIENT_ID']).
    Replace('${{BOT_DOMAIN}}', $domain) |
    Set-Content (Join-Path $tmp 'manifest.json') -Encoding utf8
Copy-Item (Join-Path $src 'color.png'), (Join-Path $src 'outline.png') $tmp
$zip = Join-Path $src 'deskify-teams.zip'
Remove-Item $zip -ErrorAction SilentlyContinue
Compress-Archive -Path (Join-Path $tmp '*') -DestinationPath $zip
Write-Host "Wrote $zip"
