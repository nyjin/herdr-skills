<!--
Default worker brief template for herdr-parallel-worktree.

- Copy this file and change section titles, order and guidance as you like. For locations and precedence, see the skill's references/brief-filling.md.
- Guidance written as HTML comments is for filling only and is stripped from the final brief.
- Reserved placeholders: {{name}} {{branch}} {{base}} {{summary}}
- The closing paragraph (commit, result report, no push) is always appended by the skill. Do not write it here.
- Section titles and content may be in any language.
-->
# [{{name}}] {{summary}}

## Goal
<!-- What "done" looks like, in a sentence or two. Take it from the user's request. -->

## References
<!--
Material the user pointed to: ticket keys, document paths, URLs, related branches.
Do not paste text here; save it to a separate file and list only the path.
Delete this whole section if there is no material.
-->

## Steps
<!--
The steps the user gave, in order. Keep tool, command and skill names exactly as the user wrote them.
If material must be read first (e.g. a ticket), make that the first step.
If the user gave no steps, use the default:
  1. Understand the relevant code
  2. Implement
  3. Verify, e.g. with tests
  4. Commit
If the user gave only some (e.g. "review before committing"), insert them at the right place in the default steps.
-->

## Rules
<!--
Constraints the user stated: commit message format, what must not be touched, coding rules.
Delete this whole section if there are none.
-->
