"""
pipeline/extractor.py
Orquestador del pipeline de extracción de materia prima.
Ejecuta los 6 pasos en secuencia y retorna un MateriaPrimaOutput.

Basado en el flujo definido en 06_materia_prima.md §8.
"""
import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from .llm_client import call_llm
from .segmentation import TextSegment, extract_segments
from .prompts import layer1_concepts, layer2_relations, layer3_repertoires

logger = logging.getLogger(__name__)


async def run_pipeline(
    pdf_bytes: bytes,
    filename: str,
    course_id: str | None = None,
) -> dict[str, Any]:
    """
    Pipeline completo de extracción. Retorna el dict de MateriaPrimaOutput.
    
    Pasos:
    1. Segmentación del PDF
    2. Capa 1: diccionario conceptual
    3. Capa 2: relaciones y clusters
    4. Capa 3: repertorios cotidianos
    5. Capas 4+5: argumentación y casos
    6. Capa 6: meta-pedagógico (algorítmico)
    """
    if not course_id:
        course_id = str(uuid.uuid4())
    
    stats = {}
    logger.info(f"[pipeline] Iniciando extracción para {filename}, course_id={course_id}")

    # ── Paso 1: Segmentación ────────────────────────────────────────────────
    logger.info("[pipeline] Paso 1: Segmentación")
    segments = extract_segments(pdf_bytes)
    stats["segments"] = len(segments)
    stats["total_chars"] = sum(s.char_count for s in segments)
    logger.info(f"[pipeline] {len(segments)} segmentos extraídos")

    # ── Paso 2: Capa 1 — Diccionario conceptual ────────────────────────────
    logger.info("[pipeline] Paso 2: Extracción de conceptos (Capa 1)")
    all_concepts: list[dict] = []
    
    for seg in segments:
        prompt = layer1_concepts.USER_PROMPT_TEMPLATE.format(
            section_title=seg.section_title,
            pages=", ".join(str(p) for p in seg.pages),
            text=seg.text,
        )
        try:
            result = await call_llm(
                system_prompt=layer1_concepts.SYSTEM_PROMPT,
                user_prompt=prompt,
            )
            new_concepts = result.get("concepts", [])
            all_concepts.extend(new_concepts)
            logger.debug(f"[pipeline] Segmento '{seg.section_title}': {len(new_concepts)} conceptos")
        except Exception as e:
            logger.warning(f"[pipeline] Error en segmento '{seg.section_title}': {e}")
        await asyncio.sleep(5)  # ← línea nueva
    
    # Deduplicar por id
    seen_ids: set[str] = set()
    unique_concepts: list[dict] = []
    for c in all_concepts:
        if c.get("id") and c["id"] not in seen_ids:
            seen_ids.add(c["id"])
            unique_concepts.append(c)
    
    stats["concepts_raw"] = len(all_concepts)
    stats["concepts_unique"] = len(unique_concepts)
    logger.info(f"[pipeline] Conceptos únicos: {len(unique_concepts)}")

    # ── Paso 3: Capa 2 — Relaciones ────────────────────────────────────────
    logger.info("[pipeline] Paso 3: Extracción de relaciones (Capa 2)")
    all_relations: list[dict] = []
    all_clusters: list[dict] = []
    
    concepts_json = json.dumps(
        [{"id": c["id"], "title": c.get("title", "")} for c in unique_concepts],
        ensure_ascii=False,
    )
    
    # Procesamos por segmentos para no exceder contexto
    for seg in segments:
        prompt = layer2_relations.USER_PROMPT_TEMPLATE.format(
            text=seg.text,
            concepts_json=concepts_json,
        )
        try:
            result = await call_llm(
                system_prompt=layer2_relations.SYSTEM_PROMPT,
                user_prompt=prompt,
            )
            all_relations.extend(result.get("relations", []))
            all_clusters.extend(result.get("clusters", []))
        except Exception as e:
            logger.warning(f"[pipeline] Error relaciones en '{seg.section_title}': {e}")
        await asyncio.sleep(5)  # ← línea nueva
    
    # Deduplicar relaciones por (from, to, type)
    seen_relations: set[tuple] = set()
    unique_relations: list[dict] = []
    for r in all_relations:
        key = (r.get("from_concept_id"), r.get("to_concept_id"), r.get("relation_type"))
        if all(key) and key not in seen_relations:
            seen_relations.add(key)
            unique_relations.append(r)
    
    stats["relations"] = len(unique_relations)
    logger.info(f"[pipeline] Relaciones únicas: {len(unique_relations)}")

    # ── Paso 4: Capa 3 — Repertorios cotidianos ────────────────────────────
    logger.info("[pipeline] Paso 4: Extracción de repertorios (Capa 3)")
    all_repertoires: list[dict] = []
    
    # Usamos el texto completo (primeros 5 segmentos para no exceder tokens)
    combined_text = "\n\n".join(s.text for s in segments[:5])
    
    prompt = layer3_repertoires.USER_PROMPT_TEMPLATE.format(
        text=combined_text,
        concepts_json=json.dumps(
            [{"id": c["id"], "title": c.get("title", ""), "definition": c.get("definition", "")}
             for c in unique_concepts],
            ensure_ascii=False,
        ),
    )
    try:
        result = await call_llm(
            system_prompt=layer3_repertoires.SYSTEM_PROMPT,
            user_prompt=prompt,
            max_tokens=6000,
        )
        all_repertoires = result.get("repertoires", [])
        stats["repertoires"] = len(all_repertoires)
        logger.info(f"[pipeline] Repertorios extraídos: {len(all_repertoires)}")
    except Exception as e:
        logger.warning(f"[pipeline] Error en repertorios: {e}")

    # ── Paso 5: Capas 4+5 — Argumentación y Casos ─────────────────────────
    # Solo si el documento tiene riqueza suficiente (> 8 conceptos)
    all_arguments: list[dict] = []
    all_cases: list[dict] = []
    
    if len(unique_concepts) > 8:
        logger.info("[pipeline] Paso 5: Extracción de argumentación y casos (Capas 4+5)")
        # TODO: Implementar en la siguiente iteración
        # Por ahora dejamos arrays vacíos — no bloquea el pipeline
        stats["arguments"] = 0
        stats["cases"] = 0
    else:
        logger.info("[pipeline] Paso 5: Omitido (documento con pocos conceptos)")
        stats["arguments"] = 0
        stats["cases"] = 0

    # ── Paso 6: Capa 6 — Meta-pedagógico ──────────────────────────────────
    logger.info("[pipeline] Paso 6: Generación de meta-pedagógico (Capa 6)")
    meta = _build_meta_pedagogical(unique_concepts, unique_relations)

    # ── Contar elementos de baja confianza ────────────────────────────────
    low_conf = sum(
        1 for c in unique_concepts if c.get("confidence_extraction") == "baja"
    ) + sum(
        1 for r in unique_relations if r.get("confidence_extraction") == "baja"
    )

    logger.info(f"[pipeline] Pipeline completado. Elementos baja confianza: {low_conf}")

    return {
        "course_id": course_id,
        "source_filename": filename,
        "extracted_at": datetime.now(timezone.utc).isoformat(),
        "concepts": unique_concepts,
        "relations": unique_relations,
        "clusters": all_clusters,
        "repertoires": all_repertoires,
        "arguments": all_arguments,
        "cases": all_cases,
        "meta": meta,
        "pipeline_stats": stats,
        "low_confidence_count": low_conf,
        "requires_professor_review": True,
    }


def _build_meta_pedagogical(
    concepts: list[dict],
    relations: list[dict],
) -> dict:
    """
    Construye la capa 6 algorítmicamente sobre el grafo de conceptos.
    No usa LLM — solo estructura el grafo ya extraído.
    """
    # Gateway concepts: marcados en Capa 1 o con muchas relaciones salientes de tipo 'requiere'
    gateway_ids = [c["id"] for c in concepts if c.get("is_gateway")]
    threshold_ids = [c["id"] for c in concepts if c.get("is_threshold")]
    
    # Prerequisite graph: aristas de tipo 'requiere'
    prereq_graph: dict[str, list[str]] = {c["id"]: [] for c in concepts}
    for r in relations:
        if r.get("relation_type") == "requiere":
            to_id = r.get("to_concept_id")
            from_id = r.get("from_concept_id")
            if to_id and from_id and to_id in prereq_graph:
                prereq_graph[to_id].append(from_id)
    
    # Suggested sequence: topological sort simple
    suggested_sequence = _topological_sort(prereq_graph)
    
    # Difficulty distribution
    diff_dist: dict[str, int] = {"basico": 0, "intermedio": 0, "avanzado": 0}
    for c in concepts:
        diff = c.get("difficulty", "intermedio")
        diff_dist[diff] = diff_dist.get(diff, 0) + 1
    
    # Densidades (heurísticas simples por ahora)
    total = len(concepts) or 1
    
    return {
        "gateway_concepts": gateway_ids,
        "threshold_concepts": threshold_ids,
        "prerequisite_graph": prereq_graph,
        "suggested_sequence": suggested_sequence,
        "difficulty_distribution": diff_dist,
        "argumentative_richness": 0.0,  # se actualiza cuando Capa 4 esté activa
        "case_density": 0.0,            # se actualiza cuando Capa 5 esté activa
        "recommended_modalities": _recommend_modalities(concepts, relations),
    }


def _topological_sort(graph: dict[str, list[str]]) -> list[str]:
    """Kahn's algorithm para ordenar conceptos respetando prerequisitos."""
    in_degree = {node: 0 for node in graph}
    for deps in graph.values():
        for dep in deps:
            if dep in in_degree:
                in_degree[dep] += 1
    
    queue = [n for n, d in in_degree.items() if d == 0]
    result = []
    
    while queue:
        node = queue.pop(0)
        result.append(node)
        for dep in graph.get(node, []):
            in_degree[dep] -= 1
            if in_degree[dep] == 0:
                queue.append(dep)
    
    return result


def _recommend_modalities(concepts: list[dict], relations: list[dict]) -> list[str]:
    """Recomienda qué dominios habilitar según la riqueza del documento."""
    modalities = ["individual"]  # siempre disponible
    
    # Si hay conceptos con is_threshold, recomendar colaborativo
    has_threshold = any(c.get("is_threshold") for c in concepts)
    if has_threshold:
        modalities.append("colaborativo")
    
    # Si hay relaciones de tipo 'contradice', recomendar colaborativo con debate
    has_contradictions = any(r.get("relation_type") == "contradice" for r in relations)
    if has_contradictions:
        modalities.append("debate")
    
    return modalities
