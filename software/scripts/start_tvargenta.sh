#!/bin/bash
# Esperar un poquito para asegurar que todo esté listo
sleep 2

# Ir al directorio del proyecto
cd /srv/tvargenta

# Activar el entorno virtual
source venv/bin/activate

# Matar proceso previo del encoder
pkill -f encoder_reader

# Lanzar backend en segundo plano
python main.py &

# Lanzar Chromium en modo kiosko
chromium-browser --kiosk --app=http://localhost:5000/tv \
  --noerrdialogs --disable-infobars --disable-translate \
  --disable-features=Translate --autoplay-policy=no-user-gesture-required &

