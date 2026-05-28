# ============================================================
#  fix_venv_packages.ps1
#  Installs all missing packages INTO the .venv (not global Python).
#
#  Usage (with venv already activated):
#    .\fix_venv_packages.ps1
#
#  Why this works:
#    `pip install X`        → might use global pip (PATH-dependent)
#    `python -m pip install X` → always uses the active Python's pip
#                                which is .venv\Scripts\python.exe
# ============================================================

$ErrorActionPreference = "Continue"

function Write-Step($msg)  { Write-Host "  -> $msg" -ForegroundColor Yellow }
function Write-Ok($msg)    { Write-Host "  [OK] $msg" -ForegroundColor Green }
function Write-Fail($msg)  { Write-Host "  [FAIL] $msg" -ForegroundColor Red }

Write-Host ""
Write-Host "=== Installing packages into .venv ===" -ForegroundColor Cyan
Write-Host "  Using: $(python --version)"
Write-Host "  Pip at: $(python -m pip --version)"
Write-Host ""

# Core AgentSkein runtime dependencies
$packages = @(
    "fastapi",
    "uvicorn[standard]",
    "httpx",
    "redis",
    "aiosqlite",
    "pydantic>=2.6.0",
    "anyio",
    "httpx",
    "rich",
    "click",
    "structlog",
    "opentelemetry-api",
    "opentelemetry-sdk",
    "ulid-py",
    "maturin"
)

Write-Step "Upgrading pip first..."
python -m pip install --upgrade pip 2>&1 | Out-Default

foreach ($pkg in $packages) {
    Write-Step "Installing $pkg ..."
    python -m pip install $pkg 2>&1 | Out-Default
    if ($LASTEXITCODE -eq 0) {
        Write-Ok "$pkg installed"
    } else {
        Write-Fail "$pkg failed (exit $LASTEXITCODE)"
    }
}

Write-Host ""
Write-Host "=== Verifying key imports ===" -ForegroundColor Cyan

$checks = @(
    @{ pkg="fastapi";   code="import fastapi; print('fastapi', fastapi.__version__)" },
    @{ pkg="uvicorn";   code="import uvicorn; print('uvicorn', uvicorn.__version__)" },
    @{ pkg="httpx";     code="import httpx;   print('httpx',   httpx.__version__)" },
    @{ pkg="redis";     code="import redis;   print('redis',   redis.__version__)" },
    @{ pkg="pydantic";  code="import pydantic; print('pydantic', pydantic.__version__)" },
    @{ pkg="rich";      code="import rich;    print('rich',    rich.__version__)" }
)

foreach ($c in $checks) {
    $result = python -c $c.code 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Ok $result
    } else {
        Write-Fail "$($c.pkg): $result"
    }
}

Write-Host ""
Write-Host "=== Starting AgentSkein API server test ===" -ForegroundColor Cyan
Write-Step "Testing server.py imports..."
$test = python -c "
import sys, os
sys.path.insert(0, '.')
from fastapi import FastAPI
from agentskein import AgentSkein
print('All server imports OK')
" 2>&1
if ($LASTEXITCODE -eq 0) {
    Write-Ok $test
} else {
    Write-Fail $test
}

Write-Host ""
Write-Host "=== Done ===" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Now start the server:" -ForegroundColor White
Write-Host "    python examples\n8n_api_server\server.py" -ForegroundColor Cyan
Write-Host ""
Write-Host "  And in another terminal, run the agents:" -ForegroundColor White
Write-Host "    python agents\run_agents.py" -ForegroundColor Cyan
Write-Host ""
