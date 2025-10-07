# SPDX-License-Identifier: LicenseRef-TVArgenta-NC-Attribution-Consult-First
# Proyecto: TVArgenta — Retro TV
# Autor: Ricardo Sappia contact:rsflightronics@gmail.com
# © 2025 Ricardo Sappia. Todos los derechos reservados.
# Licencia: No comercial, atribución y consulta previa. Se distribuye TAL CUAL, sin garantías.
# Ver LICENSE para términos completos.


from pathlib import Path
import os, getpass


ENV_ROOT = os.environ.get("TVARGENTA_ROOT")
if ENV_ROOT:
    ROOT_DIR = Path(ENV_ROOT).resolve()
else:
    # .../software/app -> .../software -> .../ (repo root)
    ROOT_DIR = Path(__file__).resolve().parents[2]

APP_DIR     = ROOT_DIR / "software" / "app"
CONTENT_DIR = ROOT_DIR / "content"
VIDEO_DIR   = CONTENT_DIR / "videos"
THUMB_DIR   = CONTENT_DIR / "thumbnails"

# Archivos de estado (en /tmp por defecto)
TMP_DIR = Path("/tmp")

# Splash y perfil de Chromium: si existe /srv/tvargenta, usamos como “datos del sistema”
# Si no, usamos ROOT_DIR.
SYSTEM_DATA_DIR = Path("/srv/tvargenta") if Path("/srv/tvargenta").exists() else ROOT_DIR
SPLASH_DIR      = APP_DIR / "assets" / "Splash" / "videos"
CHROME_PROFILE  = SYSTEM_DATA_DIR / ".chromium-profile"
CHROME_CACHE    = SYSTEM_DATA_DIR / ".chromium-cache"

# Archivos JSON
METADATA_FILE       = CONTENT_DIR / "metadata.json"
TAGS_FILE           = CONTENT_DIR / "tags.json"
CONFIG_FILE         = CONTENT_DIR / "configuracion.json"
CANALES_FILE        = CONTENT_DIR / "canales.json"
CANAL_ACTIVO_FILE   = CONTENT_DIR / "canal_activo.json"
PLAYS_FILE          = SYSTEM_DATA_DIR / "content" / "plays.json"  # persiste fuera del repo si corres en /srv

SPLASH_STATE_FILE   = SYSTEM_DATA_DIR / "Splash" / "splash_state.json"
INTRO_PATH          = SPLASH_DIR / "splash_1.mp4"

# Usuario que corre el kiosk 
USER = os.environ.get("TVARGENTA_USER") or getpass.getuser()

UPLOAD_STATUS = TMP_DIR / "upload_status.txt"
