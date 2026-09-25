#!/usr/bin/env python3
"""Read and repair Zen's own session file (zen-sessions.jsonlz4), which holds the
sidebar tab list, pinned flags, Essentials, folders and Spaces. Zen loads this
file at startup and injects it into every synced window.

Usage:
  zen_session.py info [FILE]            # tab / essential / pinned / folder / space counts
  zen_session.py essentials [FILE]      # list Essentials + pinned tabs (title, url)
  zen_session.py backups                # list zen-sessions-backup/ files, newest first
  zen_session.py restore-essentials --from BACKUP   # splice Essentials/pinned from BACKUP into the live file
  zen_session.py trim-windows           # keep one window in Firefox's session files (fixes multiplied windows)

restore-essentials refuses to run while Zen is running: Zen rewrites the file on
quit and would overwrite the splice. Quit Zen first (Cmd+Q; AppleScript `quit`
is ignored), run this, then relaunch Zen.

Needs the lz4 package: run with `uv run --with lz4 zen_session.py ...`.
"""
import glob, json, os, subprocess, sys, time

try:
    import lz4.block
except ImportError:
    sys.exit("lz4 missing: run as `uv run --with lz4 zen_session.py ...`")

PROFILES = os.path.expanduser("~/Library/Application Support/zen/Profiles")


def profile_dir():
    env = os.environ.get("ZEN_PROFILE_DIR")
    if env: return env
    cands = sorted(glob.glob(os.path.join(PROFILES, "*")), key=lambda p: os.path.getmtime(os.path.join(p, "zen-sessions.jsonlz4")) if os.path.exists(os.path.join(p, "zen-sessions.jsonlz4")) else 0, reverse=True)
    if not cands: sys.exit("no Zen profile found")
    return cands[0]


def load(f):
    raw = open(f, "rb").read()
    if raw[:8] != b"mozLz40\0": sys.exit(f"{f}: not a mozLz4 file")
    return json.loads(lz4.block.decompress(raw[8:]))


def save(f, d):
    open(f, "wb").write(b"mozLz40\0" + lz4.block.compress(json.dumps(d, separators=(",", ":")).encode()))


def url_of(t):
    return t["entries"][-1].get("url", "") if t.get("entries") else ""


def title_of(t):
    return t.get("zenStaticLabel") or (t["entries"][-1].get("title", "") if t.get("entries") else "")


def zen_running():
    out = subprocess.run(["/bin/ps", "-axo", "command"], capture_output=True, text=True).stdout
    return "Zen Browser.app/Contents/MacOS/zen" in out


def cmd_info(f):
    d = load(f); t = d["tabs"]
    print(f"{f}\n  tabs {len(t)} | essentials {sum(1 for x in t if x.get('zenEssential'))} | pinned {sum(1 for x in t if x.get('pinned'))}"
          f" | folders {len(d.get('folders', []))} | groups {len(d.get('groups', []))} | spaces {[s['name'] for s in d.get('spaces', [])]}")


def cmd_essentials(f):
    for x in load(f)["tabs"]:
        if x.get("zenEssential") or x.get("pinned"):
            print(f"{'ESS' if x.get('zenEssential') else 'PIN'}\t{title_of(x)[:50]}\t{url_of(x)[:90]}")


def cmd_backups(p):
    files = sorted(glob.glob(os.path.join(p, "zen-sessions-backup", "*")), key=os.path.getmtime, reverse=True)
    for f in files:
        try:
            d = load(f); t = d["tabs"]
            print(f"{time.strftime('%Y-%m-%d %H:%M', time.localtime(os.path.getmtime(f)))}  tabs {len(t):5d}  ess {sum(1 for x in t if x.get('zenEssential')):3d}  {os.path.basename(f)}")
        except SystemExit:
            print(f"{os.path.basename(f)}: unreadable")


def cmd_restore(p, src):
    if zen_running(): sys.exit("Zen is running. Quit it first (Cmd+Q), then rerun.")
    live = os.path.join(p, "zen-sessions.jsonlz4")
    cur, bak = load(live), load(src)
    have = {url_of(t) for t in cur["tabs"]}
    add = [t for t in bak["tabs"] if (t.get("zenEssential") or t.get("pinned")) and url_of(t) not in have]
    spaces = {s["uuid"] for s in cur.get("spaces", [])}
    for t in add:
        t["lastAccessed"] = int(time.time() * 1000)
        if t.get("zenWorkspace") not in spaces and spaces:
            t["zenWorkspace"] = next(iter(spaces))
    stamp = time.strftime("%Y%m%d-%H%M%S")
    keep = os.path.join(os.path.expanduser("~/Downloads"), f"zen-sessions.pre-restore-{stamp}.jsonlz4")
    save(keep, cur)
    cur["tabs"] = add + cur["tabs"]
    save(live, cur)
    print(f"added {len(add)} tabs from {os.path.basename(src)}; previous live file saved to {keep}")
    cmd_info(live)


def cmd_trim_windows(p):
    """Zen restores one window per entry in Firefox's session files. After a bad launch
    or repeated Dock clicks on a hidden instance those files can hold many copies of the
    same synced window. Keep the first window in each file; tabs live in zen-sessions
    and are not touched."""
    if zen_running(): sys.exit("Zen is running. Quit it first (Cmd+Q), then rerun.")
    stamp = time.strftime("%Y%m%d-%H%M%S")
    for name in ("sessionstore.jsonlz4", "sessionstore-backups/recovery.jsonlz4", "sessionstore-backups/recovery.baklz4"):
        f = os.path.join(p, name)
        if not os.path.exists(f): continue
        d = load(f); n = len(d.get("windows", []))
        keep = os.path.join(os.path.expanduser("~/Downloads"), f"{os.path.basename(f)}.pre-trim-{stamp}")
        save(keep, d)
        d["windows"] = d.get("windows", [])[:1]; d["_closedWindows"] = []; d["selectedWindow"] = 1
        save(f, d)
        print(f"{name}: windows {n} -> {len(d['windows'])} (backup {keep})")


def main():
    a = sys.argv[1:]
    if not a or a[0] in ("-h", "--help"): print(__doc__); return
    p = profile_dir()
    live = os.path.join(p, "zen-sessions.jsonlz4")
    if a[0] == "info": cmd_info(a[1] if len(a) > 1 else live)
    elif a[0] == "essentials": cmd_essentials(a[1] if len(a) > 1 else live)
    elif a[0] == "backups": cmd_backups(p)
    elif a[0] == "restore-essentials":
        if "--from" not in a: sys.exit("need --from BACKUP")
        cmd_restore(p, a[a.index("--from") + 1])
    elif a[0] == "trim-windows": cmd_trim_windows(p)
    else: sys.exit(f"unknown command {a[0]}")


if __name__ == "__main__":
    main()
