#!/usr/bin/env python3
"""Stand-in for the herdr CLI: logs each call to $FAKE_LOG and answers pane list / pane get /
plugin pane open. Opened panes are remembered next to the log so later `pane list` calls see them."""
import json
import os
import sys
import time

args = sys.argv[1:]
log = os.environ["FAKE_LOG"]
opened = log + ".opened"
with open(log, "a") as f:
    f.write(json.dumps(args) + "\n")
if args[:2] == ["pane", "list"]:
    panes = json.loads(os.environ.get("FAKE_PANES", "[]"))
    if os.path.exists(opened):
        panes += [{"pane_id": line.strip()} for line in open(opened)]
    print(json.dumps({"result": {"panes": panes}}))
elif args[:2] == ["pane", "get"]:
    print(json.dumps({"result": {"pane": json.loads(os.environ.get("FAKE_PANE", "{}"))}}))
elif args[:3] == ["plugin", "pane", "open"]:
    time.sleep(0.3)  # a real open takes a moment; widen the window concurrent hooks race in
    pane = f"w1:v{time.time_ns()}"
    with open(opened, "a") as f:
        f.write(pane + "\n")
    print(json.dumps({"result": {"plugin_pane": {"pane": {"pane_id": pane}}}}))
