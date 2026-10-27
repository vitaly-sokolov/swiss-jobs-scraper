#!/bin/sh
# Builds tinyproxy.conf from env (config/egress.env, gitignored, chmod 600):
#   UPSTREAM_HOST, UPSTREAM_PORT, UPSTREAM_USER, UPSTREAM_PASSWORD
set -eu
: "${UPSTREAM_HOST:?}" "${UPSTREAM_PORT:?}"

auth=""
if [ -n "${UPSTREAM_USER:-}" ]; then
    auth="${UPSTREAM_USER}:${UPSTREAM_PASSWORD:-}@"
fi

umask 077
cat > /tmp/tinyproxy.conf <<EOF
Port 3128
Listen 0.0.0.0
Timeout 120
MaxClients 20
LogLevel Notice
DisableViaHeader Yes
# Only reachable on the internal Docker network; no host port is published.
Allow 10.0.0.0/8
Allow 172.16.0.0/12
Allow 192.168.0.0/16
Upstream http ${auth}${UPSTREAM_HOST}:${UPSTREAM_PORT}
EOF

echo "egress: forwarding to ${UPSTREAM_HOST}:${UPSTREAM_PORT}"
exec tinyproxy -d -c /tmp/tinyproxy.conf
