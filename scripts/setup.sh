#!/usr/bin/env bash
set -euo pipefail

function require_var() {
  local name="$1"
  if [[ -z "${!name:-}" ]]; then
    echo "❌ Missing env var: $name" >&2
    exit 1
  fi
}

function health_check() {
  local url="$1"
  echo "→ Health check: ${url}/api/telegram"
  code=$(curl -s -o /dev/null -w "%{http_code}" "${url}/api/telegram")
  echo "HTTP ${code}"
}

function set_webhook() {
  local token="$1"; shift
  local url="$1"; shift
  echo "→ Setting webhook for ${url}"
  curl -s "https://api.telegram.org/bot${token}/setWebhook?url=${url}/api/telegram" | jq . || true
}

function get_info() {
  local token="$1"; shift
  echo "→ Webhook info"
  curl -s "https://api.telegram.org/bot${token}/getWebhookInfo" | jq . || true
}

echo "=== Checking required variables ==="
require_var LINKEDIN_BOT_TOKEN
require_var CREATORS_BOT_TOKEN
require_var SECONDHAND_BOT_TOKEN
require_var LINKEDIN_URL
require_var CREATORS_URL
require_var SECONDHAND_URL

echo ""
echo "=== LINKEDIN ==="
health_check "${LINKEDIN_URL}"
set_webhook "${LINKEDIN_BOT_TOKEN}" "${LINKEDIN_URL}"
get_info "${LINKEDIN_BOT_TOKEN}"

echo ""
echo "=== CREATORS ==="
health_check "${CREATORS_URL}"
set_webhook "${CREATORS_BOT_TOKEN}" "${CREATORS_URL}"
get_info "${CREATORS_BOT_TOKEN}"

echo ""
echo "=== SECONDHAND ==="
health_check "${SECONDHAND_URL}"
set_webhook "${SECONDHAND_BOT_TOKEN}" "${SECONDHAND_URL}"
get_info "${SECONDHAND_BOT_TOKEN}"

echo ""
echo "✅ Done. Send /start to each bot to test."
