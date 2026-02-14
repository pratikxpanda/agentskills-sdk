#!/usr/bin/env bash
#
# Bump the version of all agentskills packages.
#
# Usage:
#   ./scripts/bump-version.sh                    # patch: 0.1.0 -> 0.1.1
#   ./scripts/bump-version.sh --minor            # minor: 0.1.0 -> 0.2.0
#   ./scripts/bump-version.sh --major            # major: 0.1.0 -> 1.0.0
#   ./scripts/bump-version.sh --version 2.0.0    # explicit version
#   ./scripts/bump-version.sh --dry-run          # preview changes

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

PYPROJECT_FILES=(
    "pyproject.toml"
    "packages/core/agentskills-core/pyproject.toml"
    "packages/providers/agentskills-fs/pyproject.toml"
    "packages/providers/agentskills-http/pyproject.toml"
    "packages/integrations/agentskills-langchain/pyproject.toml"
    "packages/integrations/agentskills-agentframework/pyproject.toml"
    "packages/integrations/agentskills-mcp-server/pyproject.toml"
)

BUMP="patch"
EXPLICIT_VERSION=""
DRY_RUN=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --major)            BUMP="major"; shift ;;
        --minor)            BUMP="minor"; shift ;;
        --patch)            BUMP="patch"; shift ;;
        --version)          EXPLICIT_VERSION="$2"; shift 2 ;;
        --dry-run)          DRY_RUN=true; shift ;;
        *)
            echo "Unknown option: $1"
            echo "Usage: $0 [--major|--minor|--patch] [--version X.Y.Z] [--dry-run]"
            exit 1
            ;;
    esac
done

# Read current version from root pyproject.toml
current_version=$(grep -oP 'version\s*=\s*"\K[0-9]+\.[0-9]+\.[0-9]+' "$REPO_ROOT/pyproject.toml" | head -1)

if [ -z "$current_version" ]; then
    echo "Could not find version in root pyproject.toml"
    exit 1
fi

# Determine new version
if [ -n "$EXPLICIT_VERSION" ]; then
    if ! echo "$EXPLICIT_VERSION" | grep -qE '^[0-9]+\.[0-9]+\.[0-9]+$'; then
        echo "Invalid version format: $EXPLICIT_VERSION (expected X.Y.Z)"
        exit 1
    fi
    new_version="$EXPLICIT_VERSION"
else
    IFS='.' read -r major minor patch <<< "$current_version"
    case "$BUMP" in
        major) major=$((major + 1)); minor=0; patch=0 ;;
        minor) minor=$((minor + 1)); patch=0 ;;
        patch) patch=$((patch + 1)) ;;
    esac
    new_version="$major.$minor.$patch"
fi

if [ "$current_version" = "$new_version" ]; then
    echo "Version is already $current_version — nothing to do."
    exit 0
fi

echo ""
echo "  Version: $current_version -> $new_version"

if $DRY_RUN; then
    echo ""
    echo "  [DRY RUN] The following files would be updated:"
    echo ""
    for rel_path in "${PYPROJECT_FILES[@]}"; do
        echo "    $rel_path"
    done
else
    for rel_path in "${PYPROJECT_FILES[@]}"; do
        file_path="$REPO_ROOT/$rel_path"
        if [[ "$(uname)" == "Darwin" ]]; then
            sed -i '' "s/version = \"$current_version\"/version = \"$new_version\"/" "$file_path"
        else
            sed -i "s/version = \"$current_version\"/version = \"$new_version\"/" "$file_path"
        fi
        echo "  Updated $rel_path"
    done
    echo ""
    echo "  All packages bumped to $new_version"
fi
echo ""
