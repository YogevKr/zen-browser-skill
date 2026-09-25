#!/usr/bin/env python3
"""Demo: four agent sessions each lease a tab (one in the Work container), the pane
layer tiles them, agents read their pages while tiled, layouts change, cleanup.
Writes numbered PNG frames to --out (default ./demo-frames). Make a GIF with:
  magick -delay 220 -loop 0 demo-frames/*.png -resize 1400x -colors 128 -layers Optimize demo.gif
Run: uv run --with marionette-driver scripts/demo.py [--out DIR]
Needs Zen started by scripts/zen_launch.sh."""
import sys, time, json, base64, subprocess, os
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
from zen_bridge import Bridge
from marionette_driver.marionette import Marionette

OUT = sys.argv[sys.argv.index("--out") + 1] if "--out" in sys.argv else os.path.join(os.getcwd(), "demo-frames")
os.makedirs(OUT, exist_ok=True)
PRELUDE = open(os.path.join(HERE, "zen_panes.py")).read().split('PRELUDE = """')[1].split('"""')[0]

m = Marionette(host="127.0.0.1", port=2828, socket_timeout=60); m.start_session(); m.set_context("chrome")
def js(body, *args): return m.execute_script(PRELUDE + body, script_args=list(args), new_sandbox=False)
frame_n = [0]
def shot(label, pause=1.5):
    time.sleep(pause); frame_n[0] += 1
    p = f"{OUT}/{frame_n[0]:02d}-{label}.png"; open(p, "wb").write(base64.b64decode(m.screenshot(full=False))); print(f"  frame {frame_n[0]} {label}")
def split(ids, layout): return js("const [ids, l] = arguments; const tabs = ids.map(tabById); gBrowser.selectedTab = tabs[0]; gZenViewSplitter.splitTabs(tabs, l); return viewOf(tabs[0]);", ids, layout)
def focus(i): js("gBrowser.selectedTab = tabById(arguments[0]);", i)
def unsplit(): js("gZenViewSplitter.unsplitCurrentView();")

subprocess.run(["osascript", "-e", 'tell application "Zen Browser" to activate'], capture_output=True)
shot("start", 1)

# --- Act 1: four agents, four tabs, one in the Work container ---------------------------
print("act 1: four agent sessions open their own tabs")
agents = {}
plan = [("hn", "https://news.ycombinator.com/", None),
        ("gh", "https://github.com/raychao-oao/firefox-bridge", "Work"),
        ("zen", "https://zen-browser.app/release-notes/", None),
        ("wiki", "https://en.wikipedia.org/wiki/Marionette_(software)", None)]
for name, url, container in plan:
    b = Bridge(f"agent-{name}")
    args = {"url": url}
    if container:
        cs = b.call("list_containers")["containers"]; args["cookieStoreId"] = next(c["cookieStoreId"] for c in cs if c["name"] == container)
    r = b.call("acquire_tab", args); agents[name] = (b, r["tabId"]); print(f"  {name}: tab {r['tabId']} container={r.get('cookieStoreId')}")
ids = [t for _, t in agents.values()]
time.sleep(4); focus(ids[0]); shot("four-tabs-open")

# --- Act 2: grid layout --------------------------------------------------------------------
print("act 2: tile all four in a grid")
print("  ", split(ids, "grid")); shot("grid-of-four", 3)

# --- Act 3: agents read their own pages while tiled -----------------------------------------
print("act 3: each agent reads its own tab")
def text_of(b, tid):
    p = b.call("read_page", {"tabId": tid})
    return " ".join(fr.get("text", "") for fr in p.get("frames", [])) if isinstance(p, dict) else ""
hn = text_of(*agents["hn"]); lines = [l.strip() for l in hn.splitlines() if l.strip()]
print("  HN first lines:", " | ".join(lines[3:8])[:200])
gh = text_of(*agents["gh"]); print("  GitHub:", gh[:160].replace("\n", " "))
wiki = text_of(*agents["wiki"]); print("  Wikipedia:", wiki[:160].replace("\n", " "))
# cross-session isolation proof
other = agents["hn"][0].call("navigate", {"tabId": agents["gh"][1], "url": "https://example.com/"})
print("  agent hn tries to steer agent gh's tab ->", other.get("error"))
shot("agents-read", 1)

# --- Act 4: re-layout ---------------------------------------------------------------------
print("act 4: change layouts")
unsplit(); time.sleep(1)
print("  ", split(ids[:2], "vsep")); shot("hn-and-github-side-by-side", 3)
unsplit(); time.sleep(1)
print("  ", split(ids[2:], "hsep")); shot("zen-and-wiki-stacked", 3)
unsplit(); time.sleep(1)
print("  ", split(ids[:3], "grid")); shot("three-grid", 3)

# --- Act 5: cleanup -----------------------------------------------------------------------
print("act 5: cleanup")
unsplit(); time.sleep(1)
for name, (b, tid) in agents.items():
    r = b.call("close_tab", {"tabId": tid}); print(f"  {name}: close -> {r.get('ok')}"); b.close()
shot("end", 2)
m.delete_session()
print("frames in", OUT)
