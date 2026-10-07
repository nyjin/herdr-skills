#!/usr/bin/env bash
# CI helper: make sure gh >= 2.90.0 (the first release with `gh skill`) is on PATH.
# When the runner's gh is older, download the release into RUNNER_TEMP and add it to GITHUB_PATH.
set -euo pipefail
need=2.90.0
have=$(gh --version 2>/dev/null | head -1 | awk '{print $3}' || echo 0.0.0)
echo "runner gh=${have} (need ${need}+)"
if [ "$(printf '%s\n%s\n' "$need" "$have" | sort -V | head -1)" = "$need" ]; then exit 0; fi
d="${RUNNER_TEMP:?RUNNER_TEMP is set by GitHub Actions}/ghcli"
mkdir -p "$d"
curl -fsSL "https://github.com/cli/cli/releases/download/v${need}/gh_${need}_linux_amd64.tar.gz" \
  | tar -xz -C "$d" --strip-components=1
echo "$d/bin" >> "${GITHUB_PATH:?GITHUB_PATH is set by GitHub Actions}"
