#!/usr/bin/env python3
"""Turn herdr-parallel-worktree's routing hooks (PreToolUse, PostToolUse) on or off, or remove them.

Usage: manage.py <on|off|remove|status> --skill-dir <skill directory as installed>

- Plugin installs (the skill lives under ~/.claude/plugins/): the plugin's hooks/hooks.json is active by
  default. on/off only flip "hooks" in DATA_DIR/config.json; the hook scripts read it and stay silent when
  "off". remove behaves like off, because a plugin's hooks cannot be removed per user without disabling
  the plugin.
- Other installs (~/.claude/skills, gh skill, npx skills): on also registers the hooks in
  ~/.claude/settings.json; remove unregisters them. A backup of settings.json is written before any change.

Prints a JSON summary. Exits 1 with a message on stderr on failure.
"""
import argparse
import json
import os
import shutil
import sys
import tempfile
import time

SKILL = "herdr-parallel-worktree"
MARK = f"{SKILL}/scripts/hooks/route.py"
SETTINGS = os.path.expanduser("~/.claude/settings.json")


def die(msg):
    print(msg, file=sys.stderr)
    sys.exit(1)


def data_config():
    base = os.environ.get("HERDR_SKILLS_DATA_HOME") or os.path.expanduser("~/.local/share/herdr-skills")
    return os.path.join(base, SKILL, "config.json")


def read_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default
    except (OSError, ValueError) as e:
        die(f"cannot read {path}: {e}")


def write_json(path, data):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".tmp-", suffix=".json")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(tmp, path)
    except OSError as e:
        die(f"cannot write {path}: {e.strerror}")


def set_mode(mode):
    cfg = read_json(data_config(), {})
    if not isinstance(cfg, dict):
        die(f"{data_config()} must contain a JSON object")
    cfg["hooks"] = mode
    write_json(data_config(), cfg)


GUARD = '[ "$HERDR_ENV" = 1 ] || exit 0; '   # outside herdr, never start python


def hook_entries(skill_dir):
    route = f'python3 "{os.path.join(skill_dir, "scripts", "hooks", "route.py")}"'
    pre = {"type": "command", "command": f"{GUARD}{route} pre-tool-use"}
    post = {"type": "command", "command": f"{GUARD}{route} post-tool-use"}

    def bash(rule):
        return {"matcher": "Bash", "hooks": [{**pre, "if": rule}]}

    return {
        "PreToolUse": [
            bash("Bash(*worktree add*)"),
            bash("Bash(*git -C *)"),
            bash("Bash(cd *)"),   # also matches `… && cd x`: rules match each subcommand
            {"matcher": "EnterWorktree|Agent|Task", "hooks": [dict(pre)]},
            {"matcher": "Write|Edit|MultiEdit|NotebookEdit", "hooks": [dict(pre)]},
        ],
        "PostToolUse": [
            {"matcher": "Agent|Task", "hooks": [dict(post)]},
        ],
    }


def strip_ours(settings):
    """Remove every hook group whose commands point at this skill's route.py; return how many were removed."""
    removed = 0
    hooks = settings.get("hooks") or {}
    for event in list(hooks):
        kept = []
        for group in hooks[event]:
            if any(MARK in (h.get("command") or "") for h in group.get("hooks", [])):
                removed += 1
            else:
                kept.append(group)
        if kept:
            hooks[event] = kept
        else:
            del hooks[event]
    if not hooks:
        settings.pop("hooks", None)
    return removed


def save_settings(settings):
    if os.path.exists(SETTINGS):
        backup = f"{SETTINGS}.bak-{time.strftime('%Y%m%d-%H%M%S')}"
        shutil.copy2(SETTINGS, backup)
    else:
        backup = None
    write_json(SETTINGS, settings)
    return backup


def registered():
    s = read_json(SETTINGS, {})
    return any(MARK in (h.get("command") or "")
               for groups in (s.get("hooks") or {}).values() for g in groups for h in g.get("hooks", []))


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("action", choices=["on", "off", "remove", "status"])
    p.add_argument("--skill-dir", required=True)
    a = p.parse_args()
    skill_dir = os.path.abspath(os.path.expanduser(a.skill_dir))
    plugin = f"{os.sep}.claude{os.sep}plugins{os.sep}" in skill_dir
    out = {"install": "plugin" if plugin else "standalone", "config": data_config()}

    if a.action in ("on", "off", "remove"):
        set_mode("on" if a.action == "on" else "off")
    if not plugin and a.action in ("on", "remove"):
        settings = read_json(SETTINGS, {})
        if not isinstance(settings, dict):
            die(f"{SETTINGS} must contain a JSON object")
        removed = strip_ours(settings)
        if a.action == "on":
            hooks = settings.setdefault("hooks", {})
            for event, groups in hook_entries(skill_dir).items():
                hooks.setdefault(event, []).extend(groups)
        if a.action == "on" or removed:
            out["settings_backup"] = save_settings(settings)
        out["settings"] = SETTINGS
    if plugin and a.action == "remove":
        out["note"] = "plugin hooks stay installed but are now silent; disable the plugin to remove them entirely"

    cfg = read_json(data_config(), {})
    out["mode"] = cfg.get("hooks", "on") if isinstance(cfg, dict) else "on"
    out["registered_in_settings"] = None if plugin else registered()
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
