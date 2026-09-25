# zen-browser

A Claude Code skill for driving a real, logged-in [Zen Browser](https://zen-browser.app)
from coding agents. Page work goes through the
[firefox-bridge](https://github.com/raychao-oao/firefox-bridge) MCP server, with one tab
lease per agent session and Firefox containers for separate logins. Layout goes through
Marionette, Firefox's built-in automation channel, which reaches Zen's own Split View and
Spaces objects in chrome context.

`SKILL.md` is the instruction file agents read. `scripts/` holds the tools it points at.

| Script | Purpose |
|---|---|
| `zen_launch.sh` | Start Zen with Marionette and BiDi enabled, or report status |
| `zen_bridge.py` | Tabs through the bridge: summary, list, open, read, close, dedupe, raw calls |
| `zen_panes.py` | Layout through Marionette: split, unsplit, focus, Spaces, screenshots |
| `zen_session.py` | Zen's session file: Essentials, backups, restore, window trim |
| `demo.py` | Four agents in a grid, end to end |

## Install

```
git clone https://github.com/YogevKr/zen-browser-skill ~/projects/skills/zen-browser
ln -s ~/projects/skills/zen-browser ~/.claude/skills/zen-browser
```

Then install firefox-bridge (extension, native host, MCP server) as its README describes.
The bridge's native host needs the inbound frame limit raised for profiles with thousands
of tabs; see the note in `SKILL.md`.

Scripts run with [uv](https://docs.astral.sh/uv/): `uv run --with lz4 scripts/zen_session.py`
and `uv run --with marionette-driver scripts/zen_panes.py`. `zen_bridge.py` needs only
Python and Node.

## Things Zen does that shape this skill

- Window Sync: every window is a view of the same Space. Close windows, not their tabs.
- Essentials and pinned tabs look like plain tabs to extensions. Bulk closes take them.
- Zen unloads idle tabs and can hold thousands. Never put a raw tab list in an agent's context.
- Zen ignores AppleScript quit and rewrites its session file at exit.
- Start Zen through `open -a`. A bare-binary launch is invisible to the Dock.
