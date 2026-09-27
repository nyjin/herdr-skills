# herdr-skills

**English** | [한국어](README.ko.md)

Claude Code skills (Agent Skills) for [herdr](https://herdr.dev), the agent multiplexer that lives in your terminal. Run parallel coding agents in separate git worktrees and watch every Claude Code worker from the herdr sidebar — instead of invisible subagents. Install them all as a Claude Code plugin, or pick individual skills with `gh skill` or `npx skills`.

## Skills

To install one skill, put its name from the table below in `<skill>`.

<!-- skills:start -->
| Skill | Description |
|---|---|
| [`herdr-parallel-worktree`](skills/herdr-parallel-worktree/SKILL.md) | Runs several tasks in parallel inside herdr, one git worktree workspace and one visible `claude` worker per task, so you can watch each from the sidebar. Workers get a brief built from a customizable template; worker permission flags are asked on first use. Finished workers can be cleaned up and resumed later by name, conversation included. |
<!-- skills:end -->

## Install

Pick **one** of the two routes below. **Do not use both.** Plugin skills load as `/herdr-skills:<skill>` and individual installs as `/<skill>`; neither replaces the other, so installing the same skill both ways leaves two copies that trigger twice. To switch to individual installs, remove the plugin first with `/plugin uninstall herdr-skills@herdr-skills`.

### All skills — Claude Code plugin

```
/plugin marketplace add nyjin/herdr-skills
/plugin install herdr-skills@herdr-skills
```

Restart Claude Code afterwards.

### Individual skills

`install.sh` uses `gh skill` when your GitHub CLI has it (2.90.0+) and falls back to `npx skills` otherwise.

```bash
curl -fsSL https://raw.githubusercontent.com/nyjin/herdr-skills/main/install.sh | bash -s -- herdr-parallel-worktree

# every skill
curl -fsSL https://raw.githubusercontent.com/nyjin/herdr-skills/main/install.sh | bash -s -- --all

# into the current repository's .claude/skills instead of ~/.claude/skills
curl -fsSL https://raw.githubusercontent.com/nyjin/herdr-skills/main/install.sh | bash -s -- --scope project herdr-parallel-worktree
```

Or run either tool directly:

```bash
# GitHub CLI 2.90.0+ (check with `gh --version`; upgrade with `brew upgrade gh`)
gh skill preview nyjin/herdr-skills herdr-parallel-worktree
gh skill install nyjin/herdr-skills herdr-parallel-worktree --agent claude-code --scope user

# npx skills
npx skills add nyjin/herdr-skills -s herdr-parallel-worktree -a claude-code -g
```

Always pass `--agent claude-code --scope user` to `gh skill install`; without them it installs for GitHub Copilot at project scope. `gh skill update` updates installs later.

### What each route installs

| Route | Installs |
|---|---|
| `gh skill install` | the latest tagged release, or the default branch if there is none |
| `gh skill install ... --pin <tag>` | a fixed release (excluded from `gh skill update`) |
| `npx skills add` | the default branch |
| Claude Code plugin | the marketplace's current plugin version |

## Requirements

- [herdr](https://herdr.dev) — the skills only run inside a herdr session (`HERDR_ENV=1`)
- `claude` (Claude Code), `git`, `jq`, `python3`

## Settings and data

Per-user settings live outside the skill directory, so they survive reinstalls and updates:

```
${HERDR_SKILLS_DATA_HOME:-~/.local/share/herdr-skills}/<skill>/
```

`herdr-parallel-worktree` keeps `config.json` (worker `claude` flags), `briefs/` (generated worker briefs), `runs.json` (started workers and their Claude session IDs, used for cleanup and resume) and an optional `brief-template.md` (your own brief template) there. Ask Claude to "change the brief template" to customize it.

## Adding a skill

1. Create `skills/<name>/SKILL.md`. The frontmatter `name` must equal the directory name and use only lowercase letters, digits and hyphens.
2. Add a row to the Skills table in both `README.md` and `README.ko.md`, between the `skills:start` and `skills:end` markers, in alphabetical order.
3. Bump `version` in `.claude-plugin/plugin.json`.
4. After merging, publish a release so `gh skill` users get the change: `gh skill publish --tag v<version>`.

CI (`.github/workflows/skills-check.yaml`) validates the skills with `gh skill publish --dry-run`, checks that each `name` matches its directory, checks both READMEs' tables against `skills/`, and runs the plugin manifest validation.

## License

[MIT](LICENSE)
