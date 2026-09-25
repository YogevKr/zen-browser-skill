---
name: zen-browser
description: Control Yogev's real, logged-in Zen Browser (Firefox fork) from Claude Code through the firefox-bridge MCP server. Use this whenever the user wants to open, read, list, count, clean, dedupe, or close tabs in Zen, drive a page in their own browser with their own logins, run several agents on separate tabs, restore Essentials or pinned tabs, split tabs into panes or a grid, switch Spaces, focus a tab, or asks about "my browser", "my tabs", Zen windows, Spaces, containers, split view, Marionette, or firefox-bridge. Also use it before any bulk tab operation, because Zen's Window Sync and Essentials make naive tab closing destructive.
---

# Zen Browser control

The bridge drives the Zen the user is looking at, with their sessions and logins.
Every action lands in their real browser, so read the Zen facts below before bulk work.

## Setup that already exists

| Piece | Where |
|---|---|
| MCP server `firefox-bridge` | user scope in Claude Code, `node ~/repos/firefox-bridge/mcp-server/src/index.js` |
| Extension | signed, installed permanently in Zen (`firefox-bridge@firefox-bridge.local`) |
| Native host | manifest in `~/Library/Application Support/Mozilla/NativeMessagingHosts/`, Zen spawns it on start |
| Bridge state | `~/.firefox-bridge/` holds `bridge.sock` and `token`; the socket exists only while Zen runs |
| Local patch | branch `fix/stdin-decoder-limit` in the repo raises the 1 MiB inbound frame cap; without it `list_tabs` hangs on big profiles |

Health check: `ls ~/.firefox-bridge/bridge.sock` and `claude mcp get firefox-bridge`.
If the MCP server is not loaded in this session, use `scripts/zen_bridge.py`. It speaks
to the same server over stdio and needs no session restart.

## Core loop

1. `acquire_tab` with a `url` opens a new tab and leases it. With a `tabId` it leases an existing tab. Add `cookieStoreId` from `list_containers` to open inside a Firefox container, `windowId` to pick a window.
2. Work on the tab by id: `read_page`, `list_elements`, `click`, `type`, `screenshot`, `wait_for`, `navigate`.
3. `release_tab` when done, or `close_tab` to close it.

Leases are per session. Another session's tab answers `conflict`. A tab nobody leased
answers `not_leased` to close. Leases vanish when the session process exits, so a crashed
script leaves nothing locked. Two agents in two sessions can work in parallel this way,
and containers give them separate logins on the same site.

Every page action takes a `tabId`. Pass it, always. Zen has many windows and the
"active tab" is ambiguous.

## Zen facts that change how you work

**Window Sync.** Since Zen 1.18, tabs belong to a Space and windows are views of it.
`list_tabs` therefore reports the same tabs once per window with different tab ids and
identical counts. Closing a tab in one window closes it in all of them. To reduce
windows, close windows, never their tabs. The bridge has no window tool, so use macOS
accessibility: `tell application "System Events" to tell process "zen" to click (first
button of window N whose subrole is "AXCloseButton")`, backmost window first, and check
the counts after each one. An unsynced window, created by dragging a tab out, does lose
its tabs on close, so reopen them if a close drops a window with a different count.

**Essentials and pinned tabs look like ordinary tabs to the bridge.** A bulk close
takes them too. Before closing broadly, list them with
`uv run --with lz4 scripts/zen_session.py essentials` and exclude those URLs.

**Huge profiles.** The user has run with thousands of tabs. A raw `list_tabs` result is
megabytes and useless in context. Use `scripts/zen_bridge.py summary` or `list --tsv`
and read the file, never the raw tool output.

**Everything is unloaded.** Zen discards idle tabs. `read_page` on a never-loaded
session-restore tab returns `tab_not_loaded`. Navigate it first, or accept the URL and
title as the data.

**Quitting.** `tell application "Zen Browser" to quit` is ignored. Send Cmd+Q through
System Events with Zen frontmost, then poll `ps` until the process is gone. Zen rewrites
its session file at quit, so any session-file surgery happens after the process exits.

**Multiplied windows after a restart.** Zen restores one window per entry in Firefox's
session files, and a hidden or crashed instance can leave many copies of the same synced
window there. Symptom: `zen_bridge.py summary` shows several windows with identical
counts. Either close the extras one by one with the accessibility click above, or quit
Zen and run `uv run --with lz4 scripts/zen_session.py trim-windows` before relaunching.

## Bulk cleanup recipe

Closing is one `acquire_tab` plus one `close_tab` per tab, about 15 per second.
`scripts/zen_bridge.py` logs every closed tab to `~/Downloads/zen-tabs-closed.tsv`
so the user can reopen anything.

```
scripts/zen_bridge.py summary                      # windows, domains, ages, duplicates
scripts/zen_bridge.py dedupe --dry-run             # then without --dry-run
scripts/zen_bridge.py close --older-days 7 --dry-run
scripts/zen_bridge.py close --domain x.com
scripts/zen_bridge.py close --url-contains google.com/search
scripts/zen_bridge.py close --ids 4325,4327
```

Order that worked: reduce windows, dedupe by URL, close by age and category the user
chose, then hand-pick from a `list` dump for the last hundred. Ask before category cuts.
Every remaining tab is unique at that point, so the choice is the user's.

## Restoring Essentials or lost tabs

Zen writes `zen-sessions-backup/zen-sessions-YYYY-MM-DD-HH.jsonlz4` every few hours and
keeps `clean.jsonlz4` as the latest. Only the timestamped files predate a mistake.

```
uv run --with lz4 scripts/zen_session.py backups
uv run --with lz4 scripts/zen_session.py essentials <backup file>
# quit Zen (Cmd+Q via System Events), wait for the process to exit, then:
uv run --with lz4 scripts/zen_session.py restore-essentials --from <backup file>
open -a "Zen Browser"
```

The splice keeps each record intact, including the Essentials flag and pinned icon, so
Zen restores them as Essentials. Plain reopening through the bridge gives ordinary tabs
that the user must re-add by hand.

## Tool reference

Tools the server exposes: `navigate click wait_for type select_option hover read_page
read_article list_elements list_frames scroll_to drag_and_drop press_key screenshot
get_console start_console start_network get_network acquire_tab open_private_window
release_tab close_tab discard_tab go_back go_forward list_tabs request_tab_selection
get_tab_selection list_containers create_container search_history add_bookmark
list_bookmarks search_bookmarks upload_file list_dialogs respond_dialog
add_dialog_whitelist remove_dialog_whitelist webmcp_list_tools webmcp_call_tool`.

Notes:
- `screenshot` writes a PNG and returns its path. Read the file.
- `request_tab_selection` asks the user to right-click the tab they mean when two match.
- A blacklisted site pops a confirmation in Zen instead of failing. Tell the user to look.
- `discard_tab` unloads up to 50 tabs at once without a lease. It is the safe way to
  free memory. It never closes anything.
- Requests time out after 90 s in the native host.

## Panes, Spaces, and focus: the Marionette layer

The bridge cannot touch Split View, Spaces, or tab selection, because WebExtensions have
no API for them. Zen's own objects can, from a chrome-context script over Marionette,
Firefox's built-in automation channel. `scripts/zen_panes.py` wraps that, and it uses
the same tab ids as the bridge, so the two compose: lease and drive a page with the
bridge, lay it out here.

Marionette is only on when Zen was started with flags. `scripts/zen_launch.sh` does the
restart properly: Cmd+Q so Zen saves its session, then `open -a` with `--marionette`,
`--remote-debugging-port 9223`, and `--remote-allow-system-access`. Check with
`zen_launch.sh --status`. A robot icon in Zen's address bar means the flags are active.
Never start the bare binary: macOS then cannot activate it, and every Dock click hands
the hidden instance another window.

```
uv run --with marionette-driver scripts/zen_panes.py tabs            # id, selected, split, title, url
uv run --with marionette-driver scripts/zen_panes.py split 13,17     # side by side; --layout hsep | grid, up to 4
uv run --with marionette-driver scripts/zen_panes.py unsplit
uv run --with marionette-driver scripts/zen_panes.py focus 17
uv run --with marionette-driver scripts/zen_panes.py spaces          # list, active marked
uv run --with marionette-driver scripts/zen_panes.py space Work
uv run --with marionette-driver scripts/zen_panes.py screenshot out.png   # whole window
uv run --with marionette-driver scripts/zen_panes.py eval 'gBrowser.tabs.length'
```

Zen refuses to split Essentials. `eval` runs any chrome-context expression; it can do
anything the browser can, so keep it to reads and Zen's own methods.

**Worked example.** `scripts/demo.py` runs the whole stack: four bridge sessions lease
four tabs, one inside the Work container, the pane layer tiles them in a grid, each
agent reads its own page while tiled, one agent's attempt to steer another's tab is
refused, layouts change, and everything closes. It writes a PNG per step. Reuse its
shape for any "several agents, one screen" task, and build a GIF from the frames with
`magick -delay 220 -loop 0 frames/*.png -resize 1400x -colors 128 -layers Optimize out.gif`
(ffmpeg on this machine is broken by a missing x265 library).

## Alternatives, when this bridge does not fit

- Tab groups: Zen exposes none through WebExtensions. Do not promise them.
- Headless fleets: this bridge is for the user's live browser. For many isolated
  browsers use a pool such as browser-session-mcp or OpenBrowser instead.
