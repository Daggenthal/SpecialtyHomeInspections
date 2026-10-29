# Puts a "Website Editor" icon on the desktop and in the Start menu.
# The icon opens the editor (on the Raspberry Pi, reached over Tailscale) in its own
# Edge window, without an address bar, so it looks and feels like a normal program.
# Nothing else is installed and nothing runs in the background.
param([string]$Url = "__EDITOR_URL__")

$ErrorActionPreference = "Stop"
$name = "Website Editor"

function Find-Edge {
    $paths = @(
        "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe",
        "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe",
        "$env:LOCALAPPDATA\Microsoft\Edge\Application\msedge.exe"
    )
    foreach ($p in $paths) { if ($p -and (Test-Path $p)) { return $p } }
    return $null
}

Write-Host ""
Write-Host "Setting up the $name..." -ForegroundColor Cyan

# 1. Tailscale is the private connection to the Pi. Offer to install it if it's missing.
$ts = Get-Command tailscale -ErrorAction SilentlyContinue
if (-not $ts -and -not (Test-Path "$env:ProgramFiles\Tailscale\tailscale.exe")) {
    Write-Host "Tailscale isn't installed yet. It's the private connection to the editor." -ForegroundColor Yellow
    $a = Read-Host "Install it now? (Y/n)"
    if ($a -eq "" -or $a -match "^[Yy]") {
        winget install --id tailscale.tailscale -e --accept-source-agreements --accept-package-agreements
        Write-Host "Now sign in to Tailscale (its icon is by the clock), then run this again." -ForegroundColor Yellow
        Read-Host "Press Enter to close"
        exit 0
    }
}

# 2. The icon
$edge = Find-Edge
if (-not $edge) { throw "Microsoft Edge wasn't found. It comes with Windows 11; reinstall it from microsoft.com/edge." }
$home_ = Join-Path $env:LOCALAPPDATA "WebsiteEditor"
New-Item -ItemType Directory -Force -Path $home_ | Out-Null
$icon = Join-Path $home_ "editor.ico"
$src = Join-Path $PSScriptRoot "editor.ico"
if (Test-Path $src) { Copy-Item $src $icon -Force } else { $icon = "$edge,0" }

$shell = New-Object -ComObject WScript.Shell
$places = @([Environment]::GetFolderPath("Desktop"), [Environment]::GetFolderPath("Programs"))
foreach ($dir in $places) {
    $lnk = $shell.CreateShortcut((Join-Path $dir "$name.lnk"))
    $lnk.TargetPath = $edge
    $lnk.Arguments = "--app=$Url --window-size=1400,900"
    $lnk.IconLocation = $icon
    $lnk.Description = "Change and publish the business website"
    $lnk.WorkingDirectory = $home_
    $lnk.Save()
}

# 3. Quick check that the Pi answers
try {
    $u = [Uri]$Url
    $ok = Test-NetConnection -ComputerName $u.Host -Port $u.Port -InformationLevel Quiet -WarningAction SilentlyContinue
} catch { $ok = $false }

Write-Host ""
Write-Host "Done. Double-click '$name' on the desktop (it's in the Start menu too)." -ForegroundColor Green
if (-not $ok) {
    Write-Host "Heads up: the editor didn't answer just now. Make sure Tailscale is on (icon by the clock)." -ForegroundColor Yellow
}
Read-Host "Press Enter to close"
