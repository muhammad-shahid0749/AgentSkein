# ============================================================================
#  AgentSkein — Windows Development Environment Setup Script
#  Run this once in PowerShell (as Administrator) to install everything.
#
#  Usage:
#    1. Open PowerShell as Administrator
#    2. Run:  Set-ExecutionPolicy RemoteSigned -Scope CurrentUser
#    3. Run:  cd "D:\iRAP\Global Talent Visa - Ideas\agentskein"
#    4. Run:  .\setup_windows.ps1
#
#  What this installs:
#    1.  winget  (Windows Package Manager — if missing)
#    2.  Python 3.12
#    3.  Rust (rustup + stable toolchain)
#    4.  Git for Windows
#    5.  Docker Desktop
#    6.  Windows Terminal
#    7.  VSCode extensions (Python, Pylance, Rust Analyzer, Ruff, TOML, Docker, GitLens)
#    8.  uv  (fast Python package manager)
#    9.  Python virtual environment + all project dependencies
#    10. Rust extension compilation via maturin
#    11. Smoke tests
# ============================================================================

# ── Error handling strategy ──────────────────────────────────────────────────
# Use "Continue" globally so stderr from native tools (rustup, pip, cargo,
# docker) does not abort the script.  Real failures are detected via
# $LASTEXITCODE checks and try/catch where appropriate.
# PowerShell cmdlet errors still surface normally.
$ErrorActionPreference = "Continue"

# ── Colour helpers ───────────────────────────────────────────────────────────
function Write-Header([string]$msg) {
    Write-Host ""
    Write-Host ("=" * 65) -ForegroundColor Cyan
    Write-Host "  $msg"   -ForegroundColor Cyan
    Write-Host ("=" * 65) -ForegroundColor Cyan
}
function Write-Step([string]$msg)  { Write-Host "  -> $msg" -ForegroundColor Yellow }
function Write-Ok([string]$msg)    { Write-Host "  [OK]   $msg" -ForegroundColor Green }
function Write-Warn([string]$msg)  { Write-Host "  [WARN] $msg" -ForegroundColor Magenta }
function Write-Fail([string]$msg)  { Write-Host "  [FAIL] $msg" -ForegroundColor Red }

# ── Safe version reader ───────────────────────────────────────────────────────
# Merges stderr into stdout and returns the first non-empty line.
# Prevents "NativeCommandError" when a tool writes info to stderr.
function Get-NativeVersion([string]$cmd, [string]$arg = "--version") {
    $output = & $cmd $arg 2>&1 | Where-Object { $_ -match '\S' } | Select-Object -First 1
    return "$output"
}

# ── Safe native runner ────────────────────────────────────────────────────────
# Runs a native command, shows output, and returns exit code.
# Never throws on non-zero exit — caller decides what to do.
function Invoke-Native {
    param([string]$cmd, [string[]]$args)
    & $cmd @args 2>&1 | Out-Default
    return $LASTEXITCODE
}

# ── Check if a command exists ─────────────────────────────────────────────────
function Test-Command([string]$cmd) {
    return [bool](Get-Command $cmd -ErrorAction SilentlyContinue)
}

# ── winget installer helper ───────────────────────────────────────────────────
function Install-Via-Winget([string]$id, [string]$name) {
    Write-Step "Installing $name ..."
    winget install --id $id --silent `
        --accept-package-agreements --accept-source-agreements `
        --no-upgrade 2>&1 | Out-Default
    if ($LASTEXITCODE -eq 0 -or $LASTEXITCODE -eq -1978335189) {
        # -1978335189 = APPINSTALLER_CLI_ERROR_PACKAGE_ALREADY_INSTALLED
        Write-Ok "$name ready"
    } else {
        Write-Warn "$name install may have failed (exit $LASTEXITCODE) — check manually"
    }
}

# ============================================================================
Write-Header "AgentSkein — Windows Setup"
Write-Host "  Installs: Python 3.12, Rust, Git, Docker, VSCode extensions,"
Write-Host "            virtual environment, and compiles the Rust merge engine."
Write-Host ""
$confirm = Read-Host "  Continue? (y/N)"
if ($confirm -notin @("y","Y")) { Write-Host "  Aborted."; exit 0 }

# ============================================================================
#  STEP 1: winget
# ============================================================================
Write-Header "Step 1: winget"
if (-not (Test-Command "winget")) {
    Write-Step "winget not found — opening the Microsoft Store to App Installer"
    Start-Process "ms-windows-store://pdp/?productid=9NBLGGH4NNS1"
    Write-Warn "Install App Installer from the Store window, then re-run this script."
    exit 1
}
Write-Ok "winget $(& winget --version 2>&1 | Select-Object -First 1)"

# ============================================================================
#  STEP 2: Python 3.12
# ============================================================================
Write-Header "Step 2: Python 3.12"
$pyExists = Test-Command "python"
if ($pyExists) {
    $pyver = (& python --version 2>&1) -join " "
    if ($pyver -match "3\.1[2-9]") {
        Write-Ok "Python already installed: $pyver"
    } else {
        Write-Warn "Found $pyver — installing Python 3.12 alongside it"
        Install-Via-Winget "Python.Python.3.12" "Python 3.12"
    }
} else {
    Install-Via-Winget "Python.Python.3.12" "Python 3.12"
}

# ============================================================================
#  STEP 3: Rust
# ============================================================================
Write-Header "Step 3: Rust (rustup)"
if (Test-Command "rustup") {
    # rustup --version prints an info line to stderr — capture both streams
    $rustupVer = (& rustup --version 2>&1) -join " " | Select-String "rustup" | ForEach-Object { "$_" }
    Write-Ok "Rust already installed: $rustupVer"
} else {
    Write-Step "Downloading rustup-init.exe ..."
    $rustupExe = "$env:TEMP\rustup-init.exe"
    Invoke-WebRequest -Uri "https://win.rustup.rs/x86_64" -OutFile $rustupExe -UseBasicParsing
    Write-Step "Running rustup-init (this takes ~2 minutes) ..."
    Start-Process -FilePath $rustupExe -ArgumentList "-y --default-toolchain stable" -Wait -NoNewWindow
    $env:PATH = "$env:USERPROFILE\.cargo\bin;$env:PATH"
    Write-Ok "Rust installed"
}

# Ensure stable is default — rustup writes info to stderr, so capture both
Write-Step "Ensuring stable toolchain is default ..."
& rustup default stable 2>&1 | Out-Default
& rustup update  stable  2>&1 | Out-Default
$rustcVer = (& rustc --version 2>&1) -join " "
Write-Ok "rustc: $rustcVer"

# ============================================================================
#  STEP 4: Git
# ============================================================================
Write-Header "Step 4: Git"
if (Test-Command "git") {
    $gitVer = (& git --version 2>&1) -join " "
    Write-Ok "Git already installed: $gitVer"
} else {
    Install-Via-Winget "Git.Git" "Git for Windows"
    # Reload PATH so git is available in this session
    $env:PATH = [System.Environment]::GetEnvironmentVariable("PATH","Machine") + ";" +
                [System.Environment]::GetEnvironmentVariable("PATH","User")
}

# ============================================================================
#  STEP 5: Docker Desktop
# ============================================================================
Write-Header "Step 5: Docker Desktop"
if (Test-Command "docker") {
    $dockerVer = (& docker --version 2>&1) -join " "
    Write-Ok "Docker already installed: $dockerVer"
} else {
    Write-Step "Installing Docker Desktop (~600 MB, please be patient) ..."
    Install-Via-Winget "Docker.DockerDesktop" "Docker Desktop"
    Write-Warn "IMPORTANT: Start Docker Desktop from the Start Menu before"
    Write-Warn "running 'docker compose up redis -d'  (first launch takes ~1 min)"
}

# ============================================================================
#  STEP 6: Windows Terminal (nice to have)
# ============================================================================
Write-Header "Step 6: Windows Terminal"
if (Test-Command "wt") {
    Write-Ok "Windows Terminal already installed"
} else {
    Install-Via-Winget "Microsoft.WindowsTerminal" "Windows Terminal"
}

# ============================================================================
#  STEP 7: VSCode extensions
# ============================================================================
Write-Header "Step 7: VSCode Extensions"
if (Test-Command "code") {
    $extensions = @(
        @{ id = "ms-python.python";             name = "Python" },
        @{ id = "ms-python.pylance";            name = "Pylance" },
        @{ id = "ms-python.black-formatter";    name = "Black Formatter" },
        @{ id = "charliermarsh.ruff";           name = "Ruff Linter" },
        @{ id = "rust-lang.rust-analyzer";      name = "Rust Analyzer" },
        @{ id = "tamasfe.even-better-toml";     name = "Even Better TOML" },
        @{ id = "ms-azuretools.vscode-docker";  name = "Docker" },
        @{ id = "eamodio.gitlens";              name = "GitLens" },
        @{ id = "ms-vscode.makefile-tools";     name = "Makefile Tools" }
    )
    foreach ($ext in $extensions) {
        Write-Step "Extension: $($ext.name)"
        & code --install-extension $ext.id --force 2>&1 | Out-Null
    }
    Write-Ok "All VSCode extensions installed"
} else {
    Write-Warn "VSCode 'code' command not found in PATH."
    Write-Warn "Install VSCode from https://code.visualstudio.com/ then re-run,"
    Write-Warn "OR tick 'Add to PATH' during VSCode installation."
}

# ============================================================================
#  STEP 8: Find project folder
# ============================================================================
Write-Header "Step 8: Project Folder"
$scriptDir  = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectDir = $scriptDir

if (-not (Test-Path "$projectDir\pyproject.toml")) {
    Write-Warn "pyproject.toml not found in $projectDir"
    $projectDir = Read-Host "  Enter full path to the agentskein project folder"
}
Write-Ok "Project folder: $projectDir"
Set-Location $projectDir

# ============================================================================
#  STEP 9: uv (fast Python package manager)
# ============================================================================
Write-Header "Step 9: uv"
if (Test-Command "uv") {
    $uvVer = (& uv --version 2>&1) -join " "
    Write-Ok "uv already installed: $uvVer"
} else {
    Write-Step "Installing uv ..."
    try {
        Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
        $env:PATH = "$env:USERPROFILE\.local\bin;$env:PATH"
        Write-Ok "uv installed"
    } catch {
        Write-Warn "uv auto-install failed — will use pip instead"
    }
}

# ============================================================================
#  STEP 10: Virtual environment + Python dependencies
# ============================================================================
Write-Header "Step 10: Virtual Environment & Dependencies"

# Create the venv
Write-Step "Creating .venv ..."
if (Test-Command "uv") {
    & uv venv .venv 2>&1 | Out-Default
} else {
    & python -m venv .venv 2>&1 | Out-Default
}

# Activate it
Write-Step "Activating .venv ..."
& ".\.venv\Scripts\Activate.ps1"

# Refresh PATH so the venv's Scripts folder is first
$env:PATH = "$projectDir\.venv\Scripts;$env:PATH"

# Upgrade pip first
Write-Step "Upgrading pip ..."
& python -m pip install --upgrade pip 2>&1 | Out-Default

# Install runtime dependencies WITHOUT triggering maturin Rust build.
# We list them explicitly so we bypass the maturin build-backend.
# maturin develop (Step 11) will handle the editable install + Rust compilation.
Write-Step "Installing runtime dependencies ..."
$runtimeDeps = @(
    "redis>=5.0.0", "aiosqlite>=0.19.0", "pydantic>=2.6.0",
    "anyio>=4.3.0", "httpx>=0.27.0", "rich>=13.7.0",
    "click>=8.1.7", "structlog>=24.1.0",
    "opentelemetry-api>=1.24.0", "opentelemetry-sdk>=1.24.0",
    "ulid-py>=1.1.0"
)
& python -m pip install @runtimeDeps 2>&1 | Out-Default

Write-Step "Installing dev dependencies ..."
$devDeps = @(
    "pytest>=8.1.0", "pytest-asyncio>=0.23.0", "pytest-cov>=5.0.0",
    "ruff>=0.4.0", "mypy>=1.9.0", "hypothesis>=6.100.0",
    "faker>=24.0.0", "fakeredis>=2.0.0"
)
& python -m pip install @devDeps 2>&1 | Out-Default

Write-Step "Installing maturin (Rust extension builder) ..."
& python -m pip install "maturin>=1.5,<2.0" 2>&1 | Out-Default

Write-Ok "Python dependencies installed"

# ============================================================================
#  STEP 11: maturin develop — compiles Rust AND installs the package
# ============================================================================
Write-Header "Step 11: maturin develop (Rust compilation + editable install)"
Write-Step "This builds the Rust merge engine AND installs agentskein in the venv."
Write-Step "Takes ~1-2 minutes on first run ..."
Write-Host ""

# Ensure Cargo is on PATH for this session
$env:PATH = "$env:USERPROFILE\.cargo\bin;$env:PATH"

if (Test-Command "maturin") {
    & maturin develop --manifest-path core\Cargo.toml 2>&1 | Out-Default
    if ($LASTEXITCODE -eq 0) {
        Write-Ok "Rust extension compiled + agentskein package installed"
        & python -c "from agentskein._core import py_three_way_merge; print('  Rust merge engine: OK')" 2>&1 | Out-Default
    } else {
        Write-Fail "maturin develop failed (exit $LASTEXITCODE)"
        Write-Warn ""
        Write-Warn "Falling back: installing agentskein as plain Python package ..."
        Write-Warn "(Rust merge engine disabled — Python fallback will be used)"
        Write-Warn ""
        # Install agentskein as a plain Python package without Rust by
        # temporarily patching pyproject.toml to use setuptools
        & python -m pip install --no-build-isolation `
            --config-settings="build-args=--skip-cargo-build" `
            -e . 2>&1 | Out-Default
        if ($LASTEXITCODE -ne 0) {
            # Last resort: just add the source folder to PYTHONPATH permanently
            Write-Warn "Editable install failed too. Adding project root to PYTHONPATH ..."
            [System.Environment]::SetEnvironmentVariable(
                "PYTHONPATH",
                $projectDir,
                [System.EnvironmentVariableTarget]::User
            )
            $env:PYTHONPATH = $projectDir
            Write-Ok "PYTHONPATH set to $projectDir (permanent, user scope)"
        }
    }
} else {
    Write-Warn "maturin not found on PATH even after install — adding PYTHONPATH fallback"
    [System.Environment]::SetEnvironmentVariable(
        "PYTHONPATH", $projectDir, [System.EnvironmentVariableTarget]::User
    )
    $env:PYTHONPATH = $projectDir
    Write-Ok "PYTHONPATH set to $projectDir"
}

# ============================================================================
#  STEP 12: Smoke tests
# ============================================================================
Write-Header "Step 12: Smoke Tests"

Write-Step "Import test ..."
$importTest = & python -c "
from agentskein import AgentSkein, ConflictStrategy, SQLiteBackend
print('All imports OK')
print('Version:', __import__('agentskein').__version__)
" 2>&1
Write-Host "  $importTest" -ForegroundColor White

Write-Step "Unit + E2E tests (no Redis required) ..."
& python -m pytest tests/unit/ tests/e2e/ -q --no-header `
    --override-ini="addopts=" 2>&1 | Out-Default

if ($LASTEXITCODE -eq 0) {
    Write-Ok "All tests passed"
} else {
    Write-Warn "Some tests failed — see output above"
}

# ============================================================================
#  STEP 13: Redis quick-start reminder
# ============================================================================
Write-Header "Step 13: Redis Quick Start (when you need it)"
Write-Host ""
Write-Host "  For production use with Redis:" -ForegroundColor White
Write-Host "    1. Start Docker Desktop from the Start Menu" -ForegroundColor Gray
Write-Host "    2. In this folder, run:" -ForegroundColor Gray
Write-Host "         docker compose up redis -d" -ForegroundColor Cyan
Write-Host "    3. Redis is now at redis://localhost:6379" -ForegroundColor Gray
Write-Host ""
Write-Host "  For offline use (zero setup, no Redis):" -ForegroundColor White
Write-Host "    from agentskein import AgentSkein" -ForegroundColor Cyan
Write-Host "    from agentskein.storage.sqlite_backend import SQLiteBackend" -ForegroundColor Cyan
Write-Host "    mesh = AgentSkein('agent-1', 'my-task'," -ForegroundColor Cyan
Write-Host "                      backend=SQLiteBackend('data.db'))" -ForegroundColor Cyan

# ============================================================================
#  DONE
# ============================================================================
Write-Header "Setup Complete"
Write-Host ""
Write-Host "  Your AgentSkein environment is ready." -ForegroundColor Green
Write-Host ""
Write-Host "  QUICK COMMANDS (activate .venv first each session):" -ForegroundColor White
Write-Host "    .\.venv\Scripts\Activate.ps1" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Run the multi-agent demo:" -ForegroundColor White
Write-Host "    python examples\raw_api\multi_agent_demo.py" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Run all tests:" -ForegroundColor White
Write-Host "    pytest tests\unit\ tests\e2e\ -v" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Run comparison benchmarks:" -ForegroundColor White
Write-Host "    cd ..\comparison" -ForegroundColor Cyan
Write-Host "    python run_all_benchmarks.py" -ForegroundColor Cyan
Write-Host ""
Write-Host "  CLI dashboard (needs Redis):" -ForegroundColor White
Write-Host "    agentskein watch --namespace my-task" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Open in VSCode:" -ForegroundColor White
Write-Host "    code ." -ForegroundColor Cyan
Write-Host ""
Write-Host ("=" * 65) -ForegroundColor Cyan
