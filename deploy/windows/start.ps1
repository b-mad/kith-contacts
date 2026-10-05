# Start Kith Contacts on Windows (I-13, ADR-0019).
# Run by double-clicking "Start Kith Contacts.bat". Works in Windows PowerShell 5.1 and later.
# Keep this file plain ASCII: Windows PowerShell 5.1 reads files without a BOM as ANSI.

$ErrorActionPreference = 'Continue'
$Program = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$Data = Join-Path $env:USERPROFILE 'KithContacts'
$Settings = Join-Path $Data 'settings.env'
$Project = 'kith-contacts'

function Finish([int]$Code) {
    Write-Host ''
    Read-Host 'Press Enter to close this window' | Out-Null
    exit $Code
}

function Get-Setting([string]$Key) {
    $line = Get-Content -LiteralPath $Settings -ErrorAction SilentlyContinue |
        Where-Object { $_ -match "^$Key=" } | Select-Object -Last 1
    if (-not $line) { return '' }
    return ($line -replace "^$Key=", '').Trim('"')
}

function Clean-Name([string]$Value, [string]$Default) {
    $v = ($Value -replace '["$\\`]', '').Trim()
    if ($v.Length -gt 40) { $v = $v.Substring(0, 40) }
    if ($v) { return $v } else { return $Default }
}

function Test-Docker {
    & docker info *> $null
    return ($LASTEXITCODE -eq 0)
}

function First-Start {
    Write-Host ''
    Write-Host 'First start: two quick questions.'
    Write-Host ''
    Write-Host 'Which contact books do you want?'
    Write-Host '  1  Work      (colleagues, customers, vendors)'
    Write-Host '  2  Personal  (family, friends, services)'
    Write-Host '  3  Both'
    $pick = Read-Host 'Type 1, 2 or 3 and press Enter [1]'
    switch ($pick.Trim()) {
        '2' { $profiles = 'personal' }
        '3' { $profiles = 'work,personal' }
        default { $profiles = 'work' }
    }
    $workName = 'Work'
    $personalName = 'Personal'
    if ($profiles -like '*work*') {
        $workName = Clean-Name (Read-Host 'Name for your work contact book [Work]') 'Work'
    }
    if ($profiles -like '*personal*') {
        $personalName = Clean-Name (Read-Host 'Name for your personal contact book [Personal]') 'Personal'
    }
    $region = 'US'
    try {
        $name = (Get-Culture).Name
        if ($name -match '-([A-Z]{2})$') { $region = $Matches[1] }
    } catch { }
    $text = @"
# Kith Contacts settings. Change a value, then double-click "Start Kith Contacts" again.
# No passwords are kept here.

# Contact books to run: work, personal, or work,personal
COMPOSE_PROFILES=$profiles

WORK_NAME="$workName"
WORK_COLOR="#1f6feb"
WORK_TYPES="Employee,Customer,Vendor"
WORK_PORT=5170

PERSONAL_NAME="$personalName"
PERSONAL_COLOR="#8250df"
PERSONAL_TYPES="Family,Friend,Service provider"
PERSONAL_PORT=5171

# Country for phone numbers typed without a +code (two letters, e.g. US, GB, CA)
PHONE_REGION=$region

"@
    New-Item -ItemType Directory -Force -Path $Data | Out-Null
    # UTF-8 without a byte order mark, which Docker Compose expects
    [System.IO.File]::WriteAllText($Settings, ($text -replace "`r`n", "`n"), (New-Object System.Text.UTF8Encoding $false))
    Write-Host ''
    Write-Host "Saved your answers in $Settings"
}

Write-Host 'Kith Contacts'
Write-Host '==============='

# 1. Docker Desktop installed?
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    $bin = Join-Path $env:ProgramFiles 'Docker\Docker\resources\bin'
    if (Test-Path (Join-Path $bin 'docker.exe')) {
        $env:Path = "$env:Path;$bin"
    } else {
        Write-Host ''
        Write-Host 'Docker Desktop is not installed yet. It is free and runs Kith Contacts.'
        Write-Host "Opening the download page. Install it (step 1 in 'Start here'), then try again."
        Start-Process 'https://www.docker.com/products/docker-desktop/'
        Finish 1
    }
}

# 2. Docker Desktop running?
if (-not (Test-Docker)) {
    Write-Host ''
    Write-Host 'Starting Docker Desktop. This can take a minute...'
    $desktop = Join-Path $env:ProgramFiles 'Docker\Docker\Docker Desktop.exe'
    if (Test-Path $desktop) {
        Start-Process $desktop
    } else {
        Write-Host 'Could not find Docker Desktop. Open it from the Start menu, then try again.'
        Finish 1
    }
    for ($i = 0; $i -lt 90; $i++) {
        if (Test-Docker) { break }
        Write-Host -NoNewline '.'
        Start-Sleep -Seconds 2
    }
    Write-Host ''
    if (-not (Test-Docker)) {
        Write-Host 'Docker Desktop did not finish starting within 3 minutes.'
        Write-Host "Open Docker Desktop, wait until it shows 'Engine running', then try again."
        Finish 1
    }
}

# 3. Settings (first start only) and folders
if (-not (Test-Path -LiteralPath $Settings)) { First-Start }
New-Item -ItemType Directory -Force -Path (Join-Path (Join-Path $Data 'Backups') 'work') | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path (Join-Path $Data 'Backups') 'personal') | Out-Null

# 4. Build and start
$version = (Select-String -LiteralPath (Join-Path $Program 'pyproject.toml') -Pattern '^version = "(.*)"' |
    Select-Object -First 1).Matches[0].Groups[1].Value
$env:APP_VERSION = $version
$env:CONTACTS_BACKUPS = (Join-Path $Data 'Backups') -replace '\\', '/'
Write-Host ''
Write-Host "Starting Kith Contacts $version."
Write-Host 'The first start, and the first start after an update, take 5 to 10 minutes.'
& docker compose --project-name $Project --env-file $Settings -f (Join-Path $Program 'compose.yaml') `
    up -d --build --remove-orphans --wait --wait-timeout 300
if ($LASTEXITCODE -ne 0) {
    Write-Host ''
    Write-Host 'Kith Contacts could not start. Look at the last lines above:'
    Write-Host " - 'port is already allocated' or 'address already in use': another program uses the"
    Write-Host "   port. Close it, or change WORK_PORT / PERSONAL_PORT in $Settings."
    Write-Host " - 'failed to resolve' or 'network': check the internet connection and try again."
    Write-Host " - anything else: see 'Something went wrong' in Start here."
    Finish 1
}

# 5. Open the contact books
$profiles = Get-Setting 'COMPOSE_PROFILES'
Write-Host ''
if ($profiles -like '*work*') {
    $url = 'http://localhost:' + (Get-Setting 'WORK_PORT')
    Write-Host ((Get-Setting 'WORK_NAME') + ': ' + $url)
    Start-Process $url
}
if ($profiles -like '*personal*') {
    $url = 'http://localhost:' + (Get-Setting 'PERSONAL_PORT')
    Write-Host ((Get-Setting 'PERSONAL_NAME') + ': ' + $url)
    Start-Process $url
}
Write-Host ''
Write-Host 'Kith Contacts is running. Bookmark the page in your browser.'
Write-Host 'It keeps running in Docker Desktop, also after a restart, until you use Stop Kith Contacts.'
Write-Host ('Backups are saved daily in ' + (Join-Path $Data 'Backups'))
Finish 0
