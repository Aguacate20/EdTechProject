"""
pipeline/extractor.py — v3.5

Cambios respecto a v2:

  1. CANONICALIZACIÓN DE CONCEPTOS entre la capa 1 y el enriquecimiento.
     Medido sobre un paper real: 76 conceptos extraídos donde había ~28, con
     seis variantes del mismo framework y cuatro del mismo índice. Como el
     enriquecimiento elige por importancia entre los duplicados, gastaba cupos
     en el mismo concepto dos veces.

  2. CAPAS 4 Y 5 POR LOTES. Antes era una sola llamada por documento con
     max_tokens=6000. Un JSON de casos para un paper rico no cabe, se truncaba,
     el parseo fallaba y se reintentaba cuatro veces la llamada idéntica hasta
     dejar la capa vacía. Ahora van por lotes de segmentos, como las capas 1 y 2.

  3. MANEJO EXPLÍCITO DE TRUNCAMIENTO. `LLMTruncated` trae los elementos
     completos rescatados; se usan en vez de descartarlos, y queda registrado.

  4. EL ESPACIADO ENTRE LLAMADAS SALE DEL SEMÁFORO. En v2 el `sleep` estaba
     dentro del `async with`, así que cada llamada retenía un cupo de
     concurrencia durante su espera además de su ejecución.

  5. INSTRUMENTACIÓN POR PASO. `pipeline_stats.timings` trae los segundos de
     cada capa, para que el próximo diagnóstico de lentitud salga del output.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from . import (canonicalize, compiler, coverage, graph_utils, grounding,
               model_pool, sections, validation)
from .llm_client import LLMError, LLMTruncated, call_llm
from .prompts import (
    layer1_concepts,
    layer1b_enrichment,
    layer1c_canonical,
    layer2_relations,
    layer2b_axes,
    layer3_repertoires,
    layer4_arguments,
    layer5_cases,
    layer5b_scenarios,
)
from .segmentation import extract_segments

logger = logging.getLogger(__name__)


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


BUDGETS = {
    "concepts": _env_int("BUDGET_CONCEPTS", 90_000),
    "relations": _env_int("BUDGET_RELATIONS", 60_000),
    "enrichment": _env_int("BUDGET_ENRICHMENT", 40_000),
    "repertoires": _env_int("BUDGET_REPERTOIRES", 30_000),
    "arguments": _env_int("BUDGET_ARGUMENTS", 40_000),
    "cases": _env_int("BUDGET_CASES", 50_000),
}

# Conceptos que reciben la segunda pasada de profundización.
#
# El techo estaba en 14 y dejaba 15 de 29 conceptos sin `distinctions`, que es
# la materia prima de los distractores caracterizados y de las facetas con las
# que se construyen los ejes. Subirlo cuesta unos minutos por documento y mejora
# dos cosas a la vez: la calidad del feedback en los fallos y el desbloqueo de
# C4 MAPEAR.
MAX_ENRICH = _env_int("MAX_ENRICH_CONCEPTS", 24)
ENRICH_MIN_IMPORTANCE = float(os.environ.get("ENRICH_MIN_IMPORTANCE", "0.45"))
MAX_CASES_FOR_SCENARIOS = _env_int("MAX_CASES_FOR_SCENARIOS", 8)
CONCURRENCY = _env_int("LLM_CONCURRENCY", 6)
# Espaciado entre llamadas. En la última corrida cinco capas reportaron "1 lote
# con error": no fallaron, pero cada lote perdido se lleva su material —las
# relaciones bajaron de 51 a 31 y los ejes quedaron en 1—. El patrón es
# consistente con rechazos por cuota, y un par de segundos de espacio los evita
# a cambio de unos minutos más de proceso.
CALL_SPACING_S = float(os.environ.get("LLM_CALL_SPACING_S", "2"))
SEGMENTS_PER_BATCH = _env_int("SEGMENTS_PER_BATCH", 3)
# La adjudicación de canonicalización va por tandas: con 25 grupos candidatos en
# una sola llamada la respuesta se truncaba antes del primer elemento completo,
# así que ni el rescate podía salvar nada y la capa quedaba en cero.
# Grupos de canonicalización por llamada. Con 32 conceptos y grupos de 5 las
# tres tandas fallaron TODAS por truncamiento: no es azar, es tamaño. Cada grupo
# lleva dos o tres conceptos con su definición, y la respuesta debe caber además.
CANON_GROUPS_PER_CALL = _env_int("CANON_GROUPS_PER_CALL", 3)
# Conceptos por llamada al buscar intuiciones cotidianas. Con la lista completa
# el modelo devuelve tres o cuatro y da el resto por imposible; por lotes chicos
# recorre todos. Y 32 conceptos por 7 campos de texto no caben en una respuesta.
REPERTOIRE_CONCEPTS_PER_CALL = _env_int("REPERTOIRE_CONCEPTS_PER_CALL", 6)
# Topes globales. Los del prompt son POR LOTE, y con nueve lotes por capa eso no
# controla nada: salieron 34 tesis y 20 marcos para un paper de doce páginas.
MAX_THESES = _env_int("MAX_THESES", 8)
MAX_FRAMEWORKS = _env_int("MAX_FRAMEWORKS", 5)
MAX_AXES = _env_int("MAX_AXES", 4)
# Conceptos por llamada al ubicarlos en un eje. Con 31 conceptos y 4 ejes en una
# sola respuesta la capa se truncaba entera.
AXIS_CONCEPTS_PER_CALL = _env_int("AXIS_CONCEPTS_PER_CALL", 16)
MERGE_TARGET_CHARS = _env_int("MERGE_TARGET_CHARS", 6000)

# Techo de tokens y calidad requerida por capa.
#
# El techo importa tanto como el modelo: los proveedores estiman el consumo
# sumando la entrada más ESTE número, así que declarar 6000 para una respuesta
# de 2000 gasta 6000 de cuota. Los valores salen de la salida máxima observada
# en una corrida real, con margen.
#
# El tier 'alta' se reserva para razonamiento y esquemas complejos. Las capas
# con entrada grande (enriquecimiento ~9.6K, repertorios ~10K) solo caben en
# modelos con TPM alto; el enrutador las manda ahí solo, sin necesidad de
# fijarles proveedor.
LAYERS = {
    "capa1":       {"tier": "media", "max_tokens": _env_int("MT_CAPA1", 6000)},
    "capa1b":      {"tier": "alta",  "max_tokens": _env_int("MT_CAPA1B", 3500)},
    "capa1c":      {"tier": "alta",  "max_tokens": _env_int("MT_CAPA1C", 4000)},
    "capa2":       {"tier": "media", "max_tokens": _env_int("MT_CAPA2", 5500)},
    # Los ejes se piden DE A UNO. En una sola llamada, 4 ejes × 31 conceptos con
    # justificación son ~124 entradas: no entran en ningún techo razonable y la
    # respuesta se truncaba antes del primer eje completo.
    "capa2b":      {"tier": "alta",  "max_tokens": _env_int("MT_CAPA2B", 5000)},
    "capa3":       {"tier": "alta",  "max_tokens": _env_int("MT_CAPA3", 3500)},
    "capa4":       {"tier": "alta",  "max_tokens": _env_int("MT_CAPA4", 6500)},
    "capa5":       {"tier": "media", "max_tokens": _env_int("MT_CAPA5", 3500)},
    "capa5b":      {"tier": "media", "max_tokens": _env_int("MT_CAPA5B", 3500)},
}
ENABLE_CANONICALIZATION = os.environ.get("ENABLE_CANONICALIZATION", "1") != "0"
# Descartar conceptos sin anclaje textual. Se puede apagar para comparar, pero
# apagarlo devuelve el comportamiento que dejaba entrar conceptos inventados.
VERIFICAR_ANCLAJE = os.environ.get("VERIFICAR_ANCLAJE", "1") != "0"


class _Status:
    def __init__(self) -> None:
        self.entries: list[dict] = []
        self.timings: dict[str, float] = {}

    def record(self, layer: str, status: str, items: int = 0, detail: str = "") -> None:
        self.entries.append({"layer": layer, "status": status, "items": items, "detail": detail})
        if status == "failed":
            logger.error("[pipeline] capa %s FALLÓ: %s", layer, detail)

    def time(self, layer: str, seconds: float) -> None:
        self.timings[layer] = round(seconds, 1)

    def failed_layers(self) -> list[str]:
        return [e["layer"] for e in self.entries if e["status"] == "failed"]


class _Caller:
    """Limita concurrencia y espacia llamadas, sin retener el cupo durante la espera."""

    def __init__(self, concurrency: int, spacing: float) -> None:
        self.semaphore = asyncio.Semaphore(concurrency)
        self.spacing = spacing
        self.truncations: list[str] = []

    async def json(
        self,
        system_prompt: str,
        user_prompt: str,
        label: str,
        max_tokens: int | None = None,
        tier: str | None = None,
    ) -> tuple[dict | None, str | None]:
        """Devuelve (payload, error). Un truncamiento rescatado devuelve payload
        y error=None, dejando constancia en `truncations`."""
        config = LAYERS.get(label.split("_")[0], {})
        async with self.semaphore:
            try:
                return await call_llm(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    max_tokens=max_tokens or config.get("max_tokens", 4096),
                    tier=tier or config.get("tier", "alta"),
                    label=label,
                ), None
            except LLMTruncated as e:
                self.truncations.append(label)
                if e.partial:
                    return e.partial, None
                return None, f"truncado sin rescate: {e}"
            except LLMError as e:
                return None, str(e)[:250]
            except Exception as e:  # noqa: BLE001
                return None, f"{type(e).__name__}: {e}"[:250]

    async def spaced(self) -> None:
        if self.spacing > 0:
            await asyncio.sleep(self.spacing)


async def run_pipeline(
    pdf_bytes: bytes,
    filename: str,
    course_id: str | None = None,
) -> dict[str, Any]:
    if not course_id:
        course_id = str(uuid.uuid4())

    stats: dict[str, Any] = {}
    status = _Status()
    caller = _Caller(CONCURRENCY, CALL_SPACING_S)
    truncated_any = False
    t_start = time.monotonic()

    logger.info("[pipeline] Iniciando extracción para %s, course_id=%s", filename, course_id)

    # ── Paso 1: Segmentación ───────────────────────────────────────────────
    t0 = time.monotonic()
    all_segments = sections.annotate(extract_segments(pdf_bytes, max_chars_per_segment=6000))
    raw_body = sections.strip_backmatter(all_segments)
    body = sections.merge_segments(raw_body, MERGE_TARGET_CHARS)
    status.time("segmentation", time.monotonic() - t0)

    stats["segments_total"] = len(all_segments)
    stats["segments_body_raw"] = len(raw_body)
    stats["segments_body"] = len(body)
    stats["total_chars"] = sum(s.char_count for s in body)
    stats["section_coverage"] = sections.coverage_report(body)

    if not body:
        status.record("segmentation", "failed", 0, "El PDF no produjo texto utilizable.")
        return _finalize({}, course_id, filename, stats, status, False, t_start)
    status.record("segmentation", "ok", len(body))

    def batches_of(segs: list, n: int = SEGMENTS_PER_BATCH) -> list[list]:
        return [segs[i:i + n] for i in range(0, len(segs), n)]

    # ── Paso 2: Capa 1 — Conceptos ─────────────────────────────────────────
    t0 = time.monotonic()
    seg_concepts, trunc = sections.select_for_layer(body, "concepts", BUDGETS["concepts"])
    truncated_any |= trunc

    async def concept_batch(batch):
        prompt = layer1_concepts.USER_PROMPT_TEMPLATE.format(
            section_title=" / ".join(s.section_title or "—" for s in batch),
            pages=", ".join(str(p) for p in sorted({p for s in batch for p in s.pages})),
            text=sections.combine(batch),
        )
        payload, error = await caller.json(
            layer1_concepts.SYSTEM_PROMPT, prompt, "capa1"
        )
        await caller.spaced()
        # v3.8: la capa 1 declara el objeto de estudio (la obra, el caso, la
        # empresa que el texto analiza) en vez de convertirlo en concepto-eje
        obj = (payload or {}).get("objeto_de_estudio")
        if isinstance(obj, dict) and obj.get("title") and not objeto_de_estudio:
            objeto_de_estudio.update({"title": str(obj["title"]), "descripcion": str(obj.get("descripcion") or "")})
        return (payload or {}).get("concepts", []), error

    objeto_de_estudio: dict = {}
    results = await asyncio.gather(*[concept_batch(b) for b in batches_of(seg_concepts)])
    raw_concepts: list[dict] = []
    concept_errors = [e for _, e in results if e]
    for items, _ in results:
        raw_concepts.extend(items)

    # Dedup exacto previo (barato) antes de canonicalizar.
    # Cuántos lotes nombraron cada concepto: es la señal más honesta para
    # elegir el título canónico cuando hay variantes en conflicto.
    counts: dict[str, int] = {}
    for c in raw_concepts:
        key = canonicalize.normalize(c.get("title", "")) or c.get("id", "")
        counts[key] = counts.get(key, 0) + 1

    seen: set[str] = set()
    concepts: list[dict] = []
    for c in raw_concepts:
        cid = c.get("id")
        if cid and cid not in seen:
            seen.add(cid)
            key = canonicalize.normalize(c.get("title", "")) or cid
            c["_extraction_count"] = counts.get(key, 1)
            concepts.append(c)

    # ── Verificación de anclaje textual ───────────────────────────────────
    # Antes de canonicalizar, para que un concepto inventado no arrastre
    # fusiones ni se convierta en distractor de otros. En la corrida medida
    # entró un "Perceived Cognitive Consistency Index (PCCI)" que el paper
    # nunca menciona —define PCCI como Parasocial Co-Creation Index— y llegó
    # hasta los ítems del juego.
    verificador = grounding.Verificador(sections.combine(body, with_headers=False))
    concepts = verificador.verificar_conceptos(concepts, descartar=VERIFICAR_ANCLAJE)
    stats["grounding"] = verificador.informe()

    status.time("layer1_concepts", time.monotonic() - t0)
    stats["concepts_raw"] = len(raw_concepts)
    stats["concepts_after_exact_dedup"] = len(concepts)

    if not concepts:
        status.record("layer1_concepts", "failed", 0,
                      f"Ningún concepto extraído. Errores: {concept_errors[:2]}")
        return _finalize({}, course_id, filename, stats, status, truncated_any, t_start)
    status.record("layer1_concepts", "ok", len(concepts),
                  f"{len(concept_errors)} lotes con error" if concept_errors else "")

    # ── Paso 2.2: Canonicalización ─────────────────────────────────────────
    t0 = time.monotonic()
    canon_report: dict = {}
    if ENABLE_CANONICALIZATION and len(concepts) > 3:
        concepts, _, canon_report, oversized = canonicalize.deterministic_pass(concepts)

        # Los grupos que el paso determinista aplazó por tamaño van primero:
        # son los que más riesgo tienen de esconder una fusión indebida.
        # Las siglas van primero: es la señal más fuerte y la única inmune al
        # idioma del título.
        groups = canonicalize.dedupe_group_list(
            canonicalize.acronym_candidates(concepts)
            + oversized
            + canonicalize.similarity_candidates(concepts)
        )
        if groups:
            tandas = [
                groups[i:i + CANON_GROUPS_PER_CALL]
                for i in range(0, len(groups), CANON_GROUPS_PER_CALL)
            ]

            async def canon_batch(tanda):
                payload, error = await caller.json(
                    layer1c_canonical.SYSTEM_PROMPT,
                    layer1c_canonical.USER_PROMPT_TEMPLATE.format(
                        groups=_render_groups(tanda)
                    ),
                    "capa1c_canonical",
                )
                await caller.spaced()
                return (payload or {}).get("merges", []), error

            canon_results = await asyncio.gather(*[canon_batch(x) for x in tandas])
            merges = [m for items, _ in canon_results for m in items]
            canon_errors = [e for _, e in canon_results if e]

            applied: list[dict] = []
            if merges:
                concepts, _, applied = canonicalize.apply_llm_decisions(concepts, merges)
            canon_report["llm_fusions"] = applied
            canon_report["adjudicacion_lotes"] = len(tandas)
            status.record(
                "layer1c_canonical",
                "ok" if merges else ("failed" if len(canon_errors) == len(tandas) else "empty"),
                len(applied),
                f"{len(canon_errors)} tandas con error" if canon_errors else "",
            )
        else:
            status.record("layer1c_canonical", "skipped", 0, "sin grupos candidatos")
    else:
        status.record("layer1c_canonical", "skipped", 0, "desactivado o muy pocos conceptos")

    status.time("canonicalization", time.monotonic() - t0)
    stats["concepts_unique"] = len(concepts)
    stats["canonicalization"] = canon_report
    logger.info("[pipeline] Conceptos tras canonicalizar: %d", len(concepts))

    valid_ids = {c["id"] for c in concepts}
    concepts_json = json.dumps(
        [{"id": c["id"], "title": c.get("title", "")} for c in concepts],
        ensure_ascii=False,
    )

    # ── Paso 2.5: Enriquecimiento ──────────────────────────────────────────
    t0 = time.monotonic()
    seg_enrich, trunc = sections.select_for_layer(body, "enrichment", BUDGETS["enrichment"])
    truncated_any |= trunc
    enrich_text = sections.combine(seg_enrich)

    to_enrich = sorted(
        [c for c in concepts if c.get("importance", 0) >= ENRICH_MIN_IMPORTANCE],
        key=lambda c: (-float(c.get("importance") or 0), -len(c.get("definition") or "")),
    )[:MAX_ENRICH]

    enriched_count = 0
    enrich_errors: list[str] = []
    if to_enrich:
        async def enrich_batch(batch):
            concepts_list = "\n\n".join(
                f"ID: {c['id']}\nTítulo: {c.get('title','')}\nDefinición inicial: {c.get('definition','')}"
                for c in batch
            )
            payload, error = await caller.json(
                layer1b_enrichment.SYSTEM_PROMPT,
                layer1b_enrichment.USER_PROMPT_TEMPLATE_BATCH.format(
                    full_text=enrich_text,
                    concepts_list=concepts_list,
                    valid_ids=", ".join(sorted(valid_ids)),
                ),
                "capa1b_enriquecimiento",
            )
            await caller.spaced()
            return (payload or {}).get("concepts", []), error

        enrich_results = await asyncio.gather(
            *[enrich_batch(b) for b in batches_of(to_enrich, 3)]
        )
        by_id = {c["id"]: c for c in concepts}
        for items, error in enrich_results:
            if error:
                enrich_errors.append(error)
            for e in items:
                target = by_id.get(e.get("id"))
                if not target:
                    continue
                target["core_definition"] = e.get("core_definition")
                target["subdimensions"] = e.get("subdimensions") or []
                target["distinctions"] = [
                    d for d in (e.get("distinctions") or [])
                    if d.get("from_concept") in valid_ids
                ]
                target["measurement_approach"] = e.get("measurement_approach")
                target["theoretical_role"] = e.get("theoretical_role")
                target["key_tensions"] = e.get("key_tensions") or []
                target["evolution_in_paper"] = e.get("evolution_in_paper")
                target["is_enriched"] = True
                enriched_count += 1

    status.time("layer1b_enrichment", time.monotonic() - t0)
    stats["concepts_enriched"] = enriched_count
    stats["concepts_eligible_for_enrichment"] = len(to_enrich)
    status.record(
        "layer1b_enrichment",
        "ok" if enriched_count else ("failed" if to_enrich else "skipped"),
        enriched_count,
        (f"{len(concepts) - enriched_count} conceptos sin `distinctions`: no pueden "
         f"generar distractores caracterizados. Errores: {enrich_errors[:1]}")
        if enriched_count < len(concepts) else "",
    )

    # ── Paso 3: Capa 2 — Relaciones ────────────────────────────────────────
    t0 = time.monotonic()
    seg_rel, trunc = sections.select_for_layer(body, "relations", BUDGETS["relations"])
    truncated_any |= trunc

    async def relation_batch(batch):
        payload, error = await caller.json(
            layer2_relations.SYSTEM_PROMPT,
            layer2_relations.USER_PROMPT_TEMPLATE.format(
                text=sections.combine(batch, with_headers=False),
                concepts_json=concepts_json,
            ),
            "capa2_relaciones",
        )
        await caller.spaced()
        return (payload or {}).get("relations", []), error

    lotes_rel = batches_of(seg_rel)
    rel_results = await asyncio.gather(*[relation_batch(b) for b in lotes_rel])
    # Igual que en repertorios: un lote de relaciones perdido son varias aristas
    # menos en el grafo, y el grafo es lo que sostiene las mecánicas C y D.
    fallidos_rel = [b for b, (_, e) in zip(lotes_rel, rel_results) if e]
    if fallidos_rel:
        logger.info("[pipeline] reintentando %d lote(s) de relaciones", len(fallidos_rel))
        rel_results = list(rel_results) + list(
            await asyncio.gather(*[relation_batch(b) for b in fallidos_rel])
        )
    raw_relations: list[dict] = []
    rel_errors = [e for _, e in rel_results if e]
    for items, _ in rel_results:
        raw_relations.extend(items)

    relations = verificador.verificar_relaciones(raw_relations)
    relations, rel_report = graph_utils.dedupe_relations(relations, valid_ids)
    # Una descripción que solo nombra a uno de los dos extremos produce
    # retroalimentación confusa: el estudiante lee sobre un concepto cuando la
    # pregunta era sobre el vínculo entre dos. No se descarta la arista, se
    # marca para que el consumidor use un texto genérico.
    rel_report["descripciones_incompletas"] = graph_utils.validar_descripciones(
        relations, concepts
    )
    status.time("layer2_relations", time.monotonic() - t0)
    stats["relations_raw"] = len(raw_relations)
    stats["relations"] = len(relations)

    # ── Co-ocurrencia: qué conceptos trata el texto en el mismo sitio ──────
    #
    # No afirma ningún vínculo, solo cercanía textual. Cubre el hueco entre "el
    # documento dice que A causa B" y "no hay conexión", que hasta ahora se
    # leían igual. Sale del troceado, sin LLM: es gratis.
    cooccurrences = graph_utils.compute_cooccurrences(concepts, body)
    stats["cooccurrences"] = len(cooccurrences)
    stats.update(rel_report)
    status.record(
        "layer2_relations",
        "ok" if relations else ("failed" if len(rel_errors) == len(rel_results) else "empty"),
        len(relations),
        f"{len(rel_errors)} lotes con error" if rel_errors else "",
    )

    clusters = graph_utils.compute_clusters([c["id"] for c in concepts], relations)
    stats["clusters"] = len(clusters)

    # ── Paso 3.5: Ejes de atributos ────────────────────────────────────────
    t0 = time.monotonic()
    axes: list[dict] = []
    with_subs = [c for c in concepts if c.get("subdimensions")]
    if len(with_subs) >= 3:
        # Fase 1: definir los ejes, sin ubicar conceptos. Respuesta corta.
        # Solo los NOMBRES de las subdimensiones: para decidir qué ejes existen
        # no hacen falta las descripciones, y con 14 conceptos enriquecidos por 5
        # subdimensiones cada uno el payload empujaba la respuesta a truncarse.
        # Solo los nombres de faceta, deduplicados y sin decir de qué concepto
        # viene cada uno: para decidir QUÉ ejes existen eso no hace falta, y con
        # 32 conceptos el payload empujaba la respuesta a truncarse antes del
        # primer eje completo.
        nombres_faceta: list[str] = []
        for c in with_subs:
            for s in (c.get("subdimensions") or []):
                nombre = (s.get("name") or "").strip()
                if nombre and nombre not in nombres_faceta:
                    nombres_faceta.append(nombre)
        payload_text = "Facetas presentes en los conceptos del documento:\n" + "\n".join(
            f"- {x}" for x in nombres_faceta[:60]
        )
        payload, error = await caller.json(
            layer2b_axes.SYSTEM_PROMPT_DEFINE,
            layer2b_axes.USER_PROMPT_DEFINE.format(concepts_with_subdimensions=payload_text),
            "capa2b_ejes",
            max_tokens=_env_int("MT_CAPA2B_DEFINE", 3500),
        )
        await caller.spaced()

        definidos = [a for a in ((payload or {}).get("axes") or []) if a.get("id")][:MAX_AXES]

        if not definidos:
            status.record("layer2b_axes", "failed", 0, error or "no se definieron ejes")
        else:
            # Fase 2: ubicar los conceptos, un eje por llamada y por tandas.
            ubicables = [c for c in concepts if c.get("id") in valid_ids]
            tandas = [
                ubicables[i:i + AXIS_CONCEPTS_PER_CALL]
                for i in range(0, len(ubicables), AXIS_CONCEPTS_PER_CALL)
            ]

            async def place(axis, tanda):
                lista = "\n".join(
                    f"- {c['id']}: {c.get('title','')} — {(c.get('definition') or '')[:140]}"
                    for c in tanda
                )
                res, err = await caller.json(
                    layer2b_axes.SYSTEM_PROMPT_PLACE,
                    layer2b_axes.USER_PROMPT_PLACE.format(
                        axis_label=axis.get("label", ""),
                        polo_bajo=axis.get("polo_bajo", ""),
                        polo_alto=axis.get("polo_alto", ""),
                        concepts_list=lista,
                    ),
                    "capa2b_ejes",
                    max_tokens=3000,
                )
                await caller.spaced()
                return axis["id"], (res or {}).get("positions", []), err

            trabajos = [(a, tanda) for a in definidos for tanda in tandas]
            place_results = await asyncio.gather(*[place(a, tv) for a, tv in trabajos])

            # Reintento de las tandas perdidas. Era el único sitio del pipeline
            # sin reintento, y se notaba: en la última corrida cuatro llamadas de
            # ubicación fallaron, así que varios conceptos quedaron sin posición
            # en ejes que sí se habían definido bien. Un eje al que le faltan
            # conceptos no bloquea C4 pero la empobrece — el ejercicio consiste
            # justamente en ordenar conceptos entre sí.
            fallidos = [
                (a, tv) for (a, tv), (_, _, err) in zip(trabajos, place_results) if err
            ]
            if fallidos:
                logger.info("[pipeline] reintentando %d tanda(s) de ubicación en ejes",
                            len(fallidos))
                place_results = list(place_results) + list(
                    await asyncio.gather(*[place(a, tv) for a, tv in fallidos])
                )

            posiciones: dict[str, list[dict]] = {a["id"]: [] for a in definidos}
            place_errors = [e for _, _, e in place_results if e]
            for axis_id, items, _ in place_results:
                for p in items:
                    if (p.get("concept_id") in valid_ids
                            and isinstance(p.get("position"), (int, float))
                            and axis_id in posiciones):
                        # Deduplicar: con el reintento un concepto puede llegar
                        # dos veces para el mismo eje, y una posición repetida
                        # rompería el orden relativo que C4 evalúa.
                        if not any(x.get("concept_id") == p["concept_id"]
                                   for x in posiciones[axis_id]):
                            posiciones[axis_id].append(p)

            # Un eje solo sirve si ubica a una parte razonable de los conceptos:
            # con tres de veintiséis no hay orden relativo que evaluar.
            minimo = max(4, int(len(ubicables) * 0.4))
            axes = []
            descartados_eje = []
            for a in definidos:
                pos = posiciones.get(a["id"], [])
                if len(pos) >= minimo:
                    axes.append({**a, "positions": pos})
                elif pos:
                    descartados_eje.append(f"{a.get('label')} ({len(pos)}/{len(ubicables)})")

            cobertura = (
                round(sum(len(a["positions"]) for a in axes) /
                      max(len(axes) * len(ubicables), 1), 2)
                if axes else 0.0
            )
            detalle = []
            if place_errors:
                detalle.append(f"{len(place_errors)} llamadas de ubicación con error")
            if descartados_eje:
                detalle.append(f"ejes con muy pocos conceptos ubicados: {', '.join(descartados_eje)}")
            if axes:
                detalle.append(f"cobertura {cobertura:.0%} de los conceptos")

            status.record(
                "layer2b_axes",
                "ok" if axes else "failed",
                len(axes),
                " · ".join(detalle),
            )
            stats["ejes_cobertura"] = cobertura
    else:
        status.record("layer2b_axes", "skipped", 0,
                      "Menos de 3 conceptos con subdimensiones: C4 MAPEAR no será instanciable.")
    status.time("layer2b_axes", time.monotonic() - t0)
    stats["axes"] = len(axes)

    # ── Paso 4: Capa 3 — Repertorios ───────────────────────────────────────
    t0 = time.monotonic()
    seg_rep, trunc = sections.select_for_layer(body, "repertoires", BUDGETS["repertoires"])
    truncated_any |= trunc
    texto_rep = sections.combine(seg_rep, with_headers=False)

    # Por lotes, no en una sola llamada. Dos razones que apuntan a lo mismo:
    #
    # De tamaño: cada intuición lleva siete campos de texto y el prompt pide dos
    # o tres frases en el contraste científico. Con 32 conceptos la respuesta se
    # truncaba sin rescate y la capa quedaba en cero.
    #
    # De calidad: con la lista completa delante, el modelo produce tres o cuatro
    # intuiciones y da el resto por imposible. Por lotes chicos recorre todos los
    # conceptos, que es lo que la meta de cobertura pide.
    #
    # Se priorizan los conceptos donde una intuición previa pesa más: los puerta
    # y umbral primero, después por importancia.
    ordenados = sorted(
        concepts,
        key=lambda c: (
            0 if (c.get("is_gateway") or c.get("is_threshold")) else 1,
            -float(c.get("importance") or 0),
        ),
    )
    lotes_rep = [
        ordenados[i:i + REPERTOIRE_CONCEPTS_PER_CALL]
        for i in range(0, len(ordenados), REPERTOIRE_CONCEPTS_PER_CALL)
    ]

    async def repertoire_batch(lote):
        payload, error = await caller.json(
            layer3_repertoires.SYSTEM_PROMPT,
            layer3_repertoires.USER_PROMPT_TEMPLATE.format(
                text=texto_rep,
                concepts_json=json.dumps(
                    [{"id": c["id"], "title": c.get("title", ""),
                      "definition": (c.get("definition") or "")[:220]}
                     for c in lote],
                    ensure_ascii=False,
                ),
            ),
            "capa3_repertorios",
        )
        await caller.spaced()
        return (payload or {}).get("repertoires", []), error

    rep_results = await asyncio.gather(*[repertoire_batch(l) for l in lotes_rep])
    # Segunda pasada sobre los lotes que fallaron. Un lote perdido se lleva su
    # material entero, y en una capa por lotes eso es una fracción visible del
    # resultado: no reintentar es aceptar perderla.
    fallidos = [l for l, (_, e) in zip(lotes_rep, rep_results) if e]
    if fallidos:
        logger.info("[pipeline] reintentando %d lote(s) de repertorios", len(fallidos))
        rep_results = list(rep_results) + list(
            await asyncio.gather(*[repertoire_batch(l) for l in fallidos])
        )
    repertoires: list[dict] = []
    vistos_rep: set = set()
    rep_errores = [e for _, e in rep_results if e]
    for items_r, _ in rep_results:
        for r in items_r or []:
            clave = (r.get("concept_id"), canonicalize.normalize(r.get("label", "")))
            if clave in vistos_rep:
                continue
            vistos_rep.add(clave)
            repertoires.append(r)

    status.time("layer3_repertoires", time.monotonic() - t0)
    status.record(
        "layer3_repertoires",
        "ok" if repertoires else ("failed" if len(rep_errores) == len(lotes_rep) else "empty"),
        len(repertoires),
        (f"{len(rep_errores)} de {len(lotes_rep)} lotes con error"
         if rep_errores else
         f"{len(repertoires)} intuiciones para {len(concepts)} conceptos"),
    )
    stats["repertoires"] = len(repertoires)
    stats["repertoire_lotes"] = len(lotes_rep)

    # ── Paso 5: Capas 4 y 5, ahora por lotes ───────────────────────────────
    t0 = time.monotonic()
    seg_args, t1 = sections.select_for_layer(body, "arguments", BUDGETS["arguments"])
    seg_cases, t2 = sections.select_for_layer(body, "cases", BUDGETS["cases"])
    truncated_any |= (t1 or t2)

    async def argument_batch(batch):
        payload, error = await caller.json(
            layer4_arguments.SYSTEM_PROMPT,
            layer4_arguments.USER_PROMPT_TEMPLATE.format(
                text=sections.combine(batch), concepts_json=concepts_json,
            ),
            "capa4_argumentos",
        )
        await caller.spaced()
        return payload or {}, error

    async def case_batch(batch):
        payload, error = await caller.json(
            layer5_cases.SYSTEM_PROMPT,
            layer5_cases.USER_PROMPT_TEMPLATE.format(
                text=sections.combine(batch), concepts_json=concepts_json,
            ),
            "capa5_casos",
        )
        await caller.spaced()
        return (payload or {}).get("cases", []), error

    arg_results, case_results = await asyncio.gather(
        asyncio.gather(*[argument_batch(b) for b in batches_of(seg_args)]),
        asyncio.gather(*[case_batch(b) for b in batches_of(seg_cases)]),
    )

    frameworks = _dedupe_by_id(
        [f for payload, _ in arg_results for f in (payload.get("frameworks") or [])]
    )
    theses = _dedupe_by_id(
        [t for payload, _ in arg_results for t in (payload.get("theses") or [])]
    )

    # El tope del prompt es por lote, así que no controla el total. Se unifica
    # por parecido del enunciado —no por id— y se aplica un tope global.
    frameworks, fw_descartados = canonicalize.dedupe_by_text(
        frameworks, ["label"], threshold=0.6,
        merge_lists=("principios_centrales", "rivales", "concept_ids"),
        max_items=MAX_FRAMEWORKS,
        score_key=lambda f: (len(f.get("principios_centrales") or []), len(f.get("rivales") or [])),
    )
    theses, th_descartados = canonicalize.dedupe_by_text(
        theses, ["statement"], threshold=0.6,
        merge_lists=("supporting_arguments", "counterarguments",
                     "criterios_defensa_valida", "criterios_refutacion_valida", "concept_ids"),
        max_items=MAX_THESES,
        score_key=lambda t: (
            len(t.get("criterios_defensa_valida") or []),
            len(t.get("counterarguments") or []),
            len(t.get("supporting_arguments") or []),
        ),
    )
    stats["theses_descartadas"] = th_descartados
    stats["frameworks_descartados"] = fw_descartados

    # Las tesis y los marcos sobrevivientes pueden referirse a marcos que se
    # descartaron por el tope global, o a ids que un lote inventó y otro nunca
    # produjo. Sin esta limpieza, un marco queda declarando rivales inexistentes
    # y cualquier actividad de contraste entre marcos elige contra la nada.
    fw_ids = {f.get("id") for f in frameworks}
    for th in theses:
        if th.get("framework_id") and th["framework_id"] not in fw_ids:
            th["framework_id"] = None
    huerfanos = canonicalize.strip_dangling_refs(frameworks, ["rivales"], fw_ids)
    stats["rivales_huerfanos"] = huerfanos

    # Un marco sin rivales no sirve para F3 REFUTAR, y conviene que se sepa.
    stats["frameworks_con_rival"] = sum(1 for f in frameworks if f.get("rivales"))
    arg_errors = [e for _, e in arg_results if e]
    cases = _dedupe_by_id([c for items, _ in case_results for c in items])
    case_errors = [e for _, e in case_results if e]

    status.time("layers_4_5", time.monotonic() - t0)
    status.record(
        "layer4_arguments",
        "ok" if theses else ("failed" if len(arg_errors) == len(arg_results) else "empty"),
        len(theses),
        (f"{len(arg_errors)} lotes con error" if arg_errors else
         "El documento puede ser expositivo sin debate: es un resultado válido." if not theses else ""),
    )
    status.record(
        "layer5_cases",
        "ok" if cases else ("failed" if len(case_errors) == len(case_results) else "empty"),
        len(cases),
        f"{len(case_errors)} lotes con error" if case_errors else "",
    )
    # Los casos y las tesis se marcan pero no se descartan: en estas capas el
    # modelo sintetiza legítimamente sobre varias frases, así que una cita que
    # no calza no prueba invención.
    cases = verificador.verificar_items(cases, etiqueta="casos")
    theses = verificador.verificar_items(theses, etiqueta="tesis")
    stats["grounding"] = verificador.informe()

    stats["frameworks"] = len(frameworks)
    stats["theses"] = len(theses)
    stats["cases"] = len(cases)

    # ── Paso 5.5: Escenarios derivados ─────────────────────────────────────
    t0 = time.monotonic()
    scenarios: list[dict] = []
    cases_with_gold = [c for c in cases if (c.get("resolucion_esperada") or "").strip()]
    if cases_with_gold:
        subset = cases_with_gold[:MAX_CASES_FOR_SCENARIOS]
        # También por lotes: un escenario por caso son tres variantes, y ocho
        # casos en una sola respuesta es exactamente lo que se truncaba.
        async def scenario_batch(chunk):
            payload, error = await caller.json(
                layer5b_scenarios.SYSTEM_PROMPT,
                layer5b_scenarios.USER_PROMPT_TEMPLATE.format(
                    concepts_json=concepts_json,
                    cases_json=json.dumps(
                        [{"id": c["id"], "concept_ids": c.get("concept_ids", []),
                          "description": c.get("description", ""),
                          "dominio": c.get("dominio", ""),
                          "resolucion_esperada": c.get("resolucion_esperada", "")}
                         for c in chunk],
                        ensure_ascii=False,
                    ),
                ),
                "capa5b_escenarios",
            )
            await caller.spaced()
            return (payload or {}).get("scenarios", []), error

        chunks = [subset[i:i + 3] for i in range(0, len(subset), 3)]
        scen_results = await asyncio.gather(*[scenario_batch(c) for c in chunks])
        scenarios = _dedupe_by_id([s for items, _ in scen_results for s in items])
        scen_errors = [e for _, e in scen_results if e]
        status.record(
            "layer5b_scenarios",
            "ok" if scenarios else ("failed" if scen_errors else "empty"),
            len(scenarios),
            f"{len(scen_errors)} lotes con error" if scen_errors else "",
        )
    else:
        status.record("layer5b_scenarios", "skipped", 0,
                      "Ningún caso trae `resolucion_esperada`: sin gold no hay variantes derivables.")
    status.time("layer5b_scenarios", time.monotonic() - t0)
    stats["scenarios"] = len(scenarios)
    stats["truncated_calls"] = caller.truncations

    raw_output = {
        "concepts": concepts,
        "objeto_de_estudio": objeto_de_estudio or None,
        "relations": relations,
        # Aparte de `relations` a propósito: una co-ocurrencia no es una
        # relación del documento, y mezclarlas haría que un consumidor afirme
        # cosas que nadie dijo.
        "cooccurrences": cooccurrences,
        "clusters": clusters,
        "axes": axes,
        "repertoires": repertoires,
        "frameworks": frameworks,
        "theses": theses,
        "cases": cases,
        "scenarios": scenarios,
    }
    return _finalize(raw_output, course_id, filename, stats, status, truncated_any, t_start)


def _dedupe_by_id(items: list[dict]) -> list[dict]:
    seen: set[str] = set()
    out: list[dict] = []
    for item in items:
        key = item.get("id")
        if key and key not in seen:
            seen.add(key)
            out.append(item)
    return out


def _render_groups(groups: list[list[dict]]) -> str:
    lines: list[str] = []
    for i, group in enumerate(groups, 1):
        lines.append(f"GRUPO {i}:")
        for c in group:
            definition = (c.get("definition") or "")[:220]
            lines.append(f"  - id: {c.get('id')} | título: {c.get('title')}")
            lines.append(f"    definición: {definition}")
        lines.append("")
    return "\n".join(lines)


def _finalize(
    raw_output: dict,
    course_id: str,
    filename: str,
    stats: dict,
    status: _Status,
    truncated: bool,
    t_start: float,
) -> dict[str, Any]:
    clean, report = validation.validate_output(raw_output) if raw_output else ({}, {})

    if clean:
        clean["meta"] = _build_meta(clean)
        status.record("layer6_meta", "ok", len(clean["meta"].get("signal_coverage", [])))

    status.time("total", time.monotonic() - t_start)
    stats["timings_seconds"] = status.timings
    try:
        pool = model_pool.get_pool()
        stats["model_pool"] = pool.capacity_summary()
        stats["model_usage"] = pool.stats()
    except Exception:  # noqa: BLE001
        pass

    failed = status.failed_layers()
    clean.update({
        "course_id": course_id,
        "source_filename": filename,
        "extracted_at": datetime.now(timezone.utc).isoformat(),
        "schema_version": "2.1.0",
        "pipeline_stats": stats,
        "layer_status": status.entries,
        "validation_report": report,
        "truncated": truncated,
        "requires_professor_review": True,
        # El alias `arguments` se retiró en v2.2.4: duplicaba `theses` byte a byte
        # —12 KB de los 138 del documento— sin indicar cuál era la fuente de
        # verdad. La página de revisión ya lee `theses`.
        "review_flags": {
            "failed_layers": failed,
            "truncated": truncated,
            "truncated_calls": stats.get("truncated_calls", []),
            "low_confidence_count": clean.get("low_confidence_count", 0),
        },
    })
    # Paquete de juego: la materia prima queda como está —la lee el profesor— y
    # el compilador produce aparte la vista que consume el juego.
    if clean.get("concepts"):
        try:
            clean["game_bundle"] = compiler.compile_bundle(clean)
        except Exception as e:  # noqa: BLE001
            logger.error("[pipeline] La compilación falló: %s", e)
            clean["game_bundle"] = None
            status.record("compiler", "failed", 0, str(e)[:200])
        else:
            gb = clean["game_bundle"]["stats"]
            status.record("compiler", "ok", gb["items_precompilados"],
                          f"{gb['mecanicas_disponibles']}/{gb['mecanicas_totales']} mecánicas")

    logger.info(
        "[pipeline] Completado en %.0fs. Capas fallidas: %s",
        status.timings.get("total", 0), failed or "ninguna",
    )
    return clean


def _build_meta(data: dict) -> dict:
    concept_ids = [c["id"] for c in data.get("concepts", [])]
    relations = data.get("relations", [])

    prereq, unlocks = graph_utils.build_prereq_graphs(concept_ids, relations)
    calidad_secuencia = graph_utils.sequence_quality(prereq, len(concept_ids))
    data = {**data, "_sequence_quality": calidad_secuencia}
    densities = coverage.compute_densities(data)

    diff_dist: dict[str, int] = {"basico": 0, "intermedio": 0, "avanzado": 0}
    for c in data.get("concepts", []):
        key = c.get("difficulty", "intermedio")
        if key in diff_dist:
            diff_dist[key] += 1

    meta = {
        "gateway_concepts": [c["id"] for c in data.get("concepts", []) if c.get("is_gateway")],
        "threshold_concepts": [c["id"] for c in data.get("concepts", []) if c.get("is_threshold")],
        "prerequisite_graph": prereq,
        "unlocks_graph": unlocks,
        "suggested_sequence": graph_utils.topological_sort(prereq),
        "sequence_quality": calidad_secuencia,
        "difficulty_distribution": diff_dist,
        "recommended_modalities": coverage.recommend_modalities(data),
        "signal_coverage": coverage.compute_signal_coverage(data),
        "family_availability": coverage.compute_family_availability(data),
    }
    meta.update(densities)
    return meta
