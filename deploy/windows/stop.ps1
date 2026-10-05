# Stop Kith Contacts on Windows (I-13, ADR-0019). Your contacts and backups are kept.
# Keep this file plain ASCII: Windows PowerShell 5.1 reads files without a BOM as ANSI.

$ErrorActionPreference = 'Continue'
$Program = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$Data = Join-Path $env:USERPROFILE 'KithContacts'
$Settings = Join-Path $Data 'settings.env'

function Finish([int]$Code) {
    Write-Host ''
    Read-Host 'Press Enter to close this window' | Out-Null
    exit $Code
}

Write-Host 'Stopping Kith Contacts...'
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    $bin = Join-Path $env:ProgramFiles 'Docker\Docker\resources\bin'
    if (Test-Path (Join-Path $bin 'docker.exe')) { $env:Path = "$env:Path;$bin" }
}
& docker info *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Host 'Docker Desktop is not running, so Kith Contacts is already stopped.'
    Finish 0
}
if (-not (Test-Path -LiteralPath $Settings)) {
    Write-Host 'Kith Contacts has not been started on this computer yet.'
    Finish 0
}
$env:CONTACTS_BACKUPS = (Join-Path $Data 'Backups') -replace '\\', '/'
$env:APP_VERSION = (Select-String -LiteralPath (Join-Path $Program 'pyproject.toml') -Pattern '^version = "(.*)"' |
    Select-Object -First 1).Matches[0].Groups[1].Value
& docker compose --project-name kith-contacts --env-file $Settings -f (Join-Path $Program 'compose.yaml') `
    --profile work --profile personal stop
if ($LASTEXITCODE -eq 0) {
    Write-Host 'Stopped. Your contacts and backups are kept; Start Kith Contacts brings them back.'
    Finish 0
}
Write-Host 'Kith Contacts could not be stopped. Quit Docker Desktop instead.'
Finish 1
