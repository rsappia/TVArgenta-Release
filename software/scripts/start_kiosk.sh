#!/bin/bash

# Iniciar el backend de Flask en segundo plano
source /srv/tvargenta/venv/bin/activate
python /srv/tvargenta/app.py &

# Esperar a que el servidor se levante
sleep 10

# Iniciar Chromium
/usr/bin/chromium-browser --noerrdialogs --disable-infobars --kiosk http://localhost:5000

# Asegurarse de que el script siga activo mientras Chromium lo esté
wait
