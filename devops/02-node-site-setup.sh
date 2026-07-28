#!/usr/bin/env bash
#
# 02-node-site-setup.sh — per-app setup for a Node/SvelteKit site run by PM2
# behind nginx, deployed by push (the server holds NO GitHub credentials).
# Run as root AFTER 01-server-init.sh. Idempotent: safe to re-run.
#
# The deploy flow this creates:
#
#   laptop$ git remote add production ssh://APP_USER@SERVER/home/APP_USER/repos/APP_NAME.git
#   laptop$ git push production main
#   laptop$ ssh APP_USER@SERVER "cd ~/APP_NAME && npm run redeploy"
#
# What it does, in order:
#   1. nginx + firewall ports 80/443
#   2. Bare git repo the laptop pushes to (~/repos/APP_NAME.git)
#   3. Secrets file /etc/tubbylabs/APP_NAME.env (FORM_SECRET pre-generated)
#   4. Placeholder self-signed TLS cert (Cloudflare "Full" mode works with it;
#      replace with a Cloudflare Origin CA cert at the same paths for Full strict)
#   5. nginx vhost: HTTP->HTTPS, www->apex, security headers, immutable asset
#      caching, Cloudflare real-IP restoration, proxy to the app port
#   6. If code has been pushed: clone/pull, npm ci, migrate, build, PM2 start
#      (+ boot persistence). If not, it tells you to push and re-run.
#
# Usage:
#   APP_NAME=tubbylabs-website DOMAIN=tubbylabs.com bash 02-node-site-setup.sh
#
# Config (env vars):
#   APP_NAME    (required) pm2 app name; also the repo and directory name
#   DOMAIN      (required) canonical apex domain; www.DOMAIN 301s to it
#   APP_USER=tubby         user that owns and runs the app
#   APP_PORT=3000          local port the app listens on (nginx proxies to it)
#   APP_DIR=/home/APP_USER/APP_NAME   working copy path
#
# After the site is up, in the Cloudflare dashboard:
#   - DNS: A record for DOMAIN -> server IP (proxied), CNAME www -> DOMAIN (proxied)
#   - SSL/TLS -> Origin Server -> Create Certificate (DOMAIN + *.DOMAIN),
#     paste into /etc/ssl/tubbylabs/DOMAIN/origin.crt and origin.key,
#     `systemctl reload nginx`, then set SSL mode to Full (strict)

set -Eeuo pipefail

APP_USER="${APP_USER:-tubby}"
APP_PORT="${APP_PORT:-3000}"

step() { printf '\n==> %s\n' "$*"; }
fail() { printf 'FAILED: %s\n' "$*" >&2; exit 1; }

[[ $(id -u) -eq 0 ]] || fail "run as root"
[[ -n "${APP_NAME:-}" ]] || fail "APP_NAME is required (e.g. APP_NAME=tubbylabs-website)"
[[ -n "${DOMAIN:-}" ]] || fail "DOMAIN is required (e.g. DOMAIN=tubbylabs.com)"
id "$APP_USER" >/dev/null 2>&1 || fail "user $APP_USER missing — run 01-server-init.sh first"

APP_DIR="${APP_DIR:-/home/$APP_USER/$APP_NAME}"
BARE_REPO="/home/$APP_USER/repos/$APP_NAME.git"
CERT_DIR="/etc/ssl/tubbylabs/$DOMAIN"
ENV_FILE="/etc/tubbylabs/$APP_NAME.env"

# --- 1. nginx + firewall -----------------------------------------------------------

step "nginx + firewall"
export DEBIAN_FRONTEND=noninteractive
command -v nginx >/dev/null || { apt-get update -qq && apt-get install -y -qq nginx >/dev/null; }
ufw allow 80/tcp >/dev/null
ufw allow 443/tcp >/dev/null

# --- 2. Bare repo (push target) ------------------------------------------------------

step "Bare repo $BARE_REPO"
if [[ ! -d "$BARE_REPO" ]]; then
	sudo -u "$APP_USER" git init --bare -b main "$BARE_REPO" >/dev/null
fi

# --- 3. Secrets ------------------------------------------------------------------------

step "Secrets $ENV_FILE"
mkdir -p /etc/tubbylabs
if [[ ! -f "$ENV_FILE" ]]; then
	printf 'FORM_SECRET=%s\n' "$(openssl rand -hex 32)" >"$ENV_FILE"
fi
chown "$APP_USER:$APP_USER" "$ENV_FILE"
chmod 600 "$ENV_FILE"

# --- 4. TLS placeholder -----------------------------------------------------------------

step "TLS cert $CERT_DIR (self-signed placeholder until the CF Origin cert is pasted in)"
mkdir -p "$CERT_DIR"
if [[ ! -f "$CERT_DIR/origin.crt" ]]; then
	openssl req -x509 -nodes -newkey rsa:2048 \
		-keyout "$CERT_DIR/origin.key" -out "$CERT_DIR/origin.crt" \
		-days 3650 -subj "/CN=$DOMAIN" \
		-addext "subjectAltName=DNS:$DOMAIN,DNS:*.$DOMAIN" 2>/dev/null
	chmod 600 "$CERT_DIR/origin.key"
fi

# --- 5. nginx config ---------------------------------------------------------------------

step "nginx config"
# Cloudflare real-IP restoration (shared across sites on this server).
# Ranges: https://www.cloudflare.com/ips/ — refresh here if CF ever changes them.
if [[ ! -f /etc/nginx/conf.d/cloudflare-real-ip.conf ]]; then
	cat >/etc/nginx/conf.d/cloudflare-real-ip.conf <<'EOF'
set_real_ip_from 173.245.48.0/20;
set_real_ip_from 103.21.244.0/22;
set_real_ip_from 103.22.200.0/22;
set_real_ip_from 103.31.4.0/22;
set_real_ip_from 141.101.64.0/18;
set_real_ip_from 108.162.192.0/18;
set_real_ip_from 190.93.240.0/20;
set_real_ip_from 188.114.96.0/20;
set_real_ip_from 197.234.240.0/22;
set_real_ip_from 198.41.128.0/17;
set_real_ip_from 162.158.0.0/15;
set_real_ip_from 104.16.0.0/13;
set_real_ip_from 104.24.0.0/14;
set_real_ip_from 172.64.0.0/13;
set_real_ip_from 131.0.72.0/22;
set_real_ip_from 2400:cb00::/32;
set_real_ip_from 2606:4700::/32;
set_real_ip_from 2803:f800::/32;
set_real_ip_from 2405:b500::/32;
set_real_ip_from 2405:8100::/32;
set_real_ip_from 2a06:98c0::/29;
set_real_ip_from 2c0f:f248::/32;
real_ip_header CF-Connecting-IP;
EOF
fi

SITE_FILE="/etc/nginx/sites-available/$DOMAIN"
if [[ ! -f "$SITE_FILE" ]]; then
	cat >"$SITE_FILE" <<'EOF'
# Redirect HTTP and www to the canonical https://__DOMAIN__
server {
    listen 80;
    listen [::]:80;
    server_name __DOMAIN__ www.__DOMAIN__;
    return 301 https://__DOMAIN__$request_uri;
}
server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name www.__DOMAIN__;
    ssl_certificate __CERT_DIR__/origin.crt;
    ssl_certificate_key __CERT_DIR__/origin.key;
    return 301 https://__DOMAIN__$request_uri;
}

server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name __DOMAIN__;
    ssl_certificate __CERT_DIR__/origin.crt;
    ssl_certificate_key __CERT_DIR__/origin.key;

    # Security headers (the app also sets these on dynamic responses)
    add_header X-Content-Type-Options nosniff always;
    add_header X-Frame-Options DENY always;
    add_header Referrer-Policy strict-origin-when-cross-origin always;
    add_header Permissions-Policy "camera=(), microphone=(), geolocation=()" always;
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;

    # Long-cache immutable build assets (hashed filenames)
    location /_app/immutable/ {
        proxy_pass http://127.0.0.1:__APP_PORT__;
        proxy_set_header Host $host;
        add_header Cache-Control "public, max-age=31536000, immutable";
    }

    location / {
        proxy_pass http://127.0.0.1:__APP_PORT__;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
EOF
	sed -i "s|__DOMAIN__|$DOMAIN|g; s|__CERT_DIR__|$CERT_DIR|g; s|__APP_PORT__|$APP_PORT|g" "$SITE_FILE"
fi
ln -sf "$SITE_FILE" "/etc/nginx/sites-enabled/$DOMAIN"
rm -f /etc/nginx/sites-enabled/default
nginx -t >/dev/null || fail "nginx config test failed"
systemctl reload nginx

# --- 6. App: clone, build, PM2 --------------------------------------------------------------

step "Application"
if ! sudo -u "$APP_USER" git -C "$BARE_REPO" rev-parse main >/dev/null 2>&1; then
	cat <<EOF

No code pushed yet. From your laptop:

    git remote add production ssh://$APP_USER@$(hostname -I | awk '{print $1}')$BARE_REPO
    git push production main

then re-run this script with the same variables.
EOF
	exit 0
fi

if [[ ! -d "$APP_DIR/.git" ]]; then
	sudo -u "$APP_USER" git clone -q "$BARE_REPO" "$APP_DIR"
else
	sudo -u "$APP_USER" git -C "$APP_DIR" pull --ff-only -q origin main
fi

sudo -iu "$APP_USER" bash -c "cd '$APP_DIR' \
	&& npm ci --no-audit --no-fund \
	&& npm run migrate --if-present \
	&& npm run build"

if [[ -f "$APP_DIR/ecosystem.config.cjs" ]]; then
	sudo -iu "$APP_USER" bash -c "cd '$APP_DIR' && pm2 startOrReload ecosystem.config.cjs --update-env && pm2 save"
else
	sudo -iu "$APP_USER" bash -c "cd '$APP_DIR' && pm2 startOrReload build/index.js --name '$APP_NAME' && pm2 save"
fi

# PM2 resurrects on reboot under the app user
if ! systemctl is-enabled "pm2-$APP_USER" >/dev/null 2>&1; then
	pm2 startup systemd -u "$APP_USER" --hp "/home/$APP_USER" >/dev/null 2>&1 || true
	systemctl enable "pm2-$APP_USER" >/dev/null 2>&1 || true
fi

step "Verify"
sleep 2
curl -s -o /dev/null -w "app on 127.0.0.1:$APP_PORT -> %{http_code}\n" "http://127.0.0.1:$APP_PORT/"
curl -sk -o /dev/null -w "nginx https ($DOMAIN vhost) -> %{http_code}\n" "https://127.0.0.1/" -H "Host: $DOMAIN"

step "Done"
cat <<EOF
Remaining manual steps (Cloudflare dashboard):
  1. DNS: A record $DOMAIN -> this server (proxied); CNAME www -> $DOMAIN (proxied)
  2. SSL/TLS mode "Full" now; after step 3, "Full (strict)"
  3. Origin Server -> Create Certificate ($DOMAIN + *.$DOMAIN), paste into
     $CERT_DIR/origin.crt + origin.key, then: systemctl reload nginx
EOF
