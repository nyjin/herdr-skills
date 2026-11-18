# herdr-skills

**English** | [한국어](README.ko.md)

Agent Skills and herdr plugins for [herdr](https://herdr.dev), the agent multiplexer that lives in your terminal. Run parallel coding agents in separate git worktrees and watch every Claude Code worker from the herdr sidebar, instead of invisible subagents. Each one installs on its own: skills with `gh skill` or `npx skills`, herdr plugins with `herdr plugin install`.

## Skills

To install one skill, put its name from the table below in `<skill>`.

<!-- skills:start -->
| Skill | Description |
|---|---|
| [`herdr-parallel-worktree`](skills/herdr-parallel-worktree/SKILL.md) | Hands coding work inside herdr to visible workers, one git worktree and one `claude` worker per task, so you can watch each from the sidebar and step in. Each worker lands under its repository's space (as a workspace named after the task), or as a tab in your current space when herdr shows no space for that repository, never in a new top-level space. Works for a single ticket you want to review before the PR as well as several tasks in parallel, and leaves the tabs your herdr plugins lay out in place. Workers get a brief built from a customizable template; it runs on sensible defaults and the first run lists the settings you can change. After starting workers, and whenever you ask, it lists your current repository's workers that can go now under the heading **Cleanable workers**, sorted by status (done, working, idle), each with its status, what it was started for, its branch, last activity and where its work stands, names the ones left out and why, and cleans up only the ones you pick; the branches stay, and a cleaned-up worker can be resumed later by name, conversation included. |
<!-- skills:end -->

### Install

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

| Route | Installs |
|---|---|
| `gh skill install` | the latest tagged release, or the default branch if there is none |
| `gh skill install ... --pin <tag>` | a fixed release (excluded from `gh skill update`) |
| `npx skills add` | the default branch |

Earlier versions were also a Claude Code plugin (`herdr-skills@herdr-skills`); that plugin is gone. If you installed it, remove it first with `/plugin uninstall herdr-skills@herdr-skills` and `/plugin marketplace remove herdr-skills`, then install the skill as above and ask Claude to "turn on the herdr hook".

### Requirements

- [herdr](https://herdr.dev): the skills only run inside a herdr session (`HERDR_ENV=1`)
- `claude` (Claude Code), `git`, `jq`, `python3`

### Hooks

`herdr-parallel-worktree` keeps its skill description short, because every Claude Code session carries it, including sessions outside herdr. Hooks make it reliable instead. They only act inside herdr (`HERDR_ENV=1`):

- **SessionStart**: each session starts with one short paragraph naming its role: your main session is the orchestrator, which hands off every task, even a single ticket, as a worker you can watch (and treats another skill's "dispatch a subagent per ticket" as a worker); a worker learns its name and that anything outside its worktree goes back as a handoff.
- **Your session's own worktree**: `EnterWorktree` is not blocked, for when you want this session itself to move into a worktree. Claude Code creates it as it always does (`.claude/worktrees/<name>` on branch `worktree-<name>`), and a PostToolUse hook then opens it in the herdr sidebar under its repository's space and tells the session its label (when herdr shows no space for that repository it opens nothing, and the session stays in its own tab); when `ExitWorktree` removes it, the hook closes that workspace. A detached `git worktree add` (a checkout for reading) passes too; any other `git worktree add` from the main session is denied with the same guidance: work on a task goes to a worker, whose worktree follows the repository's conventions. A worktree from `claude --worktree` at launch does not appear in the sidebar, since no tool call creates it.
- **PreToolUse**: handing work to an agent in its own worktree goes through the skill: a worktree-isolated subagent from the main session is denied and sent to the skill, a subagent that tries to create a worktree is told to stop and hand the task back as a `HERDR-HANDOFF` block, and a worker started by the skill is told to do the work itself. Entering an existing worktree with `EnterWorktree` is allowed. A subagent's or worker's file edit outside its own worktree is stopped the same way, naming who owns that place.
- **PostToolUse**: after a subagent's or worker's Bash command, if the command named a path in another worktree and something there actually changed while it ran, it is told to stop and hand that part back. Reads are fine. When the main session starts a subagent, one line tells it how to handle a returned `HERDR-HANDOFF` block.

Every handoff names an **owner**, and the main session routes it: to the worker that owns that worktree (as a follow-up, reopening or resuming that worker if needed), to you when it is your main checkout (it tells you what changed and asks), or to a new worker, started right away and reported afterwards. The hooks judge tool calls and their effects, never the wording of a prompt. Outside herdr they return before python starts; for the plain main session, the hooks on every edit and Bash command stop before doing any work.

The hooks are off until you ask Claude to "turn on the herdr hook", since that registers them in `~/.claude/settings.json` (a backup is written first). The registered entries are a copy, so after updating the skill, ask once more so that new hook events are registered. You can later ask Claude to turn them off, on, or remove them.

### Settings and data

Per-user settings live outside the skill directory, so they survive reinstalls and updates:

```
${HERDR_SKILLS_DATA_HOME:-~/.local/share/herdr-skills}/<skill>/
```

`herdr-parallel-worktree` keeps `config.json` (worker `claude` flags and the hook switch; written with defaults on the first run, and you can edit it or ask Claude to change it), `briefs/` (generated worker briefs), `runs.json` (started workers, their one-line task summaries and Claude session IDs, used for the cleanup list and resume) and an optional `brief-template.md` (your own brief template) there. Ask Claude to "change the brief template" to customize it.

## herdr plugins

Plugins for herdr itself, installed with `herdr plugin install`, not through Claude Code.

None live here at the moment. [peek](https://github.com/nyjin/herdr-peek), which renders a file or link that a pane points at in the pane beside it, has moved to its own repository; its README explains how to install it.

<!-- herdr-plugins:start -->
| Plugin | Description |
|---|---|
<!-- herdr-plugins:end -->

## Repository layout

| Path | What |
|---|---|
| `skills/<name>/` | one Agent Skill: `SKILL.md`, `references/`, `assets/`, `scripts/`, and its `tests/` |
| `herdr-plugins/<name>/` | one herdr plugin: `herdr-plugin.toml`, its scripts, `README.md` / `README.ko.md`, and its `tests/` |
| `docs/superpowers/` | design documents (`specs/`) and implementation plans (`plans/`) |
| `scripts/check.sh` | every repository check, run the same way locally and in CI |
| `scripts/release.sh` | publishes a skills release from CI when `skills/` changed |
| `install.sh` | installs skills individually |

## Contributing

All text in the repository is English. Korean appears only in the `README.ko.md` files and, where it does a job, in tests (for example patterns that match Korean model replies); `scripts/check.sh language` checks this.

### Adding a skill

1. Create `skills/<name>/SKILL.md`. The frontmatter `name` must equal the directory name and use only lowercase letters, digits and hyphens.
2. Add a row to the Skills table in both `README.md` and `README.ko.md`, between the `skills:start` and `skills:end` markers, in alphabetical order.
3. Commit it as a `feat:`. After merging, CI publishes a release so `gh skill` users get it (see [Checks and releases](#checks-and-releases)).

### Adding a herdr plugin

1. Create `herdr-plugins/<name>/` with its `herdr-plugin.toml` (its version lives there), a `README.md` and a `README.ko.md`.
2. Add a row to the herdr plugins table in both READMEs, between the `herdr-plugins:start` and `herdr-plugins:end` markers, in alphabetical order.

### Checks and releases

CI (`.github/workflows/skills-check.yaml`) runs `scripts/check.sh` on pull requests and pushes to `main`: it validates the skills with `gh skill publish --dry-run`, checks that each `name` matches its directory, checks both READMEs' tables against `skills/` and `herdr-plugins/`, checks the language rule, tests the release decision, and runs the smoke and unit tests.

When the checks pass on a push to `main`, CI publishes a release so `gh skill` users get the change: `scripts/release.sh` runs `gh skill publish --tag v<next>`. The release tag is the skills' version. Only the commits since the last `v<major>.<minor>.<patch>` tag that change `skills/` count, and their [Conventional Commits](https://www.conventionalcommits.org/) types set the bump; the largest wins:

| Commits that change `skills/` | Release |
|---|---|
| a breaking change: `type!:` or a `BREAKING CHANGE:` footer | major |
| `feat` | minor |
| `fix` or `perf` | patch |
| only other types (`docs`, `test`, `refactor`, `chore`, ...) | none |

Commits outside `skills/` never publish a release: a herdr plugin's version lives in its `herdr-plugin.toml`. If `main` moved on before the release job ran, that run publishes nothing and the newer push's run does, since `gh skill publish` tags the branch's tip. `scripts/release.sh --dry-run` prints what the current checkout would publish, without publishing.

## License

[MIT](LICENSE)
