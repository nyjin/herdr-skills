#!/usr/bin/env python3
"""Rust renderer: find, zoom and the native source view. Times by the driver (wall ms), frames kept to look at.

  fbench.py <source>:<line> [<source>:<line> ...]   pages out/M1n.html .. M4n.html must exist (made by mdhtml)"""
import json, os, select, statistics, subprocess, sys, time, zlib, struct
HERE = os.path.dirname(os.path.abspath(__file__)); os.chdir(HERE)
FR = "out/rs-frames"; RS = "./peekd-rs/target/release"

def png(src, dst, w, h):
    raw = open(src, "rb").read(); rows = bytearray()
    for y in range(h):
        row = raw[y*w*4:(y+1)*w*4]; rgba = bytearray(row); rgba[0::4], rgba[2::4] = row[2::4], row[0::4]; rows += b"\0" + rgba
    ch = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    open(dst, "wb").write(b"\x89PNG\r\n\x1a\n" + ch(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)) + ch(b"IDAT", zlib.compress(bytes(rows), 3)) + ch(b"IEND", b""))

class D:
    def __init__(self):
        self.p = subprocess.Popen([f"{RS}/peekd-rs"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True); self.p.stdout.readline()
    def ask(self, **c):
        t = time.perf_counter(); self.p.stdin.write(json.dumps(c) + "\n"); self.p.stdin.flush()
        if not select.select([self.p.stdout], [], [], 20)[0]: self.p.kill(); raise SystemExit(f"no reply to {c}")
        r = json.loads(self.p.stdout.readline()); r["wall"] = round((time.perf_counter() - t) * 1000, 1); return r

d = D(); W, H = 1000, 1300
d.ask(cmd="load", html="out/S4.html", width=W, height=H)
out = {}
# 1. source view: native highlight -> page -> first screen at the clicked line
src = []
for i, spec in enumerate(sys.argv[1:]):
    path, _, line = spec.rpartition(":"); line = int(line or 0); name = key = f"S{i + 1}"
    html = f"out/{key}-src.html"
    t = time.perf_counter()
    g = subprocess.run([f"{RS}/srchtml", path, html, str(line or 0)], capture_output=True, text=True)
    gen = round((time.perf_counter() - t) * 1000, 1); info = json.loads(g.stderr.strip().splitlines()[-1])
    r = d.ask(cmd="load", html=html, width=W, height=H)
    f = d.ask(cmd="frame", y=r.get("top", 0), scale=1, path=f"{FR}/src-{key}.bgra")
    src.append({"file": name, "lines": info["lines"], "generate": gen, "syntax_load": info["load_syntax_ms"], "open": r["wall"], "frame": f["wall"],
                "total": round(gen + r["wall"] + f["wall"], 1), "top": r.get("top")})
    if key == "S2": png(f"{FR}/src-{key}.bgra", "out/rs-src-S2.png", W, H)
out["source"] = src
# 2. find: whole-document search, then stepping to the next match
fnd = []
for doc, q in (("M2n", "skill"), ("M4n", "table"), ("M3n", "the")):
    d.ask(cmd="load", html=f"out/{doc}.html", width=W, height=H)
    first = d.ask(cmd="find", q=q, n=0)
    nexts = [d.ask(cmd="find", q=q, n=i)["wall"] for i in range(1, 6)]
    y = max(0, first["y"] - 200)
    f = d.ask(cmd="frame", y=y, scale=1, path=f"{FR}/find-{doc}.bgra")
    fnd.append({"doc": doc, "q": q, "count": first["count"], "find_first": first["wall"], "find_next_median": statistics.median(nexts), "frame": f["wall"]})
    if doc == "M2n": png(f"{FR}/find-{doc}.bgra", "out/rs-find-M2n.png", W, H)
    d.ask(cmd="find", q="", n=0)
out["find"] = fnd
# 3. zoom: re-layout at the new zoom, then re-capture
zm = []
d.ask(cmd="load", html="out/M1n.html", width=W, height=H)
for z in (1.25, 1.5, 0.8, 1.0):
    r = d.ask(cmd="zoom", z=z); f = d.ask(cmd="frame", y=0, scale=1, path=f"{FR}/zoom-{z}.bgra")
    zm.append({"z": z, "zoom": r["wall"], "frame": f["wall"], "total": round(r["wall"] + f["wall"], 1), "doc_h": r.get("doc_h"), "err": r.get("error")})
    if z == 1.5: png(f"{FR}/zoom-{z}.bgra", "out/rs-zoom-1.5.png", W, H)
out["zoom"] = zm
d.p.stdin.write('{"cmd":"quit"}\n'); d.p.stdin.flush()
json.dump(out, open("out/fbench.json", "w"), indent=1)
for k, rows in out.items():
    print("==", k)
    for r in rows: print("  ", r)
