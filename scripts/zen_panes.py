#!/usr/bin/env python3
"""Control Zen's layout from chrome context over Marionette: split view (panes),
tab focus, Spaces, and window screenshots. Needs Zen launched by zen_launch.sh.

Tab ids here are the same ids the bridge (zen_bridge.py, firefox-bridge MCP) uses,
so the two tools compose: lease and drive a page with the bridge, lay it out here.

Usage (run with `uv run --with marionette-driver zen_panes.py ...`):
  zen_panes.py tabs                          # id, selected, split, title, url for the current window
  zen_panes.py split ID,ID[,ID,ID] [--layout vsep|hsep|grid]   # tile 2-4 tabs (default vsep = side by side)
  zen_panes.py unsplit                       # dissolve the split the selected tab is in
  zen_panes.py focus ID                      # select a tab (raises its split if it has one)
  zen_panes.py spaces                        # list Spaces, mark the active one
  zen_panes.py space NAME_OR_UUID            # switch the window to that Space
  zen_panes.py screenshot PATH.png           # whole browser window
  zen_panes.py eval 'JS'                     # chrome-context expression, returns JSON
"""
import base64, json, os, sys

try:
    from marionette_driver.marionette import Marionette
except ImportError:
    sys.exit("marionette-driver missing: run as `uv run --with marionette-driver zen_panes.py ...`")

PORT = int(os.environ.get("ZEN_MARIONETTE_PORT", "2828"))

# Map WebExtension tab ids (what the bridge uses) <-> chrome tab elements.
PRELUDE = """
const { ExtensionParent } = ChromeUtils.importESModule("resource://gre/modules/ExtensionParent.sys.mjs");
const tracker = ExtensionParent.apiManager.global.tabTracker;
const tabId = t => tracker.getId(t);
const tabById = id => gBrowser.tabs.find(t => tracker.getId(t) === id);
const viewOf = t => { const i = gZenViewSplitter._data.findIndex(g => g.tabs.includes(t)); return i < 0 ? null : {view: i, grid: gZenViewSplitter._data[i].gridType, size: gZenViewSplitter._data[i].tabs.length}; };
"""


def connect():
    try:
        m = Marionette(host="127.0.0.1", port=PORT, socket_timeout=60)
        m.start_session()
    except Exception as e:
        sys.exit(f"cannot reach Marionette on {PORT}: {e}\nStart Zen with scripts/zen_launch.sh")
    m.set_context("chrome")
    return m


def js(m, body, *args):
    return m.execute_script(PRELUDE + body, script_args=list(args), new_sandbox=False)


def cmd_tabs(m, a):
    rows = js(m, """
      return gBrowser.tabs.filter(t => !t.hasAttribute('zen-empty-tab')).map(t => ({
        id: tabId(t), selected: t === gBrowser.selectedTab, pinned: t.pinned, essential: t.hasAttribute('zen-essential'),
        split: viewOf(t), title: t.label, url: t.linkedBrowser?.currentURI?.spec || '' }));""")
    for r in rows:
        flags = ("*" if r["selected"] else " ") + ("E" if r["essential"] else "P" if r["pinned"] else " ")
        split = f"split#{r['split']['view']}/{r['split']['grid']}" if r["split"] else ""
        print(f"{r['id']:>6} {flags} {split:14} {r['title'][:45]:45} {r['url'][:70]}")


def cmd_split(m, a):
    ids = [int(x) for x in a[0].split(",")]
    layout = a[a.index("--layout") + 1] if "--layout" in a else "vsep"
    if layout not in ("vsep", "hsep", "grid"): sys.exit("layout must be vsep, hsep or grid")
    r = js(m, """
      const [ids, layout] = arguments; const tabs = ids.map(tabById);
      const missing = ids.filter((id, i) => !tabs[i]); if (missing.length) return {error: 'unknown tab ids ' + missing};
      if (tabs.some(t => t.hasAttribute('zen-essential'))) return {error: 'Zen cannot split Essentials'};
      gBrowser.selectedTab = tabs[0];
      gZenViewSplitter.splitTabs(tabs, layout);
      return {ok: true, split: viewOf(tabs[0]), max: gZenViewSplitter.MAX_TABS};""", ids, layout)
    print(json.dumps(r))


def cmd_unsplit(m, a):
    print(json.dumps(js(m, "gZenViewSplitter.unsplitCurrentView(); return {ok: true, views: gZenViewSplitter._data.length};")))


def cmd_focus(m, a):
    print(json.dumps(js(m, "const t = tabById(arguments[0]); if (!t) return {error: 'unknown tab'}; gBrowser.selectedTab = t; return {ok: true, split: viewOf(t)};", int(a[0]))))


def js_async(m, body, *args):
    # Zen's workspace getters return promises; resolve them inside the browser.
    return m.execute_async_script(PRELUDE + "const done = arguments[arguments.length - 1]; (async () => {" + body + "})().then(done, e => done({error: String(e)}));",
                                  script_args=list(args), new_sandbox=False)


def cmd_spaces(m, a):
    r = js_async(m, """
      const ws = gZenWorkspaces; const data = await ws.getWorkspaces(); const list = data?.workspaces || data || [];
      return list.map(w => ({uuid: w.uuid, name: w.name, icon: w.icon, container: w.containerTabId, active: w.uuid === ws.activeWorkspace}));""")
    if isinstance(r, dict) and r.get("error"): sys.exit(r["error"])
    for w in r: print(f"{'*' if w['active'] else ' '} {w['name']:30} container={w.get('container')} {w['uuid']}")


def cmd_space(m, a):
    print(json.dumps(js_async(m, """
      const key = arguments[0]; const ws = gZenWorkspaces; const data = await ws.getWorkspaces(); const list = data?.workspaces || data || [];
      const w = list.find(x => x.uuid === key || (x.name || '').toLowerCase() === key.toLowerCase()); if (!w) return {error: 'no such space'};
      await ws.changeWorkspace(w); return {ok: true, active: w.name};""", a[0])))


def cmd_screenshot(m, a):
    open(a[0], "wb").write(base64.b64decode(m.screenshot(full=False)))
    print("wrote", a[0])


def cmd_eval(m, a):
    print(json.dumps(js(m, "return (" + a[0] + ");"), ensure_ascii=False, default=str)[:20000])


def main():
    a = sys.argv[1:]
    if not a or a[0] in ("-h", "--help"): print(__doc__); return
    cmds = {"tabs": cmd_tabs, "split": cmd_split, "unsplit": cmd_unsplit, "focus": cmd_focus,
            "spaces": cmd_spaces, "space": cmd_space, "screenshot": cmd_screenshot, "eval": cmd_eval}
    if a[0] not in cmds: sys.exit(f"unknown command {a[0]}")
    m = connect()
    try:
        cmds[a[0]](m, a[1:])
    finally:
        m.delete_session()


if __name__ == "__main__":
    main()
