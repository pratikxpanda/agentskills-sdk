#!/usr/bin/env bash
#
# Build and publish all agentskills packages to PyPI in dependency order.
#
# Usage:
#   ./scripts/publish.sh                # publish to PyPI
#   ./scripts/publish.sh --test-pypi    # publish to TestPyPI
#   ./scripts/publish.sh --build-only   # build without publishing

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

PACKAGES=(
    "packages/core/agentskills-core"
    "packages/providers/agentskills-fs"
    "packages/providers/agentskills-http"
    "packages/integrations/agentskills-langchain"
    "packages/integrations/agentskills-agentframework"
    "packages/integrations/agentskills-mcp"
)

TEST_PYPI=false
BUILD_ONLY=false

for arg in "$@"; do
    case "$arg" in
        --test-pypi)  TEST_PYPI=true ;;
        --build-only) BUILD_ONLY=true ;;
        *)
            echo "Unknown option: $arg"
            echo "Usage: $0 [--test-pypi] [--build-only]"
            exit 1
            ;;
    esac
done

PUBLISH_ARGS=()
if $TEST_PYPI; then
    PUBLISH_ARGS+=("--repository" "testpypi")
fi

failed=()

for pkg in "${PACKAGES[@]}"; do
    pkg_path="$REPO_ROOT/$pkg"
    pkg_name="$(basename "$pkg")"

    echo ""
    echo "========================================"
    echo "  Building $pkg_name"
    echo "========================================"

    cd "$pkg_path"

    # Clean previous builds
    rm -rf dist

    if ! poetry build; then
        failed+=("$pkg_name")
        echo "FAILED to build $pkg_name"
        continue
    fi

    if ! $BUILD_ONLY; then
        echo "  Publishing $pkg_name..."
        if ! poetry publish "${PUBLISH_ARGS[@]}"; then
            failed+=("$pkg_name")
            echo "FAILED to publish $pkg_name"
            continue
        fi
        echo "  Published $pkg_name"
    fi
done

echo ""
echo "========================================"
if [ ${#failed[@]} -eq 0 ]; then
    if $BUILD_ONLY; then
        echo "  All packages built successfully!"
    else
        target="PyPI"
        $TEST_PYPI && target="TestPyPI"
        echo "  All packages published to $target!"
    fi
else
    echo "  Failed packages: ${failed[*]}"
    exit 1
fi
echo "========================================"
echo ""
