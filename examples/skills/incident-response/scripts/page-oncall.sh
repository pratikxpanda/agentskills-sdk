#!/usr/bin/env bash
# page-oncall.sh — Page the on-call engineer via PagerDuty API
#
# Usage: ./page-oncall.sh <service-id> <severity> <description>
#
# Requires: PAGERDUTY_API_KEY environment variable

set -euo pipefail

SERVICE_ID="${1:?Usage: page-oncall.sh <service-id> <severity> <description>}"
SEVERITY="${2:?Severity required (critical|error|warning|info)}"
DESCRIPTION="${3:?Description required}"

API_KEY="${PAGERDUTY_API_KEY:?Set PAGERDUTY_API_KEY environment variable}"

curl -s -X POST "https://events.pagerduty.com/v2/enqueue" \
  -H "Content-Type: application/json" \
  -d "{
    \"routing_key\": \"${SERVICE_ID}\",
    \"event_action\": \"trigger\",
    \"payload\": {
      \"summary\": \"${DESCRIPTION}\",
      \"severity\": \"${SEVERITY}\",
      \"source\": \"agentskills-incident-response\"
    }
  }"

echo ""
echo "Paged on-call for service ${SERVICE_ID} with severity ${SEVERITY}"
