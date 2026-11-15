# Repository layout and language — design

- Date: 2026-11-15
- Base: `5e8f6fd` (herdr-parallel-worktree 0.9.0, glow-preview 0.3.0)
- Scope: repository layout, the Claude Code plugin bundle, `manage.py`, `SKILL.md`, the glow-preview herdr plugin (renamed `peek`), `scripts/check.sh`, CI, READMEs, `docs/superpowers`, a new `CLAUDE.md`

## 1. What was wrong

The repository holds two kinds of things, and they were tangled:

| What | Problem |
|---|---|
| `.claude-plugin/` with `source: "./"` | The whole repository was the Claude Code plugin, so installing it copied the herdr plugin, `docs/` and every test into the plugin cache. |
| "plugin" | Meant three things: the Claude Code plugin bundle, "plugin installs" in `SKILL.md` and `manage.py`, and herdr plugins. |
| Hook definitions | Two copies, `hooks/hooks.json` (bundle) and `manage.py hook_entries()` (individual installs), kept equal by `test_registration.py`. The README had to warn against installing both ways. |
| Releases | The latest GitHub release was v0.6.0 while `plugin.json` said 0.9.0, so `gh skill install` handed out 0.6.0. |
| Language | Skill files were English (`test_language.py`), but the rule covered only the skill directory: nine of eleven docs under `docs/superpowers` and the glow-preview plugin's UI were Korean. |
| glow-preview | The name named one of its viewers; it also shows source with bat and fetches Jira, Confluence and GitHub PR links. |

## 2. Decisions

1. **No Claude Code plugin bundle.** Skills install individually (`install.sh`, `gh skill`, `npx skills`). `.claude-plugin/` and `hooks/hooks.json` go; `manage.py hook_entries()` is the only hook definition. Cost: a new install has its hooks off until the user says "turn on the herdr hook" (already true for individual installs).
2. **Two top-level kinds, each self-contained:** `skills/<name>/` (Agent Skills) and `herdr-plugins/<name>/` (herdr plugins). Each carries its own tests.
3. **Keep `herdr-plugins/`, not `plugins/`.** `gh skill` scans `plugins/{scope}/skills/*/SKILL.md`, so `plugins/` already means Claude Code-style plugins to it; the name also says which tool installs the plugin.
4. **Keep `skills/herdr-parallel-worktree/` where it is.** The maintainer's install is a symlink into this checkout, and the hooks in `~/.claude/settings.json` run through it.
5. **glow-preview becomes `peek`:** id `nyjin.peek`, folder `herdr-plugins/peek`, `scripts/peek.py`, `PEEK_*` variables, `~/.local/state/peek` and `~/.cache/peek`. No migration code: the plugin was published two days earlier, and the maintainer's machine has no state, cache, key binding or old hook for it. `install.sh` goes with the old-hook cleanup it existed for; `herdr plugin link herdr-plugins/peek` links a checkout.
6. **English everywhere.** Korean appears only in `README.ko.md` files (explanation for readers), in the README language switcher, and in tests where it is functional (patterns that match Korean model replies, sample content), with an English comment. peek's UI is English. The Korean docs are translated without changing their content; dated records keep the names and files they describe.
7. **One language check for the whole repository**, `scripts/check.sh language`, replaces the skill-only `test_language.py`. `CLAUDE.md` states the layout and the rule, so sessions and workers write English from the start.
8. **The release tag is the skills' version.** With `plugin.json` gone, nothing in the tree carries a skill version; `gh skill publish --tag v<version>` does. A herdr plugin's version stays in its `herdr-plugin.toml`.

## 3. Changes

- Delete `.claude-plugin/`, `hooks/hooks.json`.
- `manage.py`: one path. `on` registers in `settings.json` and sets the switch on; `off` sets it off; `remove` sets it off and unregisters; the output drops `install`.
- `SKILL.md`: drop the plugin-install branches (settings intro, first-run notice, Hooks).
- `test_registration.py`: checks `hook_entries()` directly. `hook_cost.py`: runs `hook_entries()`'s commands.
- `scripts/check.sh`: drop `manifests` and the `hooks.json` probe; `readme` also checks the herdr plugins tables; `unit` runs every `skills/*/tests`; new `language`.
- CI: same steps as `check.sh`.
- READMEs: skills and herdr plugins as two sections, one install route each, a note for users of the old bundle, release step instead of the version bump.
- peek: rename, English UI and manifest, tests, READMEs.
- `docs/superpowers`: translate nine documents.

## 4. Verification

- `scripts/check.sh` passes, `language` included.
- `manage.py on|off|remove|status` against a scratch `HOME` and `HERDR_SKILLS_DATA_HOME`.
- `herdr plugin link herdr-plugins/peek` is left to the maintainer's herdr (the plugin needs herdr 0.9.3; the CLI here is 0.9.0).

## 5. What shipped (2026-11-15)

Five commits on `restructure-layout`, as designed, with these details:

- peek is 0.4.0. Its READMEs tell installers of `nyjin.glow-preview` to uninstall it first: a note, not code.
- One Korean string stays in peek's tests (`fake_cli.py`, `test_fetch.py`): a Jira comment that checks non-ASCII text comes through the CLI's JSON unchanged, with an English comment.
- The 2026-10-05 plan quotes the Korean alternative of `live_skill.py`'s `WORKER_STOP` pattern. It is written with Python Unicode escapes, which match the same text, instead of being translated into a pattern that would match something else.
- `check.sh language` writes its own Hangul ranges as escapes, so it passes over itself; a probe file with Korean fails it and the README language switcher passes.
- `scripts/check.sh` passes in full. `manage.py on → status → off → on → remove → status` against a scratch `HOME` registers, silences and unregisters as described and keeps an unrelated hook in `settings.json`.
- Not checked here: `herdr plugin link herdr-plugins/peek`, which needs herdr 0.9.3.

## 6. After this

- Publish a release so `gh skill` users get past v0.6.0.
- Users of the old bundle uninstall it, install the skill and turn the hook on (README).
