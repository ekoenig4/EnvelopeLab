<#
.SYNOPSIS
    Set up EnvelopeLab on Windows: Python, a virtualenv and the Python package, then check
    that the library and the desktop application start.

.DESCRIPTION
    Windows needs no system libraries (the Qt, VTK and Gmsh wheels bring their own). The
    script:

      1. finds Python 3.11 or newer (the "py" launcher first, then "python"), or installs
         Python 3.12 with winget when -InstallPython is given;
      2. creates the virtualenv .venv and runs pip install -e ".[gui,fast]" (-Dev: also the
         test and docs tools, and the pre-commit hooks);
      3. checks that the library and Gmsh import, reports whether CalculiX (ccx) is found,
         and starts the main window headless to prove Qt works;
      4. with -Shortcut, puts an "EnvelopeLab" shortcut on the desktop.

    Run it from a checkout of the repository. When PowerShell refuses to run scripts
    ("running scripts is disabled on this system"), use scripts\install_env.cmd instead,
    which starts this script with the execution policy bypassed for that one run.

.EXAMPLE
    scripts\install_env.cmd
.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\install_env.ps1 -InstallPython -Shortcut
.EXAMPLE
    scripts\install_env.cmd -Dev
#>
[CmdletBinding()]
param(
    # pip extras to install (default: the application with the compiled solver kernel).
    [string]$Extras = "gui,fast",
    # Developer setup: extras dev,docs,gui,fast and the pre-commit hooks.
    [switch]$Dev,
    # Virtualenv directory, relative to the repository (default .venv).
    [string]$Venv = ".venv",
    # Python >= 3.11 used to create the virtualenv (default: found automatically).
    [string]$Python = "",
    # Install Python 3.12 with winget when no suitable Python is found.
    [switch]$InstallPython,
    # Put an EnvelopeLab shortcut on the desktop.
    [switch]$Shortcut,
    # Skip the final checks.
    [switch]$NoCheck,
    # Print the commands without running them.
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
if ($Dev) { $Extras = "dev,docs,gui,fast" }
$ExtrasList = $Extras.Split(",") | ForEach-Object { $_.Trim() } | Where-Object { $_ }

# The virtualenv layout: Scripts\*.exe on Windows. PowerShell 7 on Linux or macOS (used to
# test this script) has bin/* instead; Windows PowerShell 5.1 has no $IsLinux ($null).
$VenvDir = if ([System.IO.Path]::IsPathRooted($Venv)) { $Venv } else { Join-Path $Root $Venv }
if ($IsLinux -or $IsMacOS) { $Bin = "bin"; $Exe = "" } else { $Bin = "Scripts"; $Exe = ".exe" }
$VenvPython = Join-Path (Join-Path $VenvDir $Bin) "python$Exe"
$App = Join-Path (Join-Path $VenvDir $Bin) "envelopelab$Exe"

function Say([string]$Text) { Write-Host "`n==> $Text" -ForegroundColor Cyan }

function Run([string]$Exe, [string[]]$Arguments) {
    Write-Host "  $Exe $($Arguments -join ' ')"
    if ($DryRun) { return }
    & $Exe @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "command failed (exit code $LASTEXITCODE): $Exe $($Arguments -join ' ')"
    }
}

# A Python candidate is a command plus leading arguments, e.g. ("py", "-3.12").
function Test-Python([string]$Exe, [string[]]$Prefix) {
    if (-not (Get-Command $Exe -ErrorAction SilentlyContinue)) { return $null }
    try {
        # The Microsoft Store "python.exe" stub prints nothing useful and fails here.
        $out = & $Exe @Prefix -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
    } catch { return $null }
    if ($LASTEXITCODE -ne 0 -or -not $out) { return $null }
    $version = [version]("$out".Trim())
    if ($version -lt [version]"3.11") { return $null }
    return [pscustomobject]@{ Exe = $Exe; Prefix = $Prefix; Version = $version }
}

function Find-Python {
    if ($Python) {
        $found = Test-Python $Python @()
        if (-not $found) { throw "$Python is not Python 3.11 or newer" }
        return $found
    }
    # 3.12 and 3.13 first: every dependency (Qt, VTK, Gmsh, Numba) has wheels for them.
    foreach ($v in "3.12", "3.13", "3.11") {
        $found = Test-Python "py" @("-$v")
        if ($found) { return $found }
    }
    foreach ($exe in "python", "python3") {
        $found = Test-Python $exe @()
        if ($found) { return $found }
    }
    return $null
}

# --- 1. Python --------------------------------------------------------------------------
Say "Python"
$py = Find-Python
if (-not $py -and $InstallPython) {
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        throw "winget is not available: install Python 3.12 from https://www.python.org/downloads/windows/ (tick 'Add python.exe to PATH') and run this script again"
    }
    Run "winget" @("install", "--id", "Python.Python.3.12", "--exact", "--scope", "user",
        "--accept-package-agreements", "--accept-source-agreements")
    # winget changes PATH for new windows only: read it again for this one.
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "User") + ";" +
        [Environment]::GetEnvironmentVariable("Path", "Machine")
    if (-not $DryRun) { $py = Find-Python }
}
if (-not $py) {
    if ($DryRun) {
        $py = [pscustomobject]@{ Exe = "py"; Prefix = @("-3.12"); Version = [version]"3.12" }
    } else {
        Write-Host @"
No Python 3.11 or newer was found.
  * Run this script again with -InstallPython (installs Python 3.12 with winget), or
  * install Python 3.12 from https://www.python.org/downloads/windows/ and tick
    'Add python.exe to PATH' in the installer, then run this script again.
"@ -ForegroundColor Yellow
        exit 1
    }
}
Write-Host "  using $($py.Exe) $($py.Prefix -join ' ') (Python $($py.Version))"
if ($py.Version -ge [version]"3.14") {
    Write-Host "  warning: Python $($py.Version) is newer than the tested versions (3.11-3.13); if pip fails, install Python 3.12 and pass it with -Python" -ForegroundColor Yellow
}

# --- 2. Virtualenv and package -----------------------------------------------------------
Say "virtualenv $VenvDir"
if (Test-Path $VenvPython) {
    Write-Host "  exists, reused"
} else {
    Run $py.Exe ($py.Prefix + @("-m", "venv", $VenvDir))
}

Say "EnvelopeLab with extras: $($ExtrasList -join ', ')"
Run $VenvPython @("-m", "pip", "install", "--upgrade", "pip")
Run $VenvPython @("-m", "pip", "install", "-e", ".[$($ExtrasList -join ',')]")
if ($ExtrasList -contains "dev") {
    if (Test-Path (Join-Path $Root ".git")) {
        Run $VenvPython @("-m", "pre_commit", "install")
    } else {
        Write-Host "  not a git checkout: pre-commit hooks not installed"
    }
}

# --- 3. Checks ----------------------------------------------------------------------------
$failed = @()
if (-not $NoCheck -and -not $DryRun) {
    Say "checks"
    & $VenvPython -c "import envelopelab; print('envelopelab: ok')"
    if ($LASTEXITCODE -ne 0) { $failed += "envelopelab import" }
    & $VenvPython -c "import gmsh; print(f'gmsh: {gmsh.__version__}')"
    if ($LASTEXITCODE -ne 0) { $failed += "gmsh import" }
    @'
try:
    from calculix_adapter import find_calculix
except ImportError:
    print("CalculiX adapter: not installed")
else:
    found = find_calculix()
    print(f"CalculiX: {found.version} at {found.executable}" if found else
          "CalculiX: ccx not found (optional: Run CalculiX will be disabled; "
          "see docs/dev/calculix-installation.md)")
'@ | & $VenvPython -
    if ($ExtrasList -contains "gui") {
        # Start the main window headless: proves Qt, PySide6 and the app import and run.
        $env:QT_QPA_PLATFORM = "offscreen"
        @'
import tempfile
from pathlib import Path

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

app = QApplication([])
from envelopelab_app.main_window import MainWindow

with tempfile.TemporaryDirectory() as tmp:
    settings = QSettings(str(Path(tmp) / "settings.ini"), QSettings.Format.IniFormat)
    settings.setValue("preferences/recovery_dir", str(Path(tmp) / "recovery"))
    window = MainWindow(settings, enable_3d=False, interactive=False)
    window.show()
    app.processEvents()
    window.close()
print("desktop application: starts (headless check)")
'@ | & $VenvPython -
        if ($LASTEXITCODE -ne 0) { $failed += "desktop application start" }
        Remove-Item Env:\QT_QPA_PLATFORM
    }
}

# --- 4. Desktop shortcut --------------------------------------------------------------------
if ($Shortcut -and ($ExtrasList -contains "gui")) {
    Say "desktop shortcut"
    $desktop = [Environment]::GetFolderPath("Desktop")
    if (-not $desktop) {
        Write-Host "  no desktop folder: shortcut not made"
    } else {
        $link = Join-Path $desktop "EnvelopeLab.lnk"
        Write-Host "  $link -> $App"
    }
    if ($desktop -and -not $DryRun) {
        $shell = New-Object -ComObject WScript.Shell
        $item = $shell.CreateShortcut($link)
        $item.TargetPath = $App
        $item.WorkingDirectory = $Root
        $item.Save()
    }
}

if ($failed.Count -gt 0) {
    Write-Host "`nFAILED: $($failed -join ', ')" -ForegroundColor Red
    exit 1
}
Say "done"
Write-Host @"
Start EnvelopeLab with:
  $App
or, after activating the virtualenv (cmd: $VenvDir\Scripts\activate.bat), with: envelopelab
Activating it in PowerShell needs scripts allowed once:
  Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
If the window stays black or the 3D view fails: envelopelab --software-gl (or --no-3d).
"@
