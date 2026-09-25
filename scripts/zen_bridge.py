#!/usr/bin/env python3
"""Drive the user's real Zen/Firefox through firefox-bridge from a script.

Talks to the firefox-bridge MCP server over stdio, so it works even when the
MCP server is not loaded in the current Claude Code session. One process =
one bridge session = one set of tab leases. Leases drop when the process exits.

Usage:
  zen_bridge.py summary                  # counts by window, domain, age; duplicate stats
  zen_bridge.py list [--tsv PATH]        # every tab (id, window, title, url), or write a TSV
  zen_bridge.py open URL [URL...] [--container NAME] [--background]
  zen_bridge.py read TAB_ID              # page text of one tab (leases it first)
  zen_bridge.py close --ids 1,2,3        # close tabs by id (logs to --log)
  zen_bridge.py close --domain x.com --url-contains /search --older-days 7 --dry-run
  zen_bridge.py dedupe [--dry-run]       # close duplicate URLs, keep first
  zen_bridge.py call TOOL '{"json":"args"}'   # raw tool call

Every close writes the closed tabs to --log (default ~/Downloads/zen-tabs-closed.tsv).
"""
import argparse, json, os, queue, subprocess, sys, threading, time
from collections import Counter, defaultdict
from urllib.parse import urlparse

NODE = os.environ.get("ZEN_BRIDGE_NODE") or "node"
SERVER = os.environ.get("ZEN_BRIDGE_SERVER") or os.path.expanduser("~/repos/firefox-bridge/mcp-server/src/index.js")


class Bridge:
    def __init__(self, name="zen_bridge"):
        self.p = subprocess.Popen([NODE, SERVER], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, text=True)
        self.q, self.n = queue.Queue(), 0
        threading.Thread(target=self._reader, daemon=True).start()
        self._req("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                 "clientInfo": {"name": name, "version": "0"}})
        self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def _reader(self):
        for line in self.p.stdout:
            line = line.strip()
            if line.startswith("{"):
                self.q.put(json.loads(line))

    def _send(self, m):
        self.p.stdin.write(json.dumps(m) + "\n"); self.p.stdin.flush()

    def _req(self, method, params, timeout=95):
        self.n += 1; i = self.n
        self._send({"jsonrpc": "2.0", "id": i, "method": method, "params": params})
        end = time.time() + timeout
        while time.time() < end:
            try:
                m = self.q.get(timeout=max(0.1, end - time.time()))
            except queue.Empty:
                break
            if m.get("id") == i:
                return m
        return {"error": {"message": "timeout"}}

    def call(self, tool, args=None, timeout=95):
        m = self._req("tools/call", {"name": tool, "arguments": args or {}}, timeout)
        if "error" in m:
            return {"ok": False, "error": m["error"]}
        out = []
        for c in m["result"].get("content", []):
            try: out.append(json.loads(c["text"]))
            except Exception: out.append(c.get("text"))
        return out[0] if len(out) == 1 else out

    def tabs(self):
        r = self.call("list_tabs")
        if not isinstance(r, dict) or not r.get("ok"):
            sys.exit(f"list_tabs failed: {r}")
        return r["tabs"]

    def close_tab(self, tab_id):
        a = self.call("acquire_tab", {"tabId": tab_id})
        if not (isinstance(a, dict) and a.get("ok")):
            return a
        return self.call("close_tab", {"tabId": tab_id})

    def close(self):
        try:
            self.p.stdin.close(); self.p.terminate()
        except Exception:
            pass


def host(u): return urlparse(u or "").hostname or ""


def log_closed(path, tabs, reason):
    new = not os.path.exists(path)
    with open(path, "a") as f:
        if new: f.write("reason\ttitle\turl\n")
        for t in tabs:
            f.write(f"{reason}\t{(t.get('title') or '').replace(chr(9), ' ')}\t{t.get('url')}\n")


def close_many(b, victims, reason, log):
    log_closed(log, victims, reason)
    ok, fail, t0 = 0, [], time.time()
    for i, t in enumerate(victims, 1):
        r = b.close_tab(t["id"])
        if isinstance(r, dict) and r.get("ok"): ok += 1
        else: fail.append((t["id"], r))
        if i % 100 == 0 or i == len(victims):
            print(f"  {i}/{len(victims)} closed={ok} failed={len(fail)} {time.time()-t0:.0f}s", flush=True)
    if fail: print("failures (first 5):", fail[:5])
    return ok


def cmd_summary(b, a):
    t = b.tabs(); now = time.time() * 1000; day = 86400000
    win = Counter(x["windowId"] for x in t)
    print(f"tabs: {len(t)} | windows: {dict(sorted(win.items()))}")
    if len(win) > 1 and len(set(win.values())) == 1:
        print("NOTE: every window has the same count. Zen Window Sync mirrors one Space across windows;"
              " closing a tab in one window closes it everywhere. Close extra WINDOWS, not their tabs.")
    print(f"unloaded (discarded): {sum(1 for x in t if x.get('discarded'))} | containers: {dict(Counter(x.get('cookieStoreId') for x in t))}")
    urls = Counter(x["url"] for x in t)
    print(f"distinct urls: {len(urls)} | duplicate tabs: {sum(c-1 for c in urls.values() if c > 1)}")
    for lo, hi in [(0, 1), (1, 7), (7, 30), (30, 99999)]:
        print(f"  last accessed {lo}-{hi} days ago: {sum(1 for x in t if lo <= (now-(x.get('lastAccessed') or 0))/day < hi)}")
    print("top domains:")
    for h, c in Counter(host(x["url"]) for x in t).most_common(a.top):
        print(f"  {c:5d}  {h}")


def cmd_list(b, a):
    t = sorted(b.tabs(), key=lambda x: (x["windowId"], x["index"]))
    if a.tsv:
        with open(a.tsv, "w") as f:
            f.write("windowId\tindex\ttabId\tactive\tdiscarded\tcontainer\ttitle\turl\n")
            for x in t:
                f.write("\t".join(str(v) for v in [x["windowId"], x["index"], x["id"], x["active"], x["discarded"],
                                                    x.get("cookieStoreId"), (x.get("title") or "").replace("\t", " "), x["url"]]) + "\n")
        print(f"{len(t)} tabs written to {a.tsv}")
    else:
        for x in t:
            print(f"{x['id']}\tw{x['windowId']}\t{(x.get('title') or '')[:60]}\t{(x['url'] or '')[:100]}")


def cmd_open(b, a):
    store = None
    if a.container:
        cs = b.call("list_containers").get("containers", [])
        match = [c for c in cs if c["name"].lower() == a.container.lower()]
        if not match: sys.exit(f"no container named {a.container}; have {[c['name'] for c in cs]}")
        store = match[0]["cookieStoreId"]
    for u in a.urls:
        args = {"url": u}
        if store: args["cookieStoreId"] = store
        r = b.call("acquire_tab", args)
        print(json.dumps({k: r.get(k) for k in ("ok", "tabId", "url", "windowId", "cookieStoreId", "error")}))
        if r.get("ok") and not a.keep_lease:
            b.call("release_tab", {"tabId": r["tabId"]})


def cmd_read(b, a):
    r = b.call("acquire_tab", {"tabId": a.tab_id})
    if not r.get("ok"): sys.exit(f"acquire failed: {r}")
    p = b.call("read_page", {"tabId": a.tab_id})
    if isinstance(p, dict) and p.get("frames"):
        for fr in p["frames"]:
            print(f"--- frame {fr.get('frameId')} {fr.get('url')}\n{fr.get('text', '')}")
    else:
        print(json.dumps(p)[:4000])
    b.call("release_tab", {"tabId": a.tab_id})


def cmd_close(b, a):
    t = b.tabs(); now = time.time() * 1000; day = 86400000
    if a.ids:
        ids = {int(i) for i in a.ids.split(",")}
        victims = [x for x in t if x["id"] in ids]
    else:
        victims = t
        if a.domain: victims = [x for x in victims if host(x["url"]) == a.domain]
        if a.url_contains: victims = [x for x in victims if a.url_contains in (x["url"] or "")]
        if a.older_days is not None:
            victims = [x for x in victims if (now - (x.get("lastAccessed") or 0)) / day >= a.older_days]
        if not (a.domain or a.url_contains or a.older_days is not None):
            sys.exit("refusing to close everything: give --ids or a filter")
    print(f"matched {len(victims)} of {len(t)} tabs")
    for x in victims[:15]: print(f"  {x['id']}\t{(x.get('title') or '')[:50]}\t{(x['url'] or '')[:80]}")
    if len(victims) > 15: print(f"  ... {len(victims)-15} more")
    if a.dry_run: return
    print("closed", close_many(b, victims, a.reason or "close", a.log))


def cmd_dedupe(b, a):
    t = sorted(b.tabs(), key=lambda x: (x["windowId"], x["index"]))
    seen, victims = set(), []
    for x in t:
        if x["url"] in seen: victims.append(x)
        else: seen.add(x["url"])
    print(f"tabs {len(t)} | distinct {len(seen)} | duplicates to close {len(victims)}")
    if a.dry_run: return
    print("closed", close_many(b, victims, "duplicate", a.log))


def cmd_call(b, a):
    print(json.dumps(b.call(a.tool, json.loads(a.args) if a.args else {}), ensure_ascii=False)[:20000])


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--log", default=os.path.expanduser("~/Downloads/zen-tabs-closed.tsv"))
    sp = ap.add_subparsers(dest="cmd", required=True)
    s = sp.add_parser("summary"); s.add_argument("--top", type=int, default=15); s.set_defaults(f=cmd_summary)
    s = sp.add_parser("list"); s.add_argument("--tsv"); s.set_defaults(f=cmd_list)
    s = sp.add_parser("open"); s.add_argument("urls", nargs="+"); s.add_argument("--container"); s.add_argument("--keep-lease", action="store_true"); s.set_defaults(f=cmd_open)
    s = sp.add_parser("read"); s.add_argument("tab_id", type=int); s.set_defaults(f=cmd_read)
    s = sp.add_parser("close"); s.add_argument("--ids"); s.add_argument("--domain"); s.add_argument("--url-contains"); s.add_argument("--older-days", type=float); s.add_argument("--reason"); s.add_argument("--dry-run", action="store_true"); s.set_defaults(f=cmd_close)
    s = sp.add_parser("dedupe"); s.add_argument("--dry-run", action="store_true"); s.set_defaults(f=cmd_dedupe)
    s = sp.add_parser("call"); s.add_argument("tool"); s.add_argument("args", nargs="?"); s.set_defaults(f=cmd_call)
    a = ap.parse_args()
    b = Bridge()
    try:
        a.f(b, a)
    finally:
        b.close()


if __name__ == "__main__":
    main()
