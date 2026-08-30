"""
pipeline/compiler.py — v3.5

Compilador de materia prima a paquete de juego.

## Por qué existe

La materia prima está organizada por etapa del pipeline, con procedencia y
confianza en cada pieza, porque su consumidor es un profesor que revisa. El
juego necesita lo contrario: registros indexados por id, adyacencia
precalculada, pools de distractores ya armados, y un veredicto de qué se puede
instanciar con este material.

Forzar un solo documento a servir a los dos hace más difícil el trabajo del
extractor y apenas más fácil el del juego. Un compilador entre ambos resuelve
el desajuste y —esto es lo importante— es el único sitio donde cada defecto se
detecta, se repara o se reporta UNA vez, en lugar de defenderse en cincuenta
puntos del código del juego.

## Qué produce

  · `concepts` indexado por id, con dificultad efectiva y unidad asignada
  · `graph` con adyacencia precalculada y aristas agrupadas por tipo
  · `study_plan` con unidades, orden y curva de dificultad
  · `distractor_pools` por concepto, ya caracterizados con su repertorio
  · `items` precompilados para las mecánicas que los necesitan
  · `mechanics` con veredicto por mecánica y sus targets disponibles
  · `readiness` por dimensión del perfil

## Principio de diseño

**El compilador rechaza, no solo repara.** Un marco sin rivales válidos no sale
con la lista vacía: sale marcado como no apto para F3, con el motivo. Si el
juego recibe algo, puede confiar en que sirve para lo que dice servir.
"""
from __future__ import annotations

import hashlib
import logging
from collections import defaultdict
from difflib import SequenceMatcher
from typing import Any

from .grounding import normalizar  # noqa: F401

from .registry import FAMILIAS, REGISTRY, REQUISITO_LABEL

logger = logging.getLogger(__name__)

BUNDLE_VERSION = "1.0.0"

DIFICULTAD_NUM = {"basico": 1, "intermedio": 2, "avanzado": 3}

# Qué familia de mecánicas ataca cada tipo de carga cognitiva.
#
# Es la traducción operativa de "por qué cuesta" a "qué hacer al respecto".
# Antes el sistema sabía que un concepto era difícil pero no qué ejercicio
# correspondía: un concepto que cuesta porque hay mucho que retener y otro que
# cuesta porque se confunde con su vecino recibían el mismo tratamiento.
CARGA_A_FAMILIAS = {
    "memorizar":   ["A"],
    "discriminar": ["B", "C"],
    "integrar":    ["C", "D"],
    "inferir":     ["E", "F"],
}

# Tipos de relación que implican un orden natural de estudio (A antes que B).
# `requiere` es la restricción dura; el resto son preferencias que desempatan.
ORDEN_DURO = {"requiere"}
# El signo indica a quién empuja hacia adelante en el orden: positivo adelanta
# al destino de la relación, negativo adelanta al origen.
#
# Ojo con la coherencia entre estos dos, que en la primera versión quedaron
# invertidos entre sí: `A ejemplifica B` significa que A es un caso de B, así
# que B va primero; `A generaliza B` significa que A es la abstracción, así que
# A va primero. Los dos apuntan a lo mismo —el concepto general antes que su
# instancia— y por eso llevan signos opuestos.
# Convención: peso NEGATIVO adelanta al origen (A), peso POSITIVO adelanta al
# destino (B). Se lee siempre como "A <tipo> B".
ORDEN_BLANDO = {
    "causa": -1.0,        # A causa B  → la causa antes que el efecto
    "generaliza": -1.0,   # A generaliza B → la abstracción antes que su caso
    "ejemplifica": 1.0,   # A ejemplifica B → el concepto antes que su ejemplo
    "extiende": 1.0,      # A extiende B → lo básico antes que su extensión
    "apoya": 0.2,
}


# Un distractor que dice casi lo mismo que la respuesta correcta convierte el
# ítem en una trampa: el estudiante que domina el tema elige mal porque las dos
# opciones SON correctas. Medido en la corrida real con los pares de conceptos
# duplicados (los dos RAF, los tres IRM, los dos PCCI).
SIMILITUD_MAXIMA_DISTRACTOR = 0.72

# Proporción objetivo de afirmaciones VERDADERAS en los ítems de discriminación.
#
# Es el arreglo más urgente del catálogo. Con los 29 ítems B1 pidiendo lo mismo
# —"¿esta afirmación describe el concepto?" con respuesta siempre falsa— un
# jugador que responda "no" sin leer gana el 100% de esos encuentros. No es un
# problema de dificultad: es que la mecánica no mide nada.
#
# Con polaridad mixta la heurística fija baja a ~50%, que es lo que debe dar
# el azar, y el ítem vuelve a exigir leer.
PROPORCION_B1_VERDADEROS = 0.5

# Peso de una carta de relación según lo rara que sea EN ESTE bundle.
#
# En el material real `apoya` se lleva el 31% de las aristas y `ejemplifica` el
# 4%. Tratarlas igual hace que una condición del tipo "gana solo con relaciones
# de tipo X" sea un paseo con la primera e imposible con la segunda. El valor
# tiene que calcularse contra la distribución del propio documento, no contra
# una tabla fija.
def _rareza_relaciones(relations: list[dict]) -> dict[str, float]:
    total = max(len(relations), 1)
    frecuencia: dict[str, int] = defaultdict(int)
    for r in relations:
        frecuencia[(r.get("relation_type") or "").lower()] += 1
    return {
        tipo: round(min(3.0, (total / max(n, 1)) / len(frecuencia or {1: 1})), 2)
        for tipo, n in frecuencia.items()
    }


def _similitud(a: str, b: str) -> float:
    """Parecido entre dos textos, sobre forma normalizada."""
    na, nb = normalizar(a), normalizar(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    return SequenceMatcher(None, na, nb).ratio()


def _distractores_seguros(
    correcta: str,
    pool: list[dict],
    limite: int,
    descartes: list[dict],
    item_ref: str,
) -> list[dict]:
    """Filtra el pool quitando lo que se parece demasiado a la respuesta correcta.

    Es la aplicación concreta del principio de rechazar en vez de reparar: si
    un distractor no se puede distinguir de la respuesta, el ítem no se emite
    con ese distractor, y si se queda sin ninguno, no se emite el ítem.
    """
    seguros = []
    for d in sorted(pool, key=lambda x: -x["plausibilidad"]):
        sim = _similitud(correcta, d.get("texto", ""))
        if sim >= SIMILITUD_MAXIMA_DISTRACTOR:
            descartes.append({
                "item": item_ref,
                "distractor": d.get("etiqueta"),
                "motivo": f"indistinguible de la respuesta correcta (similitud {sim:.2f})",
            })
            continue
        seguros.append(d)
        if len(seguros) >= limite:
            break
    return seguros


def _hash_id(prefijo: str, *partes: str) -> str:
    crudo = "|".join(str(p) for p in partes)
    return f"{prefijo}_{hashlib.sha1(crudo.encode('utf-8')).hexdigest()[:10]}"


# ─────────────────────────────────────────────
# Plan de estudio
# ─────────────────────────────────────────────

def _build_order(concepts: list[dict], relations: list[dict]) -> tuple[list[str], dict]:
    """Orden de estudio a partir de varias señales, no solo de `requiere`.

    El defecto que resuelve: usando solo relaciones `requiere`, un paper típico
    produce dos o tres aristas sobre veinte conceptos, la cola inicial del orden
    topológico contiene todo, y la salida termina siendo alfabética. Parecía un
    plan y era el abecedario.

    Aquí las restricciones duras siguen siendo `requiere`, pero el desempate usa
    señales reales del material: si es concepto puerta, su dificultad declarada,
    su importancia, el tipo de las relaciones que lo tocan, y en qué página del
    documento aparece por primera vez. El resultado es un orden defendible
    aunque el grafo de prerrequisitos esté casi vacío.
    """
    ids = [c["id"] for c in concepts]
    by_id = {c["id"]: c for c in concepts}
    pos = {cid: i for i, cid in enumerate(ids)}

    duras: dict[str, set[str]] = {cid: set() for cid in ids}
    puntaje_blando: dict[str, float] = {cid: 0.0 for cid in ids}

    for r in relations:
        a, b = r.get("from_concept_id"), r.get("to_concept_id")
        if a not in duras or b not in duras:
            continue
        tipo = (r.get("relation_type") or "").lower()
        if tipo in ORDEN_DURO:
            duras[a].add(b)          # A requiere B → B antes que A
        elif tipo in ORDEN_BLANDO:
            # Puntaje alto = va antes (la prioridad usa -puntaje).
            peso = ORDEN_BLANDO[tipo]
            puntaje_blando[a] -= peso
            puntaje_blando[b] += peso

    def prioridad(cid: str) -> tuple:
        c = by_id[cid]
        pagina = min(c.get("source_pages") or [99])
        # El orden de los criterios importa. Las relaciones semánticas del
        # documento van ANTES que la dificultad declarada: que un concepto sea
        # la teoría general de la que otro es un caso es una señal más fina que
        # una etiqueta de tres niveles. Con la precedencia al revés, la etiqueta
        # `basico` adelantaba una aplicación por encima de la teoría que la
        # explica.
        return (
            0 if c.get("is_gateway") else 1,
            -puntaje_blando[cid],
            DIFICULTAD_NUM.get(c.get("difficulty"), 2),
            -float(c.get("importance") or 0),
            pagina,
            pos[cid],
        )

    pendientes = set(ids)
    resueltos: set[str] = set()
    orden: list[str] = []

    while pendientes:
        disponibles = [c for c in pendientes if duras[c] <= resueltos]
        if not disponibles:
            # Ciclo en los prerrequisitos: se rompe por prioridad y se registra.
            disponibles = list(pendientes)
        elegido = min(disponibles, key=prioridad)
        orden.append(elegido)
        resueltos.add(elegido)
        pendientes.discard(elegido)

    aristas_duras = sum(len(v) for v in duras.values())
    aristas_blandas = sum(
        1 for r in relations if (r.get("relation_type") or "").lower() in ORDEN_BLANDO
    )
    senales = sum([
        1 if aristas_duras else 0,
        1 if aristas_blandas else 0,
        1 if any(c.get("is_gateway") for c in concepts) else 0,
        1 if len({c.get("difficulty") for c in concepts}) > 1 else 0,
        1 if any(c.get("source_pages") for c in concepts) else 0,
    ])
    calidad = {
        "senales_usadas": senales,
        "aristas_prerequisito": aristas_duras,
        "aristas_orientativas": aristas_blandas,
        "nivel": "buena" if senales >= 4 else ("parcial" if senales >= 2 else "debil"),
    }
    if calidad["nivel"] != "buena":
        calidad["motivo"] = (
            "El documento aporta pocas señales de orden (prerrequisitos, causalidad, "
            "conceptos puerta, niveles de dificultad). El orden es orientativo."
        )
    return orden, calidad


def _build_units(orden: list[str], by_id: dict[str, dict],
                 clusters: list[dict], target: int = 5) -> list[dict]:
    """Agrupa el orden en unidades jugables, respetando los grupos temáticos.

    Se corta al llegar al tamaño objetivo, pero se prefiere cortar donde cambia
    el cluster: partir un grupo temático a la mitad produce una unidad que no se
    puede nombrar.
    """
    cluster_de: dict[str, str] = {}
    for cl in clusters or []:
        for cid in cl.get("concept_ids", []):
            cluster_de.setdefault(cid, cl.get("id"))

    unidades: list[dict] = []
    actual: list[str] = []

    def cerrar():
        if not actual:
            return
        dificultades = [DIFICULTAD_NUM.get(by_id[c].get("difficulty"), 2) for c in actual]
        etiquetas = [by_id[c].get("title", c) for c in actual]
        unidades.append({
            "id": f"unidad_{len(unidades) + 1}",
            "numero": len(unidades) + 1,
            "titulo": etiquetas[0] if len(actual) == 1 else f"{etiquetas[0]} y {len(actual) - 1} más",
            "concept_ids": list(actual),
            "dificultad_media": round(sum(dificultades) / len(dificultades), 2),
            "tiene_puerta": any(by_id[c].get("is_gateway") for c in actual),
            "tiene_umbral": any(by_id[c].get("is_threshold") for c in actual),
        })
        actual.clear()

    for cid in orden:
        if actual and len(actual) >= target:
            cambio_de_grupo = cluster_de.get(cid) != cluster_de.get(actual[-1])
            if cambio_de_grupo or len(actual) >= target + 2:
                cerrar()
        actual.append(cid)
    cerrar()
    return unidades


def _difficulty_curve(unidades: list[dict], by_id: dict[str, dict]) -> list[dict]:
    """Dificultad objetivo por unidad, sin depender de aprobación docente.

    Combina la dificultad declarada de los conceptos con la posición en el plan:
    la misma unidad al principio del curso se juega más fácil que al final,
    porque el estudiante llega con menos base.
    """
    total = max(len(unidades), 1)
    curva = []
    for i, u in enumerate(unidades):
        avance = i / total
        base = (u["dificultad_media"] - 1) / 2            # 0..1
        objetivo = round(min(1.0, 0.35 + 0.4 * base + 0.35 * avance), 2)
        curva.append({
            "unidad_id": u["id"],
            "dificultad_objetivo": objetivo,
            "n_opciones_sugerido": 3 if objetivo < 0.5 else (4 if objetivo < 0.75 else 5),
            "andamiaje_sugerido": (
                "alto" if objetivo < 0.45 else ("medio" if objetivo < 0.7 else "bajo")
            ),
        })
    return curva


# ─────────────────────────────────────────────
# Distractores
# ─────────────────────────────────────────────

def _build_distractors(concepts: list[dict], repertoires: list[dict],
                       relations: list[dict]) -> tuple[dict, dict]:
    """Pool de distractores por concepto, precompilado y caracterizado.

    Es la pieza que faltaba entre la materia prima y el juego. `distinctions`,
    `concepto_confundido` y los repertorios son el insumo, pero nadie los
    convertía en opciones incorrectas utilizables. Sin esto, A1 y B1 tienen que
    fabricar cada ítem en tiempo de juego.

    Cada distractor lleva de dónde salió, porque de eso depende la señal: un
    distractor con `repertoire_id` permite emitir anclaje cuando el estudiante
    lo elige; uno con `concepto_confundido` permite emitir relación sobre la
    arista. Un distractor sin caracterizar solo dice "se equivocó".
    """
    by_id = {c["id"]: c for c in concepts}
    reps_por_concepto: dict[str, list[dict]] = defaultdict(list)
    for r in repertoires or []:
        if r.get("concept_id") in by_id:
            reps_por_concepto[r["concept_id"]].append(r)

    vecinos: dict[str, set[str]] = defaultdict(set)
    for r in relations or []:
        a, b = r.get("from_concept_id"), r.get("to_concept_id")
        if a in by_id and b in by_id:
            vecinos[a].add(b)
            vecinos[b].add(a)

    pools: dict[str, list[dict]] = {}
    stats = {"caracterizados": 0, "por_vecindad": 0, "conceptos_sin_pool": 0}

    for c in concepts:
        cid = c["id"]
        pool: list[dict] = []
        vistos: set[str] = set()

        # 1. Distinciones explícitas: el mejor distractor posible, porque el
        #    documento dice exactamente en qué se diferencian.
        for d in c.get("distinctions") or []:
            otro = d.get("from_concept")
            if otro not in by_id or otro == cid or otro in vistos:
                continue
            vistos.add(otro)
            pool.append({
                "id": _hash_id("dist", cid, otro),
                "texto": by_id[otro].get("definition", ""),
                "etiqueta": by_id[otro].get("title", otro),
                "fuente": "distincion",
                "concepto_confundido": otro,
                "repertoire_id": None,
                "explicacion": d.get("difference", ""),
                "plausibilidad": 0.9,
            })
            stats["caracterizados"] += 1

        # 2. Repertorios cotidianos: el distractor que el estudiante ya cree.
        for r in reps_por_concepto.get(cid, []):
            pool.append({
                "id": _hash_id("rep", cid, r.get("id", "")),
                "texto": r.get("example") or r.get("description", ""),
                "etiqueta": r.get("label", ""),
                "fuente": "repertorio",
                "concepto_confundido": r.get("concepto_confundido"),
                "repertoire_id": r.get("id"),
                "explicacion": r.get("contraste_cientifico", ""),
                "contexto_donde_funciona": r.get("contexto_donde_funciona", ""),
                "plausibilidad": 0.95,
            })
            stats["caracterizados"] += 1

        # 3. Vecinos del grafo: sin explicación de la diferencia, así que valen
        #    menos y se marcan como tales.
        for otro in sorted(vecinos.get(cid, set())):
            if otro in vistos or len(pool) >= 6:
                continue
            vistos.add(otro)
            # Los distractores por vecindad no traen explicación de la
            # diferencia, y sin ella la promesa de devolver respeto en el fallo
            # —"por qué era razonable y qué criterio la distingue"— solo se
            # puede cumplir en una fracción de los casos.
            #
            # No se puede inventar la diferencia conceptual, pero sí se puede
            # construir un respaldo honesto desde el grafo: nombrar el otro
            # concepto, dar su definición y, si hay arista, decir cómo se
            # relacionan. Es menos que una distinción explícita y mucho más que
            # el silencio.
            arista = next(
                (rr for rr in (relations or [])
                 if {rr.get("from_concept_id"), rr.get("to_concept_id")} == {cid, otro}),
                None,
            )
            if arista:
                respaldo = (
                    f"«{by_id[otro].get('title', otro)}» está relacionado "
                    f"({arista.get('relation_type')}) pero no es lo mismo: "
                    f"{by_id[otro].get('definition','')[:180]}"
                )
            else:
                respaldo = (
                    f"«{by_id[otro].get('title', otro)}» es un concepto vecino del "
                    f"mismo tema: {by_id[otro].get('definition','')[:180]}"
                )
            pool.append({
                "id": _hash_id("vec", cid, otro),
                "texto": by_id[otro].get("definition", ""),
                "etiqueta": by_id[otro].get("title", otro),
                "fuente": "vecino_grafo",
                "concepto_confundido": otro,
                "repertoire_id": None,
                "explicacion": respaldo,
                "explicacion_derivada": True,
                "plausibilidad": 0.6,
            })
            stats["por_vecindad"] += 1

        if pool:
            pools[cid] = pool
        else:
            stats["conceptos_sin_pool"] += 1

    # n_efectivo: un ítem de cuatro opciones con tres distractores absurdos
    # tiene el azar de uno de dos. Se guarda para que el peso evidencial no
    # salga optimista.
    for cid, pool in pools.items():
        efectivo = 1 + sum(d["plausibilidad"] for d in pool)
        stats.setdefault("n_efectivo", {})[cid] = round(efectivo, 2)

    return pools, stats


# ─────────────────────────────────────────────
# Ítems precompilados
# ─────────────────────────────────────────────

def _build_items(concepts: list[dict], pools: dict, relations: list[dict],
                 cases: list[dict], scenarios: list[dict],
                 curva_por_concepto: dict[str, dict]) -> dict[str, list[dict]]:
    """Ítems listos para jugar, sin llamadas a un LLM en tiempo de juego.

    Se precompila solo lo determinista: opción múltiple, emparejamiento,
    clasificación. Lo que exige juicio abierto (familias F, E2, E4, E5) queda
    como plantilla con su gold, porque necesita un juez en runtime.
    """
    by_id = {c["id"]: c for c in concepts}
    items: dict[str, list[dict]] = defaultdict(list)

    # ── A1 RECONOCER y B1 DISTINGUIR ──────────────────────────────────────
    descartes: list[dict] = []

    for c in concepts:
        pool = pools.get(c["id"]) or []
        if not pool:
            continue
        cfg = curva_por_concepto.get(c["id"], {})
        n_opciones = cfg.get("n_opciones_sugerido", 4)
        correcta_txt = c.get("definition", "")
        elegidos = _distractores_seguros(
            correcta_txt, pool, n_opciones - 1, descartes, f"A1/{c['id']}"
        )
        if len(elegidos) < 2:
            # Con un solo distractor el ítem es una moneda al aire, y con cero
            # no hay ítem. Mejor no emitirlo que emitir uno que no discrimina.
            descartes.append({
                "item": f"A1/{c['id']}",
                "motivo": f"solo quedaron {len(elegidos)} distractores utilizables",
            })
            continue

        # El id de la opción correcta ya no es la palabra "correcta": era un
        # exploit de un clic, porque el identificador viajaba al cliente. Ahora
        # todos los ids son hashes indistinguibles entre sí.
        items["A1"].append({
            "id": _hash_id("A1", c["id"]),
            "mechanic_id": "A1",
            "concept_id": c["id"],
            "enunciado": f"¿Cuál corresponde a «{c.get('title','')}»?",
            "opciones": [
                {"id": _hash_id("opt", c["id"], "ok"),
                 "texto": c.get("definition", ""), "es_correcta": True}
            ] + [
                {"id": d["id"], "texto": d["texto"], "es_correcta": False,
                 "repertoire_id": d.get("repertoire_id"),
                 "concepto_confundido": d.get("concepto_confundido"),
                 "feedback": d.get("explicacion", ""),
                 "contexto_donde_funciona": d.get("contexto_donde_funciona", "")}
                for d in elegidos
            ],
            "n_efectivo": round(1 + sum(d["plausibilidad"] for d in elegidos), 2),
            "dificultad": cfg.get("dificultad_objetivo", 0.5),
        })

        # ── B1 DISTINGUIR con polaridad mixta ─────────────────────────────
        # La mitad de los ítems afirman algo FALSO (un distractor) y la otra
        # mitad algo VERDADERO (la definición real, o una faceta del concepto).
        # Sin esta mezcla, responder siempre "no" gana sin leer.
        finos = [
            d for d in pool
            if d["fuente"] in {"distincion", "repertorio"}
            and _similitud(correcta_txt, d.get("texto", "")) < SIMILITUD_MAXIMA_DISTRACTOR
        ]

        # Afirmaciones verdaderas: la definición, y cada faceta si las hay.
        verdaderas: list[dict] = []
        if correcta_txt:
            verdaderas.append({"texto": correcta_txt, "origen": "definicion"})
        for s in (c.get("subdimensions") or [])[:2]:
            desc = (s.get("description") or "").strip()
            if len(desc) > 30:
                verdaderas.append({
                    "texto": f"{s.get('name','')}: {desc}",
                    "origen": "faceta",
                })

        # Se alternan para que ni el orden ni la posición delaten la respuesta.
        n_falsas = min(2, len(finos))
        n_verdaderas = min(len(verdaderas), max(1, n_falsas)) if verdaderas else 0
        mezcla: list[tuple[bool, dict]] = []
        for i in range(max(n_falsas, n_verdaderas)):
            if i < n_falsas:
                mezcla.append((False, finos[i]))
            if i < n_verdaderas:
                mezcla.append((True, verdaderas[i]))

        for es_verdadera, fuente in mezcla:
            if es_verdadera:
                items["B1"].append({
                    "id": _hash_id("B1v", c["id"], fuente["origen"], fuente["texto"][:40]),
                    "mechanic_id": "B1",
                    "concept_id": c["id"],
                    "enunciado": f"¿Esta afirmación describe «{c.get('title','')}»?",
                    "afirmacion": fuente["texto"],
                    "respuesta_correcta": True,
                    "polaridad": "verdadera",
                    "origen_afirmacion": fuente["origen"],
                    "feedback": "",
                    "n_efectivo": 2.0,
                    "dificultad": cfg.get("dificultad_objetivo", 0.5),
                })
            else:
                d = fuente
                items["B1"].append({
                    "id": _hash_id("B1", c["id"], d["id"]),
                    "mechanic_id": "B1",
                    "concept_id": c["id"],
                    "enunciado": f"¿Esta afirmación describe «{c.get('title','')}»?",
                    "afirmacion": d["texto"],
                    "respuesta_correcta": False,
                    "polaridad": "falsa",
                    "repertoire_id": d.get("repertoire_id"),
                    "concepto_confundido": d.get("concepto_confundido"),
                    "feedback": d.get("explicacion", ""),
                    "n_efectivo": 2.0,
                    "dificultad": cfg.get("dificultad_objetivo", 0.5),
                })

    # ── A3 EVOCAR: necesita sinónimos para poder calificar ────────────────
    #
    # Y necesita que las respuestas aceptadas sean EXCLUSIVAS de un concepto.
    # En el material real tres ítems A3 distintos aceptaban "EDS" como válida:
    # el jugador escribía la respuesta correcta para uno de ellos y el sistema
    # la marcaba como error en los otros dos. Un acierto contado como fallo es
    # peor que una pregunta mal formulada.
    reclamos: dict[str, list[str]] = defaultdict(list)
    for c in concepts:
        for a in [c.get("title", "")] + list(c.get("sinonimos") or []) + \
                 list(c.get("variantes_terminologicas") or []):
            if a:
                reclamos[normalizar(a)].append(c["id"])
    ambiguas = {k for k, v in reclamos.items() if len(set(v)) > 1}

    for c in concepts:
        todas = [c.get("title", "")] + list(c.get("sinonimos") or []) + \
                list(c.get("variantes_terminologicas") or [])
        todas = [a for a in todas if a]
        aceptadas = [a for a in todas if normalizar(a) not in ambiguas]
        perdidas = [a for a in todas if normalizar(a) in ambiguas]

        # Basta UNA forma exclusiva. El umbral estaba en dos, para que la
        # calificación no fuera frágil, y descartaba conceptos perfectamente
        # evaluables: un concepto sin sinónimos tiene solo su título, y con el
        # título alcanza para pedir evocación. La tolerancia se resuelve en la
        # calificación —comparación normalizada y coincidencia parcial— no
        # exigiendo que el documento aporte alias que puede no tener.
        #
        # Lo que sí se exige es que el título tenga cuerpo: un título de tres
        # letras es adivinable y no mide recuperación.
        exclusivas = [a for a in aceptadas if len(normalizar(a)) >= 4]
        if not exclusivas:
            # El motivo se calcula POR CONCEPTO. Antes se elegía según si había
            # alguna colisión en todo el documento, así que en cuanto existía
            # una, los cuatro descartes por otra razón salían con ese mensaje.
            motivo = (
                f"su única forma aceptada la reclama otro concepto ({', '.join(perdidas[:2])})"
                if perdidas else
                "sin una forma aceptada con cuerpo suficiente para pedir evocación"
            )
            descartes.append({"item": f"A3/{c['id']}", "motivo": motivo})
            continue
        aceptadas = exclusivas
        items["A3"].append({
            "id": _hash_id("A3", c["id"]),
            "mechanic_id": "A3",
            "concept_id": c["id"],
            "enunciado": f"¿Qué concepto se define así? «{(c.get('definition') or '')[:200]}»",
            "respuestas_aceptadas": sorted(set(aceptadas)),
            # Las formas que otro concepto también reclama viajan aparte: no se
            # aceptan como correctas —sería ambiguo— pero permiten responder
            # "eso también describe a X, precisá cuál" en vez de un error seco.
            "respuestas_ambiguas": sorted(set(perdidas)),
            "dificultad": curva_por_concepto.get(c["id"], {}).get("dificultad_objetivo", 0.5),
        })

    # ── C1 CONECTAR: el tipo de relación entre dos conceptos ──────────────
    tipos_presentes = sorted({(r.get("relation_type") or "").lower()
                              for r in relations if r.get("relation_type")})
    # Si un par tiene aristas en las dos direcciones con tipos distintos, la
    # pregunta "¿qué relación va de A a B?" no tiene una única respuesta
    # correcta. En la corrida real pasó con PCCI y su duplicado.
    tipos_por_par: dict[frozenset, set[str]] = defaultdict(set)
    for r in relations or []:
        a, b = r.get("from_concept_id"), r.get("to_concept_id")
        if a and b:
            tipos_por_par[frozenset((a, b))].add((r.get("relation_type") or "").lower())

    # Regla de dominancia para pares con dos tipos.
    #
    # Descartar el par entero costaba el 31% de los ítems de C1, que es la
    # mecánica con más material del catálogo. Pero varios de esos "conflictos"
    # no son contradicciones: son relaciones asimétricas legítimas. Que A
    # requiera a B y B ejemplifique a A no es incoherente, son dos hechos
    # distintos sobre el mismo par.
    #
    # Solo se descarta cuando los dos tipos son genuinamente incompatibles
    # —afirmar que A apoya a B y que A contradice a B no puede ser cierto a la
    # vez— o cuando la dirección importa y no se puede resolver. En el resto se
    # conserva el tipo más informativo, que es el más raro en este documento.
    rareza = _rareza_relaciones(relations or [])

    # Un par con varios tipos genera UN ítem con VARIAS respuestas correctas.
    #
    # La versión anterior elegía el tipo "dominante" —el más raro— y descartaba
    # el resto. Eso era el compilador decidiendo cuál de dos vínculos ciertos es
    # el verdadero, una decisión que no le corresponde: si el documento dice que
    # A extiende a B y también que lo requiere, las dos respuestas son correctas
    # y el estudiante que elija cualquiera acertó.
    #
    # Los incompatibles ya se resolvieron en `dedupe_relations`, así que lo que
    # llega acá son tipos que pueden coexistir.
    resueltos: set[frozenset] = set()
    for r in relations or []:
        a, b = r.get("from_concept_id"), r.get("to_concept_id")
        if a not in by_id or b not in by_id:
            continue
        par = frozenset((a, b))
        if par in resueltos:
            continue
        resueltos.add(par)
        tipos = sorted(tipos_por_par[par])
        items["C1"].append({
            "id": _hash_id("C1", a, b),
            "mechanic_id": "C1",
            "par": [a, b],
            "enunciado": f"¿Qué relación va de «{by_id[a].get('title','')}» a «{by_id[b].get('title','')}»?",
            "opciones": tipos_presentes,
            "respuesta_correcta": (r.get("relation_type") or "").lower(),
            # Todas las respuestas correctas del par, no solo una.
            "respuestas_correctas": tipos,
            "n_efectivo": max(2, len(tipos_presentes) / max(len(tipos), 1)),
            # La confianza de la relación viaja al ítem: el juego puede tratar
            # una arista inferida como aproximada en vez de exigirla igual que
            # una que el documento afirma.
            "confianza": round(float(r.get("confidence_extraction") or 0.6), 2),
            "explicacion": (
                r.get("description", "")
                if not r.get("descripcion_incompleta")
                else f"El texto vincula «{by_id[a].get('title','')}» y "
                     f"«{by_id[b].get('title','')}» con una relación de tipo "
                     f"{', '.join(tipos)}."
            ),
            "descripcion_original_incompleta": bool(r.get("descripcion_incompleta")),
            # El valor de la carta sale de lo rara que es la relación en ESTE
            # documento, no de una tabla fija: `apoya` con el 31% de las aristas
            # no puede valer lo mismo que `ejemplifica` con el 4%.
            "rareza": round(
                max(rareza.get(x, 1.0) for x in tipos) if tipos else 1.0, 2),
            "dificultad": curva_por_concepto.get(a, {}).get("dificultad_objetivo", 0.5),
        })

    # ── B2 CLASIFICAR: caso → concepto que aplica ─────────────────────────
    # Los rellenos de B2 se eligen por cercanía en el grafo y rotando, no
    # tomando los tres primeros del diccionario. Con la versión anterior los 14
    # ítems compartían exactamente los mismos tres distractores: el estudiante
    # aprendía en cinco intentos que esos nunca son la respuesta, y el
    # `n_efectivo` declarado era falso.
    vecinos_de: dict[str, list[str]] = defaultdict(list)
    for r in relations or []:
        a, b = r.get("from_concept_id"), r.get("to_concept_id")
        if a in by_id and b in by_id:
            vecinos_de[a].append(b)
            vecinos_de[b].append(a)
    usos: dict[str, int] = defaultdict(int)

    for caso in cases or []:
        principal = caso.get("primary_concept_id") or (caso.get("concept_ids") or [None])[0]
        if principal not in by_id:
            continue
        candidatos = [c for c in dict.fromkeys(vecinos_de.get(principal, [])) if c != principal]
        resto = [c for c in by_id if c != principal and c not in candidatos]
        # Primero vecinos (más plausibles), después el resto; a igualdad, los
        # menos usados hasta ahora.
        candidatos = sorted(candidatos, key=lambda c: usos[c]) + sorted(resto, key=lambda c: usos[c])
        otros = []
        for cid in candidatos:
            if _similitud(by_id[principal].get("definition", ""),
                          by_id[cid].get("definition", "")) >= SIMILITUD_MAXIMA_DISTRACTOR:
                continue
            otros.append(cid)
            usos[cid] += 1
            if len(otros) >= 3:
                break
        if len(otros) < 2:
            descartes.append({"item": f"B2/{caso.get('id')}", "motivo": "sin distractores utilizables"})
            continue
        items["B2"].append({
            "id": _hash_id("B2", caso.get("id", "")),
            "mechanic_id": "B2",
            "case_id": caso.get("id"),
            "enunciado": caso.get("description", ""),
            "opciones": [principal] + otros,
            "respuesta_correcta": principal,
            "n_efectivo": 1 + len(otros),
            "dificultad": curva_por_concepto.get(principal, {}).get("dificultad_objetivo", 0.5),
        })

    # ── E1 / E3: plantillas con gold, para juez en runtime ────────────────
    for origen, mech, campo in ((cases, "E1", "caso"), (scenarios, "E3", "escenario")):
        for x in origen or []:
            gold = (x.get("resolucion_esperada") or "").strip()
            if not gold:
                continue
            # E1 PREDECIR exige que el caso admita predicción. Se generaron 8
            # ítems sobre 3 casos legítimos: pedir que anticipe el resultado de
            # un caso que ya lo revela no mide predicción, mide lectura.
            if mech == "E1" and not x.get("prediction_enabled"):
                descartes.append({
                    "item": f"E1/{x.get('id')}",
                    "motivo": "el caso no admite predicción (prediction_enabled falso)",
                })
                continue
            ids = x.get("concept_ids") or []
            items[mech].append({
                "id": _hash_id(mech, x.get("id", "")),
                "mechanic_id": mech,
                "origen": campo,
                "origen_id": x.get("id"),
                "concept_ids": ids,
                "enunciado": x.get("description", ""),
                "resolucion_esperada": gold,
                "dominio": x.get("dominio", ""),
                "distancia": x.get("distancia", "cercana" if campo == "caso" else None),
                "variables_clave": x.get("variables_clave") or [],
                "requiere_juez": True,
                "dificultad": curva_por_concepto.get(
                    ids[0] if ids else "", {}).get("dificultad_objetivo", 0.6),
            })

    # ── E2 DIAGNOSTICAR: solo donde hay un error incrustado ───────────────
    for x in list(cases or []) + list(scenarios or []):
        error = (x.get("error_embebido") or "").strip()
        if not error:
            continue
        items["E2"].append({
            "id": _hash_id("E2", x.get("id", "")),
            "mechanic_id": "E2",
            "origen_id": x.get("id"),
            "concept_ids": x.get("concept_ids") or [],
            "enunciado": x.get("description", ""),
            "error_esperado": error,
            "repertoire_id": x.get("repertoire_id"),
            "requiere_juez": True,
            "dificultad": 0.7,
        })

    return dict(items), descartes


# ─────────────────────────────────────────────
# Veredicto por mecánica
# ─────────────────────────────────────────────

def _ejes_provisionales(concepts_idx: dict, relations: list[dict]) -> list[dict]:
    """Ejes derivados de campos que ya existen, cuando no hay ejes semánticos.

    C4 MAPEAR es la mecánica de tablero más rica del catálogo y está bloqueada
    por falta de ejes. Extraerlos del texto es trabajo de una subcapa nueva;
    mientras tanto, tres de los ejes se pueden derivar de campos poblados al
    100%: el tipo de concepto, su dificultad y su centralidad en el grafo.

    Comparar un concepto teórico contra uno metodológico es una distinción de
    dominio real, así que el ejercicio no es falso. Pero **no** son ejes que el
    documento propone, y por eso van marcados como provisionales: presentarlos
    como si vinieran del texto sería atribuirle al autor una organización que no
    escribió.
    """
    if not concepts_idx:
        return []

    grados: dict[str, int] = defaultdict(int)
    for r in relations or []:
        grados[r.get("from_concept_id")] += 1
        grados[r.get("to_concept_id")] += 1
    max_grado = max(grados.values()) if grados else 1

    ORDEN_TIPO = {"empirico": 0.0, "aplicado": 0.33, "metodologico": 0.66, "teorico": 1.0}
    ejes = [
        {
            "id": "concreto_abstracto_provisional",
            "label": "Grado de abstracción",
            "polo_bajo": "empírico / aplicado",
            "polo_alto": "teórico",
            "provisional": True,
            "derivado_de": "campo `tipo` del concepto",
            "positions": [
                {"concept_id": cid,
                 "position": ORDEN_TIPO.get(c.get("tipo", "teorico"), 0.5),
                 "justificacion": f"tipo declarado: {c.get('tipo')}"}
                for cid, c in concepts_idx.items()
            ],
            "confidence_extraction": 0.4,
        },
        {
            "id": "accesible_exigente_provisional",
            "label": "Exigencia para quien empieza",
            "polo_bajo": "accesible",
            "polo_alto": "exigente",
            "provisional": True,
            "derivado_de": "campo `dificultad_declarada`",
            "positions": [
                {"concept_id": cid,
                 "position": {"basico": 0.15, "intermedio": 0.5, "avanzado": 0.9}.get(
                     c.get("dificultad_declarada", "intermedio"), 0.5),
                 "justificacion": f"dificultad: {c.get('dificultad_declarada')}"}
                for cid, c in concepts_idx.items()
            ],
            "confidence_extraction": 0.4,
        },
    ]

    if max_grado > 2:
        ejes.append({
            "id": "periferico_central_provisional",
            "label": "Centralidad en el tema",
            "polo_bajo": "periférico",
            "polo_alto": "central",
            "provisional": True,
            "derivado_de": "número de conexiones en el grafo",
            "positions": [
                {"concept_id": cid,
                 "position": round(grados.get(cid, 0) / max_grado, 2),
                 "justificacion": f"{grados.get(cid, 0)} conexiones"}
                for cid in concepts_idx
            ],
            "confidence_extraction": 0.5,
        })
    return ejes


def _capabilities(
    data: dict, bundle_parcial: dict, pools: dict, items: dict,
    veredictos: dict, relations: list[dict], concepts_idx: dict,
) -> dict:
    """Qué se puede instanciar con este material, calculado y explícito.

    El motor de juego necesita saber, antes de empezar, qué anclas hay, qué
    condiciones son aplicables y qué encuentros existen de verdad. Hoy tiene que
    deducirlo recorriendo el paquete, o peor, adivinarlo y descubrirlo al fallar.

    Además le dice al profesor qué se puede y qué no con lo que subió, que es
    información que hoy nadie le da.
    """
    grados: dict[str, int] = defaultdict(int)
    for r in relations or []:
        grados[r.get("from_concept_id")] += 1
        grados[r.get("to_concept_id")] += 1

    anclas = sorted([cid for cid, g in grados.items() if g >= 3 and cid in concepts_idx],
                    key=lambda c: -grados[c])
    umbrales = [cid for cid, c in concepts_idx.items() if c.get("es_umbral")]
    puertas = [cid for cid, c in concepts_idx.items() if c.get("es_puerta")]
    rareza = _rareza_relaciones(relations or [])

    repertorios = data.get("repertoires", []) or []
    escenarios = data.get("scenarios", []) or []
    casos = data.get("cases", []) or []
    con_pool = {cid for cid, p in pools.items() if len(p) >= 3}

    # Condiciones transversales (familia J) y si el material las sostiene.
    condiciones = {
        "cadena": {
            "instanciable": len(anclas) >= 2,
            "capacidad": len(anclas),
            "motivo": "" if len(anclas) >= 2 else
                      f"solo {len(anclas)} concepto(s) con 3+ conexiones sirven de ancla",
        },
        "monocultivo": {
            "instanciable": len(rareza) >= 2,
            "por_tipo": rareza,
            "nota": "el peso de cada tipo es inverso a su frecuencia en este documento; "
                    "una condición sobre el tipo más común es trivial y sobre el más raro, "
                    "casi imposible",
        },
        "umbral": {
            "instanciable": len(umbrales) >= 2,
            "capacidad": len(umbrales),
            "motivo": "" if len(umbrales) >= 2 else "faltan conceptos umbral",
        },
        "enjambre": {
            "instanciable": len(con_pool) >= 5,
            "capacidad": len(con_pool),
            "motivo": "" if len(con_pool) >= 5 else
                      f"solo {len(con_pool)} concepto(s) tienen 3+ distractores",
        },
        "eco_de_intuicion": {
            "instanciable": len(repertorios) >= 1,
            "capacidad": len(repertorios),
            "nota": "con pocos repertorios debe ser evento raro y memorable, "
                    "no enemigo recurrente",
        },
        "portal_por_distancia": {
            "instanciable": bool(escenarios),
            "por_distancia": {
                d: sum(1 for s in escenarios if s.get("distancia") == d)
                for d in ("cercana", "media", "lejana")
            },
        },
        "marco_rival": {
            "instanciable": sum(1 for f in (data.get("frameworks") or []) if f.get("rivales")) >= 2,
            "capacidad": sum(1 for f in (data.get("frameworks") or []) if f.get("rivales")),
        },
    }

    return {
        "anclas": anclas[:20],
        "conceptos_puerta": puertas,
        "conceptos_umbral": umbrales,
        "conceptos_sin_pool": [cid for cid in concepts_idx if cid not in pools],
        "conceptos_pool_minimo": [
            cid for cid, p in pools.items() if len(p) < 2
        ],
        "rareza_relaciones": rareza,
        "relaciones_por_confianza": {
            "afirmadas": sum(1 for r in relations
                             if float(r.get("confidence_extraction") or 0.6) >= 0.8),
            "implicadas": sum(1 for r in relations
                              if 0.6 <= float(r.get("confidence_extraction") or 0.6) < 0.8),
            "inferidas": sum(1 for r in relations
                             if float(r.get("confidence_extraction") or 0.6) < 0.6),
        },
        "pares_con_varios_tipos": sum(
            1 for r in relations if len(r.get("tipos_del_par") or []) > 1),
        "co_ocurrencias": len(data.get("cooccurrences", []) or []),
        "descripciones_incompletas": sum(
            1 for r in relations if r.get("descripcion_incompleta")),
        "mecanicas_jugables": sorted(m for m, v in veredictos.items() if v.get("jugable")),
        "encuentros_por_mecanica": {k: len(v) for k, v in items.items()},
        "condiciones": condiciones,
        "casos_con_prediccion": sum(1 for c in casos if c.get("prediction_enabled")),
        "casos_con_error": sum(
            1 for x in list(casos) + list(escenarios) if (x.get("error_embebido") or "").strip()
        ),
        "distractores_con_explicacion_propia": sum(
            1 for p in pools.values() for d in p
            if d.get("explicacion") and not d.get("explicacion_derivada")
        ),
        "distractores_con_explicacion_derivada": sum(
            1 for p in pools.values() for d in p if d.get("explicacion_derivada")
        ),
    }


def _inventory(data: dict, pools: dict) -> dict[str, int]:
    concepts = data.get("concepts", [])
    relations = data.get("relations", [])
    cases = data.get("cases", [])
    scenarios = data.get("scenarios", [])

    por_tipo: dict[str, int] = defaultdict(int)
    for r in relations:
        por_tipo[(r.get("relation_type") or "").lower()] += 1

    inv = {
        "concepto": sum(1 for c in concepts if (c.get("definition") or "").strip()),
        "sinonimos": sum(1 for c in concepts
                         if (c.get("sinonimos") or c.get("variantes_terminologicas"))),
        "distractores": len(pools),
        "arista": len(relations),
        "cluster": len(data.get("clusters", [])),
        "eje": len(data.get("axes", [])),
        "repertorio": sum(1 for r in data.get("repertoires", [])
                          if (r.get("contraste_cientifico") or "").strip()),
        "caso_gold": sum(1 for c in cases if (c.get("resolucion_esperada") or "").strip()),
        "caso_multi": sum(1 for c in cases if len(c.get("concept_ids") or []) >= 2),
        "caso_error": sum(1 for x in list(cases) + list(scenarios)
                          if (x.get("error_embebido") or "").strip()),
        "escenario": len(scenarios),
        "escenario_lejano": sum(1 for s in scenarios if s.get("distancia") == "lejana"),
        "tesis": sum(1 for t in data.get("theses", [])
                     if (t.get("criterios_defensa_valida") or [])),
        "marco_rival": sum(1 for f in data.get("frameworks", []) if (f.get("rivales") or [])),
    }
    for tipo, n in por_tipo.items():
        inv[f"arista_tipo:{tipo}"] = n
    return inv


def _evaluate_mechanics(inv: dict, items: dict, permitir_juez: bool,
                        permitir_peer: bool) -> dict[str, dict]:
    veredictos: dict[str, dict] = {}
    for mid, spec in REGISTRY.items():
        faltantes: list[str] = []
        for req, minimo in (spec["requiere"] or {}).items():
            if req == "ninguno":
                continue
            if req == "juez":
                if not permitir_juez:
                    faltantes.append("evaluación por IA en tiempo de juego")
                continue
            if req == "peer":
                if not permitir_peer:
                    faltantes.append("otro estudiante presente")
                continue
            disponible = inv.get(req, 0)
            if disponible < minimo:
                faltantes.append(
                    f"{REQUISITO_LABEL.get(req, req)}: hay {disponible}, hacen falta {minimo}"
                )

        listos = items.get(mid, [])
        requiere_juez = bool((spec["requiere"] or {}).get("juez"))
        requiere_peer = bool((spec["requiere"] or {}).get("peer"))
        sin_contenido = not (spec["requiere"] or {}).get("ninguno")

        # "Disponible" tenía un problema: 26 mecánicas salían disponibles y sin
        # un solo ítem. El veredicto decía que se podían jugar y el motor de
        # sesiones no encontraba con qué. Ahora se distingue lo que está listo
        # de lo que solo tiene la materia prima necesaria.
        estado = "lista" if listos else (
            "necesita_juez" if requiere_juez and not faltantes else (
                "necesita_peer" if requiere_peer and not faltantes else (
                    "sin_items" if not faltantes and sin_contenido else "bloqueada"
                )
            )
        )
        if estado == "sin_items":
            faltantes = faltantes + [
                "la materia prima alcanza, pero el compilador no generó ítems "
                "para esta mecánica todavía"
            ]

        veredictos[mid] = {
            "mechanic_id": mid,
            "nombre": spec["nombre"],
            "familia": spec["familia"],
            "familia_nombre": FAMILIAS.get(spec["familia"], spec["familia"]),
            "estado": estado,
            "jugable": bool(listos),
            "disponible": not faltantes,
            "faltantes": faltantes,
            "items_precompilados": len(listos),
            "requiere_juez": bool((spec["requiere"] or {}).get("juez")),
            "requiere_peer": bool((spec["requiere"] or {}).get("peer")),
            "senales": spec["senales"],
        }
    return veredictos


def _readiness(veredictos: dict, inv: dict) -> list[dict]:
    """Qué dimensiones del perfil puede alimentar este curso, y con qué mecánicas."""
    # La cobertura se calcula sobre lo JUGABLE, no sobre lo "disponible". Una
    # dimensión que solo la emiten mecánicas sin ítems no es medible hoy, por
    # mucho que el material la permita en principio.
    por_dim: dict[str, list[str]] = defaultdict(list)
    por_dim_potencial: dict[str, list[str]] = defaultdict(list)
    for mid, v in veredictos.items():
        for s in v["senales"]:
            if v.get("jugable"):
                por_dim[s["dimension"]].append(mid)
            elif v["disponible"]:
                por_dim_potencial[s["dimension"]].append(mid)

    todas = sorted({s["dimension"] for v in veredictos.values() for s in v["senales"]})
    salida = []
    for dim in todas:
        fuentes = sorted(set(por_dim.get(dim, [])))
        bloqueadas = sorted({
            mid for mid, v in veredictos.items()
            if not v["disponible"] and any(s["dimension"] == dim for s in v["senales"])
        })
        potenciales = sorted(set(por_dim_potencial.get(dim, [])))
        salida.append({
            "dimension": dim,
            "medible": bool(fuentes),
            "mecanicas_disponibles": fuentes,
            "mecanicas_potenciales": potenciales,
            "mecanicas_bloqueadas": bloqueadas,
            "motivo": "" if fuentes else (
                f"Hay materia prima para {', '.join(potenciales)} pero todavía no "
                f"se generan ítems para esas mecánicas."
                if potenciales else
                f"Ninguna mecánica que emita esta dimensión es instanciable. "
                f"Bloqueadas: {', '.join(bloqueadas) or 'ninguna'}."
            ),
        })
    return salida


# ─────────────────────────────────────────────
# Entrada principal
# ─────────────────────────────────────────────

def compile_bundle(data: dict, permitir_juez: bool = True,
                   permitir_peer: bool = False) -> dict[str, Any]:
    """Compila la materia prima en un paquete listo para el juego."""
    concepts = [c for c in data.get("concepts", []) if c.get("id")]
    by_id = {c["id"]: c for c in concepts}
    relations = [
        r for r in data.get("relations", [])
        if r.get("from_concept_id") in by_id and r.get("to_concept_id") in by_id
    ]
    clusters = data.get("clusters", []) or []
    # Un solo cluster con casi todos los conceptos no segmenta nada: es lo que
    # pasa cuando el grafo está bien conectado y label propagation converge a
    # una comunidad única. En ese caso los clusters no aportan y las unidades
    # del plan quedan como única segmentación real, así que se descartan para
    # no dar la impresión de que hay temas separados cuando no los hay.
    if len(clusters) == 1 and len(clusters[0].get("concept_ids", [])) > len(concepts) * 0.6:
        logger.info("[compiler] cluster único con %d de %d conceptos: se descarta",
                    len(clusters[0]["concept_ids"]), len(concepts))
        clusters = []
    cases = data.get("cases", []) or []
    scenarios = data.get("scenarios", []) or []

    # ── Plan de estudio ───────────────────────────────────────────────────
    orden, calidad_orden = _build_order(concepts, relations)
    unidades = _build_units(orden, by_id, clusters)
    curva = _difficulty_curve(unidades, by_id)
    curva_por_unidad = {c["unidad_id"]: c for c in curva}
    unidad_de: dict[str, str] = {}
    for u in unidades:
        for cid in u["concept_ids"]:
            unidad_de[cid] = u["id"]
    # La dificultad se ajusta por concepto, no solo por unidad. Dentro de una
    # misma unidad puede convivir un concepto básico con uno avanzado, y darles
    # el mismo objetivo desperdicia la información que el extractor ya tiene.
    curva_por_concepto: dict[str, dict] = {}
    for cid, uid in unidad_de.items():
        base = dict(curva_por_unidad.get(uid, {}))
        propio = (DIFICULTAD_NUM.get(by_id[cid].get("difficulty"), 2) - 1) / 2  # 0..1
        mezcla = round(
            min(1.0, max(0.2, 0.6 * base.get("dificultad_objetivo", 0.5) + 0.4 * propio)), 2
        )
        base["dificultad_objetivo"] = mezcla
        base["n_opciones_sugerido"] = 3 if mezcla < 0.5 else (4 if mezcla < 0.75 else 5)
        base["andamiaje_sugerido"] = (
            "alto" if mezcla < 0.45 else ("medio" if mezcla < 0.7 else "bajo")
        )
        curva_por_concepto[cid] = base

    # ── Distractores e ítems ──────────────────────────────────────────────
    pools, stats_pool = _build_distractors(concepts, data.get("repertoires", []), relations)
    items, descartes = _build_items(
        concepts, pools, relations, cases, scenarios, curva_por_concepto
    )

    # ── Grafo indexado ────────────────────────────────────────────────────
    adyacencia: dict[str, list[dict]] = defaultdict(list)
    por_tipo: dict[str, list[dict]] = defaultdict(list)
    for r in relations:
        arista = {
            "from": r["from_concept_id"], "to": r["to_concept_id"],
            "tipo": (r.get("relation_type") or "").lower(),
            "descripcion": r.get("description", ""),
        }
        adyacencia[arista["from"]].append(arista)
        adyacencia[arista["to"]].append({**arista, "invertida": True})
        por_tipo[arista["tipo"]].append(arista)

    # ── Conceptos indexados, ya con su unidad y su dificultad efectiva ────
    concepts_idx = {}
    for i, cid in enumerate(orden):
        c = by_id[cid]
        cfg = curva_por_concepto.get(cid, {})
        concepts_idx[cid] = {
            "id": cid,
            "titulo": c.get("title", ""),
            "definicion": c.get("core_definition") or c.get("definition", ""),
            "definicion_corta": c.get("definition", ""),
            "sinonimos": sorted(set(
                (c.get("sinonimos") or []) + (c.get("variantes_terminologicas") or [])
            )),
            "tipo": c.get("tipo", "teorico"),
            "dificultad_declarada": c.get("difficulty", "intermedio"),
            "dificultad_objetivo": cfg.get("dificultad_objetivo", 0.5),
            "n_opciones": cfg.get("n_opciones_sugerido", 4),
            "andamiaje": cfg.get("andamiaje_sugerido", "medio"),
            "importancia": float(c.get("importance") or 0.5),
            "es_puerta": bool(c.get("is_gateway")),
            "es_umbral": bool(c.get("is_threshold")),
            "unidad_id": unidad_de.get(cid),
            "posicion": i + 1,
            "subdimensiones": c.get("subdimensions") or [],
            "tensiones": c.get("key_tensions") or [],
            "paginas": c.get("source_pages") or [],
            "carga_cognitiva": c.get("carga_cognitiva") or [],
            "familias_recomendadas": sorted({
                f for carga in (c.get("carga_cognitiva") or [])
                for f in CARGA_A_FAMILIAS.get(carga, [])
            }) or ["A"],
            "n_distractores": len(pools.get(cid, [])),
            "n_efectivo": stats_pool.get("n_efectivo", {}).get(cid, 1.0),
        }

    # ── Veredictos ────────────────────────────────────────────────────────
    inv = _inventory(data, pools)
    veredictos = _evaluate_mechanics(inv, items, permitir_juez, permitir_peer)
    readiness = _readiness(veredictos, inv)

    disponibles = [m for m, v in veredictos.items() if v["disponible"]]
    jugables = [m for m, v in veredictos.items() if v.get("jugable")]
    total_items = sum(len(v) for v in items.values())

    # Conceptos que no se pueden ejercitar. Sin esta lista aparecen en el plan
    # de estudio como cualquier otro y el estudiante nunca recibe un ejercicio
    # sobre ellos, sin explicación.
    con_aristas = set()
    for r in relations:
        con_aristas.add(r["from_concept_id"])
        con_aristas.add(r["to_concept_id"])
    inutilizables = []
    for cid in concepts_idx:
        motivos = []
        if cid not in pools:
            motivos.append("sin distractores: no se pueden generar preguntas de opción")
        if cid not in con_aristas:
            motivos.append("sin conexiones: queda fuera de las mecánicas de relación")
        tiene_items = any(
            any(i.get("concept_id") == cid
                or cid in (i.get("concept_ids") or [])
                or cid in (i.get("par") or [])
                for i in lista)
            for lista in items.values()
        )
        if not tiene_items:
            motivos.append("ningún ejercicio lo cubre")
        if motivos:
            inutilizables.append({
                "concept_id": cid,
                "titulo": concepts_idx[cid]["titulo"],
                "motivos": motivos,
                "ejercitable": tiene_items,
            })

    bundle = {
        "bundle_version": BUNDLE_VERSION,
        "course_id": data.get("course_id"),
        "source_filename": data.get("source_filename"),
        "compiled_from_schema": data.get("schema_version"),
        "concepts": concepts_idx,
        "graph": {
            "adyacencia": dict(adyacencia),
            "por_tipo": dict(por_tipo),
            "clusters": clusters,
            # Cercanía textual sin vínculo afirmado: cubre el hueco entre "el
            # documento afirma una relación" y "no hay nada".
            "cooccurrences": data.get("cooccurrences", []) or [],
            # Si el extractor no produjo ejes semánticos, se derivan de campos
            # existentes y quedan marcados como provisionales. Desbloquea C4 sin
            # atribuirle al documento una organización que no propone.
            "ejes": (data.get("axes") or []) or _ejes_provisionales(concepts_idx, relations),
            "ejes_son_provisionales": not (data.get("axes") or []),
        },
        "study_plan": {
            "orden": orden,
            "unidades": unidades,
            "curva_dificultad": curva,
            "calidad": calidad_orden,
        },
        "distractor_pools": pools,
        "items": items,
        "mechanics": veredictos,
        "readiness": readiness,
        "items_descartados": descartes,
        "conceptos_con_problemas": inutilizables,
        "capabilities": _capabilities(
            data, {}, pools, items, veredictos, relations, concepts_idx
        ),
        "content": {
            "repertoires": data.get("repertoires", []) or [],
            "cases": cases,
            "scenarios": scenarios,
            "theses": data.get("theses", []) or [],
            "frameworks": data.get("frameworks", []) or [],
        },
        "stats": {
            "conceptos": len(concepts_idx),
            "aristas": len(relations),
            "unidades": len(unidades),
            "items_precompilados": total_items,
            "items_por_mecanica": {k: len(v) for k, v in items.items()},
            "mecanicas_disponibles": len(disponibles),
            "mecanicas_jugables": len(jugables),
            "mecanicas_totales": len(REGISTRY),
            "conceptos_no_ejercitables": sum(
                1 for x in inutilizables if not x["ejercitable"]),
            "distractores": stats_pool,
            "items_descartados": len(descartes),
            "dimensiones_medibles": sum(1 for r in readiness if r["medible"]),
        },
    }
    logger.info(
        "[compiler] %d conceptos, %d unidades, %d ítems, %d/%d mecánicas disponibles",
        len(concepts_idx), len(unidades), total_items, len(disponibles), len(REGISTRY),
    )
    return bundle
