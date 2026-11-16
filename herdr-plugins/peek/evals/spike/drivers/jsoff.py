#!/usr/bin/env python3
"""The page as peek would ship it (content JavaScript off, CSP, no title signal): readiness, script blocking,
find highlight, elementFromPoint for clicks, and remote images arriving after the first capture."""
import json, os, select, subprocess, time
E = os.path.dirname(os.path.abspath(__file__)); os.chdir(E)
p = subprocess.Popen(["peekd-rs/target/release/peekd-rs", "--jsoff"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True); p.stdout.readline()
def ask(**c):
    t = time.perf_counter(); p.stdin.write(json.dumps(c) + "\n"); p.stdin.flush()
    if not select.select([p.stdout], [], [], 20)[0]: raise SystemExit(f"no reply to {c}")
    r = json.loads(p.stdout.readline()); r["wall"] = round((time.perf_counter() - t) * 1000, 1); return r
def js(code): return json.loads(ask(cmd="eval", js=code)["result"])
def share(path, rect, color, w=1000):
    b = open(path, "rb").read(); x0, y0, x1, y1 = [int(v) for v in rect]; n = hit = 0
    for yy in range(max(0, y0), min(1300, y1)):
        for xx in range(max(0, x0), min(w, x1)):
            i = (yy * w + xx) * 4; n += 1; hit += abs(b[i+2]-color[0]) < 25 and abs(b[i+1]-color[1]) < 25 and abs(b[i]-color[2]) < 25
    return round(hit / max(n, 1), 2)
IMGS = "const im=[...document.images]; return [im.length, im.filter(i => i.complete && i.naturalWidth > 0).length];"
for page in ("out/nojs-test.html", "out/M3-nojs.html"):
    print("==", page)
    r = ask(cmd="load", html=page, width=1000, height=1300); print(" load (readyState, no title signal):", r.get("ms"), "ms, doc_h", r.get("doc_h"), r.get("error", ""))
    print(" title (a script would change it):", repr(js("return document.title;")), "| images [all, loaded] at ready:", js(IMGS))
    # remote images: capture now, wait for them, capture again
    first = js("const i=[...document.images].find(i => /^https?:/.test(i.src)); if (!i) return null; i.scrollIntoView(); const r=i.getBoundingClientRect(); return [window.scrollY, r.left, r.top, r.right, r.bottom];")
    if first:
        y = first[0]; ask(cmd="frame", y=y, scale=1, path="out/rs-frames/img-a.bgra")
        t0 = time.time()
        while time.time() - t0 < 6 and js(IMGS)[1] < js(IMGS)[0] - (1 if "nojs-test" in page else 0): time.sleep(0.1)
        waited = round((time.time() - t0) * 1000); ask(cmd="frame", y=y, scale=1, path="out/rs-frames/img-b.bgra")
        a, b = open("out/rs-frames/img-a.bgra", "rb").read(), open("out/rs-frames/img-b.bgra", "rb").read()
        x0, y0, x1, y1 = [int(v) for v in first[1:]]; diff = sum(a[(yy*1000+xx)*4] != b[(yy*1000+xx)*4] for yy in range(max(0,y0), min(1300,y1)) for xx in range(max(0,x0), min(1000,x1)))
        print(f" remote image: waited {waited} ms, images now {js(IMGS)}, pixels changed in its box on recapture: {diff}")
    # clicks: which link is under a point
    hit = js("const a=document.querySelector('a[href]'); a.scrollIntoView(); const r=a.getBoundingClientRect(); const e=document.elementFromPoint(r.left + r.width/2, r.top + r.height/2); return [e && e.closest('a') ? e.closest('a').href : null, a.href, Math.round(window.scrollY)];")
    print(" elementFromPoint -> link:", hit[0] == hit[1], hit[0])
    # find with the highlight styles already in the page
    f = ask(cmd="find", q="agent", n=0)
    rect = js("const b=[...CSS.highlights.get('peek-cur')][0].getBoundingClientRect(); return [b.left, b.top + scrollY, b.right, b.bottom + scrollY];")
    top = max(0, f["y"] - 200); ask(cmd="frame", y=top, scale=1, path="out/rs-frames/find-nojs.bgra")
    print(" find 'agent':", f["count"], "matches,", f["ms"], "ms; current match yellow share:", share("out/rs-frames/find-nojs.bgra", (rect[0], rect[1]-top, rect[2], rect[3]-top), (249, 226, 175)))
p.stdin.write('{"cmd":"quit"}\n'); p.stdin.flush()
