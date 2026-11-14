#!/bin/sh
# Link this plugin into herdr. Nothing opens without a click, so no Claude Code hook is registered;
# a hook left by an earlier version (0.1-0.2) is removed, with a backup of settings.json first.
set -eu
root=$(cd "$(dirname "$0")" && pwd)
herdr=${HERDR_BIN_PATH:-herdr}

if "$herdr" plugin list 2>/dev/null | grep -q 'nyjin.glow-preview'; then
    echo "herdr plugin already linked"
else
    "$herdr" plugin link "$root"
fi

python3 - <<'PY'
import json, os, shutil, time
path = os.path.expanduser("~/.claude/settings.json")
if not os.path.exists(path):
    raise SystemExit(0)
settings = json.load(open(path))
groups = (settings.get("hooks") or {}).get("PostToolUse") or []
kept = [g for g in groups if not any("glowp.py\" hook" in h.get("command", "") for h in g.get("hooks", []))]
if len(kept) == len(groups):
    raise SystemExit(0)
backup = f"{path}.bak-{time.strftime('%Y%m%d-%H%M%S')}"
shutil.copy2(path, backup)
settings["hooks"]["PostToolUse"] = kept
tmp = path + ".tmp"
with open(tmp, "w") as f:
    json.dump(settings, f, ensure_ascii=False, indent=2)
    f.write("\n")
os.replace(tmp, path)
print(f"removed the old glow-preview Claude Code hook (backup: {backup})")
PY
