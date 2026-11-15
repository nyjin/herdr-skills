#!/usr/bin/env python3
"""herdr 0.9.5, standard Kitty graphics: key-to-screen latency for each viewer setup, measured on the experiment
window (latency2), plus the viewer's own timings. Writes out/exp5.json."""
import json, os, statistics, subprocess, sys, time
E = os.path.dirname(os.path.abspath(__file__)); S = os.path.dirname(E)
H = f"{S}/herdr095/herdr-macos-aarch64"; SOCK = os.path.expanduser("~/.config/herdr/sessions/peek-exp5/herdr.sock")
WIN = sys.argv[1]; PANE = "w1:p1"; V = f"{E}/peekd-rs/target/release/peekv"
env = {k: v for k, v in os.environ.items() if not k.startswith("HERDR")}; env["HERDR_SOCKET_PATH"] = SOCK
def hx(*a): return subprocess.run([H, *a], env=env, capture_output=True, text=True)
def trig(text): return ["/usr/bin/env", f"HERDR_SOCKET_PATH={SOCK}", H, "pane", "send-text", PANE, text]
def lat(text, n=12):
    r = subprocess.run([f"{E}/latency2", WIN, str(n), "400", "--", *trig(text)], capture_output=True, text=True)
    ms = sorted(json.loads(l)["ms"] for l in r.stdout.splitlines() if l.strip())
    ok = [m for m in ms if m > 0]
    return {"median": statistics.median(ok) if ok else None, "p90": ok[int(len(ok) * .9) - 1] if ok else None, "min": ok[0] if ok else None, "misses": len(ms) - len(ok), "all": ok}
res = {}
# baseline: plain text echo in the same pane
def idle():   # the pane's shell must be at its prompt before the next command is typed
    hx("pane", "send-keys", PANE, "C-c"); time.sleep(0.6); hx("pane", "send-text", PANE, "q"); time.sleep(0.6); hx("pane", "send-keys", PANE, "C-c"); time.sleep(0.8)
idle(); hx("pane", "run", PANE, f"clear; less {E}/out/long.txt"); time.sleep(1.5)
res["text: less page"] = lat(" "); idle()
EV = "/Users/nyjin/src/herdr-skills-peek/herdr-plugins/peek/evals/screens"
for mode, medium, screens, scale in (("frame", "s", 0, 1.0), ("frame", "s", 0, 0.75), ("frame", "s", 0, 0.5), ("tall", "s", 1.5, 0.5), ("tall", "s", 2, 0.5)):
    log = f"{E}/out/exp5-{mode}-{medium}-{screens}-{scale}.jsonl"; open(log, "w").close()
    hx("pane", "run", PANE, f"clear; {V} {E}/out/M2n.html --mode {mode} --medium {medium} --screens {screens or 2} --scale {scale} --log {log}"); time.sleep(4)
    r = lat("j"); time.sleep(0.5)
    subprocess.run(["screencapture", "-x", "-o", "-l", WIN, f"{EV}/2026-11-15-v095-{mode}-x{screens}-scale{scale}.png"])
    hx("pane", "send-text", PANE, "q"); time.sleep(1); idle()
    draws = [json.loads(l) for l in open(log) if '"draw"' in l and '"key"' in l]
    r["viewer_key_to_written_median"] = round(statistics.median(d["key_to_written"] for d in draws), 1) if draws else None
    r["recaptures"] = f"{sum(1 for d in draws if d.get('recapture'))}/{len(draws)}"
    r["frame_mb"] = round(max((d.get("bytes", 0) for d in draws), default=0) / 1048576, 1)
    r["errors"] = [l.strip()[:120] for l in open(log) if "kitty-reply" in l or '"error"' in l][:2]
    res[f"{mode} {medium} scale {scale}" + (f" x{screens}" if screens else "")] = r
json.dump(res, open(f"{E}/out/exp5.json", "w"), indent=1)
for k, v in res.items():
    print(f"{k:16} key->screen median {v['median']} p90 {v['p90']} min {v['min']} misses {v['misses']} | viewer {v.get('viewer_key_to_written_median')} | recapture {v.get('recaptures')} | frame {v.get('frame_mb')} MB | {v.get('errors')}")
