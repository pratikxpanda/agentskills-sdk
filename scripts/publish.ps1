<#
.SYNOPSIS
    Build and publish all agentskills packages to PyPI in dependency order.

.DESCRIPTION
    Builds and publishes packages in the correct order:
      1. agentskills-core (no internal deps)
      2. agentskills-fs, agentskills-http (depend on core)
      3. agentskills-langchain, agentskills-agentframework, agentskills-modelcontextprotocol (depend on core)

.PARAMETER TestPyPI
    Publish to TestPyPI instead of PyPI.

.PARAMETER BuildOnly
    Only build packages without publishing.

.EXAMPLE
    .\scripts\publish.ps1
    .\scripts\publish.ps1 -TestPyPI
    .\scripts\publish.ps1 -BuildOnly
#>

param(
    [switch]$TestPyPI,
    [switch]$BuildOnly
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot

$packages = @(
    "packages/core/agentskills-core",
    "packages/providers/agentskills-fs",
    "packages/providers/agentskills-http",
    "packages/integrations/agentskills-langchain",
    "packages/integrations/agentskills-agentframework",
    "packages/integrations/agentskills-mcp"
)

$publishArgs = @()
if ($TestPyPI) {
    $publishArgs += "--repository", "testpypi"
}

$failed = @()

foreach ($pkg in $packages) {
    $pkgPath = Join-Path $repoRoot $pkg
    $pkgName = Split-Path -Leaf $pkg

    Write-Host "`n========================================" -ForegroundColor Cyan
    Write-Host "  Building $pkgName" -ForegroundColor Cyan
    Write-Host "========================================" -ForegroundColor Cyan

    Push-Location $pkgPath
    try {
        # Clean previous builds
        if (Test-Path "dist") {
            Remove-Item -Recurse -Force "dist"
        }

        poetry build
        if ($LASTEXITCODE -ne 0) {
            $failed += $pkgName
            Write-Host "FAILED to build $pkgName" -ForegroundColor Red
            continue
        }

        if (-not $BuildOnly) {
            Write-Host "  Publishing $pkgName..." -ForegroundColor Yellow
            poetry publish @publishArgs
            if ($LASTEXITCODE -ne 0) {
                $failed += $pkgName
                Write-Host "FAILED to publish $pkgName" -ForegroundColor Red
                continue
            }
            Write-Host "  Published $pkgName" -ForegroundColor Green
        }
    }
    finally {
        Pop-Location
    }
}

Write-Host "`n========================================" -ForegroundColor Cyan
if ($failed.Count -eq 0) {
    if ($BuildOnly) {
        Write-Host "  All packages built successfully!" -ForegroundColor Green
    } else {
        $target = if ($TestPyPI) { "TestPyPI" } else { "PyPI" }
        Write-Host "  All packages published to $target!" -ForegroundColor Green
    }
} else {
    Write-Host "  Failed packages: $($failed -join ', ')" -ForegroundColor Red
    exit 1
}
Write-Host "========================================`n" -ForegroundColor Cyan
