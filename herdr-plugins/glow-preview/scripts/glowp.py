#!/usr/bin/env python3
"""glow-preview: show markdown, source files and Jira/Confluence/PR links beside a Claude Code pane.

  glowp.py link     herdr link handler action ($HERDR_PLUGIN_CLICKED_URL, $HERDR_PANE_ID).
  glowp.py toggle   herdr action: flip rendered/source for the viewer it was run from.
  glowp.py viewer   the plugin pane: follows <state>/<$GLOWP_SOURCE>.json and shows it in less.

Nothing opens without a click: the link handler writes the state file and opens the viewer pane
when the source pane has none. The viewer renders with glow (markdown) or bat (source, or markdown as source) into a
file and pages it with less, restarting less when the state changes; nothing is typed into a shell.
"""
import json
import os
import select
import shlex
import shutil
import signal
import subprocess
import sys
import termios
import time
import tty

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fetch  # noqa: E402
import resolve  # noqa: E402
import targets  # noqa: E402

PLUGIN_ID = "nyjin.glow-preview"
# Appended, not prepended: the user's own wrappers (e.g. a gh that picks the account per repo) must win.
os.environ["PATH"] = os.environ.get("PATH", "") + ":/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"


def herdr_cmd():
    return shlex.split(os.environ.get("GLOWP_HERDR") or os.environ.get("HERDR_BIN_PATH") or "herdr")


def herdr(*args):
    return subprocess.run(herdr_cmd() + list(args), capture_output=True, text=True, timeout=10)


def herdr_json(*args):
    r = herdr(*args)
    return json.loads(r.stdout).get("result", {}) if r.returncode == 0 and r.stdout.strip() else {}


def notify(body):
    herdr("notification", "show", "glow-preview", "--body", body)


def state_dir():
    # Fixed on purpose: herdr gives plugin panes their own HERDR_PLUGIN_STATE_DIR, but the Claude Code
    # hook runs outside herdr's plugin runner, and both sides must meet in one folder.
    return os.environ.get("GLOWP_STATE_DIR") or os.path.expanduser("~/.local/state/glow-preview")


def state_file(source, ext):
    return os.path.join(state_dir(), source.replace("/", "_") + ext)


def is_markdown(path):
    return path.lower().endswith((".md", ".markdown"))


def write_atomic(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w") as f:
        f.write(text)
    os.replace(tmp, path)


def viewer_alive(source):
    try:
        viewer = open(state_file(source, ".viewer")).read().strip()
    except OSError:
        return False
    panes = herdr_json("pane", "list").get("panes", [])
    return any(p.get("pane_id") == viewer for p in panes)


def source_lock(source):
    """Serialise check-and-open per source pane: Claude fires several async hooks at once."""
    path = state_file(source, ".lock")
    os.makedirs(state_dir(), exist_ok=True)
    deadline = time.time() + 10
    while True:
        try:
            os.close(os.open(path, os.O_CREAT | os.O_EXCL))
            return path
        except FileExistsError:
            try:
                if time.time() - os.path.getmtime(path) > 15:  # left by a killed hook
                    os.remove(path)
                    continue
            except OSError:
                continue
            if time.time() > deadline:
                return None
            time.sleep(0.05)


def write_state(source, items, toggle=False):
    st = {"items": items, "seq": time.time_ns()}
    if toggle:
        st["toggle"] = True
    write_atomic(state_file(source, ".json"), json.dumps(st))


def show(source, items):
    write_state(source, items)
    lock = source_lock(source)
    try:
        if viewer_alive(source):
            return
        r = herdr("plugin", "pane", "open", "--plugin", PLUGIN_ID, "--entrypoint", "viewer",
                  "--placement", "split", "--target-pane", source, "--direction", "right",
                  "--no-focus", "--env", f"GLOWP_SOURCE={source}")
        # Record the new pane now, not when the viewer process starts, so a hook right behind
        # this one sees it and does not open a second viewer.
        try:
            pane = json.loads(r.stdout)["result"]["plugin_pane"]["pane"]["pane_id"]
            write_atomic(state_file(source, ".viewer"), pane)
        except (ValueError, KeyError, TypeError):
            pass
    finally:
        if lock:
            os.remove(lock)


def cmd_link():
    source = os.environ.get("HERDR_PANE_ID")
    text = os.environ.get("HERDR_PLUGIN_CLICKED_URL", "")
    if not source or not text:
        return 1
    t = targets.classify(text)
    if t["kind"] == "path" and t["text"].startswith(("http://", "https://")):
        # A web URL that only looked like a file (…/blob/main/README.md): keep the default and open it.
        subprocess.run([os.environ.get("GLOWP_OPEN", "open"), t["text"]])
        return 0
    if t["kind"] != "path":
        show(source, [{"url": t["url"]}])
        return 0
    pane = herdr_json("pane", "get", source).get("pane", {})
    found = resolve.candidates(
        t["text"], pane.get("foreground_cwd") or pane.get("cwd"), (pane.get("agent_session") or {}).get("value"),
        home=os.path.expanduser("~"), tmp_root=f"/private/tmp/claude-{os.getuid()}",
        projects_root=os.path.expanduser("~/.claude/projects"))
    if not found:
        notify(f"파일을 찾지 못했습니다: {t['text']}")
        return 0
    show(source, [{"path": p, "line": t["line"]} for p in found])
    return 0


def cmd_toggle():
    """Flip rendered/source for the viewer the action was run from (the viewer pane or its Claude pane)."""
    me = os.environ.get("HERDR_PANE_ID", "")
    source = me
    for name in os.listdir(state_dir()) if os.path.isdir(state_dir()) else []:
        if name.endswith(".viewer"):
            with open(os.path.join(state_dir(), name)) as f:
                if f.read().strip() == me:
                    source = name[:-len(".viewer")]
    st = read_state(source)
    if not st:
        return 0
    write_atomic(state_file(source, ".mode"), "rendered" if read_mode(source) == "source" else "source")
    write_state(source, st.get("items") or [], toggle=True)
    return 0


# ---- viewer -------------------------------------------------------------------------------

def reset_terminal():
    sys.stdout.write("\x1b[?1049l\x1b[?25h\x1b[0m\x1b[2J\x1b[H")
    sys.stdout.flush()
    subprocess.run(["stty", "sane"], stdin=sys.stdin)


def read_state(source):
    try:
        with open(state_file(source, ".json")) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def read_mode(source):
    try:
        with open(state_file(source, ".mode")) as f:
            return f.read().strip() or "rendered"
    except OSError:
        return "rendered"


def ensure_tool(cmd, formula):
    if shutil.which(cmd):
        return True
    if not shutil.which("brew"):
        print(f"{cmd}가 없습니다. 설치한 뒤 r 을 누르세요.")
        return False
    notify(f"{cmd}가 없어 설치합니다 (brew install {formula}).")
    print(f"{cmd}가 없어 설치합니다: brew install {formula}\n")
    ok = subprocess.run(["brew", "install", formula]).returncode == 0 and shutil.which(cmd)
    notify(f"{cmd} 설치를 마쳤습니다." if ok else f"{cmd} 설치에 실패했습니다. 뷰어 pane의 출력을 확인하세요.")
    return bool(ok)


def changed(source, seq):
    st = read_state(source)
    return bool(st) and st.get("seq") != seq


def wait_key(source, seq, keys):
    """Wait for one of `keys` or a state change. Returns the key, or None when the state changed."""
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        while True:
            if changed(source, seq):
                return None
            if select.select([sys.stdin], [], [], 0.3)[0]:
                ch = os.read(fd, 1).decode(errors="ignore")
                if ch in keys:
                    return ch
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


BAT_HEADER_LINES = 1  # bat's header-filename line above line 1


def less_prompt(label):
    """less's prompt names the rendered temp file by default; show what is being viewed instead."""
    esc = "".join("\\" + c if c in "?:.%\\" else c for c in label)
    return f"-Ps{esc} · q 메뉴$"


def render(path, mode, line, width, label):
    """Render to an ANSI file for less. Returns (file, less arguments)."""
    out = os.path.join(state_dir(), f"render-{os.getpid()}.ansi")
    if is_markdown(path) and mode == "rendered":
        cmd = ["glow", "-s", os.environ.get("GLOWP_STYLE", "auto"), "-w", str(width), path]
    else:
        cmd = ["bat", "--color=always", "--paging=never", "--style=numbers,header-filename",
               f"--terminal-width={width + 2}", path]
        if line:
            cmd.insert(-1, f"--highlight-line={line}")
    with open(out, "w") as f:
        subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT)
    args = ["less", "-R", "-j.3", less_prompt(label)]
    if line and not (is_markdown(path) and mode == "rendered"):
        args.append(f"+{line + BAT_HEADER_LINES}g")
    return out, args



def page(source, seq, path, mode, line, label):
    """Show one file in less until it quits (True) or the state changes (False)."""
    width = max(shutil.get_terminal_size().columns - 2, 20)
    out, args = render(path, mode, line, width, label)
    child = subprocess.Popen(args + [out])
    try:
        while child.poll() is None:
            if changed(source, seq):
                child.terminate()
                try:
                    child.wait(2)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait()
                return False
            time.sleep(0.3)
        return True
    finally:
        reset_terminal()


def load(source, seq, item, refresh):
    """The file to show for an item, as (file, ok, label), or None when the state changed meanwhile.
    A link is read from its cache (keyed by the URL's hash) and fetched only when there is no cached
    copy or `refresh` is set; only a successful fetch is cached, a failure is shown and retried later."""
    if "url" not in item:
        return item["path"], True, item["path"].replace(os.path.expanduser("~"), "~", 1)
    url = item["url"]
    cache = fetch.cache_path(url)
    if refresh or not os.path.exists(cache):
        reset_terminal()
        print(f"가져오는 중…\n{url}")
        md, ok, tool = fetch.fetch_markdown(url)
        if changed(source, seq):
            return None
        if not ok:
            write_atomic(cache + ".error.md", md)
            return cache + ".error.md", False, url
        write_atomic(cache, md)
        write_atomic(cache + ".tool", tool)
    try:
        with open(cache + ".tool") as f:
            tool = f.read().strip()
    except OSError:
        tool = "?"
    when = time.strftime("%m-%d %H:%M", time.localtime(os.path.getmtime(cache)))
    return cache, True, f"{url} · {tool} · 가져온 시각 {when}"


def pick(source, seq, items):
    print("같은 이름의 파일이 여러 개입니다. 번호를 고르세요 (최근에 다룬 파일이 위):\n")
    for i, it in enumerate(items[:9], 1):
        print(f"  {i}. {it['path'].replace(os.path.expanduser('~'), '~', 1)}")
    print("\n  q. 닫기")
    key = wait_key(source, seq, "q" + "".join(str(i) for i in range(1, min(len(items), 9) + 1)))
    if key is None or key == "q":
        return key
    return items[int(key) - 1]


def menu(item, path, ok, is_md):
    keys = [("r", "다시 보기")]
    if is_md:
        keys.append(("s", "렌더링/원문 전환"))
    if "url" in item:
        keys.append(("f", "새로 가져오기"))
        keys.append(("o", "브라우저로 열기"))
    keys.append(("q", "닫기"))
    print(f"{item.get('url') or path}\n\n  " + " · ".join(f"{k} {label}" for k, label in keys))
    return "".join(k for k, _ in keys)


def cmd_viewer():
    source = os.environ.get("GLOWP_SOURCE")
    me = os.environ.get("HERDR_PANE_ID", "")
    if not source:
        print("GLOWP_SOURCE가 없습니다.")
        return 1
    write_atomic(state_file(source, ".viewer"), me)
    try:
        for cmd, formula in (("glow", "glow"), ("bat", "bat")):
            while not ensure_tool(cmd, formula):
                if wait_key(source, (read_state(source) or {}).get("seq"), "rq") == "q":
                    return 0
        st = read_state(source) or {}
        chosen, refresh = None, False
        while True:
            seq, items = st.get("seq"), st.get("items") or []
            reset_terminal()
            if not items:
                print("Claude pane에서 파일 경로나 링크를 클릭하면 여기에 보여 줍니다.  q 닫기")
                if wait_key(source, seq, "q") == "q":
                    return 0
                st, chosen = read_state(source) or {}, None
                continue
            if chosen is None:
                chosen = items[0] if len(items) == 1 else pick(source, seq, items)
                if chosen == "q":
                    return 0
                if chosen is None:
                    st = read_state(source) or {}
                    continue
            item = chosen
            got = load(source, seq, item, refresh)
            refresh = False
            if got is None:
                st, chosen = read_state(source) or {}, None
                continue
            path, ok, label = got
            if page(source, seq, path, read_mode(source), item.get("line"), label):
                key = wait_key(source, seq, menu(item, path, ok, is_markdown(path)))
                if key == "q":
                    return 0
                if key == "r":
                    continue
                if key == "s":
                    write_atomic(state_file(source, ".mode"), "rendered" if read_mode(source) == "source" else "source")
                    continue
                if key == "o":
                    subprocess.run(["open", item["url"]])
                    continue
                if key == "f":
                    refresh = True
                    continue
            new = read_state(source) or {}
            if new.get("toggle") and new.get("items") == items:  # only the mode flipped: keep the item
                st = new
                continue
            st, chosen = new, None
    finally:
        try:
            os.remove(os.path.join(state_dir(), f"render-{os.getpid()}.ansi"))
        except OSError:
            pass
        try:
            if open(state_file(source, ".viewer")).read().strip() == me:
                os.remove(state_file(source, ".viewer"))
        except OSError:
            pass


def main(argv):
    cmd = argv[1] if len(argv) > 1 else ""
    handlers = {"link": cmd_link, "viewer": cmd_viewer, "toggle": cmd_toggle}
    if cmd in handlers:
        return handlers[cmd]()
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
