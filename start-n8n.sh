#!/usr/bin/env bash
# Start a local, self-hosted n8n for this project. Its data (database, encryption key) goes to
# .n8n-data/, which is git-ignored. Needs Node 20+; the first run downloads n8n via npx.
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p output
export N8N_USER_FOLDER="$PWD/.n8n-data"
export N8N_RESTRICT_FILE_ACCESS_TO="$PWD/output"   # the alert log is the only file it writes
export N8N_DIAGNOSTICS_ENABLED=false
export N8N_PERSONALIZATION_ENABLED=false
export N8N_VERSION_NOTIFICATIONS_ENABLED=false
if [ -x .n8n-runtime/node_modules/.bin/n8n ]; then
  exec .n8n-runtime/node_modules/.bin/n8n start
else
  exec npx --yes n8n@2.46.7 start
fi
