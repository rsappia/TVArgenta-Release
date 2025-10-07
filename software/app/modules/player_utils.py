import json
from pathlib import Path
    
videos_en_cola = []
indice_video_actual = 0

def cambiar_canal(nuevo_canal_id, resetear_cola=True):

    global videos_en_cola, indice_video_actual

    with open("/srv/tvargenta/content/canal_activo.json", "w", encoding="utf-8") as f:
        json.dump({"canal_id": nuevo_canal_id}, f, indent=2)

    with open("/srv/tvargenta/content/canales.json", "r", encoding="utf-8") as f:
        canales = json.load(f)

    with open("/srv/tvargenta/content/metadata.json", "r", encoding="utf-8") as f:
        metadata = json.load(f)

    with open("/srv/tvargenta/content/configuracion.json", "r", encoding="utf-8") as f:
        configuracion = json.load(f)
        tags_excluidos = set(configuracion.get("tags_excluidos", []))

    canal_info = canales.get(nuevo_canal_id, {})
    tags_prioridad = set(canal_info.get("tags_prioridad", []))

    if resetear_cola:
        videos_en_cola.clear()
        for video_id, datos in metadata.items():
            video_tags = set(datos.get("tags", []))
            if tags_prioridad & video_tags and not (video_tags & tags_excluidos):
                videos_en_cola.append(video_id)
        indice_video_actual = 0

    if videos_en_cola:
        print(f"[CANAL] {nuevo_canal_id} tiene {len(videos_en_cola)} video(s) válidos.")
        print(f"[DEBUG] Lista de videos en cola para {nuevo_canal_id}:")
        for i, vid in enumerate(videos_en_cola):
            print(f"  {i+1}. {vid}")
    else:
        print(f"[CANAL] No hay videos válidos para el canal {nuevo_canal_id}")
