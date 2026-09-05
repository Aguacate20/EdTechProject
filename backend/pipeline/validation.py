"""
pipeline/validation.py — v2.2.4

Validación y reparación del output del LLM contra el schema.

En v1 los modelos Pydantic de `models/materia_prima.py` no se importaban en
ninguna parte: `run_pipeline` devolvía los dicts crudos del LLM directo al
frontend. El schema existía como documentación, no como contrato. Un valor de
enum alucinado, un `concept_id` inventado o un campo faltante llegaban intactos
hasta la pantalla del profesor.

Criterio de esta capa: **reparar cuando es seguro, descartar cuando no, y
reportar siempre**. Nunca silenciar. El `validation_report` es lo que permite
distinguir un paper pobre de una extracción fallida.
"""
from __future__ import annotations

import re

import logging
from typing import Any

from pydantic import ValidationError

from pipeline.canonicalize import normalize_domain, strip_dangling_refs
from models.materia_prima import (
    Concept,
    ConceptAxis,
    ConceptCluster,
    ConceptRelation,
    CommonRepertoire,
    EvidenceCase,
    Framework,
    GeneratedScenario,
    MateriaPrimaOutput,
    RelationType,
    Thesis,
    TransferDistance,
)

logger = logging.getLogger(__name__)


def _validate_list(raw: list[dict], model, label: str, report: dict) -> list:
    ok, dropped = [], []
    for item in raw or []:
        try:
            ok.append(model(**item))
        except ValidationError as e:
            dropped.append({
                "item_id": item.get("id") if isinstance(item, dict) else None,
                "errors": [f"{'.'.join(str(x) for x in err['loc'])}: {err['msg']}"
                           for err in e.errors()[:3]],
            })
        except TypeError:
            dropped.append({"item_id": None, "errors": ["item no es un objeto"]})
    if dropped:
        report.setdefault("dropped", {})[label] = dropped
        logger.warning("[validation] %s: %d descartados de %d", label, len(dropped), len(raw or []))
    return ok


def _coerce_relation_types(relations: list[dict], report: dict) -> list[dict]:
    """Repara tipos de relación fuera de la tipología en vez de descartar la arista."""
    valid = {t.value for t in RelationType}
    aliases = {
        "causa_efecto": "causa", "produce": "causa", "genera": "causa",
        "ejemplo": "ejemplifica", "ilustra": "ejemplifica",
        "generaliza_a": "generaliza", "abstrae": "generaliza",
        "contrasta_con": "contrasta", "difiere": "contrasta", "se_opone": "contradice",
        "depende": "requiere", "presupone": "requiere",
        "amplia": "extiende", "amplía": "extiende",
        "refina": "matiza", "limita": "matiza",
        "sustenta": "apoya", "respalda": "apoya",
    }
    repaired = 0
    for r in relations:
        t = (r.get("relation_type") or "").strip().lower().replace(" ", "_")
        if t in valid:
            r["relation_type"] = t
            continue
        if t in aliases:
            r["relation_type"] = aliases[t]
            repaired += 1
        else:
            # Tipo fuera de la tipología cerrada. Se aproxima a `apoya` con la
            # confianza al piso: en el bundle 1.1.0 eso lo deja como
            # «insinuado» (nunca «el texto lo dice»), y el tipo original queda
            # a la vista del profesor para que decida.
            r["relation_type_original"] = t
            r["relation_type"] = "apoya"
            r["confidence_extraction"] = min(_num(r.get("confidence_extraction")), 0.3)
            repaired += 1
    if repaired:
        report["relation_types_repaired"] = repaired
    return relations


def _num(v, default: float = 0.6) -> float:
    if isinstance(v, (int, float)):
        return float(v)
    return {"alta": 0.9, "media": 0.6, "baja": 0.3}.get(str(v).lower(), default)


def _prune_references(items: list[dict], field: str, valid_ids: set[str], label: str, report: dict) -> list[dict]:
    """Quita referencias a conceptos inexistentes. Si un item se queda sin
    ninguna referencia válida, se descarta entero."""
    kept, dropped = [], 0
    for item in items or []:
        refs = item.get(field) or []
        if isinstance(refs, str):
            refs = [refs]
        clean = [r for r in refs if r in valid_ids]
        if not clean:
            dropped += 1
            continue
        item[field] = clean
        kept.append(item)
    if dropped:
        report.setdefault("orphaned", {})[label] = dropped
    return kept


def _normalize_domains(cases: list[dict], scenarios: list[dict], report: dict) -> int:
    """Unifica la escritura de los dominios ANTES de comparar distancias.

    Sin esto, "interacción humano‑computadora" (guion no separable) y
    "interacción humano-computadora" (guion normal) cuentan como dominios
    distintos, y toda variante entre ellos se marca como transferencia lejana
    sin serlo.
    """
    formas: dict[str, set[str]] = {}
    for item in list(cases or []) + list(scenarios or []):
        crudo = item.get("dominio")
        if not crudo:
            continue
        canon = normalize_domain(crudo)
        formas.setdefault(canon, set()).add(crudo)
        item["dominio"] = canon
    colisiones = {k: sorted(v) for k, v in formas.items() if len(v) > 1}
    if colisiones:
        report["dominios_unificados"] = colisiones
    return len(colisiones)


def _drop_self_distinctions(concepts: list[dict], report: dict) -> int:
    """Un concepto no se distingue de sí mismo.

    En la corrida medida dos conceptos se listaban a sí mismos con
    `"difference": "N/A"`. Eso llega al generador de distractores como una
    opción incorrecta sin contenido.
    """
    quitadas = 0
    for c in concepts or []:
        distinciones = c.get("distinctions") or []
        limpias = [
            d for d in distinciones
            if d.get("from_concept") and d["from_concept"] != c.get("id")
            and (d.get("difference") or "").strip().lower() not in {"", "n/a", "na", "-"}
        ]
        quitadas += len(distinciones) - len(limpias)
        c["distinctions"] = limpias
    if quitadas:
        report["distinciones_autorreferentes_quitadas"] = quitadas
    return quitadas


def _norm_palabra(w: str) -> str:
    import unicodedata
    w = unicodedata.normalize("NFD", w.lower())
    return "".join(ch for ch in w if unicodedata.category(ch) != "Mn")


def _drop_fragment_synonyms(concepts: list[dict], report: dict) -> int:
    """Un fragmento de un título compuesto no es sinónimo: «sociales» no es
    sinónimo de «Crítica social» ni «cultura» de «Impacto cultural». Si se
    dejan, A3 acepta «cultura» como respuesta a impacto cultural y dos
    conceptos comparten «sociales» como respuesta ambigua. Se quitan los
    sinónimos de UNA palabra cuyo tallo (5 letras) coincide con el de alguna
    palabra del título, solo en títulos de dos o más palabras. Las siglas en
    mayúsculas (ACD, EVI) se conservan siempre."""
    quitados = 0
    for c in concepts or []:
        titulo = (c.get("title") or "").strip()
        palabras_titulo = [_norm_palabra(w) for w in re.findall(r"\w+", titulo)]
        if len(palabras_titulo) < 2:
            continue
        tallos = {w[:5] for w in palabras_titulo if len(w) > 3}
        limpios = []
        for sin in c.get("sinonimos") or []:
            s_ = str(sin).strip()
            partes = re.findall(r"\w+", s_)
            es_sigla = s_.isupper() and len(s_) <= 6
            if len(partes) == 1 and not es_sigla and _norm_palabra(partes[0])[:5] in tallos:
                quitados += 1
                continue
            limpios.append(s_)
        c["sinonimos"] = limpios
    report["synonyms_fragment_dropped"] = quitados
    return quitados


def _fix_distances(scenarios: list[dict], cases_by_id: dict[str, dict], report: dict) -> list[dict]:
    """Recalcula `distancia` en vez de aceptar la declaración del LLM.

    Regla: si el escenario cambia de dominio respecto al caso padre, la
    distancia es `lejana` por definición, diga lo que diga el modelo. Es la
    diferencia entre medir transferencia y medir reconocimiento de superficie.
    """
    corrected = 0
    for s in scenarios or []:
        parent = cases_by_id.get(s.get("parent_case_id") or "")
        if not parent:
            continue
        pdom = normalize_domain(parent.get("dominio") or "")
        sdom = normalize_domain(s.get("dominio") or "")
        declared = (s.get("distancia") or "cercana").strip().lower()
        valid = {d.value for d in TransferDistance}
        if pdom and sdom and pdom != sdom:
            # Cambiar de dominio ES la definición operativa de lejanía.
            expected = TransferDistance.LEJANA.value
        elif pdom and sdom and pdom == sdom:
            # Y no cambiarlo la excluye: los modelos sobredeclaran 'lejana' para
            # escenarios que solo cambian nombres propios y cifras.
            expected = declared if declared in {"cercana", "media"} else TransferDistance.MEDIA.value
        else:
            expected = declared if declared in valid else TransferDistance.MEDIA.value
        if expected != declared:
            s["distancia"] = expected
            corrected += 1
    if corrected:
        report["scenario_distances_corrected"] = corrected
    return scenarios


def validate_output(raw: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Valida el dict crudo del pipeline. Devuelve (output limpio, informe)."""
    report: dict[str, Any] = {}

    _drop_self_distinctions(raw.get("concepts", []), report)
    _drop_fragment_synonyms(raw.get("concepts", []), report)
    _normalize_domains(raw.get("cases", []), raw.get("scenarios", []), report)

    concepts = _validate_list(raw.get("concepts", []), Concept, "concepts", report)
    valid_ids = {c.id for c in concepts}
    report["concepts_valid"] = len(concepts)

    relations_raw = _coerce_relation_types(raw.get("relations", []), report)
    relations_raw = [
        r for r in relations_raw
        if r.get("from_concept_id") in valid_ids and r.get("to_concept_id") in valid_ids
    ]
    relations = _validate_list(relations_raw, ConceptRelation, "relations", report)

    repertoires_raw = [
        r for r in raw.get("repertoires", []) if r.get("concept_id") in valid_ids
    ]
    repertoires = _validate_list(repertoires_raw, CommonRepertoire, "repertoires", report)

    frameworks_raw = raw.get("frameworks", [])
    fw_ids_raw = {f.get("id") for f in frameworks_raw}
    huerfanos = strip_dangling_refs(frameworks_raw, ["rivales"], fw_ids_raw)
    if huerfanos:
        report["rivales_huerfanos_quitados"] = huerfanos
    frameworks = _validate_list(frameworks_raw, Framework, "frameworks", report)
    framework_ids = {f.id for f in frameworks}
    # Segunda pasada: los marcos descartados por validación dejan más huérfanos.
    frameworks_dump = [f.model_dump(mode="json") for f in frameworks]
    strip_dangling_refs(frameworks_dump, ["rivales"], framework_ids)

    theses_raw = _prune_references(raw.get("theses", []), "concept_ids", valid_ids, "theses", report)
    for t in theses_raw:
        if t.get("framework_id") and t["framework_id"] not in framework_ids:
            t["framework_id"] = None
    theses = _validate_list(theses_raw, Thesis, "theses", report)

    cases_raw = _prune_references(raw.get("cases", []), "concept_ids", valid_ids, "cases", report)
    for c in cases_raw:
        if not c.get("primary_concept_id") and c.get("concept_ids"):
            c["primary_concept_id"] = c["concept_ids"][0]
    cases = _validate_list(cases_raw, EvidenceCase, "cases", report)
    cases_by_id = {c.id: c.model_dump(mode="json") for c in cases}

    scenarios_raw = [
        s for s in raw.get("scenarios", []) if s.get("parent_case_id") in cases_by_id
    ]
    scenarios_raw = _fix_distances(scenarios_raw, cases_by_id, report)
    scenarios_raw = _prune_references(scenarios_raw, "concept_ids", valid_ids, "scenarios", report)
    scenarios = _validate_list(scenarios_raw, GeneratedScenario, "scenarios", report)

    clusters = _validate_list(raw.get("clusters", []), ConceptCluster, "clusters", report)
    axes = _validate_list(raw.get("axes", []), ConceptAxis, "axes", report)

    clean = dict(raw)
    clean.update({
        "concepts": [c.model_dump(mode="json") for c in concepts],
        "relations": [r.model_dump(mode="json") for r in relations],
        "repertoires": [r.model_dump(mode="json") for r in repertoires],
        "frameworks": frameworks_dump,
        "theses": [t.model_dump(mode="json") for t in theses],
        "cases": [c.model_dump(mode="json") for c in cases],
        "scenarios": [s.model_dump(mode="json") for s in scenarios],
        "clusters": [c.model_dump(mode="json") for c in clusters],
        "axes": [a.model_dump(mode="json") for a in axes],
    })

    # Umbral de confianza: se cuenta sobre float, no sobre etiqueta.
    # `status: borrador` en todo lo que el profesor debe aprobar. En v2.2.3 solo
    # lo llevaban los repertorios, así que no se podía condicionar la publicación
    # del resto del material a la revisión docente.
    for key in ("concepts", "relations", "frameworks", "theses", "cases", "scenarios", "axes"):
        for item in clean.get(key, []):
            item.setdefault("status", "borrador")

    clean["low_confidence_count"] = sum(
        1 for c in concepts if c.confidence_extraction < 0.5
    ) + sum(
        1 for r in relations if r.confidence_extraction < 0.5
    )

    report["totals"] = {
        "concepts": len(concepts), "relations": len(relations),
        "repertoires": len(repertoires), "frameworks": len(frameworks),
        "theses": len(theses), "cases": len(cases), "scenarios": len(scenarios),
        "clusters": len(clusters), "axes": len(axes),
    }
    return clean, report


def to_model(clean: dict[str, Any]) -> MateriaPrimaOutput | None:
    """Construye el modelo completo. Si falla, se devuelve None y el pipeline
    entrega el dict validado por partes en vez de romper la petición."""
    try:
        return MateriaPrimaOutput(**clean)
    except ValidationError as e:
        logger.error("[validation] MateriaPrimaOutput inválido: %s", e.errors()[:3])
        return None
