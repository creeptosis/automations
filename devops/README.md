# devops

Server provisioning scripts for Tubby Labs infrastructure. Conventions baked in:

- **Admin/deploy user is `tubby` on every server.** Key-only SSH, passwordless
  sudo, root SSH login disabled.
- **Servers hold no GitHub credentials.** Deploys are push-based: your laptop
  pushes to a bare repo on the server, the app directory pulls from it.
- **Secrets** live in `/etc/tubbylabs/<app>.env` (mode 600, owner `tubby`),
  loaded by PM2 via `node --env-file-if-exists`.
- **TLS**: sites sit behind Cloudflare. Origin certs live in
  `/etc/ssl/tubbylabs/<domain>/origin.{crt,key}`. The setup script creates a
  self-signed placeholder (works with Cloudflare SSL mode **Full**); replace it
  with a Cloudflare Origin CA cert and switch to **Full (strict)**.

## Fresh server, step by step

```bash
# 1. copy the scripts up (fresh image still allows root; EC2: use the image's default user)
scp devops/01-server-init.sh devops/02-node-site-setup.sh root@<ip>:

# 2. generic init: swap, node+pm2, user tubby, ufw, fail2ban, sshd hardening
ssh root@<ip> "bash 01-server-init.sh"

# 3. VERIFY before closing the root session (root login is now disabled):
ssh tubby@<ip> "sudo whoami"    # -> root

# 4. app setup: nginx, bare repo, secrets, TLS placeholder, vhost
ssh tubby@<ip> "sudo APP_NAME=tubbylabs-website DOMAIN=tubbylabs.com bash 02-node-site-setup.sh"

# 5. push the code from your laptop, then re-run step 4 (it builds + starts PM2)
git remote add production ssh://tubby@<ip>/home/tubby/repos/tubbylabs-website.git
git push production main
```

Both scripts are idempotent — re-running is always safe.

## Day-to-day deploys (once a site is live)

```bash
git push origin main          # GitHub (source of truth)
git push production main      # server bare repo
ssh tubby@<ip> "cd ~/<app> && npm run redeploy"
```

(`redeploy` is the app repo's own pipeline: validate, build, zero-downtime PM2
reload, health check.)

## Options

`01-server-init.sh`: `TUBBY_USER`, `SWAP_GB`, `NODE_MAJOR`, `PUBKEYS`,
`SKIP_HARDENING=1`. It refuses to disable root login if the new user has no
SSH keys.

`02-node-site-setup.sh`: `APP_NAME` (required), `DOMAIN` (required),
`APP_USER`, `APP_PORT`, `APP_DIR`. Multiple apps on one server: run it once
per app with a different `APP_NAME`/`DOMAIN`/`APP_PORT`.

## Live servers

| Server | IP | Apps |
| ------ | -- | ---- |
| tubby  | 178.128.98.1 | tubbylabs-website (tubbylabs.com), working copy at `~/website` |
