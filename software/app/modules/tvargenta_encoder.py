#!/usr/bin/env python3
import os
import subprocess
import time
import json
import sys
from pathlib import Path
from player_utils import cambiar_canal

APP_DIR = Path(__file__).resolve().parents[1]

try:
    sys.path.insert(0, str(APP_DIR))  # asegurar que 'settings.py' esté en sys.path
    from settings import APP_DIR as SETTINGS_APP_DIR  # type: ignore
    APP_DIR = SETTINGS_APP_DIR
except Exception:
    # si falla, seguimos con el APP_DIR físico
    pass


ENCODER_BIN = APP_DIR / "native" / "encoder_reader"

CANAL_JSON_PATH = "/srv/tvargenta/content/canales.json"
CANAL_ACTIVO_PATH = "/srv/tvargenta/content/canal_activo.json"

# --- Nuevo: trigger para menú (front hace polling de mtime) ---
MENU_TRIGGER_PATH = "/tmp/trigger_menu.json"
MENU_STATE_PATH  = "/tmp/menu_state.json"
MENU_NAV_PATH    = "/tmp/trigger_menu_nav.json"
MENU_SELECT_PATH = "/tmp/trigger_menu_select.json"

estado = "idle"          # idle | evaluando | volume
hubo_giro = False
ultimo_estado = "idle"
last_volume_activity = 0.0

def ts():
    return time.strftime("%Y-%m-%d %H:%M:%S")

def get_canal_actual():
    if Path(CANAL_ACTIVO_PATH).exists():
        with open(CANAL_ACTIVO_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get("canal_id", "default")
    return "default"

def get_lista_canales():
    with open(CANAL_JSON_PATH, "r", encoding="utf-8") as f:
        return list(json.load(f).keys())

def cambiar_al_siguiente(delta):
    canales = get_lista_canales()
    actual = get_canal_actual()
    try:
        idx = canales.index(actual)
    except ValueError:
        idx = 0
    nuevo_idx = (idx + delta) % len(canales)
    nuevo_id = canales[nuevo_idx]

    if nuevo_id != actual:
        print(f"[{ts()}] [ENCODER] Canal cambiado a: {nuevo_id}")
        cambiar_canal(nuevo_id, resetear_cola=True)

        # Notificar al frontend para que recargue
        with open("/tmp/trigger_reload.json", "w") as f:
            json.dump({"timestamp": time.time()}, f)
    else:
        print(f"[{ts()}] [ENCODER] Canal no cambió (circular)")

def ajustar_volumen(delta):
    path = "/tmp/tvargenta_volumen.json"
    valor = 50
    if os.path.exists(path):
        with open(path, "r") as f:
            valor = json.load(f).get("valor", 50)

    nuevo_valor = max(0, min(100, valor + delta))
    with open(path, "w") as f:
        json.dump({"valor": nuevo_valor}, f)

    # Notificar al frontend que hubo un cambio de volumen
    with open("/tmp/trigger_volumen.json", "w") as f:
        json.dump({"timestamp": time.time()}, f)
    print(f"[{ts()}] [VOLUMEN] Ajustado a: {nuevo_valor}")

# --- Nuevo: tocar archivo para abrir/cerrar menú (flanco de bajada sin giro) ---
def trigger_menu():
    try:
        with open(MENU_TRIGGER_PATH, "w") as f:
            json.dump({"timestamp": time.time()}, f)
        print(f"[{ts()}] [MENU] Trigger emitido ({MENU_TRIGGER_PATH})")
    except Exception as e:
        print(f"[{ts()}] [MENU] Error al emitir trigger: {e}")

def menu_is_open():
    if Path(MENU_STATE_PATH).exists():
        try:
            with open(MENU_STATE_PATH, "r") as f:
                data = json.load(f)
            return bool(data.get("open", False))
        except Exception:
            return False
    return False

def trigger_menu_nav(delta):
    try:
        with open(MENU_NAV_PATH, "w") as f:
            json.dump({"delta": int(delta), "timestamp": time.time()}, f)
        print(f"[{ts()}] [MENU] NAV delta={delta}")
    except Exception as e:
        print(f"[{ts()}] [MENU] Error NAV: {e}")

def trigger_menu_select():
    try:
        with open(MENU_SELECT_PATH, "w") as f:
            json.dump({"timestamp": time.time()}, f)
        print(f"[{ts()}] [MENU] SELECT")
    except Exception as e:
        print(f"[{ts()}] [MENU] Error SELECT: {e}")

if __name__ == "__main__":
    print(f"[{ts()}] [ENCODER] Escuchando salida de {ENCODER_BIN}")
    if not ENCODER_BIN.exists():
        raise FileNotFoundError(f"No existe {ENCODER_BIN}. ¿Compilaste encoder_reader.c?")
    proc = subprocess.Popen(
        [str(ENCODER_BIN)],
        stdout=subprocess.PIPE,
        text=True,
        cwd=str(ENCODER_BIN.parent)  # por las dudas
    )

    try:
        for raw in proc.stdout:
            # --- watchdog de volumen ---
            if estado == "volume" and last_volume_activity and (time.time() - last_volume_activity) > 3.2:
                estado = ultimo_estado
                last_volume_activity = 0.0
                print(f"[{ts()}] [ENCODER] Volume timeout → volvemos a {estado}")
            
            line = raw.strip()
            if not line:
                continue

            print(f"[{ts()}] [DEBUG] Evento recibido: {line}")

            # --- Giro del encoder ---
            if line.startswith("ROTARY_"):
                if estado == "idle":
                    if menu_is_open():
                        delta = +1 if line == "ROTARY_CW" else -1
                        trigger_menu_nav(delta)
                    else:
                        # Giro sin apretar: zapping de canales
                        print(f"[{ts()}] [ENCODER] Gesto = cambio de canal")
                        delta = +1 if line == "ROTARY_CW" else -1
                        cambiar_al_siguiente(delta)

                elif estado == "evaluando":
                    # Se estaba apretando: si gira, esto es volumen
                    estado = "volume"
                    hubo_giro = True
                    last_volume_activity = time.time()  
                    print(f"[{ts()}] [ENCODER] Gesto = volumen (entrando a modo volume)")

                elif estado == "volume":
                    # Ajuste fino del volumen
                    delta = +5 if line == "ROTARY_CW" else -5
                    ajustar_volumen(delta)
                    last_volume_activity = time.time()

            # --- Botón: flanco ascendente (apretó) ---
            elif line == "BTN_PRESS":
                if estado == "idle":
                    ultimo_estado = estado
                    estado = "evaluando"
                    hubo_giro = False
                    print(f"[{ts()}] [ENCODER] Entrando en modo evaluando (BTN_PRESS)")

            # --- Botón: flanco descendente (soltó) ---
            elif line == "BTN_RELEASE":
                if estado == "evaluando":
                    if not hubo_giro:
                        if menu_is_open():
                            trigger_menu_select()
                            estado = "idle"
                            print(f"[{ts()}] [ENCODER] Select en menú. Estado=idle")
                        else:
                            trigger_menu()
                            estado = "idle"
                            print(f"[{ts()}] [ENCODER] Evaluando->Menu toggle. Estado=idle")
                    else:
                        estado = ultimo_estado
                        hubo_giro = False
                        print(f"[{ts()}] [ENCODER] Fin de volumen; volvemos a {estado}")

                elif estado == "volume":
                    # <<--- esta rama te falta
                    estado = ultimo_estado
                    hubo_giro = False
                    print(f"[{ts()}] [ENCODER] Fin de ajuste de volumen, volvemos a {estado}")


    except KeyboardInterrupt:
        print(f"\n[{ts()}] [ENCODER] Interrumpido por teclado.")
    finally:
        proc.terminate()
