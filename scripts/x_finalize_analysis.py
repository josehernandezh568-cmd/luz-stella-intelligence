"""

Radar X V4.2 - FINALIZE: valida la respuesta manual de Claude y el
manifiesto de evidencia supervisada contra el bundle generado por
x_prepare_analysis.py, y reconstruye deterministicamente los tres JSON
operativos del sistema.

Filosofia V4.2: CLAUDE PROPONE -> PYTHON VALIDA -> PYTHON RECONSTRUYE.

Este script:
- NO llama a ninguna API (ni Anthropic ni ninguna otra).
- NO usa ANTHROPIC_API_KEY ni ANTHROPIC_MODEL.
- NO hace web_search.
- NO escribe en data/*.json -- solo en --outdir.
- Falla ANTES de escribir cualquier JSON final si hay un solo error
  de validacion (fail-closed): si falla, unicamente existen
  failure_reason.txt + intento_fallido_analysis.json en --outdir.

Uso:
  python3 scripts/x_finalize_analysis.py \
      --bundle work/prepare/radar_x_input_bundle.json \
      --response manual_input/radar_x_model_response.json \
      --evidence-manifest manual_input/radar_x_evidence_manifest.json \
      --inbox data/x_inbox.json \
      --historico data/x_historico.json \
      --radar data/x_radar.json \
      --outdir work/finalize
"""

import argparse
import copy
import hashlib
import json
import os
import sys
from urllib.parse import urlparse

# --------------------------------------------------------------------
# Enums reutilizados EXACTAMENTE de scripts/x_analyzer.py V4.1 -- sin
# ampliar valores.
# --------------------------------------------------------------------
VALID_SCRIPT_STATUS = {
    "LISTO", "REVISAR", "REVISAR_VERIFICACION",
    "BLOQUEADO_POR_VERIFICACION", "NO_APLICA",
}
VALID_ACTIONS = {"EXPLICAR", "ACLARAR", "SEGUIMIENTO", "NO_RESPONDER"}
VALID_OPPORTUNITY = {"ALTA", "MEDIA", "BAJA", "NINGUNA"}
VALID_VERIFICATION = {"alta", "media", "baja", "no_aplica"}
VALID_CLAIM_VERIFICATION = {
    "CONFIRMADO", "PARCIAL", "NO_DEMOSTRADO", "CONTRADICHO",
    "DESACTUALIZADO", "OPINION_NO_VERIFICABLE", "PREDICCION_NO_VERIFICABLE",
}
EVIDENCE_REQUIRED_VERIFICATIONS = {"CONFIRMADO", "PARCIAL", "CONTRADICHO"}

VALID_SOURCE_TYPES = {"claude_supervised", "manual_reviewed"}
ALLOWED_URL_SCHEMES = {"http", "https"}

BUNDLE_VERSION = "4.2"
BUNDLE_MODE = "manual_claude"

IMMUTABLE_POST_FIELDS = [
    "x_post_id", "author", "username", "published_at", "post_url", "post_text",
]


class FinalizeError(Exception):
    """Error de validacion controlada de la etapa FINALIZE."""


# --------------------------------------------------------------------
# Utilidades reutilizadas / adaptadas de x_analyzer.py V4.1
# --------------------------------------------------------------------

def load_json_file(path, label):
    if not os.path.exists(path):
        raise FinalizeError(f"{label}: archivo no encontrado en '{path}'.")
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        raise FinalizeError(f"{label}: JSON invalido ({e}).")


def load_repo_json_controlled(path, default, label):
    """Carga controlada de un JSON actual del repositorio (inbox/historico/
    radar). Si el archivo no existe, usa la plantilla vacia por defecto
    (misma semantica que V4.1). Si existe pero el JSON es sintacticamente
    invalido, lanza FinalizeError en vez de dejar que JSONDecodeError se
    propague sin control."""
    if not os.path.exists(path):
        return copy.deepcopy(default)
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        raise FinalizeError(f"{label}: JSON invalido en '{path}' ({e}).")


def validate_repo_inbox(inbox):
    if not isinstance(inbox, dict):
        raise FinalizeError("x_inbox.json invalido: se esperaba un objeto.")
    posts = inbox.get("posts", [])
    if not isinstance(posts, list):
        raise FinalizeError(f"x_inbox.json invalido: posts debe ser una lista (se recibio: {posts!r}).")
    for i, p in enumerate(posts):
        if not isinstance(p, dict):
            raise FinalizeError(f"x_inbox.json invalido: posts[{i}] no es un objeto.")
        pid = p.get("x_post_id")
        if pid is not None and (not isinstance(pid, str) or not pid):
            raise FinalizeError(
                f"x_inbox.json invalido: posts[{i}].x_post_id debe ser un string no "
                f"vacio cuando no es nulo (se recibio: {pid!r})."
            )


def validate_repo_historico(historico):
    if not isinstance(historico, dict):
        raise FinalizeError("x_historico.json invalido: se esperaba un objeto.")
    posts = historico.get("posts", [])
    cuts = historico.get("cuts", [])
    if not isinstance(posts, list):
        raise FinalizeError(f"x_historico.json invalido: posts debe ser una lista (se recibio: {posts!r}).")
    if not isinstance(cuts, list):
        raise FinalizeError(f"x_historico.json invalido: cuts debe ser una lista (se recibio: {cuts!r}).")
    # Esto debe ocurrir ANTES de cualquier p.get(...) sobre historico.posts
    # en el resto del flujo (p.ej. la comparacion de duplicados contra
    # x_post_id ya existente en process_analysis_item).
    for i, p in enumerate(posts):
        if not isinstance(p, dict):
            raise FinalizeError(f"x_historico.json invalido: posts[{i}] no es un objeto.")
        pid = p.get("x_post_id")
        if pid is not None and (not isinstance(pid, str) or not pid):
            raise FinalizeError(
                f"x_historico.json invalido: posts[{i}].x_post_id debe ser un string "
                f"no vacio cuando no es nulo (se recibio: {pid!r})."
            )


def validate_repo_radar(radar):
    if not isinstance(radar, dict):
        raise FinalizeError("x_radar.json invalido: se esperaba un objeto.")
    items = radar.get("items", [])
    if not isinstance(items, list):
        raise FinalizeError(f"x_radar.json invalido: items debe ser una lista (se recibio: {items!r}).")
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            raise FinalizeError(f"x_radar.json invalido: items[{i}] no es un objeto.")
        if "claims" in item:
            if not isinstance(item["claims"], list):
                raise FinalizeError(
                    f"x_radar.json invalido: items[{i}].claims debe ser una lista "
                    f"(se recibio: {item['claims']!r})."
                )
            for j, c in enumerate(item["claims"]):
                if not isinstance(c, dict):
                    raise FinalizeError(f"x_radar.json invalido: items[{i}].claims[{j}] no es un objeto.")
        if "sources" in item:
            if not isinstance(item["sources"], list):
                raise FinalizeError(
                    f"x_radar.json invalido: items[{i}].sources debe ser una lista "
                    f"(se recibio: {item['sources']!r})."
                )
            for k, s in enumerate(item["sources"]):
                if not isinstance(s, dict):
                    raise FinalizeError(f"x_radar.json invalido: items[{i}].sources[{k}] no es un objeto.")


def canonical_sha256(obj):
    """Hash SHA-256 canonico, EXACTAMENTE con la serializacion pedida."""
    blob = json.dumps(
        obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def require_nonempty_string(value, label):
    if not isinstance(value, str) or not value:
        raise FinalizeError(f"{label} debe ser un string no vacio (se recibio: {value!r}).")
    return value


def valid_url_or_raise(url, label):
    if not isinstance(url, str) or not url.strip():
        raise FinalizeError(f"{label}: URL invalida o vacia (se recibio: {url!r}).")
    parsed = urlparse(url)
    if parsed.scheme not in ALLOWED_URL_SCHEMES:
        raise FinalizeError(
            f"{label}: esquema de URL no permitido ({parsed.scheme!r}); "
            f"solo se aceptan http:// o https://."
        )
    return url


# --------------------------------------------------------------------
# Validacion de estructura base (bundle, response, manifest)
# --------------------------------------------------------------------

def validate_bundle(bundle):
    if not isinstance(bundle, dict):
        raise FinalizeError("bundle: debe ser un objeto JSON.")
    if bundle.get("version") != BUNDLE_VERSION:
        raise FinalizeError(f"bundle.version debe ser '{BUNDLE_VERSION}' (se recibio: {bundle.get('version')!r}).")
    if bundle.get("mode") != BUNDLE_MODE:
        raise FinalizeError(f"bundle.mode debe ser '{BUNDLE_MODE}' (se recibio: {bundle.get('mode')!r}).")
    if bundle.get("status") not in ("READY_FOR_CLAUDE", "NO_PENDING_POSTS"):
        raise FinalizeError(f"bundle.status invalido: {bundle.get('status')!r}.")
    if not isinstance(bundle.get("posts_a_procesar"), list):
        raise FinalizeError("bundle.posts_a_procesar debe ser una lista.")
    seen_ids = []
    for i, p in enumerate(bundle["posts_a_procesar"]):
        if not isinstance(p, dict):
            raise FinalizeError(f"bundle.posts_a_procesar[{i}] no es un objeto.")
        pid = require_nonempty_string(p.get("x_post_id"), f"bundle.posts_a_procesar[{i}].x_post_id")
        seen_ids.append(pid)
    dup_ids = {x for x in seen_ids if seen_ids.count(x) > 1}
    if dup_ids:
        raise FinalizeError(
            f"bundle.posts_a_procesar contiene x_post_id duplicado(s): "
            f"{sorted(dup_ids, key=str)}. No se deduplica ni se elige uno: es un error de origen."
        )
    if not isinstance(bundle.get("evidencia_reutilizable"), list):
        raise FinalizeError("bundle.evidencia_reutilizable debe ser una lista.")
    for i, u in enumerate(bundle["evidencia_reutilizable"]):
        if not isinstance(u, str) or not u:
            raise FinalizeError(f"bundle.evidencia_reutilizable[{i}] debe ser un string no vacio.")

    # Hueco 1: coherencia status <-> posts_a_procesar. No se corrige
    # silenciosamente ni se cambia el status: falla cerrado.
    status = bundle.get("status")
    if status == "NO_PENDING_POSTS" and len(bundle["posts_a_procesar"]) != 0:
        raise FinalizeError(
            "bundle.status=NO_PENDING_POSTS pero posts_a_procesar no esta vacio "
            f"(contiene {len(bundle['posts_a_procesar'])} post(s)); esto es incoherente."
        )
    if status == "READY_FOR_CLAUDE" and len(bundle["posts_a_procesar"]) == 0:
        raise FinalizeError(
            "bundle.status=READY_FOR_CLAUDE pero posts_a_procesar esta vacio; "
            "esto es incoherente (deberia ser NO_PENDING_POSTS)."
        )


def validate_response_structure(response):
    if not isinstance(response, dict):
        raise FinalizeError("response: debe ser un objeto JSON.")
    if response.get("version") != BUNDLE_VERSION:
        raise FinalizeError(f"response.version debe ser '{BUNDLE_VERSION}' (se recibio: {response.get('version')!r}).")
    if response.get("mode") != BUNDLE_MODE:
        raise FinalizeError(f"response.mode debe ser '{BUNDLE_MODE}' (se recibio: {response.get('mode')!r}).")
    require_nonempty_string(response.get("input_sha256"), "response.input_sha256")
    if not isinstance(response.get("analysis"), list):
        raise FinalizeError(f"response.analysis debe ser una lista (se recibio: {response.get('analysis')!r}).")
    if not isinstance(response.get("unprocessed"), list):
        raise FinalizeError(f"response.unprocessed debe ser una lista (se recibio: {response.get('unprocessed')!r}).")
    for i, a in enumerate(response["analysis"]):
        if not isinstance(a, dict):
            raise FinalizeError(f"response.analysis[{i}] no es un objeto (tipo {type(a).__name__}).")
    for i, u in enumerate(response["unprocessed"]):
        if not isinstance(u, dict):
            raise FinalizeError(f"response.unprocessed[{i}] no es un objeto (tipo {type(u).__name__}).")


def validate_manifest_structure(manifest, expected_ids):
    """Devuelve manifest_permissions: dict {url: set(x_post_id autorizados)}.
    Si la misma URL aparece mas de una vez en evidence_urls, sus used_for
    se COMBINAN (union), nunca se pierden autorizaciones previas."""
    if not isinstance(manifest, dict):
        raise FinalizeError("manifest: debe ser un objeto JSON.")
    if manifest.get("version") != BUNDLE_VERSION:
        raise FinalizeError(f"manifest.version debe ser '{BUNDLE_VERSION}' (se recibio: {manifest.get('version')!r}).")
    if manifest.get("mode") != BUNDLE_MODE:
        raise FinalizeError(f"manifest.mode debe ser '{BUNDLE_MODE}' (se recibio: {manifest.get('mode')!r}).")
    require_nonempty_string(manifest.get("input_sha256"), "manifest.input_sha256")
    if not isinstance(manifest.get("evidence_urls"), list):
        raise FinalizeError(f"manifest.evidence_urls debe ser una lista (se recibio: {manifest.get('evidence_urls')!r}).")

    manifest_permissions = {}
    for i, ev in enumerate(manifest["evidence_urls"]):
        if not isinstance(ev, dict):
            raise FinalizeError(f"manifest.evidence_urls[{i}] no es un objeto.")
        url = valid_url_or_raise(ev.get("url"), f"manifest.evidence_urls[{i}].url")
        source_type = ev.get("source_type")
        if source_type not in VALID_SOURCE_TYPES:
            raise FinalizeError(
                f"manifest.evidence_urls[{i}].source_type invalido: {source_type!r} "
                f"(debe ser uno de {sorted(VALID_SOURCE_TYPES)})."
            )
        used_for = ev.get("used_for")
        if not isinstance(used_for, list) or not used_for:
            raise FinalizeError(f"manifest.evidence_urls[{i}].used_for debe ser una lista no vacia.")
        for j, uid in enumerate(used_for):
            if not isinstance(uid, str) or not uid:
                raise FinalizeError(f"manifest.evidence_urls[{i}].used_for[{j}] debe ser un string no vacio.")
            if uid not in expected_ids:
                raise FinalizeError(
                    f"manifest.evidence_urls[{i}].used_for[{j}] referencia x_post_id "
                    f"desconocido (no pertenece al lote): {uid!r}."
                )
        manifest_permissions.setdefault(url, set()).update(used_for)
    return manifest_permissions


def is_url_allowed_for_pid(url, pid, reusable_urls, manifest_permissions):
    """Regla de procedencia por post (Hueco 2): una URL es valida para un
    pid concreto si A) es heredada (evidencia_reutilizable, sin requerir
    used_for), o B) esta en el manifest Y ese pid esta explicitamente
    autorizado en su used_for."""
    if url in reusable_urls:
        return True
    return pid in manifest_permissions.get(url, set())


# --------------------------------------------------------------------
# Cobertura del lote
# --------------------------------------------------------------------

def compute_coverage(expected_ids, analysis, unprocessed):
    analysis_ids_list = []
    for i, a in enumerate(analysis):
        pid = a.get("x_post_id")
        require_nonempty_string(pid, f"response.analysis[{i}].x_post_id")
        analysis_ids_list.append(pid)

    unprocessed_ids_list = []
    for i, u in enumerate(unprocessed):
        pid = u.get("x_post_id")
        require_nonempty_string(pid, f"response.unprocessed[{i}].x_post_id")
        unprocessed_ids_list.append(pid)

    dup_a = {x for x in analysis_ids_list if analysis_ids_list.count(x) > 1}
    if dup_a:
        raise FinalizeError(f"x_post_id duplicado dentro de 'analysis': {sorted(dup_a, key=str)}")

    dup_u = {x for x in unprocessed_ids_list if unprocessed_ids_list.count(x) > 1}
    if dup_u:
        raise FinalizeError(f"x_post_id duplicado dentro de 'unprocessed': {sorted(dup_u, key=str)}")

    analysis_ids = set(analysis_ids_list)
    unprocessed_ids = set(unprocessed_ids_list)

    en_ambos = analysis_ids & unprocessed_ids
    if en_ambos:
        raise FinalizeError(f"IDs presentes en analysis Y unprocessed a la vez: {sorted(en_ambos, key=str)}")

    desconocidos = (analysis_ids | unprocessed_ids) - expected_ids
    if desconocidos:
        raise FinalizeError(f"IDs desconocidos (no pertenecen al lote): {sorted(desconocidos, key=str)}")

    faltantes = expected_ids - analysis_ids - unprocessed_ids
    if faltantes:
        raise FinalizeError(f"IDs del lote sin cobertura en analysis ni unprocessed: {sorted(faltantes, key=str)}")

    return analysis_ids, unprocessed_ids


# --------------------------------------------------------------------
# Validacion de score, claims, sources, evidencia (endurecida V4.2)
# --------------------------------------------------------------------

def validate_score(score, pid):
    if score is None:
        return
    if isinstance(score, bool):
        raise FinalizeError(f"{pid}: score no puede ser booleano.")
    if not isinstance(score, (int, float)):
        raise FinalizeError(f"{pid}: score debe ser int o float (se recibio: {score!r}).")
    if not (0 <= score <= 100):
        raise FinalizeError(f"{pid}: score fuera de rango [0,100]: {score!r}.")


def collect_and_validate_claim_evidence(item, pid, reusable_urls, manifest_permissions):
    """Valida claims[] estructuralmente (tipos endurecidos V4.2) y
    devuelve el set de URLs validas usadas como evidencia DENTRO de
    claims[].evidence[] (nunca sources[]), para la regla de minimo 2 de
    LISTO. Cada URL de evidencia debe estar autorizada especificamente
    para este pid (heredada, o manifest con este pid en su used_for)."""
    if "claims" not in item:
        return set(), []
    claims = item["claims"]
    if not isinstance(claims, list):
        raise FinalizeError(f"{pid}: claims debe ser una lista (se recibio: {claims!r}).")

    valid_evidence_urls = set()
    for j, c in enumerate(claims):
        if not isinstance(c, dict):
            raise FinalizeError(f"{pid}: claims[{j}] no es un objeto.")
        cv = c.get("verification")
        if cv not in VALID_CLAIM_VERIFICATION:
            raise FinalizeError(f"{pid}: claims[{j}].verification invalido: {cv!r}.")

        ev_urls_this_claim = []
        if "evidence" in c:
            evidence = c["evidence"]
            if not isinstance(evidence, list):
                raise FinalizeError(f"{pid}: claims[{j}].evidence debe ser una lista (se recibio: {evidence!r}).")
            for k, ev in enumerate(evidence):
                if not isinstance(ev, dict):
                    raise FinalizeError(
                        f"{pid}: claims[{j}].evidence[{k}] tiene un tipo no permitido "
                        f"({type(ev).__name__}); debe ser un objeto con 'url'."
                    )
                if "url" not in ev:
                    raise FinalizeError(f"{pid}: claims[{j}].evidence[{k}] no contiene la clave 'url'.")
                url = valid_url_or_raise(ev["url"], f"{pid}: claims[{j}].evidence[{k}].url")
                if not is_url_allowed_for_pid(url, pid, reusable_urls, manifest_permissions):
                    raise FinalizeError(
                        f"{pid}: claims[{j}].evidence[{k}].url no esta autorizada para este "
                        f"post (no es heredada, y el manifest no incluye a {pid!r} en el "
                        f"used_for de esta URL): {url}"
                    )
                ev_urls_this_claim.append(url)
                valid_evidence_urls.add(url)

        if cv in EVIDENCE_REQUIRED_VERIFICATIONS and not ev_urls_this_claim:
            raise FinalizeError(
                f"{pid}: claims[{j}].verification={cv} requiere al menos una evidencia valida."
            )

    return valid_evidence_urls, claims


def validate_sources(item, pid, reusable_urls, manifest_permissions):
    if "sources" not in item:
        return
    sources = item["sources"]
    if not isinstance(sources, list):
        raise FinalizeError(f"{pid}: sources debe ser una lista (se recibio: {sources!r}).")
    for k, s in enumerate(sources):
        if not isinstance(s, dict):
            raise FinalizeError(f"{pid}: sources[{k}] no es un objeto.")
        if "url" in s:
            url = valid_url_or_raise(s["url"], f"{pid}: sources[{k}].url")
            if not is_url_allowed_for_pid(url, pid, reusable_urls, manifest_permissions):
                raise FinalizeError(
                    f"{pid}: sources[{k}].url no esta autorizada para este post (no es "
                    f"heredada, y el manifest no incluye a {pid!r} en el used_for de "
                    f"esta URL): {url}"
                )


def validate_item_coherence(item, pid):
    pub = item.get("publicable")
    ss = item.get("script_status")
    co = item.get("content_opportunity")
    ra = item.get("recommended_action")
    script = item.get("script")

    if ss not in VALID_SCRIPT_STATUS:
        raise FinalizeError(f"{pid}: script_status invalido: {ss!r}.")
    if ra not in VALID_ACTIONS:
        raise FinalizeError(f"{pid}: recommended_action invalido: {ra!r}.")
    if co not in VALID_OPPORTUNITY:
        raise FinalizeError(f"{pid}: content_opportunity invalido: {co!r}.")
    verification = item.get("verification")
    if verification not in VALID_VERIFICATION:
        raise FinalizeError(f"{pid}: verification invalido: {verification!r}.")

    if ra == "NO_RESPONDER":
        if not (pub is False and ss == "NO_APLICA" and script is None):
            raise FinalizeError(f"{pid}: NO_RESPONDER mal formado (regla A de V4.1).")

    if co in ("BAJA", "NINGUNA"):
        if not (pub is False and script is None):
            raise FinalizeError(f"{pid}: oportunidad {co} con publicable/script invalido (regla B).")

    if ss == "LISTO":
        if not (pub is True and co in ("ALTA", "MEDIA") and script is not None):
            raise FinalizeError(f"{pid}: LISTO sin cumplir publicable/oportunidad/script (regla C).")


def validate_listo_min_two_sources(item, pid, valid_evidence_urls):
    if item.get("script_status") != "LISTO":
        return
    if len(valid_evidence_urls) < 2:
        raise FinalizeError(
            f"{pid}: script_status=LISTO requiere al menos 2 URLs DISTINTAS y validas "
            f"dentro de claims[].evidence[] (sources[] no cuenta); se encontraron "
            f"{len(valid_evidence_urls)}: {sorted(valid_evidence_urls)}"
        )


# --------------------------------------------------------------------
# Flujo principal
# --------------------------------------------------------------------

def process_analysis_item(a, pid, posts_by_id, reusable_urls, manifest_permissions):
    """Procesa un elemento ANALIZADO/DESCARTADO de analysis[]. Devuelve
    (final_status, radar_item_or_None, discard_reason_or_None)."""
    status = a.get("final_status")
    if status not in ("ANALIZADO", "DESCARTADO"):
        raise FinalizeError(f"{pid}: final_status invalido: {status!r}.")

    original_post = posts_by_id.get(pid)
    if original_post is None:
        raise FinalizeError(f"{pid}: no se encontro el post original en bundle.posts_a_procesar.")

    if status == "DESCARTADO":
        if a.get("radar_item") is not None:
            raise FinalizeError(f"{pid}: DESCARTADO pero radar_item no es null.")
        reason = a.get("discard_reason")
        if not isinstance(reason, str) or not reason.strip():
            raise FinalizeError(f"{pid}: DESCARTADO sin discard_reason valido.")
        return "DESCARTADO", None, reason

    # ANALIZADO
    item = a.get("radar_item")
    if not isinstance(item, dict):
        raise FinalizeError(f"{pid}: ANALIZADO pero radar_item no es un objeto valido.")

    # CAMPOS INMUTABLES: Python es la unica fuente de verdad, nunca Claude.
    for field in IMMUTABLE_POST_FIELDS:
        item[field] = original_post.get(field)

    validate_score(item.get("score"), pid)
    valid_evidence_urls, _claims = collect_and_validate_claim_evidence(item, pid, reusable_urls, manifest_permissions)
    validate_sources(item, pid, reusable_urls, manifest_permissions)
    validate_item_coherence(item, pid)
    validate_listo_min_two_sources(item, pid, valid_evidence_urls)

    item.setdefault("carried_over", False)
    item["carried_over"] = False  # el modelo nunca decide esto

    return "ANALIZADO", item, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bundle", required=True)
    ap.add_argument("--response", required=True)
    ap.add_argument("--evidence-manifest", required=True)
    ap.add_argument("--inbox", required=True)
    ap.add_argument("--historico", required=True)
    ap.add_argument("--radar", required=True)
    ap.add_argument("--outdir", required=True)
    args = ap.parse_args()

    os.makedirs(args.outdir, exist_ok=True)

    def fail(msg, expected_ids=None, analysis_ids=None, unprocessed_ids=None, input_sha256=None):
        with open(os.path.join(args.outdir, "failure_reason.txt"), "w", encoding="utf-8") as f:
            f.write("FINALIZE no supero las validaciones. NO se genero ningun JSON final.\n\n")
            f.write(f"- {msg}\n")
        safe = {
            "version": BUNDLE_VERSION,
            "input_sha256": input_sha256,
            "errors": [msg],
            "expected_ids": sorted(expected_ids, key=str) if expected_ids is not None else None,
            "received_analysis_ids": sorted(analysis_ids, key=str) if analysis_ids is not None else None,
            "received_unprocessed_ids": sorted(unprocessed_ids, key=str) if unprocessed_ids is not None else None,
        }
        with open(os.path.join(args.outdir, "intento_fallido_analysis.json"), "w", encoding="utf-8") as f:
            json.dump(safe, f, ensure_ascii=False, indent=2)
        print(f"ERROR: {msg}", file=sys.stderr)
        sys.exit(1)

    # --- Carga ---
    try:
        bundle = load_json_file(args.bundle, "bundle")
        response = load_json_file(args.response, "response")
        manifest = load_json_file(args.evidence_manifest, "manifest")
    except FinalizeError as e:
        fail(str(e))
        return

    try:
        inbox = load_repo_json_controlled(
            args.inbox, {"last_updated": None, "timezone": "America/Bogota", "posts": []}, "x_inbox.json"
        )
        validate_repo_inbox(inbox)

        historico = load_repo_json_controlled(
            args.historico,
            {"version": "1.0", "last_updated": None, "timezone": "America/Bogota", "cuts": [], "posts": []},
            "x_historico.json",
        )
        validate_repo_historico(historico)

        radar = load_repo_json_controlled(
            args.radar, {"last_updated": None, "timezone": "America/Bogota", "cut": None, "items": []}, "x_radar.json"
        )
        validate_repo_radar(radar)
    except FinalizeError as e:
        fail(str(e))
        return

    # --- Validacion estructural base ---
    try:
        validate_bundle(bundle)
    except FinalizeError as e:
        fail(str(e))
        return

    input_sha256 = canonical_sha256(bundle)

    try:
        validate_response_structure(response)
    except FinalizeError as e:
        fail(str(e), input_sha256=input_sha256)
        return

    posts_a_procesar = bundle["posts_a_procesar"]
    posts_by_id = {p["x_post_id"]: p for p in posts_a_procesar}
    expected_ids = set(posts_by_id.keys())
    reusable_urls = set(bundle["evidencia_reutilizable"])

    try:
        manifest_permissions = validate_manifest_structure(manifest, expected_ids)
    except FinalizeError as e:
        fail(str(e), input_sha256=input_sha256)
        return

    # --- Integridad: hash del bundle debe coincidir en response y manifest ---
    if response.get("input_sha256") != input_sha256:
        fail(
            f"response.input_sha256 no coincide con el hash real del bundle "
            f"(esperado {input_sha256}, recibido {response.get('input_sha256')!r}).",
            input_sha256=input_sha256,
        )
        return
    if manifest.get("input_sha256") != input_sha256:
        fail(
            f"manifest.input_sha256 no coincide con el hash real del bundle "
            f"(esperado {input_sha256}, recibido {manifest.get('input_sha256')!r}).",
            input_sha256=input_sha256,
        )
        return

    analysis = response["analysis"]
    unprocessed = response["unprocessed"]

    # --- Caso NO_PENDING_POSTS: no debe haber respuesta "innecesaria" ---
    if bundle.get("status") == "NO_PENDING_POSTS":
        if analysis or unprocessed:
            fail(
                "bundle.status=NO_PENDING_POSTS pero la respuesta contiene analysis/"
                "unprocessed no vacios; no habia nada que analizar en este lote.",
                expected_ids=expected_ids, input_sha256=input_sha256,
            )
            return
        # Nada que procesar: se preservan integramente los JSON actuales.
        final_historico = copy.deepcopy(historico)
        final_radar = copy.deepcopy(radar)
        final_inbox = copy.deepcopy(inbox)
        report = {
            "status": "SUCCESS",
            "version": BUNDLE_VERSION,
            "input_sha256": input_sha256,
            "expected_posts": 0,
            "analyzed_posts": 0,
            "unprocessed_posts": 0,
            "deferred_posts": len(bundle.get("posts_diferidos_por_limite", [])),
            "validation_errors": 0,
            "nota": "bundle.status=NO_PENDING_POSTS: no habia posts que procesar en este lote.",
        }
        _write_success(args.outdir, final_radar, final_historico, final_inbox, report)
        print("FINALIZE completado (NO_PENDING_POSTS, sin cambios).")
        return

    # --- Cobertura del lote ---
    try:
        analysis_ids, unprocessed_ids = compute_coverage(expected_ids, analysis, unprocessed)
    except FinalizeError as e:
        fail(str(e), expected_ids=expected_ids, input_sha256=input_sha256)
        return

    # --- Procesar cada item de analysis ---
    new_radar_items = []
    new_historico_records = []
    try:
        for a in analysis:
            pid = a.get("x_post_id")
            if pid in {p.get("x_post_id") for p in historico.get("posts", [])}:
                raise FinalizeError(f"{pid}: ya existe en x_historico.json (duplicado).")
            status, item, discard_reason = process_analysis_item(a, pid, posts_by_id, reusable_urls, manifest_permissions)
            if status == "DESCARTADO":
                op = posts_by_id[pid]
                new_historico_records.append({
                    "x_post_id": pid,
                    "author": op.get("author"),
                    "username": op.get("username"),
                    "published_at": op.get("published_at"),
                    "post_url": op.get("post_url"),
                    "processed_at": None,  # el timestamp real lo define el flujo de PREPARE/manual, no se inventa aqui
                    "final_status": "DESCARTADO",
                    "recommended_action": "NO_APLICA",
                    "verification": "no_aplica",
                    "score": None,
                    "discard_reason": discard_reason,
                })
            else:
                new_radar_items.append(item)
                new_historico_records.append({
                    "x_post_id": pid,
                    "author": item.get("author"),
                    "username": item.get("username"),
                    "published_at": item.get("published_at"),
                    "post_url": item.get("post_url"),
                    "processed_at": None,
                    "final_status": "ANALIZADO",
                    "recommended_action": item.get("recommended_action"),
                    "verification": item.get("verification"),
                    "score": item.get("score"),
                    "discard_reason": None,
                })

        # --- Validar unprocessed: solo referencia a EXPECTED_IDS (ya
        # garantizado por compute_coverage), con razon presente. ---
        for u in unprocessed:
            reason = u.get("reason")
            if not isinstance(reason, str) or not reason.strip():
                raise FinalizeError(f"{u.get('x_post_id')}: unprocessed sin 'reason' valido.")

    except FinalizeError as e:
        fail(
            str(e), expected_ids=expected_ids,
            analysis_ids=analysis_ids, unprocessed_ids=unprocessed_ids,
            input_sha256=input_sha256,
        )
        return

    # --- Reconstruccion determinista (misma logica que V4.1) ---
    final_historico = copy.deepcopy(historico)
    final_historico.setdefault("cuts", [])
    final_historico.setdefault("posts", [])
    final_historico["version"] = historico.get("version", "1.0")
    final_historico["timezone"] = "America/Bogota"

    if new_historico_records:
        cut_counts = {
            "explicar": sum(1 for r in new_historico_records if r["recommended_action"] == "EXPLICAR"),
            "aclarar": sum(1 for r in new_historico_records if r["recommended_action"] == "ACLARAR"),
            "seguimiento": sum(1 for r in new_historico_records if r["recommended_action"] == "SEGUIMIENTO"),
            "no_responder": sum(1 for r in new_historico_records if r["recommended_action"] == "NO_RESPONDER"),
        }
        new_cut = {
            "date": bundle["run"].get("run_date") if isinstance(bundle.get("run"), dict) else None,
            "time": bundle["run"].get("run_time") if isinstance(bundle.get("run"), dict) else None,
            "timezone": "America/Bogota",
            "inbox_received": len(posts_a_procesar) + len(bundle.get("posts_diferidos_por_limite", [])),
            "processed": len(new_historico_records),
            "relevant": len(new_radar_items),
            "discarded": sum(1 for r in new_historico_records if r["final_status"] == "DESCARTADO"),
            **cut_counts,
            "publicables": sum(1 for it in new_radar_items if it.get("publicable")),
            "scripts_listo": sum(1 for it in new_radar_items if it.get("script_status") == "LISTO"),
        }
        final_historico["cuts"].append(new_cut)
        final_historico["posts"].extend(new_historico_records)
        final_historico["last_updated"] = new_cut["date"]

        final_radar_items = new_radar_items
        for i, it in enumerate(sorted(final_radar_items, key=lambda x: -(x.get("score") or 0)), start=1):
            it["rank"] = i
        final_radar = {
            "last_updated": new_cut["date"],
            "timezone": "America/Bogota",
            "cut": {"date": new_cut["date"], "time": new_cut["time"], "timezone": "America/Bogota"},
            "items": final_radar_items,
        }
    else:
        # 0 posts procesados (todo quedo en unprocessed): se preserva
        # integramente el estado anterior.
        final_radar = copy.deepcopy(radar)

    # x_inbox.json: se remueven SOLO los IDs que quedaron en 'analysis'
    # (ANALIZADO o DESCARTADO); todo lo demas (diferidos, unprocessed,
    # otros estados) permanece intacto tal como esta en el inbox actual.
    final_inbox = copy.deepcopy(inbox)
    final_inbox["posts"] = [
        p for p in final_inbox.get("posts", []) if p.get("x_post_id") not in analysis_ids
    ]

    report = {
        "status": "SUCCESS",
        "version": BUNDLE_VERSION,
        "input_sha256": input_sha256,
        "expected_posts": len(expected_ids),
        "analyzed_posts": len(new_historico_records),
        "unprocessed_posts": len(unprocessed_ids),
        "deferred_posts": len(bundle.get("posts_diferidos_por_limite", [])),
        "validation_errors": 0,
    }
    _write_success(args.outdir, final_radar, final_historico, final_inbox, report)
    print("FINALIZE completado exitosamente.")


def _write_success(outdir, final_radar, final_historico, final_inbox, report):
    with open(os.path.join(outdir, "x_radar.json"), "w", encoding="utf-8") as f:
        json.dump(final_radar, f, ensure_ascii=False, indent=2)
    with open(os.path.join(outdir, "x_historico.json"), "w", encoding="utf-8") as f:
        json.dump(final_historico, f, ensure_ascii=False, indent=2)
    with open(os.path.join(outdir, "x_inbox.json"), "w", encoding="utf-8") as f:
        json.dump(final_inbox, f, ensure_ascii=False, indent=2)
    with open(os.path.join(outdir, "analysis_report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()

