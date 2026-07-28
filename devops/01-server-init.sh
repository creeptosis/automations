#!/usr/bin/env bash
#
# 01-server-init.sh — generic first-boot setup for a fresh Ubuntu server
# (DigitalOcean droplet, EC2 instance, ...). Idempotent: safe to re-run.
#
# What it does, in order:
#   1. Swap file (small VMs OOM during npm/vite builds)
#   2. Base packages: git, curl, ufw, fail2ban, unattended-upgrades
#   3. Node.js LTS (NodeSource) + PM2
#   4. The standard Tubby Labs admin/deploy user "tubby":
#      key-only SSH (keys copied from the invoking account), passwordless sudo
#   5. Firewall: deny incoming except SSH (app ports are opened by app scripts)
#   6. fail2ban (sshd brute-force protection)
#   7. sshd hardening: PermitRootLogin no, PasswordAuthentication no
#      (skipped automatically if the new user ended up with no SSH keys)
#
# Usage, as root on the fresh server:
#   bash 01-server-init.sh
#
# Config (env vars, all optional):
#   TUBBY_USER=tubby   admin/deploy username (convention: tubby on every server)
#   SWAP_GB=2          swap size in GB; 0 disables
#   NODE_MAJOR=22      Node.js major version
#   PUBKEYS="ssh-ed25519 AAAA... you@laptop"
#                      newline-separated public keys for the user; default:
#                      copied from $SUDO_USER's (EC2) or root's authorized_keys
#   SKIP_HARDENING=1   leave sshd config untouched
#
# IMPORTANT: before closing your current session, verify from your laptop that
#   ssh <TUBBY_USER>@<server-ip>   and   sudo whoami
# both work. Root SSH login is disabled at the end of this script.

set -Eeuo pipefail

TUBBY_USER="${TUBBY_USER:-tubby}"
SWAP_GB="${SWAP_GB:-2}"
NODE_MAJOR="${NODE_MAJOR:-22}"

step() { printf '\n==> %s\n' "$*"; }
fail() { printf 'FAILED: %s\n' "$*" >&2; exit 1; }

[[ $(id -u) -eq 0 ]] || fail "run as root (sudo -i first on EC2-style images)"
command -v apt-get >/dev/null || fail "this script supports Ubuntu/Debian (apt) only"

# --- 1. Swap -------------------------------------------------------------------

step "Swap (${SWAP_GB}G)"
if [[ "$SWAP_GB" != "0" ]] && ! swapon --show | grep -q .; then
	fallocate -l "${SWAP_GB}G" /swapfile
	chmod 600 /swapfile
	mkswap /swapfile >/dev/null
	swapon /swapfile
	grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >>/etc/fstab
	echo 'vm.swappiness=10' >/etc/sysctl.d/99-swap.conf
	sysctl -p /etc/sysctl.d/99-swap.conf >/dev/null
	echo "created ${SWAP_GB}G swapfile"
else
	echo "swap already present or disabled — skipping"
fi

# --- 2. Base packages ------------------------------------------------------------

step "Base packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq curl git ufw fail2ban unattended-upgrades ca-certificates >/dev/null

# --- 3. Node.js + PM2 ------------------------------------------------------------

step "Node.js ${NODE_MAJOR}.x + PM2"
if ! command -v node >/dev/null || [[ "$(node -v | sed 's/v\([0-9]*\).*/\1/')" -lt "$NODE_MAJOR" ]]; then
	curl -fsSL "https://deb.nodesource.com/setup_${NODE_MAJOR}.x" | bash - >/dev/null 2>&1
	apt-get install -y -qq nodejs >/dev/null
fi
command -v pm2 >/dev/null || npm install -g pm2 --silent >/dev/null
# don't leave a stray root-owned pm2 daemon behind
pm2 kill >/dev/null 2>&1 || true
echo "node $(node -v), pm2 $(pm2 -v 2>/dev/null | tail -1)"

# --- 4. Admin/deploy user ----------------------------------------------------------

step "User '$TUBBY_USER' (key-only SSH, passwordless sudo)"
if ! id "$TUBBY_USER" >/dev/null 2>&1; then
	adduser --disabled-password --gecos "" "$TUBBY_USER" >/dev/null
	usermod -aG sudo "$TUBBY_USER"
fi

# Collect public keys: PUBKEYS env > $SUDO_USER's keys (EC2) > root's keys.
# The grep strips EC2's command="..." prefixes so the copied keys actually work.
collect_keys() {
	if [[ -n "${PUBKEYS:-}" ]]; then
		printf '%s\n' "$PUBKEYS"
		return
	fi
	local f
	for f in "/home/${SUDO_USER:-}/.ssh/authorized_keys" /root/.ssh/authorized_keys; do
		if [[ -s "$f" ]]; then
			grep -Eo '(ssh-(ed25519|rsa)|ecdsa-sha2-[a-z0-9-]+|sk-[a-z0-9@.-]+) [A-Za-z0-9+/=]+( [^ ]+)?' "$f" && return
		fi
	done
	true
}

install -d -m 700 -o "$TUBBY_USER" -g "$TUBBY_USER" "/home/$TUBBY_USER/.ssh"
collect_keys >"/home/$TUBBY_USER/.ssh/authorized_keys"
chown "$TUBBY_USER:$TUBBY_USER" "/home/$TUBBY_USER/.ssh/authorized_keys"
chmod 600 "/home/$TUBBY_USER/.ssh/authorized_keys"
KEY_COUNT="$(grep -c . "/home/$TUBBY_USER/.ssh/authorized_keys" || true)"
echo "$KEY_COUNT SSH key(s) installed for $TUBBY_USER"

# Passwordless sudo: SSH is key-only and the user has no password to type.
echo "$TUBBY_USER ALL=(ALL) NOPASSWD:ALL" >"/etc/sudoers.d/$TUBBY_USER"
chmod 440 "/etc/sudoers.d/$TUBBY_USER"
visudo -c >/dev/null || fail "sudoers validation failed"

# --- 5. Firewall -------------------------------------------------------------------

step "Firewall (SSH only; app scripts open their own ports)"
ufw default deny incoming >/dev/null
ufw default allow outgoing >/dev/null
ufw allow OpenSSH >/dev/null
ufw --force enable >/dev/null
ufw status | head -5

# --- 6. fail2ban ---------------------------------------------------------------------

step "fail2ban"
systemctl enable --now fail2ban >/dev/null 2>&1
echo "sshd jail active"

# --- 7. sshd hardening -----------------------------------------------------------------

step "sshd hardening"
if [[ "${SKIP_HARDENING:-0}" == "1" ]]; then
	echo "SKIP_HARDENING=1 — leaving sshd config untouched"
elif [[ "$KEY_COUNT" -eq 0 ]]; then
	echo "WARNING: no SSH keys installed for $TUBBY_USER — NOT disabling root login."
	echo "Add keys (PUBKEYS env or authorized_keys) and re-run."
else
	printf 'PermitRootLogin no\nPasswordAuthentication no\n' >/etc/ssh/sshd_config.d/99-hardening.conf
	sshd -t || fail "sshd config test failed"
	systemctl reload ssh || systemctl reload sshd
	echo "root SSH login disabled, password auth disabled"
fi

step "Done"
cat <<EOF
Server initialised. BEFORE closing this session, verify from your laptop:

    ssh $TUBBY_USER@<this-server-ip>    # must log in
    sudo whoami                          # must print root

Next: run an app setup script, e.g. 02-node-site-setup.sh.
EOF
