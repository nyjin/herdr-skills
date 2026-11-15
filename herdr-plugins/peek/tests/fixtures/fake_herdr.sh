#!/bin/sh
# Stand-in for the herdr CLI in tests/link.rs, run as PEEK_HERDR="sh <this file>".
#
# Logs each call to $FAKE_LOG as one line, every argument followed by the unit separator (0x1f), so arguments with
# spaces survive. Answers the calls peek makes:
#   pane list          the panes in $FAKE_PANE_IDS (space-separated) plus every pane this fake opened
#   pane get <id>      {"result":{"pane":$FAKE_PANE}}
#   plugin pane open   waits 0.3 s (a real open takes a moment, which widens the window concurrent clicks race in),
#                      then answers a new pane id and remembers it next to the log
# Anything else (notification show, or peek's PEEK_OPEN pointed here) is only logged.
us=$(printf '\037')
line=""
for arg in "$@"; do
  line="$line$arg$us"
done
printf '%s\n' "$line" >> "$FAKE_LOG"

opened="$FAKE_LOG.opened"
case "$1 $2 $3" in
  "pane list "*)
    ids="${FAKE_PANE_IDS:-}"
    [ -f "$opened" ] && ids="$ids $(cat "$opened")"
    panes=""
    for id in $ids; do
      panes="$panes${panes:+,}{\"pane_id\":\"$id\"}"
    done
    printf '{"result":{"panes":[%s]}}\n' "$panes"
    ;;
  "pane get "*)
    pane="${FAKE_PANE:-}"
    [ -n "$pane" ] || pane='{}'
    printf '{"result":{"pane":%s}}\n' "$pane"
    ;;
  "plugin pane open")
    sleep 0.3
    pane="w1:v$$"
    printf '%s\n' "$pane" >> "$opened"
    printf '{"result":{"plugin_pane":{"pane":{"pane_id":"%s"}}}}\n' "$pane"
    ;;
esac
