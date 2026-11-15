# herdr-skills

Agent Skills and herdr plugins for herdr. Each unit installs on its own; there is no Claude Code plugin bundle.

## Layout

- `skills/<name>/`: one Agent Skill (`SKILL.md`, `references/`, `assets/`, `scripts/`, `tests/`). Installed individually with `install.sh`, `gh skill` or `npx skills`; its hooks are registered by its own script (`herdr-parallel-worktree`: `scripts/hooks/manage.py`). The maintainer's install is a symlink into this checkout, so `skills/herdr-parallel-worktree/` must not move.
- `herdr-plugins/<name>/`: one herdr plugin (`herdr-plugin.toml`, scripts, `README.md` / `README.ko.md`, `tests/`). Not `plugins/`: `gh skill` reads that name as Claude Code-style plugins.
- `docs/superpowers/specs/`, `docs/superpowers/plans/`: design documents and plans. Dated records: when behaviour changes later, update the current design doc, not old plans.
- `scripts/check.sh`: every check, the same locally and in CI. Run `scripts/check.sh` before committing.

## Language

Everything in the repository is English: skill text, script and hook messages, herdr plugin manifests and UI strings, docs, specs, plans, commit messages. Write specs and plans in English even when the conversation is in Korean.

Korean appears only in `README.ko.md` files (explanation for readers) and in tests where it does a job (patterns that match Korean model replies, sample content), with an English comment saying why. `scripts/check.sh language` enforces this.

## Releases

The release tag is the skills' version: `gh skill publish --tag v<version>` after merging. A herdr plugin's version lives in its `herdr-plugin.toml`.

## Worktrees

Agent worktrees (herdr workers, `superpowers:using-git-worktrees`) go under `.worktrees/<name>` (git-ignored), one per task. Claude Code's own `EnterWorktree` keeps using `.claude/worktrees/`.
