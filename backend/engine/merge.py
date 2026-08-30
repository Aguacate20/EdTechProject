"""
engine/merge.py — NUEVO en v2.5

Fusiona los documentos de un estudiante en un plan de estudios único.

## El cambio de modelo

Hasta v2.4 cada PDF era un curso independiente: el estudiante elegía uno y
estudiaba dentro de él. Eso funciona para probar, pero no es lo que pasa en la
realidad — nadie estudia "el PDF 3", estudia un tema que aparece repartido en
varias lecturas.

Ahora hay **un plan por estudiante**. Cada documento que sube se fusiona con lo
que ya tenía: los conceptos que aparecen en dos lecturas se unifican, el grafo
se conecta entre documentos, y el orden de estudio se recalcula sobre el
conjunto.

## Lo difícil no es concatenar, es unificar

Dos documentos sobre el mismo tema van a nombrar el mismo concepto de formas
distintas, y con siglas propias. Si no se unifican, el estudiante ve el mismo
concepto tres veces como si fueran cosas distintas y su perfil se fragmenta en
tres celdas que deberían ser una.

Se reutiliza la canonicalización que ya existe, con una diferencia importante:
**entre documentos se es más conservador que dentro de uno**. Dentro de un
documento, dos apariciones del mismo término casi siempre son el mismo
concepto. Entre documentos no: "función" en un texto de cálculo y en uno de
programación son cosas distintas, y fundirlas destruiría justo la distinción
que hay que enseñar.

Por eso acá solo se unifica con coincidencia estructural fuerte —mismo título
normalizado, o misma sigla con definiciones que se parecen— y nunca por
parecido semántico suelto.

## Qué se conserva de cada documento

La procedencia. Cada concepto del plan sabe de qué documentos viene, y cuando
un concepto aparece en varios, se queda con la definición más completa pero
recuerda todas las fuentes. Eso importa para el estudiante ("esto lo viste en
dos lecturas") y para el profesor que revisa.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from difflib import SequenceMatcher
from typing import Any

from pipeline.canonicalize import _parenthetical, normalize
from pipeline.compiler import compile_bundle

logger = logging.getLogger(__name__)

# Umbral para aceptar que dos definiciones describen lo mismo. Alto a
# propósito: entre documentos, el costo de fundir de más es mayor que el de
# dejar un duplicado, porque fundir borra una distinción que puede ser el
# contenido de una clase entera.
UMBRAL_DEFINICION = 0.62


def _similar(a: str, b: str) -> float:
    na, nb = normalize(a or ""), normalize(b or "")
    if not na or not nb:
        return 0.0
    return SequenceMatcher(None, na, nb).ratio()


def _claves(concepto: dict) -> set[str]:
    """Claves estructurales de un concepto: título, título sin paréntesis, sigla."""
    titulo = concepto.get("titulo") or concepto.get("title") or ""
    base, sigla = _parenthetical(titulo)
    claves = {normalize(titulo)}
    if base:
        claves.add(normalize(base))
    if sigla:
        claves.add(f"@{normalize(sigla)}")
    return {c for c in claves if c and c != "@"}


def _mejor_definicion(a: dict, b: dict) -> dict:
    """Se queda con el concepto mejor documentado, sumando la procedencia."""
    def puntaje(c: dict) -> tuple:
        return (
            1 if c.get("subdimensiones") else 0,
            len(c.get("definicion") or ""),
            float(c.get("importancia") or 0),
        )

    ganador, otro = (a, b) if puntaje(a) >= puntaje(b) else (b, a)
    fusionado = dict(ganador)

    fuentes = list(ganador.get("fuentes") or []) + list(otro.get("fuentes") or [])
    fusionado["fuentes"] = sorted({f for f in fuentes if f})

    # Alias: el nombre que usa el otro documento es un sinónimo legítimo.
    alias = set(fusionado.get("sinonimos") or []) | set(otro.get("sinonimos") or [])
    titulo_otro = (otro.get("titulo") or "").strip()
    if titulo_otro and normalize(titulo_otro) != normalize(fusionado.get("titulo", "")):
        alias.add(titulo_otro)
    fusionado["sinonimos"] = sorted(a for a in alias if a)

    # Lo que uno tiene y el otro no, se suma.
    for campo in ("subdimensiones", "tensiones"):
        if not fusionado.get(campo) and otro.get(campo):
            fusionado[campo] = otro[campo]
    fusionado["carga_cognitiva"] = sorted(
        set(fusionado.get("carga_cognitiva") or []) | set(otro.get("carga_cognitiva") or [])
    )
    fusionado["es_puerta"] = bool(fusionado.get("es_puerta") or otro.get("es_puerta"))
    fusionado["es_umbral"] = bool(fusionado.get("es_umbral") or otro.get("es_umbral"))
    fusionado["importancia"] = max(
        float(fusionado.get("importancia") or 0), float(otro.get("importancia") or 0)
    )
    return fusionado


def fusionar_documentos(documentos: list[dict]) -> dict:
    """Un plan único a partir de la materia prima de varios documentos.

    `documentos` es una lista de {"id", "title", "materia_prima"}.

    El resultado se recompila con el mismo compilador que usa un documento
    solo, así que el plan fusionado tiene exactamente la misma forma: no hay
    dos formatos que mantener, y el motor de sesiones no distingue si estudia
    sobre uno o sobre veinte.
    """
    if not documentos:
        return {}

    if len(documentos) == 1:
        mp = dict(documentos[0]["materia_prima"])
        for c in mp.get("concepts", []):
            c["fuentes"] = [documentos[0]["id"]]
        bundle = compile_bundle(mp)
        bundle["materia_prima"] = mp
        bundle["fuentes"] = [{"id": documentos[0]["id"], "title": documentos[0].get("title")}]
        bundle["diagnostico_documentos"] = [{
            "id": documentos[0]["id"],
            "title": documentos[0].get("title"),
            "conceptos": len(mp.get("concepts", [])),
            "relaciones": len(mp.get("relations", [])),
            "repertorios": len(mp.get("repertoires", [])),
            "casos": len(mp.get("cases", [])),
            "escenarios": len(mp.get("scenarios", [])),
            "tesis": len(mp.get("theses", [])),
            "layer_status": mp.get("layer_status", []),
            "pipeline_stats": {
                k: v for k, v in (mp.get("pipeline_stats") or {}).items()
                if k in ("timings_seconds", "canonicalization", "grounding",
                         "section_coverage", "model_usage", "truncated_calls")
            },
            "validation_report": mp.get("validation_report", {}),
            "review_flags": mp.get("review_flags", {}),
        }]
        for cid, c in bundle.get("concepts", {}).items():
            c["fuentes"] = [documentos[0]["id"]]
            c["n_fuentes"] = 1
        return bundle

    # ── Unificación de conceptos entre documentos ────────────────────────
    canonicos: dict[str, dict] = {}          # id canónico → concepto
    por_clave: dict[str, str] = {}           # clave estructural → id canónico
    alias_a_canonico: dict[tuple[str, str], str] = {}   # (doc, id local) → canónico
    fusiones: list[dict] = []

    for doc in documentos:
        doc_id = doc["id"]
        for c in doc["materia_prima"].get("concepts", []):
            local = dict(c)
            local["fuentes"] = [doc_id]
            local["titulo"] = local.get("title") or local.get("titulo")
            local["definicion"] = local.get("definition") or local.get("definicion")

            claves = _claves(local)
            candidato_id = None
            for k in claves:
                if k in por_clave:
                    candidato_id = por_clave[k]
                    break

            if candidato_id:
                existente = canonicos[candidato_id]
                # Coincidencia por sigla: se exige además que las definiciones
                # se parezcan. Dos escalas distintas pueden compartir sigla.
                por_sigla = any(k.startswith("@") and por_clave.get(k) == candidato_id
                                for k in claves)
                sim = _similar(existente.get("definicion", ""), local.get("definicion", ""))
                if por_sigla and sim < UMBRAL_DEFINICION:
                    candidato_id = None
                    fusiones.append({
                        "tipo": "rechazada",
                        "a": existente.get("titulo"), "b": local.get("titulo"),
                        "motivo": f"comparten sigla pero las definiciones difieren (similitud {sim:.2f})",
                    })

            if candidato_id:
                canonicos[candidato_id] = _mejor_definicion(canonicos[candidato_id], local)
                alias_a_canonico[(doc_id, c["id"])] = candidato_id
                fusiones.append({
                    "tipo": "fusionada",
                    "canonico": candidato_id,
                    "absorbido": c["id"],
                    "documento": doc_id,
                })
            else:
                nuevo_id = c["id"] if c["id"] not in canonicos else f"{c['id']}__{doc_id[:6]}"
                local["id"] = nuevo_id
                canonicos[nuevo_id] = local
                alias_a_canonico[(doc_id, c["id"])] = nuevo_id

            for k in claves:
                por_clave.setdefault(k, alias_a_canonico[(doc_id, c["id"])])

    # ── Reescritura de referencias ────────────────────────────────────────
    def remapear(doc_id: str, cid: str | None) -> str | None:
        if not cid:
            return None
        return alias_a_canonico.get((doc_id, cid), cid)

    relaciones: list[dict] = []
    repertorios: list[dict] = []
    casos: list[dict] = []
    escenarios: list[dict] = []
    tesis: list[dict] = []
    marcos: list[dict] = []

    ids_validos = set(canonicos)

    for doc in documentos:
        d = doc["id"]
        mp = doc["materia_prima"]

        for r in mp.get("relations", []):
            a = remapear(d, r.get("from_concept_id"))
            b = remapear(d, r.get("to_concept_id"))
            if a in ids_validos and b in ids_validos and a != b:
                relaciones.append({**r, "from_concept_id": a, "to_concept_id": b,
                                   "fuente_documento": d})

        for rep in mp.get("repertoires", []):
            cid = remapear(d, rep.get("concept_id"))
            if cid in ids_validos:
                repertorios.append({
                    **rep,
                    "id": f"{rep.get('id')}__{d[:6]}",
                    "concept_id": cid,
                    "concepto_confundido": remapear(d, rep.get("concepto_confundido")),
                    "fuente_documento": d,
                })

        for caso in mp.get("cases", []):
            ids = [remapear(d, x) for x in (caso.get("concept_ids") or [])]
            ids = [x for x in ids if x in ids_validos]
            if ids:
                casos.append({
                    **caso, "id": f"{caso.get('id')}__{d[:6]}",
                    "concept_ids": ids,
                    "primary_concept_id": remapear(d, caso.get("primary_concept_id")) or ids[0],
                    "fuente_documento": d,
                })

        for esc in mp.get("scenarios", []):
            ids = [remapear(d, x) for x in (esc.get("concept_ids") or [])]
            ids = [x for x in ids if x in ids_validos]
            escenarios.append({
                **esc, "id": f"{esc.get('id')}__{d[:6]}",
                "parent_case_id": f"{esc.get('parent_case_id')}__{d[:6]}",
                "concept_ids": ids, "fuente_documento": d,
            })

        for t in mp.get("theses", []):
            ids = [remapear(d, x) for x in (t.get("concept_ids") or [])]
            tesis.append({**t, "id": f"{t.get('id')}__{d[:6]}",
                          "concept_ids": [x for x in ids if x in ids_validos],
                          "framework_id": (f"{t['framework_id']}__{d[:6]}"
                                           if t.get("framework_id") else None),
                          "fuente_documento": d})

        for f in mp.get("frameworks", []):
            marcos.append({**f, "id": f"{f.get('id')}__{d[:6]}",
                           "rivales": [f"{r}__{d[:6]}" for r in (f.get("rivales") or [])],
                           "concept_ids": [remapear(d, x) for x in (f.get("concept_ids") or [])],
                           "fuente_documento": d})

    # Los conceptos vuelven a la forma que espera el compilador.
    conceptos_salida = []
    for cid, c in canonicos.items():
        conceptos_salida.append({
            **c,
            "id": cid,
            "title": c.get("titulo") or c.get("title"),
            "definition": c.get("definicion") or c.get("definition"),
            "distinctions": [
                {**dd, "from_concept": alias_a_canonico.get(
                    (c["fuentes"][0], dd.get("from_concept")), dd.get("from_concept"))}
                for dd in (c.get("distinctions") or [])
            ],
        })

    materia_fusionada = {
        "course_id": "plan_" + (documentos[0]["id"] or "")[:8],
        "source_filename": f"{len(documentos)} documentos",
        "schema_version": "2.4.0",
        "concepts": conceptos_salida,
        "relations": relaciones,
        "clusters": [],          # se recalculan en el compilador
        "axes": [],
        "repertoires": repertorios,
        "frameworks": marcos,
        "theses": tesis,
        "cases": casos,
        "scenarios": escenarios,
    }

    bundle = compile_bundle(materia_fusionada)
    # La materia prima fusionada viaja junto al paquete compilado. Son dos
    # vistas del mismo material y las dos hacen falta: el paquete responde
    # "qué se puede jugar", la materia prima responde "qué dice el documento".
    # La página del plan necesita ambas.
    bundle["materia_prima"] = materia_fusionada
    bundle["fuentes"] = [{"id": d["id"], "title": d.get("title")} for d in documentos]
    # Diagnóstico por documento: de dónde salió cada cosa y qué falló al
    # extraerla. Sin esto, un plan pobre no se puede atribuir a su origen.
    bundle["diagnostico_documentos"] = [{
        "id": d["id"],
        "title": d.get("title"),
        "conceptos": len(d["materia_prima"].get("concepts", [])),
        "relaciones": len(d["materia_prima"].get("relations", [])),
        "repertorios": len(d["materia_prima"].get("repertoires", [])),
        "casos": len(d["materia_prima"].get("cases", [])),
        "escenarios": len(d["materia_prima"].get("scenarios", [])),
        "tesis": len(d["materia_prima"].get("theses", [])),
        "layer_status": d["materia_prima"].get("layer_status", []),
        "pipeline_stats": {
            k: v for k, v in (d["materia_prima"].get("pipeline_stats") or {}).items()
            if k in ("timings_seconds", "canonicalization", "grounding",
                     "section_coverage", "model_usage", "truncated_calls")
        },
        "validation_report": d["materia_prima"].get("validation_report", {}),
        "review_flags": d["materia_prima"].get("review_flags", {}),
    } for d in documentos]
    bundle["fusion"] = {
        "documentos": len(documentos),
        "conceptos_totales": sum(len(d["materia_prima"].get("concepts", [])) for d in documentos),
        "conceptos_unificados": len(canonicos),
        "fusiones": [f for f in fusiones if f["tipo"] == "fusionada"][:50],
        "fusiones_rechazadas": [f for f in fusiones if f["tipo"] == "rechazada"][:20],
    }

    # Cada concepto lleva de qué documentos viene: le sirve al estudiante
    # ("esto apareció en dos lecturas") y al profesor que revisa.
    for cid, c in bundle.get("concepts", {}).items():
        origen = canonicos.get(cid, {})
        c["fuentes"] = origen.get("fuentes") or []
        c["n_fuentes"] = len(c["fuentes"])

    logger.info(
        "[merge] %d documentos → %d conceptos (de %d extraídos)",
        len(documentos), len(canonicos), bundle["fusion"]["conceptos_totales"],
    )
    return bundle
