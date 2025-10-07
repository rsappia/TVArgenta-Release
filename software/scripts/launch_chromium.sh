#!/bin/bash
set -euo pipefail

export DISPLAY=:0
export XAUTHORITY=/home/rs/.Xauthority
export XDG_RUNTIME_DIR=/run/user/1000
export DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus
export HOME=/home/rs

# Evitar bloqueo si quedó instancia previa
/usr/bin/pkill -f 'chromium-browser.*--app=http://localhost:5000/tv' || true

# Darle un toque de tiempo a Flask
sleep 3

# Lanzar en background y salir
/usr/bin/chromium-browser --kiosk --app=http://localhost:5000/tv \
  --noerrdialogs --disable-infobars --disable-translate \
  --disable-features=Translate --autoplay-policy=no-user-gesture-required \
  --password-store=basic --no-first-run --disable-session-crashed-bubble \
  >/home/rs/chromium_kiosk.log 2>&1 &
exit 0

