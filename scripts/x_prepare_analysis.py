"""
Radar X V4.2 - Preparacion del lote para analisis manual con Claude.

Filosofia V4.2: CLAUDE PROPONE -> PYTHON VALIDA -> PYTHON RECONSTRUYE.
Este script cubre EXCLUSIVAMENTE la etapa de preparacion (la parte
inicial que en V4.1 vivia dentro de scripts/x_analyzer.py, antes de la
llamada a la API). No llama a ningun modelo, no requiere
ANTHROPIC_API_KEY, no hace busquedas web, y no genera ningun JSON
operativo del repositorio (x_radar.json / x_historico.json /
x_inbox.json). Su unica salida es un paquete de entrada
(radar_x_input_bundle.json) para que un humano lo pegue manualmente en
una conversacion de Claude.

Uso:
  python3 scripts/x_prepare_analysis.py \
      --inbox data/x_inbox.json \
      --historico data/x_historico.json \
      --radar data/x_radar.json \
      --outdir work/prepare \
      [--max-posts 15]
"""

import argparse
import copy
import json
import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

BOGOTA_TZ = ZoneInfo("America/Bogota")
BUNDLE_VERSION = "4.2"


class PrepareError(Exception):
    """Error de validacion controlada de la etapa de preparacion."""


# --------------------------------------------------------------------
# Reutilizado de scripts/x_analyzer.py V4.1 (misma semantica, cambios
# minimos de nombre donde hizo falta para este contexto).
# --------------------------------------------------------------------

def load_json(path, default):
    """Identico a x_analyzer.py: si el archivo no existe, usa el default;
    si existe, lo carga tal cual (json.load se encarga de rechazar JSON
    invalido con su propia excepcion, que capturamos mas abajo)."""
    if not os.path.exists(path):
        return copy.deepcopy(default)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def compute_run_timestamp():
    """Identico a x_analyzer.py: unica fuente de verdad para fecha/hora,
    calculada aqui, nunca por el modelo."""
    now = datetime.now(BOGOTA_TZ)
    return {
        "run_date": now.strftime("%Y-%m-%d"),
        "run_time": now.strftime("%H:%M"),
        "run_timestamp": now.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "timezone": "America/Bogota",
    }


def collect_reusable_evidence_urls(historico, radar):
    """Identico a x_analyzer.py en su logica de recoleccion, mas endurecido
    (Hueco 7): para evidence.url y sources[].url, si el valor existe debe
    ser string no vacio. Un tipo distinto (int, etc.) se considera
    estructuralmente invalido y se reporta via PrepareError -- no se
    convierte silenciosamente con str()."""
    urls = set()
    for i, item in enumerate(radar.get("items", [])):
        for j, c in enumerate(item.get("claims", []) or []):
            for k, ev in enumerate(c.get("evidence", []) or []):
                if isinstance(ev, dict) and "url" in ev and ev["url"] is not None:
                    url = ev["url"]
                    if not isinstance(url, str) or not url:
                        raise PrepareError(
                            f"x_radar.json invalido: items[{i}].claims[{j}].evidence[{k}].url "
                            f"debe ser un string no vacio (se recibio: {url!r})."
                        )
                    urls.add(url)
                elif isinstance(ev, str):
                    if not ev:
                        raise PrepareError(
                            f"x_radar.json invalido: items[{i}].claims[{j}].evidence[{k}] "
                            f"es un string vacio."
                        )
                    urls.add(ev)
        for k, s in enumerate(item.get("sources", []) or []):
            if isinstance(s, dict) and "url" in s and s["url"] is not None:
                url = s["url"]
                if not isinstance(url, str) or not url:
                    raise PrepareError(
                        f"x_radar.json invalido: items[{i}].sources[{k}].url debe ser un "
                        f"string no vacio (se recibio: {url!r})."
                    )
                urls.add(url)
    return urls


# --------------------------------------------------------------------
# Validaciones minimas de estructura de entrada
# --------------------------------------------------------------------

def validate_base_structures(inbox, historico, radar, max_posts_raw):
    if not isinstance(inbox, dict) or not isinstance(inbox.get("posts", []), list):
        raise PrepareError("x_inbox.json invalido: se esperaba un objeto con 'posts' como lista.")
    for i, p in enumerate(inbox.get("posts", [])):
        if not isinstance(p, dict):
            raise PrepareError(f"x_inbox.json invalido: posts[{i}] no es un objeto.")

    if not isinstance(historico, dict) or not isinstance(historico.get("posts", []), list) \
            or not isinstance(historico.get("cuts", []), list):
        raise PrepareError("x_historico.json invalido: se esperaba un objeto con 'posts' y 'cuts' como listas.")

    # Hueco 1: cada historico.posts[i] debe ser objeto.
    for i, p in enumerate(historico.get("posts", [])):
        if not isinstance(p, dict):
            raise PrepareError(f"x_historico.json invalido: posts[{i}] no es un objeto.")

    # Hueco 6: x_post_id no nulo de historico.posts debe ser string no vacio.
    for i, p in enumerate(historico.get("posts", [])):
        pid = p.get("x_post_id")
        if pid is not None and (not isinstance(pid, str) or not pid):
            raise PrepareError(
                f"x_historico.json invalido: posts[{i}].x_post_id debe ser un string "
                f"no vacio cuando no es nulo (se recibio: {pid!r})."
            )

    if not isinstance(radar, dict) or not isinstance(radar.get("items", []), list):
        raise PrepareError("x_radar.json invalido: se esperaba un objeto con 'items' como lista.")

    # Hueco 2: cada radar.items[i] debe ser objeto.
    for i, item in enumerate(radar.get("items", [])):
        if not isinstance(item, dict):
            raise PrepareError(f"x_radar.json invalido: items[{i}] no es un objeto.")

        # Hueco 3 (cerrado): si la clave "claims" existe -- incluso si su
        # valor es null -- debe ser una lista. Solo la AUSENCIA de la
        # clave esta permitida sin mas requisitos.
        if "claims" in item:
            if not isinstance(item["claims"], list):
                raise PrepareError(
                    f"x_radar.json invalido: items[{i}].claims debe ser una lista "
                    f"(se recibio: {item['claims']!r})."
                )
            for j, c in enumerate(item["claims"]):
                if not isinstance(c, dict):
                    raise PrepareError(f"x_radar.json invalido: items[{i}].claims[{j}] no es un objeto.")

                # Ultimo hueco: claims[].evidence[] debe ser lista, y cada
                # elemento debe ser dict CON clave "url" (string no-blank),
                # o string legacy no-blank (compatibilidad V4.1). Ningun
                # otro caso se acepta ni se ignora silenciosamente.
                if "evidence" in c:
                    if not isinstance(c["evidence"], list):
                        raise PrepareError(
                            f"x_radar.json invalido: items[{i}].claims[{j}].evidence debe "
                            f"ser una lista (se recibio: {c['evidence']!r})."
                        )
                    for k, ev in enumerate(c["evidence"]):
                        if isinstance(ev, dict):
                            if "url" not in ev:
                                raise PrepareError(
                                    f"x_radar.json invalido: items[{i}].claims[{j}].evidence[{k}] "
                                    f"es un objeto pero no contiene la clave 'url' (requerida)."
                                )
                            url = ev["url"]
                            if not isinstance(url, str):
                                raise PrepareError(
                                    f"x_radar.json invalido: items[{i}].claims[{j}].evidence[{k}].url "
                                    f"debe ser un string (se recibio: {url!r})."
                                )
                            if url.strip() == "":
                                raise PrepareError(
                                    f"x_radar.json invalido: items[{i}].claims[{j}].evidence[{k}].url "
                                    f"no puede ser una cadena vacia o solo espacios."
                                )
                        elif isinstance(ev, str):
                            # String legacy V4.1: la evidencia completa es la URL.
                            if ev.strip() == "":
                                raise PrepareError(
                                    f"x_radar.json invalido: items[{i}].claims[{j}].evidence[{k}] "
                                    f"(string legacy) no puede ser una cadena vacia o solo espacios."
                                )
                        else:
                            raise PrepareError(
                                f"x_radar.json invalido: items[{i}].claims[{j}].evidence[{k}] tiene "
                                f"un tipo no permitido ({type(ev).__name__}); debe ser objeto con "
                                f"'url' o string legacy no vacio."
                            )

        # Hueco 4 (cerrado): si la clave "sources" existe -- incluso si su
        # valor es null -- debe ser una lista.
        if "sources" in item:
            if not isinstance(item["sources"], list):
                raise PrepareError(
                    f"x_radar.json invalido: items[{i}].sources debe ser una lista "
                    f"(se recibio: {item['sources']!r})."
                )
            for k, s in enumerate(item["sources"]):
                if not isinstance(s, dict):
                    raise PrepareError(f"x_radar.json invalido: items[{i}].sources[{k}] no es un objeto.")

                # sources[].url, si la clave existe, debe ser string no
                # vacio/no blank; null falla.
                if "url" in s:
                    url = s["url"]
                    if not isinstance(url, str):
                        raise PrepareError(
                            f"x_radar.json invalido: items[{i}].sources[{k}].url debe ser un "
                            f"string (se recibio: {url!r})."
                        )
                    if url.strip() == "":
                        raise PrepareError(
                            f"x_radar.json invalido: items[{i}].sources[{k}].url no puede ser "
                            f"una cadena vacia o solo espacios."
                        )

    try:
        max_posts = int(max_posts_raw)
    except (TypeError, ValueError):
        raise PrepareError(f"MAX_POSTS_PER_RUN invalido (no es un entero): {max_posts_raw!r}")
    if max_posts < 1:
        raise PrepareError(f"MAX_POSTS_PER_RUN debe ser >= 1, se recibio: {max_posts}")
    return max_posts


def validate_pending_posts_published_at(inbox):
    """Hueco 5: antes de ordenar, cada post PENDIENTE_ANALISIS debe tener
    published_at como string no vacio. No se convierte None a "" ni se
    inventa fecha alguna -- falla cerrado con indice y x_post_id
    identificables para que el problema se pueda ubicar en el JSON de
    origen."""
    for i, p in enumerate(inbox.get("posts", [])):
        if p.get("collection_status") != "PENDIENTE_ANALISIS":
            continue
        published_at = p.get("published_at")
        if not isinstance(published_at, str) or not published_at:
            pid = p.get("x_post_id", "sin x_post_id")
            raise PrepareError(
                f"x_inbox.json invalido: posts[{i}] (x_post_id={pid!r}) tiene "
                f"published_at invalido para un post PENDIENTE_ANALISIS "
                f"(se recibio: {published_at!r}); debe ser un string no vacio."
            )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--inbox", required=True)
    ap.add_argument("--historico", required=True)
    ap.add_argument("--radar", required=True)
    ap.add_argument("--outdir", required=True)
    ap.add_argument(
        "--max-posts",
        default=os.environ.get("MAX_POSTS_PER_RUN", "15"),
        help="Maximo de posts a incluir en posts_a_procesar (default: 15 o MAX_POSTS_PER_RUN).",
    )
    args = ap.parse_args()

    os.makedirs(args.outdir, exist_ok=True)

    def fail(msg):
        with open(os.path.join(args.outdir, "failure_reason.txt"), "w", encoding="utf-8") as f:
            f.write("La preparacion del lote NO se pudo completar.\n\n")
            f.write(f"- {msg}\n")
        print(f"ERROR: {msg}", file=sys.stderr)
        sys.exit(1)

    # Carga con manejo de JSON invalido (json.load lanza JSONDecodeError)
    try:
        inbox = load_json(args.inbox, {"last_updated": None, "timezone": "America/Bogota", "posts": []})
    except json.JSONDecodeError as e:
        fail(f"x_inbox.json no es JSON valido: {e}")
        return
    try:
        historico = load_json(args.historico, {"version": "1.0", "last_updated": None, "timezone": "America/Bogota", "cuts": [], "posts": []})
    except json.JSONDecodeError as e:
        fail(f"x_historico.json no es JSON valido: {e}")
        return
    try:
        radar = load_json(args.radar, {"last_updated": None, "timezone": "America/Bogota", "cut": None, "items": []})
    except json.JSONDecodeError as e:
        fail(f"x_radar.json no es JSON valido: {e}")
        return

    try:
        max_posts = validate_base_structures(inbox, historico, radar, args.max_posts)
    except PrepareError as e:
        fail(str(e))
        return

    try:
        validate_pending_posts_published_at(inbox)
    except PrepareError as e:
        fail(str(e))
        return

    run_ts = compute_run_timestamp()

    # --- Seleccion determinista: identica semantica a x_analyzer.py V4.1 ---
    pendientes = [p for p in inbox.get("posts", []) if p.get("collection_status") == "PENDIENTE_ANALISIS"]
    pendientes_ordenados = sorted(pendientes, key=lambda p: p.get("published_at", ""))
    posts_to_process = pendientes_ordenados[:max_posts]
    posts_deferred = pendientes_ordenados[max_posts:]
    otros_posts_inbox = [p for p in inbox.get("posts", []) if p.get("collection_status") != "PENDIENTE_ANALISIS"]

    known_ids = sorted({p.get("x_post_id") for p in historico.get("posts", []) if p.get("x_post_id")})
    try:
        reusable_urls = sorted(collect_reusable_evidence_urls(historico, radar))
    except PrepareError as e:
        fail(str(e))
        return
    carried_over_context = radar.get("items", [])  # se pasa tal cual, sin modificar ni resumir

    status = "READY_FOR_CLAUDE" if posts_to_process else "NO_PENDING_POSTS"

    bundle = {
        "version": BUNDLE_VERSION,
        "mode": "manual_claude",
        "status": status,
        "run": {
            "run_date": run_ts["run_date"],
            "run_time": run_ts["run_time"],
            "run_timestamp": run_ts["run_timestamp"],
            "timezone": run_ts["timezone"],
        },
        "limits": {
            "max_posts_per_run": max_posts,
        },
        "posts_a_procesar": posts_to_process,
        "posts_diferidos_por_limite": posts_deferred,
        "ids_ya_conocidos": known_ids,
        "contexto_carried_over": carried_over_context,
        "evidencia_reutilizable": reusable_urls,
        "instructions_for_claude": {
            "analyze_only_posts_a_procesar": True,
            "do_not_reconstruct_final_repository_json": True,
            "expected_response_file": "radar_x_model_response.json",
            "expected_evidence_file": "radar_x_evidence_manifest.json",
        },
    }

    with open(os.path.join(args.outdir, "radar_x_input_bundle.json"), "w", encoding="utf-8") as f:
        json.dump(bundle, f, ensure_ascii=False, indent=2)

    report = {
        "status": status,
        "posts_en_inbox": len(inbox.get("posts", [])),
        "posts_pendientes_totales": len(pendientes),
        "posts_a_procesar": len(posts_to_process),
        "posts_diferidos_por_limite": len(posts_deferred),
        "otros_posts_inbox_no_pendientes": len(otros_posts_inbox),
        "ids_ya_conocidos": len(known_ids),
        "items_carried_over_disponibles": len(carried_over_context),
        "evidencia_reutilizable_urls": len(reusable_urls),
        "max_posts_per_run_usado": max_posts,
    }
    with open(os.path.join(args.outdir, "prepare_report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(f"Preparacion completada. status={status}. Bundle escrito en {args.outdir}")


if __name__ == "__main__":
    main()
