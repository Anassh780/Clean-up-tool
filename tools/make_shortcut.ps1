<#
.SYNOPSIS
    Put a "Sweep Web" shortcut on the current user's Desktop.

.DESCRIPTION
    Creates a normal .lnk that starts "Sweep Web.bat" with the repository (or
    portable folder) as its working directory. No registry writes, no service,
    no administrator rights. The shortcut is the only thing created.

    -Uninstall removes exactly that shortcut and nothing else.

.PARAMETER Uninstall
    Remove the shortcut instead of creating it.

.PARAMETER ShortcutPath
    Override the .lnk path. Defaults to Desktop\Sweep Web.lnk. Useful for
    testing or for putting the shortcut in a Start Menu folder.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\tools\make_shortcut.ps1

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\tools\make_shortcut.ps1 -Uninstall
#>
[CmdletBinding()]
param(
    [switch]$Uninstall,
    [string]$ShortcutPath = ""
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot

if ([string]::IsNullOrWhiteSpace($ShortcutPath)) {
    $desktop = [Environment]::GetFolderPath("Desktop")
    if ([string]::IsNullOrWhiteSpace($desktop)) {
        throw "Windows did not report a Desktop folder. Pass -ShortcutPath explicitly."
    }
    $ShortcutPath = Join-Path $desktop "Sweep Web.lnk"
}
$ShortcutPath = [System.IO.Path]::GetFullPath($ShortcutPath)

if ([System.IO.Path]::GetExtension($ShortcutPath) -ne ".lnk") {
    throw "Refusing to touch ${ShortcutPath}: this script only creates or removes .lnk shortcuts."
}

if ($Uninstall) {
    if (Test-Path -LiteralPath $ShortcutPath) {
        Remove-Item -LiteralPath $ShortcutPath -Force
        Write-Host "Removed $ShortcutPath"
    } else {
        Write-Host "No shortcut at $ShortcutPath; nothing to remove."
    }
    exit 0
}

$target = Join-Path $Root "Sweep Web.bat"
if (-not (Test-Path -LiteralPath $target)) {
    throw "Cannot find '$target'. Run this script from the Sweep folder (tools\make_shortcut.ps1)."
}

# Prefer a real icon when the project or a portable build provides one; a .lnk
# without an icon still works, it just uses the default batch-file icon.
$icon = ""
foreach ($candidate in @(
        (Join-Path $Root "sweep.ico"),
        (Join-Path $Root "assets\sweep.ico"),
        (Join-Path $Root "dist\Sweep\Sweep.exe")
    )) {
    if (Test-Path -LiteralPath $candidate) {
        $icon = $candidate
        break
    }
}

$parent = Split-Path -Parent $ShortcutPath
if ($parent -and -not (Test-Path -LiteralPath $parent)) {
    New-Item -ItemType Directory -Path $parent | Out-Null
}

$shell = New-Object -ComObject WScript.Shell
try {
    $shortcut = $shell.CreateShortcut($ShortcutPath)
    $shortcut.TargetPath = $target
    $shortcut.WorkingDirectory = $Root
    $shortcut.Description = "Sweep - local Windows cleanup console (web interface)"
    if ($icon) {
        $shortcut.IconLocation = "$icon,0"
    }
    $shortcut.Save()
} finally {
    if ($shell) {
        [void][System.Runtime.InteropServices.Marshal]::ReleaseComObject($shell)
    }
}

if (-not (Test-Path -LiteralPath $ShortcutPath)) {
    throw "Windows did not create $ShortcutPath."
}
Write-Host "Created $ShortcutPath"
Write-Host "  target:  $target"
Write-Host "  workdir: $Root"
if ($icon) { Write-Host "  icon:    $icon" }
