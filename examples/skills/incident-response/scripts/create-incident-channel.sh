#!/usr/bin/env bash
# create-incident-channel.sh — Create a dedicated Slack incident channel
#
# Usage: ./create-incident-channel.sh <incident-title>
#
# Creates a channel named #inc-YYYY-MM-DD-<title-slug>
# Requires: SLACK_BOT_TOKEN environment variable

set -euo pipefail

TITLE="${1:?Usage: create-incident-channel.sh <incident-title>}"

TOKEN="${SLACK_BOT_TOKEN:?Set SLACK_BOT_TOKEN environment variable}"

# Build channel name: #inc-2026-02-11-database-outage
DATE=$(date +%Y-%m-%d)
SLUG=$(echo "${TITLE}" | tr '[:upper:]' '[:lower:]' | tr ' ' '-' | tr -cd 'a-z0-9-')
CHANNEL_NAME="inc-${DATE}-${SLUG}"

# Truncate to Slack's 80-char channel name limit
CHANNEL_NAME="${CHANNEL_NAME:0:80}"

RESPONSE=$(curl -s -X POST "https://slack.com/api/conversations.create" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d "{
    \"name\": \"${CHANNEL_NAME}\",
    \"is_private\": false
  }")

CHANNEL_ID=$(echo "${RESPONSE}" | python3 -c "import sys,json; print(json.load(sys.stdin).get('channel',{}).get('id','UNKNOWN'))")

echo "Created incident channel: #${CHANNEL_NAME} (${CHANNEL_ID})"

# Set channel topic
curl -s -X POST "https://slack.com/api/conversations.setTopic" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d "{
    \"channel\": \"${CHANNEL_ID}\",
    \"topic\": \"Incident: ${TITLE} | Status: Investigating | IC: TBD\"
  }" > /dev/null

echo "Channel topic set. Invite the incident team to #${CHANNEL_NAME}"
