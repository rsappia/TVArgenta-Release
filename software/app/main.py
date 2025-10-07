# SPDX-License-Identifier: LicenseRef-TVArgenta-NC-Attribution-Consult-First
# Proyecto: TVArgenta — Retro TV
# Autor: Ricardo Sappia contact:rsflightronics@gmail.com
# © 2025 Ricardo Sappia. Todos los derechos reservados.
# Licencia: No comercial, atribución y consulta previa. Se distribuye TAL CUAL, sin garantías.
# Ver LICENSE para términos completos.


from flask import Flask, render_template, request, redirect, url_for, jsonify, send_from_directory, flash, render_template_string, send_file
import threading
import os
import json
import subprocess
from werkzeug.utils import secure_filename
import tempfile
import shutil
from datetime import datetime, UTC
import atexit
import signal
import time
import random
import logging
from logging.handlers import RotatingFileHandler
import math
import base64, urllib.parse
from pathlib import Path
from settings import (
    ROOT_DIR, APP_DIR, CONTENT_DIR, VIDEO_DIR, THUMB_DIR,
    METADATA_FILE, TAGS_FILE, CONFIG_FILE, CANALES_FILE, CANAL_ACTIVO_FILE,
    SPLASH_DIR, SPLASH_STATE_FILE, INTRO_PATH, CHROME_PROFILE, CHROME_CACHE, 
    PLAYS_FILE, USER, UPLOAD_STATUS, TMP_DIR
)                       

log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)  # solo errores visibles
app = Flask(__name__)

# --- LOGGING ---------------------------------------------------------------
LOG_PATH = str(TMP_DIR / "tvargenta.log") 
logger = logging.getLogger("tvargenta")
logger.setLevel(logging.INFO)

if not logger.handlers:
    _h = RotatingFileHandler(LOG_PATH, maxBytes=1_000_000, backupCount=3)
    _fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )
    _h.setFormatter(_fmt)
    logger.addHandler(_h)

def _hdr(name):
    # mini helper para loggear origen de las requests
    ref = request.headers.get("Referer", "-")
    ua  = request.headers.get("User-Agent", "-")
    ip  = request.headers.get("X-Forwarded-For") or request.remote_addr
    return f"{name} ref={ref} ip={ip} ua={ua}"
# --------------------------------------------------------------------------



# Ruta base de videos y metadatos
TRIGGER_PATH = str(TMP_DIR / "trigger_reload.json")
VOLUMEN_PATH = str(TMP_DIR / "tvargenta_volumen.json")
MENU_TRIGGER_PATH = str(TMP_DIR / "trigger_menu.json")
MENU_STATE_PATH  = str(TMP_DIR / "menu_state.json")
MENU_NAV_PATH    = str(TMP_DIR / "trigger_menu_nav.json")
MENU_SELECT_PATH = str(TMP_DIR / "trigger_menu_select.json")

INTRO_FLAG  = "/tmp/tvargenta_show_intro"
LAUNCH_FLAG      = str(TMP_DIR / "tvargenta_kiosk_launched")
CURRENT_SPLASH_FILE = str(TMP_DIR / "tvargenta_current_splash.json")


ALSA_DEVICE   = "default"   
SPLASH_DONE   = "/tmp/.tvargenta_splash_done"

PING_FILE = "/tmp/tvargenta_kiosk_ping.txt"
FRONT_PING_PATH = "/tmp/tvargenta_front_ping.json"

CONTENT_DIR = Path(CONTENT_DIR)

DEFAULT_CONFIG = {"tags_prioridad": [], "tags_incluidos": []}
DEFAULT_CANAL_ACTIVO = {"canal_id": "1"}


def get_next_splash_path():
    """
    Elige el splash *para este arranque* sin avanzar todavía el índice persistente.
    Escribe la elección en /tmp para que /splash la use.
    """
    try:
        files = sorted(
            f for f in os.listdir(SPLASH_DIR)
            if f.lower().endswith(".mp4") and f.startswith("splash_")
        )
    except Exception as e:
        logger.error(f"[SPLASH] no puedo listar {SPLASH_DIR}: {e}")
        files = []

    if not files:
        # fallback al que ya usabas
        path = INTRO_PATH if os.path.isfile(INTRO_PATH) else None
        logger.info(f"[SPLASH] fallback path={path}")
    else:
        st = _load_splash_state()
        idx = st.get("index", 0) % len(files)
        path = os.path.join(SPLASH_DIR, files[idx])
        logger.info(f"[SPLASH] choose idx={idx} file={files[idx]}")

    # guardo la selección de este run
    try:
        with open(CURRENT_SPLASH_FILE, "w", encoding="utf-8") as f:
            json.dump({"path": path}, f)
    except Exception as e:
        logger.warning(f"[SPLASH] no pude escribir CURRENT_SPLASH_FILE: {e}")

    return path

try:
    with open(INTRO_FLAG, "w") as f:
        f.write("1")
except Exception:
    pass
    
try:
    _maybe = get_next_splash_path()
    if _maybe and os.path.isfile(_maybe):
        INTRO_PATH = _maybe
except Exception:
    pass

os.makedirs(os.path.dirname(PLAYS_FILE), exist_ok=True)

# Tags y grupos por defecto
DEFAULT_TAGS = {
    "Personajes": {
        "color": "#facc15",
        "tags": ["Mirtha", "Franchella", "Menem", "Cristina", "Milei"]
    },
    "Temas": {
        "color": "#3b82f6",
        "tags": ["politica", "humor", "clasicos", "virales", "efemerides", "publicidad"]
    },
    "Otros": {
        "color": "#ec4899",
        "tags": ["Simuladores", "Simpsons", "familia", "personal", "milagros", "menemismo", "test"]
    }
}

# Canales predefinidos
DEFAULT_CANALES = {

        "Canal de Prueba": {
        "nombre": "Test",
        "descripcion": "Canal de prueba",
        "tags_prioridad": ["test"],
        "tags_excluidos": [],
        "icono": "mate.png",
        "intro_video_id": ""
    }
}

shown_videos_por_canal = {}

# --- Anti-bounce / cooldown ---
last_next_call = {}   # canal_id -> timestamp del último /api/next_video servido
NEXT_COOLDOWN = 3.0   # segundos de ventana anti-encadenados
STICKY_WINDOW = 3.0   # segundos
last_choice_per_canal = {}  # canal_id -> {"video_id": str, "ts": float}

# --- De-dupe primer NEXT por canal ---
pending_pick = {}  # canal_id -> {"video_id": str, "ts": float}
PENDING_TTL = 12.0  # segundos; reusar el mismo pick dentro de este tiempo

_last_trigger_mtime_served = 0.0  # para /api/should_reload (one-shot)
_last_menu_mtime_served = 0.0
_last_nav_mtime_served = 0.0
_last_sel_mtime_served = 0.0

# --- Boot / Frontend probes -------------------------------------------------
_last_frontend_ping = 0.0  # epoch de último ping recibido
_last_frontend_stage = "boot"
PING_GRACE = 25.0  # segundos de gracia después de lanzar Chromium
_watchdog_already_retry = False # evita relanzar Chromium más de 1 vez

if os.path.exists(TRIGGER_PATH):
    try:
        _last_trigger_mtime_served = os.path.getmtime(TRIGGER_PATH)
    except Exception:
        _last_trigger_mtime_served = 0.0
        
def _write_json_atomic(path, data):
    path = Path(path)  # acepta str o Path
    path.parent.mkdir(parents=True, exist_ok=True)

    tmp = path.with_suffix(path.suffix + ".tmp")  # p.ej. plays.json.tmp
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)  # atómico en el mismo fs

def _ensure_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        _write_json_atomic(path, data)
        
def _all_tags_from_tagsfile():
    """Devuelve el set de todos los tags definidos en tags.json."""
    try:
        tags_data = load_tags()  # ya la tenés definida más abajo
        return {t for grupo in tags_data.values() for t in grupo.get("tags", [])}
    except Exception:
        return set()
        
def _bootstrap_config_from_tags_if_empty():
    """
    Si configuracion.json no tiene 'tags_incluidos', lo poblamos con TODOS los tags
    de tags.json. Y si 'tags_prioridad' está vacío, lo iniciamos con el mismo orden.
    """
    try:
        cfg = load_config()  # <- esta función ya debe estar definida al momento de llamar
        if not cfg.get("tags_incluidos"):
            todos = sorted(_all_tags_from_tagsfile())
            if todos:
                cfg["tags_incluidos"] = todos
                if not cfg.get("tags_prioridad"):
                    cfg["tags_prioridad"] = todos[:]
                _write_json_atomic(CONFIG_FILE, cfg)  # ATÓMICO
                logger.info(f"[BOOT] Config inicial poblada con {len(todos)} tags desde tags.json")
    except Exception as e:
        logger.warning(f"[BOOT] No pude poblar configuracion desde tags.json: {e}")

# Semillas de JSONs (no pisan si ya existen)
_ensure_json(TAGS_FILE,       DEFAULT_TAGS)         
_ensure_json(CONFIG_FILE,     DEFAULT_CONFIG)       
_ensure_json(CANALES_FILE,    DEFAULT_CANALES)      
_ensure_json(METADATA_FILE,   {})                   
_ensure_json(CANAL_ACTIVO_FILE, DEFAULT_CANAL_ACTIVO)  


 

def restart_kiosk(url="http://localhost:5000/tv"):
    env = os.environ.copy()
    env["DISPLAY"] = ":0"
    env["XAUTHORITY"] = f"/home/{USER}/.Xauthority"

    chromium_log = "/tmp/chromium_kiosk.log"

    try:
        # Cerrar sólo lo visible del browser
        subprocess.run(["pkill", "-f", "chromium"], check=False)

        # Esperar X (:0) hasta ~12s
        for i in range(60):
            if os.path.exists("/tmp/.X11-unix/X0"):
                break
            time.sleep(0.2)
        else:
            logger.error("[KIOSK] DISPLAY :0 no disponible. Aborto lanzamiento.")
            return

        # Esperar que Flask esté sirviendo la URL raíz (o /) antes de lanzar
        import urllib.request
        for _ in range(30):
            try:
                urllib.request.urlopen("http://127.0.0.1:5000/", timeout=1)
                break
            except:
                time.sleep(0.3)

        user_data_dir = str(CHROME_PROFILE)
        cache_dir     = str(CHROME_CACHE)
        for d in (user_data_dir, cache_dir):
            try:
                os.makedirs(d, exist_ok=True)
                os.chmod(d, 0o755)
            except Exception as e:
                logger.warning(f"[KIOSK] No pude preparar {d}: {e}")

        chromium_bin = "/usr/bin/chromium-browser" if os.path.exists("/usr/bin/chromium-browser") else "/usr/bin/chromium"
        
        # Limpieza de locks del perfil (cuando hay apagados bruscos quedan "Singleton*" y bloquea primer boot)
        try:
            for fn in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
                p = os.path.join(user_data_dir, fn)
                if os.path.exists(p):
                    os.remove(p)
        except Exception as e:
            print("[KIOSK] No pude limpiar locks de perfil:", e)

        cmd = [
            chromium_bin,
            "--kiosk", f"--app={url}",
            "--noerrdialogs",
            "--disable-infobars",
            "--disable-translate",
            "--disable-features=Translate",
            "--autoplay-policy=no-user-gesture-required",
            "--ozone-platform=x11",
            "--use-gl=angle", "--use-angle=gl",
            "--disable-features=VaapiVideoDecoder",
            f"--user-data-dir={user_data_dir}",
            f"--disk-cache-dir={cache_dir}",
            # logging de Chromium para primer boot:
            "--enable-logging=stderr", "--v=1",
            "--no-first-run",
            "--no-default-browser-check",
            "--enable-logging=stderr",
            "--v=1",
            
        ]
        logger.info(f"[KIOSK] Lanzando: {' '.join(cmd)} DISPLAY={env.get('DISPLAY')} X0={'ok' if os.path.exists('/tmp/.X11-unix/X0') else 'NO'} bin={chromium_bin}")

        # Redirigimos stdout/stderr a archivo para diagnósticos post-boot
        with open(chromium_log, "ab", buffering=0) as logf:
            subprocess.Popen(cmd, env=env, stdout=logf, stderr=logf)
            logger.info(f"[KIOSK] Chromium log -> {chromium_log}")

    except Exception as e:
        logger.error(f"[KIOSK] Error lanzando Chromium: {e}")

    
def launch_kiosk_once():
    try:
        if not os.path.exists(LAUNCH_FLAG):
            # si existe intro flag, arrancamos mostrando la imagen de espera (pre-loader local)
            if os.path.exists(INTRO_FLAG):
                url = Path(APP_DIR, "templates", "kiosk_boot.html").as_uri()
            else:
                url = "http://localhost:5000/"
            restart_kiosk(url=url)
            with open(LAUNCH_FLAG, "w") as f:
                f.write("1")
    except Exception as e:
        print("[KIOSK] Error lanzando Chromium:", e)


   
# Función para cargar canales
def load_canales():
    if os.path.exists(CANALES_FILE):
        with open(CANALES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

# Función para guardar canales
def save_canales(data):
    with open(CANALES_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"tags_prioridad": [], "tags_incluidos": []}
    
# Ruta para ver y gestionar tags
def load_tags():
    with open(TAGS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_tags(tags_data):
    with open(TAGS_FILE, "w", encoding="utf-8") as f:
        json.dump(tags_data, f, indent=2, ensure_ascii=False)

_bootstrap_config_from_tags_if_empty()

def get_canal_activo():
    if os.path.exists(CANAL_ACTIVO_FILE):
        with open(CANAL_ACTIVO_FILE, "r", encoding="utf-8") as f:
            return json.load(f).get("canal_id", "base")
    return "base"

def set_canal_activo(canal_id):
    with open(CANAL_ACTIVO_FILE, "w", encoding="utf-8") as f:
        json.dump({"canal_id": canal_id}, f, indent=2, ensure_ascii=False)


def sanity_check_thumbnails(video_id=None):
    targets = [video_id] if video_id else metadata.keys()

    for vid in targets:
        video_path = os.path.join(VIDEO_DIR, vid + ".mp4")
        thumbnail_path = os.path.join(CONTENT_DIR, "thumbnails", vid + ".jpg")

        if os.path.exists(video_path) and not os.path.exists(thumbnail_path):
            try:
                print(f"🖼 Generando thumbnail para: {vid}")
                subprocess.run([
                    "ffmpeg",
                    "-ss", "00:00:02",
                    "-i", video_path,
                    "-frames:v", "1",
                    "-q:v", "4",
                    thumbnail_path
                ], check=True)
                print(f"✅ Thumbnail generado: {thumbnail_path}")
            except Exception as e:
                print(f"⚠️ No se pudo generar thumbnail para {vid}. Se usará el por defecto. Error: {e}")

def get_video_resolution(filepath):
    try:
        result = subprocess.run([
            "ffprobe", "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height",
            "-of", "default=noprint_wrappers=1:nokey=1",
            filepath
        ], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

        width, height = map(int, result.stdout.strip().split("\n"))
        return width, height
    except Exception as e:
        print(f"⚠️ Error al obtener resolución de {filepath}: {e}")
        return None, None

def escribir_estado(status):
    with open(UPLOAD_STATUS, "w", encoding="utf-8") as f:
        f.write(status)

def eliminar_estado():
    if UPLOAD_STATUS.exists(): UPLOAD_STATUS.unlink()

def sincronizar_videos():
    archivos_video = {
        os.path.splitext(f)[0] for f in os.listdir(VIDEO_DIR)
        if f.lower().endswith(('.mp4', '.webm', '.mov'))
    }
    entradas_metadata = set(metadata.keys())

    videos_validos = {k: v for k, v in metadata.items() if k in archivos_video}
    videos_fantasmas = {k: v for k, v in metadata.items() if k not in archivos_video}
    videos_nuevos = sorted(archivos_video - entradas_metadata)

    return videos_validos, videos_fantasmas, videos_nuevos


def backup_tags():
    if os.path.exists(TAGS_FILE):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_file = os.path.join(CONTENT_DIR, f"tags_backup_{timestamp}.json")
        shutil.copy(TAGS_FILE, backup_file)
        print(f"🧾 Backup creado: {backup_file}")


def clean_config_tags(tags_data, config_data):
    # Lista completa de tags válidos (los que existen actualmente)
    valid_tags = {tag for info in tags_data.values() for tag in info["tags"]}

    # Filtrar configuración y eliminar fantasmas
    config_data["tags_prioridad"] = [t for t in config_data.get("tags_prioridad", []) if t in valid_tags]
    config_data["tags_incluidos"] = [t for t in config_data.get("tags_incluidos", []) if t in valid_tags]

    return config_data

def get_video_duration(filepath):
    try:
        result = subprocess.run([
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            filepath
        ], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        return float(result.stdout.strip())
    except Exception as e:
        print(f"⚠️ No se pudo obtener duración de {filepath}: {e}")
        return 0


def ensure_durations():
    updated = False
    for video_id, info in metadata.items():
        if "duracion" not in info:
            filepath = os.path.join(VIDEO_DIR, f"{video_id}.mp4")
            if os.path.exists(filepath):
                dur = get_video_duration(filepath)
                metadata[video_id]["duracion"] = dur
                updated = True
    if updated:
        with open(METADATA_FILE, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)
        print("🕒 Duraciones actualizadas en metadata")

def get_total_recuerdos():
    total_sec = sum(v.get("duracion", 0) for v in metadata.values())
    horas = int(total_sec // 3600)
    minutos = int((total_sec % 3600) // 60)

    if horas:
        return f"{horas}h {minutos}m"
    else:
        return f"{minutos}m"
        
# --- Preferencias UI ---
def load_ui_prefs():
    cfg = load_config()
    # default: mostrar el nombre del canal
    return {"show_channel_name": bool(cfg.get("show_channel_name", True))}

def save_ui_prefs(prefs):
    cfg = load_config()
    cfg["show_channel_name"] = bool(prefs.get("show_channel_name", True))
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
        


def _read_json(path, default):
    path = Path(path)  # acepta str o Path
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default
    except Exception:
        # si está corrupto, devolvé default
        return default



def load_plays():
    return _read_json(PLAYS_FILE, {})

def save_plays(d):
    _write_json_atomic(PLAYS_FILE, d)

def bump_play(video_id):
    d = load_plays()
    item = d.get(video_id, {"plays": 0, "last_played": None})
    item["plays"] = int(item.get("plays", 0)) + 1
    item["last_played"] = datetime.now(UTC).isoformat()
    d[video_id] = item
    save_plays(d)
    return item

def load_metadata():
    return _read_json(METADATA_FILE, {})

def _iso_to_ts(iso_str):
    try:
        return datetime.fromisoformat(iso_str.replace("Z","")).timestamp()
    except Exception:
        return 0.0

def score_for_video(video_id, metadata, plays_map):
    md = metadata.get(video_id, {})
    dur = float(md.get("duracion", 0.0))  # segundos
    minutes = max(1, math.ceil(dur / 60.0))

    pinfo = plays_map.get(video_id, {"plays": 0, "last_played": None})
    plays = int(pinfo.get("plays", 0))
    last_ts = _iso_to_ts(pinfo.get("last_played")) if pinfo.get("last_played") else 0.0

    plays_norm = plays / minutes
    # jitter muy pequeño para no ser determinista total
    jitter = random.random() * 0.01

    # Orden principal: menor plays_norm primero (más justo),
    # luego menos reciente (last_ts chico), luego jitter
    return (plays_norm, last_ts, jitter)

def _load_splash_state():
    """Lee /srv/tvargenta/Splash/splash_state.json -> {"index": int}"""
    try:
        if os.path.exists(SPLASH_STATE_FILE):
            with open(SPLASH_STATE_FILE, "r", encoding="utf-8") as f:
                d = json.load(f)
                idx = int(d.get("index", 0))
                logger.info(f"[SPLASH] state load idx={idx}")
                return {"index": idx}
    except Exception as e:
        logger.warning(f"[SPLASH] state load error: {e}")
    return {"index": 0}


def _save_splash_state(state: dict):
    """Escribe de forma atómica el estado de rotación."""
    try:
        path = Path(SPLASH_STATE_FILE)
        tmp = path.with_suffix(path.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
        logger.info(f"[SPLASH] state save -> {state}")
    except Exception as e:
        logger.error(f"[SPLASH] state save error: {e}")
   
def _advance_splash_rotation():
    try:
        files = sorted(
            f for f in os.listdir(SPLASH_DIR)
            if f.lower().endswith(".mp4") and f.startswith("splash_")
        )
    except Exception as e:
        logger.error(f"[SPLASH] listar p/advance falló: {e}")
        files = []

    if not files:
        logger.info("[SPLASH] sin archivos, no avanzo")
        return

    st = _load_splash_state()
    idx = (st.get("index", 0) + 1) % len(files)
    _save_splash_state({"index": idx})
    logger.info(f"[SPLASH] advanced -> idx={idx}")

def _touch_frontend_ping(stage: str = None):
    """Marca último ping del frontend y, opcionalmente, la etapa."""
    global _last_frontend_ping, _last_frontend_stage
    _last_frontend_ping = time.monotonic()
    if stage:
        _last_frontend_stage = stage


# --- Gestión: /gestion -------------------------------------------------

def _ctx_gestion():
    # Carga y saneos mínimos para que el dashboard esté al día
    global metadata
    metadata = load_metadata()
    ensure_durations()
    sanity_check_thumbnails()
    vids_ok, vids_fantasmas, vids_nuevos = sincronizar_videos()
    return dict(
        videos=vids_ok,
        fantasmas=vids_fantasmas,
        nuevos=vids_nuevos,
        tags=load_tags(),
        config=load_config(),
        recuerdos=get_total_recuerdos()
    )


@app.route("/")
def root():
    logger.info(_hdr("HIT /"))
    if os.path.exists(INTRO_FLAG):
        # Elegí una sola vez el splash y dejá registro para este run
        path = get_next_splash_path()
        if path and os.path.isfile(path):
            logger.info("Intro flag presente -> /splash")
            return redirect(url_for("splash"))
        else:
            logger.info("Intro flag presente, pero sin splash válido -> /tv")
            return redirect(url_for("tv"))
    logger.info("Sin intro -> /tv")
    return redirect(url_for("tv"))


@app.route("/video/<video_id>")
def video_detail(video_id):
    video = metadata.get(video_id)
    if not video:
        return "Video no encontrado", 404
    return render_template("video.html", video_id=video_id, video=video)

@app.route("/edit/<video_id>", methods=["GET", "POST"])
def edit_video(video_id):
    if request.method == "POST":
        form = request.form
        tags = form.get("tags", "")
        metadata[video_id] = {
            "title": form.get("title"),
            "tags": [tag.strip() for tag in tags.split(",") if tag.strip()],
            "personaje": form.get("personaje"),
            "fecha": form.get("fecha"),
            "modo": form.getlist("modo")
        }
        with open(METADATA_FILE, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)
        return redirect(url_for("index"))

    # Cargar video y tags
    if video_id in metadata:
        video = metadata[video_id]
    else:
        video = {
            "title": video_id.replace("_", " "),
            "tags": [],
            "personaje": "",
            "fecha": "",
            "modo": []
        }

    selected_tags = video.get("tags", [])
    tags_data = load_tags()
    tag_categoria = {tag: grupo for grupo, info in tags_data.items() for tag in info["tags"]}

    return render_template("edit.html",
                       video_id=video_id,
                       video=video,
                       selected_tags=selected_tags,
                       tag_categoria=tag_categoria,
                       tags=tags_data)

@app.route("/api/videos")
def api_videos():
    return jsonify(metadata)

@app.route("/thumbnails/<filename>")
def serve_thumbnail(filename):
    return send_from_directory(os.path.join(CONTENT_DIR, "thumbnails"), filename)

@app.route("/videos/<filename>")
def serve_video(filename):
    return send_from_directory(os.path.join(CONTENT_DIR, "videos"), filename)

@app.route("/delete_full/<video_id>")
def delete_full_video(video_id):
    video_path = os.path.join(VIDEO_DIR, video_id + ".mp4")
    if os.path.exists(video_path):
        os.remove(video_path)
        print(f"🧨 Video eliminado: {video_path}")
    else:
        print(f"⚠️ Video no encontrado para: {video_id}")

    thumbnail_path = os.path.join(CONTENT_DIR, "thumbnails", video_id + ".jpg")
    if os.path.exists(thumbnail_path):
        os.remove(thumbnail_path)
        print(f"🧹 Thumbnail eliminado: {thumbnail_path}")

    if video_id in metadata:
        del metadata[video_id]
        with open(METADATA_FILE, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)
        print(f"✅ Metadata eliminada: {video_id}")

    return redirect(url_for("index"))

@app.route("/delete/<video_id>")
def delete_video_metadata(video_id):
    removed_any = False
    if video_id in metadata:
        del metadata[video_id]
        with open(METADATA_FILE, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)
        print(f"✅ Metadata eliminada para: {video_id}")
        removed_any = True
    else:
        print(f"ℹ️ No hay metadata para: {video_id}")

    thumbnail_path = os.path.join(CONTENT_DIR, "thumbnails", video_id + ".jpg")
    if os.path.exists(thumbnail_path):
        os.remove(thumbnail_path)
        print(f"🧹 Thumbnail eliminado: {thumbnail_path}")
        removed_any = True
    else:
        print(f"ℹ️ No se encontró thumbnail para: {video_id}")

    if not removed_any:
        print(f"⚠️ Nada que borrar para: {video_id}")

    return redirect(url_for("index"))

@app.route("/upload", methods=["GET", "POST"])
def upload():
    if request.method == "GET":
        return render_template("upload.html")

    files = request.files.getlist("videos[]")
    os.makedirs(VIDEO_DIR, exist_ok=True)

    print(f"📥 Archivos recibidos: {[f.filename for f in files]}")

    for file in files:
        if not file.filename.lower().endswith(".mp4"):
            escribir_estado(f"❌ Archivo no permitido: {file.filename}")
            continue

        escribir_estado("📥 Recibiendo archivo...")

        filename = secure_filename(file.filename)
        video_id = os.path.splitext(filename)[0]
        final_path = os.path.join(VIDEO_DIR, video_id + ".mp4")

        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as tmp:
            temp_path = tmp.name
            file.save(temp_path)

        print(f"🔄 Procesando: {filename}")
        try:
            escribir_estado("📐 Comprobando resolución...")
            width, height = get_video_resolution(temp_path)
            duracion = get_video_duration(temp_path)
            metadata[video_id] = metadata.get(video_id, {})
            metadata[video_id]["duracion"] = duracion
            if width == 800 and height == 480:
                shutil.copy(temp_path, final_path)
                escribir_estado("✅ Video ya estaba en 800x480. Copiado directo")
                print(f"✅ Video ya estaba en 800x480. Copiado directo: {final_path}")
            else:
                escribir_estado("✂️ Redimensionando video...")
                subprocess.run([
                    "ffmpeg", "-i", temp_path,
                    "-vf", "scale=800:480:force_original_aspect_ratio=decrease,pad=800:480:(ow-iw)/2:(oh-ih)/2",
                    "-c:a", "copy",
                    "-y", final_path
                ], check=True)
                print(f"🎛 Video procesado con resize y crop: {final_path}")
        except Exception as e:
            escribir_estado(f"⚠️ Error al procesar {filename}")
            print(f"⚠️ Error al procesar {filename}: {e}")
        finally:
            os.remove(temp_path)

        escribir_estado("🖼 Generando thumbnail...")
        sanity_check_thumbnails(video_id)
        escribir_estado("✅ ¡Listo che! 🧉")

    eliminar_estado()
    return redirect(url_for("index"))

@app.route("/upload_status")
def upload_status():
    try:
        with open(UPLOAD_STATUS, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return "Sin actividad"
        
@app.route("/tags")
def tags():
    tags_data = load_tags()
    return_to = request.args.get("return_to")
    return render_template("tags.html", tags=tags_data, return_to=return_to)

@app.route("/add_tag", methods=["POST"])
def add_tag():
    tag = request.form.get("tag", "").strip()
    group = request.form.get("group")
    return_to = request.form.get("from_edit")

    tags_data = load_tags()

    if not tag or not group:
        return redirect(url_for("tags", from_edit=return_to))

    if group in tags_data:
        if tag not in tags_data[group]["tags"]:
            tags_data[group]["tags"].append(tag)
    else:
        tags_data[group] = {"color": "#cccccc", "tags": [tag]}

    save_tags(tags_data)

    # Agregar a configuracion.json si no existe
    config_path = os.path.join(CONTENT_DIR, "configuracion.json")
    if os.path.exists(config_path):
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
    else:
        config = {"tags_prioridad": [], "tags_incluidos": []}

    if tag not in config["tags_prioridad"]:
        config["tags_prioridad"].append(tag)
    if tag not in config["tags_incluidos"]:
        config["tags_incluidos"].append(tag)

    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)

    return redirect(url_for("tags", from_edit=return_to))


@app.route("/add_group", methods=["POST"])
def add_group():
    group = request.form.get("group").strip()
    color = request.form.get("color") or "#cccccc"
    tags_data = load_tags()

    if group and group not in tags_data:
        tags_data[group] = {"color": color, "tags": []}
        save_tags(tags_data)

    return redirect(url_for("tags"))

@app.route("/delete_tag", methods=["POST"])
def delete_tag():
    tag = request.form.get("tag")
    group = request.form.get("group")
    return_to = request.form.get("from_edit")  # Para redirigir correctamente

    if not tag or not group:
        return redirect(url_for("tags", from_edit=return_to))

    tags_data = load_tags()

    if group in tags_data and tag in tags_data[group]["tags"]:
        tags_data[group]["tags"].remove(tag)

        # También eliminarlo de todos los metadata
        for video in metadata.values():
            if tag in video.get("tags", []):
                video["tags"].remove(tag)

        # Guardar ambos archivos
        save_tags(tags_data)
        with open(METADATA_FILE, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)

        # Eliminar de configuracion.json también
        config_path = os.path.join(CONTENT_DIR, "configuracion.json")
        if os.path.exists(config_path):
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)

            config["tags_prioridad"] = [t for t in config.get("tags_prioridad", []) if t != tag]
            config["tags_incluidos"] = [t for t in config.get("tags_incluidos", []) if t != tag]

            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2, ensure_ascii=False)

    return redirect(url_for("tags", from_edit=return_to))


@app.route("/delete_group", methods=["POST"])
def delete_group():
    group = request.form.get("group")
    return_to = request.form.get("from_edit")

    if not group:
        return redirect(url_for("tags", from_edit=return_to))

    tags_data = load_tags()

    if group in tags_data:
        backup_tags()  # antes de modificar nada

        # Tags del grupo a eliminar
        tags_to_remove = tags_data[group]["tags"]

        # Eliminar del metadata
        for video in metadata.values():
            video["tags"] = [t for t in video.get("tags", []) if t not in tags_to_remove]

        # Eliminar del tags.json
        del tags_data[group]
        save_tags(tags_data)

        # Eliminar del configuracion.json
        config = load_config()
        config["tags_prioridad"] = [t for t in config.get("tags_prioridad", []) if t not in tags_to_remove]
        config["tags_incluidos"] = [t for t in config.get("tags_incluidos", []) if t not in tags_to_remove]
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)

        # Guardar metadata
        with open(METADATA_FILE, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)

        print(f"🗑 Grupo eliminado: {group} (y sus tags)")

    return redirect(url_for("tags", from_edit=return_to))


@app.route("/configuracion", methods=["GET", "POST"])
def configuracion():
    tags_data = load_tags()
    config_data = load_config()

    # 💡 Sanity check: remover tags que ya no existen
    config_data = clean_config_tags(tags_data, config_data)

    # Guardar si hubo algún cambio
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config_data, f, indent=2, ensure_ascii=False)

    return render_template("configuracion.html", tags=tags_data, config=config_data)



@app.route("/guardar_configuracion", methods=["POST"])
def guardar_configuracion():
    prioridad = request.form.get("tags_prioridad", "")
    incluidos = request.form.getlist("tags_incluidos")

    # Solo mantener en prioridad los tags incluidos
    orden_final = [tag.strip() for tag in prioridad.split(",") if tag.strip() and tag.strip() in incluidos]

    config = {
        "tags_prioridad": orden_final,
        "tags_incluidos": incluidos
    }

    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        print("✅ Configuración guardada")
    except Exception as e:
        print(f"❌ Error al guardar configuración: {e}")

    return redirect(url_for("configuracion"))

@app.route("/vertele")
def vertele():
    canales = load_canales()

    canal_activo_path = str(CANAL_ACTIVO_FILE)
    canal_activo = None

    if not os.path.exists(canal_activo_path):
        # Elegí un id real: primero el de DEFAULT_CANAL_ACTIVO si existe, si no, el primer canal disponible
        preferido = DEFAULT_CANAL_ACTIVO.get("canal_id", "1")
        if preferido not in canales:
            preferido = next(iter(canales.keys()), "1")
        with open(canal_activo_path, "w", encoding="utf-8") as f:
            json.dump({"canal_id": preferido}, f, ensure_ascii=False, indent=2)
        canal_activo = preferido
    else:
        with open(canal_activo_path, "r", encoding="utf-8") as f:
            activo_data = json.load(f)
            canal_activo = activo_data.get("canal_id") or DEFAULT_CANAL_ACTIVO.get("canal_id", "1")
            if canal_activo not in canales and canales:
                canal_activo = next(iter(canales.keys()))
                set_canal_activo(canal_activo)  # persistí la migración

    return render_template("vertele.html",
                           canales=canales,
                           canal_activo=canal_activo)



@app.route("/api/next_video")
def api_next_video():
    metadata = load_metadata()
    canales = load_canales()

    # 🧠 Canal activo + config
    canal_id = "canal_base"
    config = load_config()

    canal_activo_path = str(CANAL_ACTIVO_FILE)
    if os.path.exists(canal_activo_path):
        with open(canal_activo_path, "r", encoding="utf-8") as f:
            activo = json.load(f)
            if activo.get("canal_id") in canales:
                canal_id = activo["canal_id"]
                config = canales[canal_id]
    
    # --- De-dupe: si hay pick pendiente “fresco”, reusalo ---
    now = time.time()
    pp = pending_pick.get(canal_id)
    if pp and (now - pp.get("ts", 0.0)) < PENDING_TTL:
        vid = pp["video_id"]
        info = metadata.get(vid, {})
        logger.info(f"[NEXT-DUPE] Reuso pick pendiente canal={canal_id} video={vid}")
        return jsonify({
            "video_id": vid,
            "title": info.get("title", vid.replace("_", " ")),
            "tags": info.get("tags", []),
            "modo": canal_id,
            "canal_nombre": canales[canal_id].get("nombre", canal_id),
            "reused": True,
            "do_not_restart": True   # <--- NUEVO: indicá al player que NO reinicie si ya es el actual
        })

    
    # --- Sticky window: si otra llamada llega enseguida, devolvemos el mismo video ---
    now = time.time()
    sticky = last_choice_per_canal.get(canal_id)
    if sticky and (now - sticky["ts"]) < STICKY_WINDOW:
        elegido_id = sticky["video_id"]
        elegido_data = metadata.get(elegido_id, {})
        if elegido_data:
            return jsonify({
                "video_id": elegido_id,
                "title": elegido_data.get("title", elegido_id.replace("_", " ")),
                "tags": elegido_data.get("tags", []),
                "score_tags": 0,             # no recalculamos, es pegajoso
                "fair_plays_norm": 0.0,
                "fair_last_ts": 0.0,
                "modo": canal_id,
                "canal_nombre": canales[canal_id].get("nombre", canal_id),
                "sticky": True
            })

    # --- Cooldown por canal ---
    now = time.time()
    ultimo = last_next_call.get(canal_id, 0.0)
    sticky = last_choice_per_canal.get(canal_id)
    if (now - ultimo) < NEXT_COOLDOWN and sticky and (now - sticky["ts"]) >= STICKY_WINDOW:
        logger.info(f"[NEXT] cooldown canal={canal_id} dt={now-ultimo:.2f}s -> bloqueo")
        # Solo aplicamos cooldown si no estamos dentro de la ventana “pegajosa”
        return jsonify({"cooldown": True, "canal_id": canal_id}), 200

    prioridad = config.get("tags_prioridad", [])
    incluidos = set(config.get("tags_incluidos", prioridad))  # fallback
    if not incluidos:
        return jsonify({"error": "No hay tags incluidos definidos en la configuración."}), 400

    # <<< FIX: tomar los ya mostrados una sola vez, afuera del loop >>>
    canal_shown = shown_videos_por_canal.get(canal_id, [])

    # --- Candidatos por tags e inéditos en el canal ---
    candidatos = []
    for video_id, data in metadata.items():
        if video_id in canal_shown:
            continue
        video_tags = set(data.get("tags", []))
        if not (video_tags & incluidos):
            continue
        tag_score = sum((len(prioridad) - prioridad.index(tag)) for tag in video_tags if tag in prioridad)
        candidatos.append((video_id, data, tag_score))

    # 🔁 Si no quedan, limpiá “ya vistos” y reintentá
    if not candidatos:
        if canal_shown:
            shown_videos_por_canal[canal_id] = []
            return api_next_video()
        else:
            return jsonify({"no_videos": True, "canal_id": canal_id})

    # --- Fairness: plays normalizados + LRU + prioridad de tags + jitter ---
    plays_map = load_plays()

    def sort_key(t):
        video_id, data, tag_score = t
        plays_norm, last_ts, jitter = score_for_video(video_id, metadata, plays_map)
        # asc: menos plays_norm, menos reciente, mayor prioridad de tags, jitter
        return (plays_norm, last_ts, -tag_score, jitter)

    candidatos.sort(key=sort_key)

    elegido_id, elegido_data, tag_score = candidatos[0]
    
    pending_pick[canal_id] = {"video_id": elegido_id, "ts": time.time()}
    
    canal_shown.append(elegido_id)
    shown_videos_por_canal[canal_id] = canal_shown

    last_next_call[canal_id] = time.time()

    fair_plays_norm, fair_last_ts, _ = score_for_video(elegido_id, metadata, plays_map)
    logger.info(f"[NEXT] canal={canal_id} elegido={elegido_id} tagscore={tag_score} plays_norm={fair_plays_norm:.3f}")
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]}] [API] Reproduciendo video: {elegido_id} del canal {canal_id}")
    
    last_choice_per_canal[canal_id] = {"video_id": elegido_id, "ts": time.time()}
    
    return jsonify({
        "video_id": elegido_id,
        "title": elegido_data.get("title", elegido_id.replace("_", " ")),
        "tags": elegido_data.get("tags", []),
        "score_tags": tag_score,
        "fair_plays_norm": fair_plays_norm,
        "fair_last_ts": fair_last_ts,
        "modo": canal_id,
        "canal_nombre": canales[canal_id].get("nombre", canal_id)
    })


@app.route("/canales")
def canales():
    canales_data = load_canales()  # ya lo tenés definido
    tags_data = load_tags()
    config_data = load_config()

    return render_template("canales.html", canales=canales_data, tags=tags_data, config=config_data)

@app.route("/guardar_canal", methods=["POST"])
def guardar_canal():
    canal_id = request.form.get("canal_id")
    nombre = request.form.get("nombre", "").strip()
    descripcion = request.form.get("descripcion", "").strip()
    icono = request.form.get("icono", "").strip()
    tags_prioridad = request.form.getlist("tags_prioridad")
    intro = request.form.get("intro_video_id", "").strip()

    if not nombre:
        return redirect(url_for("canales"))

    canales = load_canales()

    # Si es nuevo, generar ID automáticamente
    if not canal_id:
        existing_ids = [int(k) for k in canales.keys() if k.isdigit()]
        canal_id = str(max(existing_ids, default=0) + 1)

    nuevo_canal = {
        "nombre": nombre,
        "descripcion": descripcion,
        "icono": icono,
        "tags_prioridad": tags_prioridad
    }

    if intro:
        nuevo_canal["intro_video_id"] = intro

    canales[canal_id] = nuevo_canal
    save_canales(canales)
    return redirect(url_for("canales"))


@app.route("/eliminar_canal/<canal_id>", methods=["POST"])
def eliminar_canal(canal_id):
    canales = load_canales()
    if canal_id in canales:
        del canales[canal_id]
        save_canales(canales)
    return redirect(url_for("canales"))

@app.route("/editar_canal/<canal_id>")
def editar_canal(canal_id):
    canales = load_canales()
    canal = canales.get(canal_id)
    if not canal:
        return redirect(url_for("canales"))

    tags_data = load_tags()
    config = load_config()

    # lista plana de todos los tags del tags.json
    todos_los_tags = [t for grupo in tags_data.values() for t in grupo.get("tags", [])]

    incluidos = set(config.get("tags_incluidos") or [])
    if incluidos:
        tags_disponibles = [t for t in todos_los_tags if t in incluidos]
    else:
        # Fallback: si no hay incluidos en config, mostrar TODOS
        tags_disponibles = todos_los_tags

    return render_template("canales.html",
                           canal_actual=canal,
                           canal_id=canal_id,
                           canales=canales,
                           tags=tags_data,
                           tags_disponibles=tags_disponibles,
                           config=config)

@app.route("/api/set_canal_activo", methods=["POST"])
def api_set_canal_activo():
    data = request.get_json()
    canal_id = data.get("canal_id")
    if not canal_id:
        return jsonify({"error": "Canal no especificado"}), 400

    canales = load_canales()
    if canal_id != "base" and canal_id not in canales:
        return jsonify({"error": "Canal no válido"}), 404

    set_canal_activo(canal_id)
    return jsonify({"ok": True, "canal_id": canal_id})

@app.route("/api/canales")
def api_canales():
    canales_data = load_canales()
    canal_activo = get_canal_activo()

    canales_list = []
    for canal_id, canal_info in canales_data.items():
        canales_list.append({
            "id": canal_id,
            "nombre": canal_info.get("nombre", canal_id),
            "icono": canal_info.get("icono", "📺")
        })

    nombre_activo = canales_data.get(canal_activo, {}).get("nombre", "Canal Base")

    return jsonify({
        "canales": canales_list,
        "canal_activo_nombre": nombre_activo
    })
    
@app.route("/tv")
def tv():
    logger.info(_hdr("HIT /tv (render player)"))
    global metadata

    if os.path.exists(METADATA_FILE):
        with open(METADATA_FILE, "r", encoding="utf-8") as f:
            metadata = json.load(f)
    else:
        metadata = {}

    # Tus funciones existentes
    ensure_durations()
    sanity_check_thumbnails()
    videos_validos, videos_fantasmas, videos_nuevos = sincronizar_videos()

    return render_template(
        "player.html",   
        videos=videos_validos,
        fantasmas=videos_fantasmas,
        nuevos=videos_nuevos,
        recuerdos=get_total_recuerdos()
    )

    
@app.route("/api/should_reload")
def api_should_reload():
    global _last_trigger_mtime_served
    if not os.path.exists(TRIGGER_PATH):
        return jsonify({"should_reload": False})

    mtime = os.path.getmtime(TRIGGER_PATH)

    # Disparar SOLO si hay un mtime nuevo que no se sirvió aún
    if mtime > _last_trigger_mtime_served:
        _last_trigger_mtime_served = mtime
        return jsonify({"should_reload": True})

    return jsonify({"should_reload": False})


@app.route("/api/volumen", methods=["GET", "POST"])
def api_volumen():
    if request.method == "POST":
        data = request.get_json()
        nuevo_valor = max(0, min(100, data.get("valor", 50)))  # rango 0–100
        with open(VOLUMEN_PATH, "w") as f:
            json.dump({"valor": nuevo_valor}, f)
        return jsonify({"ok": True, "valor": nuevo_valor})

    # método GET
    if os.path.exists(VOLUMEN_PATH):
        with open(VOLUMEN_PATH, "r") as f:
            return jsonify(json.load(f))
    else:
        return jsonify({"valor": 50})

@app.route("/api/volumen_ping")
def api_volumen_ping():
    path = "/tmp/trigger_volumen.json"
    if not os.path.exists(path):
        return jsonify({"ping": False})
    mtime = os.path.getmtime(path)
    if time.time() - mtime < 1.0:
        return jsonify({"ping": True})
    return jsonify({"ping": False})
    
    
@app.route("/api/menu_ping")
def api_menu_ping():
    """
    Devuelve True si hubo un 'touch' reciente del encoder para abrir/confirmar menú.
    Recomendado: el proceso del encoder escribe/actualiza MENU_TRIGGER_PATH
    al detectar flanco de bajada SIN giro previo.
    """
    global _last_menu_mtime_served
    path = "/tmp/trigger_menu.json"
    if not os.path.exists(path):
        return jsonify({"ping": False})

    mtime = os.path.getmtime(path)

    # Sirve una sola vez por cada nuevo mtime (borde ascendente)
    if mtime > _last_menu_mtime_served:
        _last_menu_mtime_served = mtime
        return jsonify({"ping": True, "ts": mtime})

    return jsonify({"ping": False})
    
@app.route("/api/menu_state", methods=["GET", "POST"])
def api_menu_state():
    if request.method == "POST":
        data = request.get_json(force=True)
        open_flag = bool(data.get("open", False))
        with open(MENU_STATE_PATH, "w") as f:
            json.dump({"open": open_flag, "ts": time.time()}, f)
        return jsonify({"ok": True})
    # GET
    if os.path.exists(MENU_STATE_PATH):
        with open(MENU_STATE_PATH, "r") as f:
            return jsonify(json.load(f))
    return jsonify({"open": False})
    
@app.route("/api/menu_nav")
def api_menu_nav():
    """One-shot: devuelve delta (+1/-1) una sola vez por trigger"""
    global _last_nav_mtime_served
    if not os.path.exists(MENU_NAV_PATH):
        return jsonify({"ping": False})
    mtime = os.path.getmtime(MENU_NAV_PATH)
    if mtime > _last_nav_mtime_served:
        _last_nav_mtime_served = mtime
        with open(MENU_NAV_PATH, "r") as f:
            data = json.load(f)
        return jsonify({"ping": True, "delta": data.get("delta", 0), "ts": mtime})
    return jsonify({"ping": False})
    
@app.route("/api/menu_select")
def api_menu_select():
    """One-shot: confirma selección actual"""
    global _last_sel_mtime_served
    if not os.path.exists(MENU_SELECT_PATH):
        return jsonify({"ping": False})
    mtime = os.path.getmtime(MENU_SELECT_PATH)
    if mtime > _last_sel_mtime_served:
        _last_sel_mtime_served = mtime
        return jsonify({"ping": True, "ts": mtime})
    return jsonify({"ping": False})
    
@app.route("/api/ui_prefs", methods=["GET", "POST"])
def api_ui_prefs():
    if request.method == "POST":
        data = request.get_json(force=True) or {}
        save_ui_prefs(data)
        return jsonify({"ok": True, **load_ui_prefs()})
    return jsonify(load_ui_prefs())


@app.route("/api/played", methods=["POST"])
def api_played():
    data = request.get_json(force=True) or {}
    video_id = data.get("video_id")

    try:
        for cid, pp in list(pending_pick.items()):
            if pp.get("video_id") == video_id:
                pending_pick.pop(cid, None)
                logger.info(f"[PLAYED] confirm canal={cid} video={video_id} -> limpio pending_pick")
    except Exception as e:
        logger.warning(f"[PLAYED] limpiar pending_pick: {e}")

    if not video_id:
        return jsonify({"ok": False, "error": "missing video_id"}), 400

    d = load_plays()
    item = d.get(video_id, {"plays": 0, "last_played": None})
    item["plays"] = int(item.get("plays", 0)) + 1
    item["last_played"] = datetime.now(UTC).isoformat()
    d[video_id] = item
    save_plays(d)

    return jsonify({"ok": True, "video_id": video_id, **item})

@app.route("/splash_video/<path:filename>")
def serve_splash_video(filename):
    return send_from_directory(SPLASH_DIR, filename)

from pathlib import Path

@app.route("/splash")
def splash():
    logger.info(_hdr("HIT /splash"))

    # 1) Intentar usar la elección guardada (si existe)
    splash_path = None
    try:
        cur = Path(CURRENT_SPLASH_FILE)  # CURRENT_SPLASH_FILE viene de settings (str o Path)
        if cur.exists():
            d = json.loads(cur.read_text(encoding="utf-8"))
            # Puede venir como str; normalizamos a Path
            p = d.get("path")
            if p:
                candidate = Path(p)
                if candidate.is_file():
                    splash_path = candidate
    except Exception as e:
        logger.warning(f"[SPLASH] no pude leer CURRENT_SPLASH_FILE: {e}")

    # 2) Fallback: pedir el siguiente splash
    if splash_path is None or not splash_path.is_file():
        nxt = get_next_splash_path()
        # get_next_splash_path puede devolver str o None
        if nxt:
            nxtp = Path(nxt)
            splash_path = nxtp if nxtp.is_file() else None

    # 3) Si seguimos sin splash válido, no romper la vista
    if splash_path is None:
        logger.info("[SPLASH] No hay splash disponible; omitiendo pantalla de splash.")
        # Opción A: devolver 204 (sin contenido) y que el front avance
        return "", 204
        # Opción B (alternativa): redirigir directo a la TV
        # return redirect(url_for("tv"))

    logger.info(f"[SPLASH] Usando video: {splash_path}")

    # 4) Construir URL del archivo asegurando que tenemos un nombre válido
    filename = splash_path.name  # equivalente a os.path.basename(...)
    return render_template(
        "splash.html",
        video_url=url_for("serve_splash_video", filename=filename),
        tv_url=url_for("tv")
    )



@app.route("/api/clear_intro", methods=["POST"])
def api_clear_intro():
    logger.info(_hdr("POST /api/clear_intro -> borro INTRO_FLAG y avanzo rotación"))
    try:
        _advance_splash_rotation()
    except Exception as e:
        logger.warning(f"[SPLASH] advance error: {e}")

    try:
        if os.path.exists(INTRO_FLAG):
            os.remove(INTRO_FLAG)
    except Exception:
        pass

    try:
        if os.path.exists(CURRENT_SPLASH_FILE):
            os.remove(CURRENT_SPLASH_FILE)
    except Exception:
        pass

    return jsonify({"ok": True})


@app.route("/static-intro.mp4")
def intro_video():
    return send_file(INTRO_PATH, mimetype="video/mp4")


@app.route("/api/boot_probe", methods=["POST", "GET"])
def api_boot_probe():
    # Primer latido apenas carga splash.html (o player.html)
    stage = request.args.get("stage") or "boot"
    _touch_frontend_ping(stage)
    logger.info(f"[PING] boot_probe stage={stage}")
    return ("ok", 200)

@app.route("/api/kiosk_ping", methods=["GET","POST"])
def api_kiosk_ping():
    src = request.args.get("src", "?")
    ts  = time.time()
    try:
        with open(PING_FILE, "w") as f:
            f.write(f"{ts}|{src}")
    except Exception:
        pass
    logger.info(f"[PING] {src}")
    return jsonify({"ok": True, "src": src})
 

@app.route("/api/ping", methods=["POST", "GET"])
def api_ping():
    # Heartbeat periódico desde splash/player
    stage = request.args.get("stage") or "unknown"
    _touch_frontend_ping(stage)
    # Devolvé algo ultra liviano para logs de Chromium si querés
    return jsonify(ok=True, stage=stage)
    

@app.route("/gestion")
def gestion():
    return render_template("index.html", **_ctx_gestion())

# Alias de compatibilidad: si en algún lado quedó url_for("index"), redirige a /gestion
@app.route("/index")
def index():
    return redirect(url_for("gestion"))

# (Opcional) atajo cómodo
@app.route("/admin")
def admin():
    return redirect(url_for("gestion"))
    
    
# --- Power control (halt) ---
@app.route("/api/power", methods=["POST"])
def api_power():
    data = request.get_json(force=True) or {}
    action = (data.get("action") or "").lower()
    if action == "halt":
        try:
            # Opcional: log visible
            print("[API] Halt solicitado desde UI…")
            # Lanza el halt (no bloquea)
            subprocess.Popen(["sudo", "/sbin/shutdown", "-h", "now"])
            return jsonify({"ok": True, "action": "halt"})
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 500
    return jsonify({"ok": False, "error": "unsupported action"}), 400

 
if __name__ == "__main__":
    encoder_path = str(Path(APP_DIR, "modules", "tvargenta_encoder.py"))
    
    # Asegurarse de que no quede flag viejo de kiosk
    try:
        os.remove("/tmp/tvargenta_kiosk_launched")
    except FileNotFoundError:
        pass

    #  Asegurarse de que NO quede ningún encoder viejo corriendo
    try:
        subprocess.run(["pkill", "-f", "encoder_reader"], check=False)
        time.sleep(0.2)
    except Exception as e:
        print(f"[APP] Aviso: no pude matar encoders previos: {e}")

    # Lanzar encoder limpio
    try:
        encoder_proc = subprocess.Popen(["python3", encoder_path], start_new_session=True)
    except Exception as e:
        print(f"[APP] No se pudo lanzar el encoder: {e}")
        encoder_proc = None

    def cleanup():
        if encoder_proc:
            print("[APP] Terminando proceso del encoder...")
            encoder_proc.terminate()

    atexit.register(cleanup)

    os.makedirs(VIDEO_DIR, exist_ok=True)
    os.makedirs(THUMB_DIR, exist_ok=True)

    # Lanzar Chromium una sola vez en background
    threading.Thread(target=launch_kiosk_once, daemon=True).start()
    
    def _read_ping():
        try:
            with open(PING_FILE, "r") as f:
                s = f.read().strip()
            parts = s.split("|", 1)
            return float(parts[0]), (parts[1] if len(parts) > 1 else "?")
        except Exception:
            return 0.0, "?"

    def kiosk_watchdog(timeout_first=65, retry_url="http://localhost:5000/"):
        global _last_frontend_ping, _last_frontend_stage, _watchdog_already_retry
        start = time.monotonic()

        # Espera ping real del frontend
        while (time.monotonic() - start) < timeout_first:
            if _last_frontend_ping and (time.monotonic() - _last_frontend_ping) < timeout_first:
                logger.info(f"[WD] Frontend OK (stage={_last_frontend_stage}) en {(time.monotonic()-start):.1f}s")
                return
            time.sleep(0.5)

        if _watchdog_already_retry:
            logger.warning("[WD] Sin ping y ya se reintentó antes. No relanzo más.")
            return

        logger.warning("[WD] No hubo ping de splash/player a tiempo. Reintentando Chromium una vez...")
        try:
            subprocess.run(["pkill", "-f", "chromium"], check=False)
            time.sleep(0.7)
        except Exception:
            pass

        _watchdog_already_retry = True
        restart_kiosk(url=retry_url)
      
    
    threading.Thread(target=kiosk_watchdog, daemon=True).start()

    app.run(debug=False, host="0.0.0.0")
