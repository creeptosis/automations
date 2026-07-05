#!/usr/bin/env bash
#
# install.sh — put cloudctl on the PATH via a wrapper in ~/bin.
#
#   ./install.sh              install (idempotent, safe to re-run after moving this folder)
#   ./install.sh --uninstall  remove the wrapper
#
set -euo pipefail

BIN_DIR="$HOME/bin"
WRAPPER="$BIN_DIR/cloudctl"
# Resolve the real script next to this installer, wherever the folder lives.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET="$SCRIPT_DIR/cloudctl"

if [ "${1:-}" = "--uninstall" ]; then
  rm -f "$WRAPPER"
  echo "removed $WRAPPER"
  exit 0
fi

[ -f "$TARGET" ] || { echo "error: cloudctl not found next to install.sh" >&2; exit 1; }
chmod +x "$TARGET"

mkdir -p "$BIN_DIR"
printf '#!/usr/bin/env bash\nexec "%s" "$@"\n' "$TARGET" > "$WRAPPER"
chmod +x "$WRAPPER"
echo "installed wrapper: $WRAPPER -> $TARGET"

# Ensure ~/bin is on PATH for future shells (Git Bash adds it by default only if it
# existed at shell startup; make it explicit).
case ":$PATH:" in
  *":$BIN_DIR:"*) echo "~/bin already on PATH" ;;
  *)
    if ! grep -qs 'HOME/bin' "$HOME/.bashrc"; then
      printf '\nexport PATH="$HOME/bin:$PATH"\n' >> "$HOME/.bashrc"
      echo "added ~/bin to PATH in ~/.bashrc — restart your shell or: source ~/.bashrc"
    fi
    ;;
esac

command -v cloudctl >/dev/null && echo "ready: try 'cloudctl audit'"
