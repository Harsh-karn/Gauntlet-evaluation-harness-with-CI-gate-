<#
.SYNOPSIS
    PowerShell automation script for Gauntlet commands.
.EXAMPLE
    .\make.ps1 test
    .\make.ps1 lint
#>

param (
    [Parameter(Position=0)]
    [ValidateSet("install", "test", "lint", "format", "eval", "clean", "help")]
    [string]$Target = "help"
)

switch ($Target) {
    "install" {
        Write-Host "Installing gauntlet with dev dependencies..." -ForegroundColor Cyan
        pip install -e ".[dev]"
    }
    "test" {
        Write-Host "Running pytest test suite..." -ForegroundColor Cyan
        pytest -v tests/
    }
    "lint" {
        Write-Host "Running ruff check..." -ForegroundColor Cyan
        ruff check src/ tests/
        Write-Host "Running mypy type check..." -ForegroundColor Cyan
        mypy src/ tests/
    }
    "format" {
        Write-Host "Formatting code with ruff..." -ForegroundColor Cyan
        ruff format src/ tests/
        ruff check --fix src/ tests/
    }
    "eval" {
        Write-Host "Running gauntlet evaluation harness..." -ForegroundColor Cyan
        python -m gauntlet.cli run --suites safety,quality,adversarial --baseline baselines/main.json
    }
    "clean" {
        Write-Host "Cleaning temporary build artifacts..." -ForegroundColor Cyan
        Remove-Item -Recurse -Force -ErrorAction SilentlyContinue build, dist, *.egg-info, .pytest_cache, .gauntlet_cache, report
    }
    Default {
        Write-Host "Available commands:" -ForegroundColor Yellow
        Write-Host "  .\make.ps1 install - Install package in editable mode with dev dependencies"
        Write-Host "  .\make.ps1 test    - Run pytest test suite"
        Write-Host "  .\make.ps1 lint    - Run ruff and mypy"
        Write-Host "  .\make.ps1 format  - Format code"
        Write-Host "  .\make.ps1 eval    - Run gauntlet evaluation harness"
        Write-Host "  .\make.ps1 clean   - Clean artifacts"
    }
}
