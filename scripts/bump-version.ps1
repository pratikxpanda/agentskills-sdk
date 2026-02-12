<#
.SYNOPSIS
    Bump the version of all agentskills packages.

.DESCRIPTION
    Updates the version in every package pyproject.toml and the root pyproject.toml.
    Supports semver bump types (major, minor, patch) or an explicit version string.

.PARAMETER Bump
    The semver component to bump: major, minor, or patch. Default: patch.

.PARAMETER Version
    Set an explicit version instead of bumping (e.g. "1.0.0"). Overrides -Bump.

.PARAMETER DryRun
    Show what would change without modifying any files.

.EXAMPLE
    .\scripts\bump-version.ps1                    # 0.1.0 -> 0.1.1
    .\scripts\bump-version.ps1 -Bump minor        # 0.1.0 -> 0.2.0
    .\scripts\bump-version.ps1 -Bump major        # 0.1.0 -> 1.0.0
    .\scripts\bump-version.ps1 -Version 2.0.0     # set to 2.0.0
    .\scripts\bump-version.ps1 -DryRun            # preview changes
#>

param(
    [ValidateSet("major", "minor", "patch")]
    [string]$Bump = "patch",

    [string]$Version,

    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot

$pyprojectFiles = @(
    "pyproject.toml",
    "packages/core/agentskills-core/pyproject.toml",
    "packages/providers/agentskills-fs/pyproject.toml",
    "packages/providers/agentskills-http/pyproject.toml",
    "packages/integrations/agentskills-langchain/pyproject.toml",
    "packages/integrations/agentskills-agentframework/pyproject.toml",
    "packages/integrations/agentskills-mcp/pyproject.toml"
)

# Read current version from root pyproject.toml
$rootPyproject = Join-Path $repoRoot "pyproject.toml"
$rootContent = Get-Content $rootPyproject -Raw
if ($rootContent -match 'version\s*=\s*"(\d+\.\d+\.\d+)"') {
    $currentVersion = $Matches[1]
} else {
    Write-Host "Could not find version in root pyproject.toml" -ForegroundColor Red
    exit 1
}

# Determine new version
if ($Version) {
    if ($Version -notmatch '^\d+\.\d+\.\d+$') {
        Write-Host "Invalid version format: $Version (expected X.Y.Z)" -ForegroundColor Red
        exit 1
    }
    $newVersion = $Version
} else {
    $parts = $currentVersion.Split('.')
    $major = [int]$parts[0]
    $minor = [int]$parts[1]
    $patch = [int]$parts[2]

    switch ($Bump) {
        "major" { $major++; $minor = 0; $patch = 0 }
        "minor" { $minor++; $patch = 0 }
        "patch" { $patch++ }
    }
    $newVersion = "$major.$minor.$patch"
}

if ($currentVersion -eq $newVersion) {
    Write-Host "Version is already $currentVersion — nothing to do." -ForegroundColor Yellow
    exit 0
}

Write-Host "`n  Version: $currentVersion -> $newVersion" -ForegroundColor Cyan

if ($DryRun) {
    Write-Host "`n  [DRY RUN] The following files would be updated:`n" -ForegroundColor Yellow
}

foreach ($relPath in $pyprojectFiles) {
    $filePath = Join-Path $repoRoot $relPath

    if ($DryRun) {
        Write-Host "    $relPath" -ForegroundColor Gray
        continue
    }

    $content = Get-Content $filePath -Raw
    $updated = $content -replace "version = `"$currentVersion`"", "version = `"$newVersion`""
    Set-Content -Path $filePath -Value $updated -NoNewline
    Write-Host "  Updated $relPath" -ForegroundColor Green
}

if (-not $DryRun) {
    Write-Host "`n  All packages bumped to $newVersion`n" -ForegroundColor Green
}
