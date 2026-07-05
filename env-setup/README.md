# cloudctl — cloud credential & profile manager

One entry point for setting up and auditing cloud CLI credentials on this machine
(Git Bash / WSL). Suggested folder rename: `automations/cloudctl/` (name the folder
after the tool, not the activity).

## Install

```bash
./install.sh              # puts a cloudctl wrapper in ~/bin and ensures ~/bin is on PATH
./install.sh --uninstall  # removes it
```

Re-run `./install.sh` any time you move this folder — the wrapper is regenerated
to point at the new location.

## Commands

| Command | What it does |
|---|---|
| `cloudctl audit` | List every profile/credential found on this machine (read-only) |
| `cloudctl check [cf\|aws\|do]` | Live-verify each stored credential against the provider API |
| `cloudctl doctor [--fix]` | Show which provider CLIs are installed; `--fix` installs missing ones via winget |
| `cloudctl add cf <profile>` | Interactive Cloudflare profile setup → `~/.cloudflare/<profile>.env` |
| `cloudctl add aws <profile>` | Wraps `aws configure --profile <profile>` (native AWS profiles) |
| `cloudctl add do <profile>` | Wraps `doctl auth init --context <profile>` (native doctl contexts) |
| `eval "$(cloudctl use cf <profile>)"` | Activate a Cloudflare profile in the current shell |
| `eval "$(cloudctl use aws <profile>)"` | Set `AWS_PROFILE` in the current shell |
| `cloudctl use do <profile>` | Switch doctl context (persistent) |
| `cloudctl remove <cf\|aws\|do> <profile>` | Delete a stored profile (aws edits `~/.aws/*` after confirming) |

`use` prints `export` lines rather than setting them (a child process can't modify
your shell), hence the `eval "$(...)"` pattern. Add aliases for the ones you use often:

```bash
# ~/.bashrc
alias cf-creeptosis='eval "$(cloudctl use cf creeptosis)"'
```

## Naming conventions

- **Profile names**: short kebab-case, named after the *account owner or purpose*,
  never the provider (the provider is already in the path/context):
  `personal`, `dobiqueen`, `creeptosis`, `client-acme`.
  Use the same profile name across providers when they belong to the same identity —
  `cloudctl use aws dobiqueen` and `cloudctl use cf dobiqueen` should mean the same "hat".
- **Storage layout** (one file per profile, secrets never in scripts or shell history):
  - Cloudflare: `~/.cloudflare/<profile>.env` (chmod 600)
  - AWS: native `~/.aws/credentials` + `~/.aws/config` named profiles
  - DigitalOcean: native doctl contexts (`doctl auth list`)
- **Prefer scoped API tokens over global/root keys** everywhere:
  Cloudflare API tokens over the Global API Key, AWS IAM users/roles over root keys,
  DO tokens scoped read-only when write isn't needed.

## Windows note

The PowerShell profile (`$PROFILE`) has matching `cf-<name>` functions reading the
same `~/.cloudflare/` files, so both shells share one source of truth.
