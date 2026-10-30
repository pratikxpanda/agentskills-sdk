<#
.SYNOPSIS
    Build and publish all agentskills packages to PyPI in dependency order.

.DESCRIPTION
    Builds and publishes packages in the correct order:
      1. agentskills-core (no internal deps)
            2. agentskills-adapters, agentskills-fs, agentskills-http
            3. agentskills-git (depends on core and agentskills-fs)
            4. agentskills-retrieval, agentskills-tools, agentskills-testing
            5. agentskills-mcp-server (depends on core and optional providers)

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
    "packages/adapters/agentskills-adapters",
    "packages/providers/agentskills-fs",
    "packages/providers/agentskills-git",
    "packages/providers/agentskills-http",
    "packages/providers/agentskills-azure",
    "packages/providers/agentskills-oci",
    "packages/retrieval/agentskills-retrieval",
    "packages/tools/agentskills-tools",
    "packages/testing/agentskills-testing",
    "packages/integrations/agentskills-mcp-server"
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
