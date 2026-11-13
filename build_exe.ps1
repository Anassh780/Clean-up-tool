<#
.SYNOPSIS
    Build and smoke-test the portable Sweep.exe (PyInstaller onedir).

.DESCRIPTION
    Installs PyInstaller into the current user's site-packages if it is missing,
    runs Sweep.spec, then proves the result:
      * dist\Sweep\Sweep.exe --version prints "Sweep <version>"
      * dist\Sweep\Sweep.exe web --no-browser --port <free> serves /api/health

    dist\Sweep\ is the complete application folder: copy or zip that folder.
    No Python is needed on the target PC.

.PARAMETER Python
    Python 3.10+ interpreter to build with. Defaults to $env:SWEEP_PYTHON, then
    the bundled development runtime, then "python" on PATH.

.PARAMETER NoInstall
    Fail instead of running pip install --user pyinstaller.

.PARAMETER SkipVerify
    Build only; do not start the exe or call /api/health.

.PARAMETER Port
    Port for the web smoke test. Defaults to a free ephemeral port.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\build_exe.ps1
#>
[CmdletBinding()]
param(
    [string]$Python = "",
    [switch]$NoInstall,
    [switch]$SkipVerify,
    [int]$Port = 0
)

$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
Set-Location $Root

function Test-Python([string]$Exe) {
    if ([string]::IsNullOrWhiteSpace($Exe)) { return $false }
    try {
        & $Exe -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" 2>$null
        return ($LASTEXITCODE -eq 0)
    } catch {
        return $false
    }
}

function Resolve-BuildPython {
    $candidates = @(
        $Python,
        $env:SWEEP_PYTHON,
        (Join-Path $Root "python\python.exe"),
        (Join-Path $env:USERPROFILE ".dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe"),
        "python"
    )
    foreach ($candidate in $candidates) {
        if ([string]::IsNullOrWhiteSpace($candidate)) { continue }
        if (Test-Python $candidate) { return $candidate }
    }
    throw "No Python 3.10+ found. Pass -Python <path>, set SWEEP_PYTHON, or install Python 3.10+."
}

function Get-FreePort {
    $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, 0)
    $listener.Start()
    try {
        return ([System.Net.IPEndPoint]$listener.LocalEndpoint).Port
    } finally {
        $listener.Stop()
    }
}

Write-Host "Sweep portable build"
Write-Host "  root: $Root"

$pythonExe = Resolve-BuildPython
$pyVersion = (& $pythonExe -c "import sys; print(sys.version.split()[0])" 2>$null | Out-String).Trim()
Write-Host "  python: $pythonExe ($pyVersion)"

$pyinstallerVersion = ""
try {
    $pyinstallerVersion = (& $pythonExe -c "import PyInstaller; print(PyInstaller.__version__)" 2>$null | Out-String).Trim()
} catch {
    $pyinstallerVersion = ""
}
if (-not $pyinstallerVersion -or $LASTEXITCODE -ne 0) {
    if ($NoInstall) {
        throw "PyInstaller is not installed for $pythonExe. Run without -NoInstall, or install it with: $pythonExe -m pip install --user pyinstaller"
    }
    Write-Host "  pyinstaller: not installed; installing into the user site-packages..."
    & $pythonExe -m pip install --user --disable-pip-version-check pyinstaller
    if ($LASTEXITCODE -ne 0) {
        # --user is rejected inside a virtualenv; install into that environment.
        Write-Host "  --user install failed; retrying into the interpreter's environment..."
        & $pythonExe -m pip install --disable-pip-version-check pyinstaller
    }
    if ($LASTEXITCODE -ne 0) {
        throw "pip could not install PyInstaller (exit $LASTEXITCODE). Check the network/proxy and try again."
    }
    $pyinstallerVersion = (& $pythonExe -c "import PyInstaller; print(PyInstaller.__version__)" 2>$null | Out-String).Trim()
}
Write-Host "  pyinstaller: $pyinstallerVersion"

Write-Host "`nBuilding dist\Sweep\Sweep.exe ..."
& $pythonExe -m PyInstaller --noconfirm --clean Sweep.spec
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller failed (exit $LASTEXITCODE). The analysis/build output above has the missing module or data file."
}

$exe = Join-Path $Root "dist\Sweep\Sweep.exe"
if (-not (Test-Path -LiteralPath $exe)) {
    throw "PyInstaller reported success but $exe does not exist."
}

$folderBytes = (Get-ChildItem -LiteralPath (Join-Path $Root "dist\Sweep") -Recurse -File |
    Measure-Object -Property Length -Sum).Sum
Write-Host ("  built: {0} ({1:N1} MiB)" -f $exe, ($folderBytes / 1MB))

if ($SkipVerify) {
    Write-Host "`nSkipping runtime checks (-SkipVerify)."
    exit 0
}

Write-Host "`nChecking Sweep.exe --version ..."
$versionOutput = (& $exe --version 2>&1 | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or $versionOutput -notmatch '^Sweep \d') {
    throw "Sweep.exe --version failed (exit $LASTEXITCODE): $versionOutput"
}
Write-Host "  $versionOutput"

if ($Port -le 0) { $Port = Get-FreePort }
$stdout = Join-Path $env:TEMP "sweep-exe-web-$PID.out.txt"
$stderr = Join-Path $env:TEMP "sweep-exe-web-$PID.err.txt"
Remove-Item -LiteralPath $stdout, $stderr -ErrorAction SilentlyContinue

Write-Host "`nChecking the web server on 127.0.0.1:$Port ..."
$process = Start-Process -FilePath $exe `
    -ArgumentList @("web", "--no-browser", "--port", "$Port") `
    -PassThru -WindowStyle Hidden `
    -RedirectStandardOutput $stdout -RedirectStandardError $stderr
try {
    $health = $null
    $deadline = (Get-Date).AddSeconds(45)
    while ((Get-Date) -lt $deadline) {
        if ($process.HasExited) { break }
        try {
            $health = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/health" -TimeoutSec 2
            if ($health -and $health.ok -and $health.data.status -eq "ok") { break }
        } catch {
            Start-Sleep -Milliseconds 500
        }
    }
    if (-not $health -or -not $health.ok -or $health.data.status -ne "ok") {
        $outText = if (Test-Path $stdout) { Get-Content -LiteralPath $stdout -Raw } else { "" }
        $errText = if (Test-Path $stderr) { Get-Content -LiteralPath $stderr -Raw } else { "" }
        throw "The exe did not serve /api/health.`nstdout:`n$outText`nstderr:`n$errText"
    }
    Write-Host "  /api/health -> ok, version $($health.data.version)"
} finally {
    if ($process -and -not $process.HasExited) {
        Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
        $process.WaitForExit(5000) | Out-Null
    }
    Remove-Item -LiteralPath $stdout, $stderr -ErrorAction SilentlyContinue
}

Write-Host "`nPortable build OK."
Write-Host "  Ship the whole folder: $(Join-Path $Root 'dist\Sweep')"
Write-Host "  Users run Sweep.exe for the terminal UI, or: Sweep.exe web"
Write-Host "  Note: a frozen build cannot replace itself. Use the portable zip"
Write-Host "        (tools/build_release.py) for in-app updates and rollback."
exit 0
