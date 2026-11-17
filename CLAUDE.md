# herdr-skills

Agent Skills and herdr plugins for herdr. Each unit installs on its own; there is no Claude Code plugin bundle.

## Layout

- `skills/<name>/`: one Agent Skill (`SKILL.md`, `references/`, `assets/`, `scripts/`, `tests/`). Installed individually with `install.sh`, `gh skill` or `npx skills`; its hooks are registered by its own script (`herdr-parallel-worktree`: `scripts/hooks/manage.py`). The maintainer's install is a symlink into this checkout, so `skills/herdr-parallel-worktree/` must not move.
- `herdr-plugins/<name>/`: one herdr plugin (`herdr-plugin.toml`, scripts, `README.md` / `README.ko.md`, `tests/`). Not `plugins/`: `gh skill` reads that name as Claude Code-style plugins. None live here now: peek moved to its own repository, nyjin/herdr-peek, on 2026-11-17.
- `docs/superpowers/specs/`, `docs/superpowers/plans/`: design documents and plans. Dated records: when behaviour changes later, update the current design doc, not old plans.
- `scripts/check.sh`: every check, the same locally and in CI. Run `scripts/check.sh` before committing.
- `scripts/release.sh`: publishes a skills release from CI (see Releases).

## Language

Everything in the repository is English: skill text, script and hook messages, herdr plugin manifests and UI strings, docs, specs, plans, commit messages. Write specs and plans in English even when the conversation is in Korean.

Korean appears only in `README.ko.md` files (explanation for readers) and in tests where it does a job (patterns that match Korean model replies, sample content), with an English comment saying why. `scripts/check.sh language` enforces this.

## Releases

The release tag is the skills' version, and CI publishes it: when the checks pass on a push to `main`, `scripts/release.sh` runs `gh skill publish --tag v<next>` if the commits since the last `v<major>.<minor>.<patch>` tag changed `skills/`. Their Conventional Commit types set the bump, the largest wins: a breaking change (`type!:` or a `BREAKING CHANGE` footer) is major, `feat` minor, `fix` or `perf` patch; other types, and commits outside `skills/`, publish nothing. If `main` moved on before the release job ran, that run publishes nothing and the newer push's run does. So a commit's type says what it does to the skills users install, and nobody runs `gh skill publish` by hand; `scripts/release.sh --dry-run` prints what the current checkout would publish. A herdr plugin's version lives in its `herdr-plugin.toml`.

## Worktrees

Agent worktrees (herdr workers, `superpowers:using-git-worktrees`) go under `.worktrees/<name>` (git-ignored), one per task. Claude Code's own `EnterWorktree` keeps using `.claude/worktrees/`.
