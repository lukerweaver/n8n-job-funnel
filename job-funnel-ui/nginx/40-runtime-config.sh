#!/bin/sh
set -eu

cat <<EOF >/usr/share/nginx/html/runtime-config.js
window.__JOB_FUNNEL_CONFIG__ = {
  apiBaseUrl: "${API_BASE_URL:-http://localhost:8000}"
};
EOF
