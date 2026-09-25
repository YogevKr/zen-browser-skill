#!/bin/sh
# Launch (or relaunch) the daily Zen with Marionette and WebDriver BiDi enabled,
# so scripts/zen_panes.py can reach chrome context. Ports bind to localhost only.
#
#   zen_launch.sh            # quit Zen if running (Cmd+Q, clean session save), then launch with flags
#   zen_launch.sh --status   # report whether Zen runs and whether the ports listen
#
# Marionette: 127.0.0.1:2828   BiDi: 127.0.0.1:9223
#
# Always launch through `open -a`, never the bare binary. A bare-binary launch is
# invisible to LaunchServices: the Dock cannot activate it, System Events cannot
# see it, and every Dock click hands the hidden instance one more window.
# Chrome-context access needs the `--remote-allow-system-access` flag (Gecko 156);
# the MOZ_REMOTE_ALLOW_SYSTEM_ACCESS env var cannot pass through `open`.
set -eu
APP="Zen Browser"
MARIONETTE_PORT=${ZEN_MARIONETTE_PORT:-2828}
BIDI_PORT=${ZEN_BIDI_PORT:-9223}

running() { /bin/ps -axo command | grep -q '[Z]en Browser.app/Contents/MacOS/zen'; }
listening() { lsof -nP -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1; }

if [ "${1:-}" = "--status" ]; then
  if running; then echo "zen: running"; else echo "zen: not running"; fi
  if listening "$MARIONETTE_PORT"; then echo "marionette: listening on $MARIONETTE_PORT"; else echo "marionette: off"; fi
  if listening "$BIDI_PORT"; then echo "bidi: listening on $BIDI_PORT"; else echo "bidi: off"; fi
  exit 0
fi

if running; then
  if listening "$MARIONETTE_PORT"; then
    echo "zen already runs with marionette on $MARIONETTE_PORT"; exit 0
  fi
  echo "quitting zen (Cmd+Q so it saves its session)"
  # AppleScript `quit` is ignored by Zen; the keystroke is not.
  osascript -e 'tell application "System Events" to tell process "zen" to set frontmost to true' \
            -e 'delay 0.5' \
            -e 'tell application "System Events" to keystroke "q" using command down' >/dev/null
  i=0
  while running && [ $i -lt 60 ]; do sleep 1; i=$((i+1)); done
  if running; then echo "zen did not quit within 60s; check for a dialog" >&2; exit 1; fi
  sleep 1
fi

echo "launching $APP with --marionette (port $MARIONETTE_PORT) and --remote-debugging-port $BIDI_PORT"
open -a "$APP" --args --marionette --marionette-port "$MARIONETTE_PORT" --remote-debugging-port "$BIDI_PORT" --remote-allow-system-access
i=0
while ! listening "$MARIONETTE_PORT" && [ $i -lt 90 ]; do sleep 1; i=$((i+1)); done
if listening "$MARIONETTE_PORT"; then echo "ready: marionette on $MARIONETTE_PORT"; else echo "marionette port never opened" >&2; exit 1; fi
