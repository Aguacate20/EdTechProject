"""
pipeline/graph_utils.py — v3.5

Utilidades de grafo para la capa 2 y la capa 6.

Corrige cuatro defectos de v1:
  1. Los clusters los devolvía el LLM por segmento y se acumulaban sin merge,
     produciendo N juegos solapados. Aquí se calculan algorítmicamente
     (label propagation, sin dependencias externas), como pide 06_materia_prima.
  2. `prerequisite_graph` guardaba prerequisito → dependientes, es decir lo
     contrario de lo que su nombre y el doc 06 declaran. Ahora se emiten los
     dos grafos, cada uno con su nombre correcto.
  3. `_topological_sort` podía lanzar KeyError: el incremento estaba protegido
     con `if dep in in_degree` pero el decremento no, y los ids alucinados por
     el LLM son esperables porque el prompt recibe la lista completa de conceptos.
  4. El dedup de relaciones usaba la clave (from, to, type), así que
     (A,B,apoya) y (A,B,contradice) sobrevivían juntas sin conflicto.
"""
from __future__ import annotations

import random
import re
import unicodedata
from collections import defaultdict


# ─────────────────────────────────────────────
# Relaciones
# ─────────────────────────────────────────────

_SYMMETRIC = {"contrasta", "contradice"}


# Pares de tipos que no pueden ser ciertos a la vez sobre el mismo par de
# conceptos. El resto puede coexistir: que A extienda a B y a la vez lo requiera
# son dos hechos distintos, no una contradicción.
INCOMPATIBLES = [
    {"apoya", "contradice"},
    {"generaliza", "ejemplifica"},   # dirección opuesta de la misma relación
    {"causa", "contradice"},
]


def dedupe_relations(relations: list[dict], valid_ids: set[str]) -> tuple[list[dict], dict]:
    """Deduplica por (par, tipo) y CONSERVA los tipos múltiples compatibles.

    Antes se deduplicaba por par a secas: un par con dos tipos colapsaba a uno
    solo, el de mayor confianza. Eso hacía que el extractor decidiera cuál de
    los dos vínculos era "el verdadero" —una decisión que no le corresponde—, y
    el consumidor recibía la mitad de la información sin saber que faltaba.

    Ahora un par puede tener varias aristas, una por tipo, siempre que sean
    compatibles entre sí. Solo se resuelve cuando hay una contradicción real:
    afirmar que A apoya y contradice a B no puede ser cierto de las dos formas.

    Devuelve (relaciones, informe).
    """
    by_pair_type: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
    dropped_unknown = 0

    for r in relations:
        a, b = r.get("from_concept_id"), r.get("to_concept_id")
        if not a or not b or a == b:
            continue
        if a not in valid_ids or b not in valid_ids:
            dropped_unknown += 1
            continue
        rtype = (r.get("relation_type") or "").strip().lower()
        # Los tipos simétricos se normalizan a una sola dirección para no
        # duplicar "A contrasta B" y "B contrasta A".
        key_pair = tuple(sorted((a, b))) if rtype in _SYMMETRIC else (a, b)
        by_pair_type[(key_pair[0], key_pair[1], rtype)].append(r)

    # Una entrada por (par, tipo), quedándose con la de mayor confianza.
    por_par: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for (a, b, rtype), group in by_pair_type.items():
        mejor = max(group, key=lambda g: _conf(g.get("confidence_extraction")))
        mejor = dict(mejor)
        mejor["confidence_extraction"] = _conf(mejor.get("confidence_extraction"))
        # Si varios segmentos afirmaron lo mismo, es más creíble que si lo dijo
        # uno solo: la coincidencia independiente es evidencia.
        if len(group) > 1:
            mejor["confidence_extraction"] = min(
                1.0, mejor["confidence_extraction"] + 0.1 * (len(group) - 1)
            )
            mejor["veces_afirmada"] = len(group)
        por_par[(a, b)].append(mejor)

    clean: list[dict] = []
    conflicts: list[dict] = []
    multi: list[dict] = []

    for (a, b), aristas in por_par.items():
        tipos = {(x.get("relation_type") or "").lower() for x in aristas}

        incompatible = next((inc for inc in INCOMPATIBLES if inc <= tipos), None)
        if incompatible:
            # Contradicción real: se conserva la de mayor confianza y se
            # registra, porque suele señalar que el modelo leyó dos segmentos
            # que hablaban de cosas distintas.
            conflicts.append({"from": a, "to": b, "types": sorted(tipos),
                              "incompatibles": sorted(incompatible)})
            aristas = [x for x in aristas
                       if (x.get("relation_type") or "").lower() not in incompatible]
            candidatas = [x for x in por_par[(a, b)]
                          if (x.get("relation_type") or "").lower() in incompatible]
            if candidatas:
                ganadora = max(candidatas, key=lambda g: _conf(g.get("confidence_extraction")))
                ganadora = dict(ganadora)
                ganadora["confidence_extraction"] = min(
                    _conf(ganadora.get("confidence_extraction")), 0.4)
                ganadora["conflicto_resuelto"] = sorted(incompatible)
                aristas.append(ganadora)

        if len(aristas) > 1:
            multi.append({"from": a, "to": b,
                          "tipos": sorted((x.get("relation_type") or "").lower()
                                          for x in aristas)})
            # Cada arista sabe que el par tiene más de un vínculo, para que el
            # consumidor pueda tratarlas juntas sin volver a agrupar.
            tipos_del_par = sorted((x.get("relation_type") or "").lower() for x in aristas)
            for x in aristas:
                x["tipos_del_par"] = tipos_del_par

        clean.extend(aristas)

    return clean, {
        "relations_dropped_unknown_concept": dropped_unknown,
        "relation_type_conflicts": conflicts,
        "pares_con_varios_tipos": multi,
        "relations_por_confianza": {
            "afirmadas_0.8+": sum(1 for r in clean if _conf(r.get("confidence_extraction")) >= 0.8),
            "implicadas_0.6-0.8": sum(1 for r in clean if 0.6 <= _conf(r.get("confidence_extraction")) < 0.8),
            "inferidas_bajo_0.6": sum(1 for r in clean if _conf(r.get("confidence_extraction")) < 0.6),
        },
    }


def _conf(v) -> float:
    if isinstance(v, (int, float)):
        return float(v)
    return {"alta": 0.9, "media": 0.6, "baja": 0.3}.get(str(v).lower(), 0.6)


# ─────────────────────────────────────────────
# Clusters (label propagation)
# ─────────────────────────────────────────────

def compute_clusters(
    concept_ids: list[str],
    relations: list[dict],
    max_iter: int = 30,
    seed: int = 7,
    max_fraccion: float = 0.5,
) -> list[dict]:
    """Label propagation sobre el grafo no dirigido. Determinista vía seed.

    Con `max_fraccion`, un cluster que se coma más de esa proporción del grafo
    se subdivide. Nace de un caso real: un único cluster con 26 de 29 conceptos.
    Eso no es una comunidad, es el grafo entero con otro nombre, y no sirve para
    segmentar nada.

    La subdivisión quita los nodos más conectados —que son los que unen todo—
    y vuelve a propagar sobre el resto. Es el mismo truco que se usa para
    encontrar comunidades en grafos con hubs: sin el hub, las comunidades reales
    aparecen.
    """
    if not concept_ids:
        return []

    adj: dict[str, set[str]] = {cid: set() for cid in concept_ids}
    for r in relations:
        a, b = r.get("from_concept_id"), r.get("to_concept_id")
        if a in adj and b in adj:
            adj[a].add(b)
            adj[b].add(a)

    labels = {cid: cid for cid in concept_ids}
    rng = random.Random(seed)
    nodes = list(concept_ids)

    for _ in range(max_iter):
        rng.shuffle(nodes)
        changed = False
        for node in nodes:
            neighbours = adj[node]
            if not neighbours:
                continue
            counts: dict[str, int] = defaultdict(int)
            for nb in neighbours:
                counts[labels[nb]] += 1
            best = max(sorted(counts.items()), key=lambda kv: kv[1])[0]
            if labels[node] != best:
                labels[node] = best
                changed = True
        if not changed:
            break

    groups: dict[str, list[str]] = defaultdict(list)
    for cid, label in labels.items():
        groups[label].append(cid)

    clusters = []
    for label, members in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        if len(members) < 2:
            continue
        # Un cluster que abarca casi todo se subdivide quitando los hubs.
        if len(members) > len(concept_ids) * max_fraccion and len(members) > 6:
            sub = _subdividir(members, adj, seed)
            if len(sub) > 1:
                clusters.extend(sub)
                continue
        clusters.append({"concept_ids": sorted(members), "_label": label})

    salida = []
    for i, c in enumerate(sorted(clusters, key=lambda x: -len(x["concept_ids"])), 1):
        salida.append({
            "id": f"cluster_{i}",
            "label": f"Grupo {i}",
            "concept_ids": c["concept_ids"],
        })
    return salida


def _subdividir(members: list[str], adj: dict[str, set[str]], seed: int) -> list[dict]:
    """Quita los nodos más conectados y vuelve a propagar sobre el resto.

    Los hubs son los que colapsan todas las comunidades en una: en el material
    real, tres nodos concentraban el 40% de la conectividad. Apartándolos, las
    agrupaciones reales emergen, y después los hubs se reasignan a la comunidad
    con la que tengan más aristas.
    """
    internos = {m: len(adj.get(m, set()) & set(members)) for m in members}
    umbral = sorted(internos.values(), reverse=True)
    if len(umbral) < 4:
        return []
    corte = umbral[max(1, len(umbral) // 8)]
    hubs = [m for m, g in internos.items() if g >= corte and g > 2]
    resto = [m for m in members if m not in hubs]
    if len(resto) < 4 or not hubs:
        return []

    sub_adj = {m: adj.get(m, set()) & set(resto) for m in resto}
    labels = {m: m for m in resto}
    rng = random.Random(seed + 1)
    nodos = list(resto)
    for _ in range(30):
        rng.shuffle(nodos)
        cambio = False
        for nodo in nodos:
            vecinos = sub_adj[nodo]
            if not vecinos:
                continue
            cuenta: dict[str, int] = defaultdict(int)
            for v in vecinos:
                cuenta[labels[v]] += 1
            mejor = max(sorted(cuenta.items()), key=lambda kv: kv[1])[0]
            if labels[nodo] != mejor:
                labels[nodo] = mejor
                cambio = True
        if not cambio:
            break

    grupos: dict[str, list[str]] = defaultdict(list)
    for m, lab in labels.items():
        grupos[lab].append(m)
    grupos = {k: v for k, v in grupos.items() if len(v) >= 2}
    if len(grupos) < 2:
        return []

    # Los hubs vuelven a la comunidad con la que más aristas comparten.
    for hub in hubs:
        vecinos = adj.get(hub, set())
        mejor = max(grupos, key=lambda k: len(vecinos & set(grupos[k])))
        grupos[mejor].append(hub)

    return [{"concept_ids": sorted(v), "_label": k} for k, v in grupos.items()]


# ─────────────────────────────────────────────
# Prerequisitos
# ─────────────────────────────────────────────

def build_prereq_graphs(
    concept_ids: list[str],
    relations: list[dict],
) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """Devuelve (prerequisite_graph, unlocks_graph).

    Semántica de doc 06: la relación `requiere` va de A hacia B cuando A
    presupone B. Por tanto B es prerequisito de A.
      prerequisite_graph[A] = [B, ...]   → qué necesita A
      unlocks_graph[B]      = [A, ...]   → qué habilita B
    """
    prereq: dict[str, list[str]] = {cid: [] for cid in concept_ids}
    unlocks: dict[str, list[str]] = {cid: [] for cid in concept_ids}

    for r in relations:
        if (r.get("relation_type") or "").lower() != "requiere":
            continue
        a, b = r.get("from_concept_id"), r.get("to_concept_id")
        if a in prereq and b in prereq:
            if b not in prereq[a]:
                prereq[a].append(b)
            if a not in unlocks[b]:
                unlocks[b].append(a)

    return prereq, unlocks


def sequence_quality(prereq_graph: dict[str, list[str]], concept_count: int) -> dict:
    """Qué tan informativa es la secuencia sugerida.

    En la corrida medida el grafo tenía 2 aristas sobre 23 conceptos, así que
    `topological_sort` arrancaba con TODOS los nodos en la cola inicial y los
    devolvía en orden alfabético. La salida parecía un plan de estudio y era el
    abecedario.

    Eso importa porque planeación es una de las doce dimensiones del perfil, y
    el sistema no puede evaluar las decisiones del estudiante contra un orden
    que no significa nada. Es preferible declararlo no medible.
    """
    aristas = sum(len(v) for v in prereq_graph.values())
    nodos = max(concept_count, 1)
    ratio = aristas / nodos
    con_prereq = sum(1 for v in prereq_graph.values() if v)

    if ratio >= 0.5:
        nivel, motivo = "buena", ""
    elif ratio >= 0.2:
        nivel = "parcial"
        motivo = (f"Solo {aristas} relaciones de prerrequisito para {nodos} conceptos: "
                  f"el orden es orientativo y gran parte queda sin ordenar.")
    else:
        nivel = "no_confiable"
        motivo = (f"Solo {aristas} relaciones de prerrequisito para {nodos} conceptos. "
                  f"La secuencia resultante es prácticamente alfabética, no pedagógica: "
                  f"no debe usarse para evaluar las decisiones de planeación del estudiante.")

    return {
        "nivel": nivel,
        "aristas": aristas,
        "conceptos_con_prerequisito": con_prereq,
        "ratio": round(ratio, 2),
        "motivo": motivo,
    }


def topological_sort(prereq_graph: dict[str, list[str]]) -> list[str]:
    """Kahn sobre prerequisite_graph. Empieza por los conceptos sin prerequisitos.

    Robusto a ids desconocidos y a ciclos: lo que no se puede ordenar se anexa
    al final en orden estable en vez de perderse silenciosamente.
    """
    nodes = list(prereq_graph.keys())
    node_set = set(nodes)
    deps = {n: [d for d in prereq_graph.get(n, []) if d in node_set] for n in nodes}

    dependents: dict[str, list[str]] = {n: [] for n in nodes}
    for n, ds in deps.items():
        for d in ds:
            dependents[d].append(n)

    in_degree = {n: len(deps[n]) for n in nodes}
    queue = sorted([n for n, d in in_degree.items() if d == 0])
    result: list[str] = []

    while queue:
        node = queue.pop(0)
        result.append(node)
        for dep in dependents.get(node, []):
            in_degree[dep] -= 1
            if in_degree[dep] == 0:
                queue.append(dep)
        queue.sort()

    if len(result) < len(nodes):
        remaining = [n for n in nodes if n not in set(result)]
        result.extend(remaining)  # ciclo: se anexa en vez de descartarse

    return result


def compute_cooccurrences(
    concepts: list[dict],
    segments: list,
    min_parrafos: int = 2,
    max_pares: int = 300,
) -> list[dict]:
    """Pares de conceptos que aparecen juntos en el mismo párrafo.

    No afirma NINGÚN vínculo: solo dice que el texto los trata en el mismo
    sitio. Es deliberadamente débil, y esa debilidad es lo que la hace útil —
    cubre el hueco entre "el documento afirma que A causa B" y "no hay ninguna
    conexión", que hasta ahora se leía igual: silencio.

    Sale del troceado, sin llamar a ningún modelo, así que es gratis.

    Va en una lista APARTE de `relations` a propósito. Mezclarla contaminaría el
    grafo: una co-ocurrencia no es una relación del documento y un consumidor
    que las trate igual estaría afirmando cosas que nadie dijo.
    """
    if not concepts:
        return []

    # Formas buscables por concepto: título, título sin paréntesis, sigla,
    # sinónimos. Se descartan las muy cortas, que producen falsos positivos.
    formas: dict[str, list[str]] = {}
    for c in concepts:
        titulo = c.get("title") or c.get("titulo") or ""
        variantes = {titulo}
        base = re.sub(r"\s*\([^)]*\)\s*$", "", titulo).strip()
        if base:
            variantes.add(base)
        m = re.search(r"\(([^)]{2,12})\)", titulo)
        if m:
            variantes.add(m.group(1).strip())
        variantes |= set(c.get("sinonimos") or [])
        limpias = [_norm_texto(v) for v in variantes if v]
        formas[c["id"]] = [v for v in set(limpias) if len(v) >= 4]

    texto_total = "\n\n".join(
        (s.text if hasattr(s, "text") else str(s)) for s in (segments or [])
    )
    parrafos = [p for p in re.split(r"\n\s*\n", texto_total) if len(p.strip()) > 80]
    if not parrafos:
        return []

    juntos: dict[tuple[str, str], int] = defaultdict(int)
    apariciones: dict[str, int] = defaultdict(int)

    for parrafo in parrafos:
        norm = _norm_texto(parrafo)
        presentes = [cid for cid, fs in formas.items() if any(f in norm for f in fs)]
        for cid in presentes:
            apariciones[cid] += 1
        # Un párrafo que menciona medio documento no dice nada sobre ningún par.
        if len(presentes) > 8:
            continue
        for i, a in enumerate(presentes):
            for b in presentes[i + 1:]:
                juntos[tuple(sorted((a, b)))] += 1

    salida = []
    for (a, b), n in juntos.items():
        if n < min_parrafos:
            continue
        # Fuerza relativa: dos conceptos que aparecen en todo el documento van a
        # coincidir por azar. Lo informativo es que coincidan MÁS de lo esperado.
        esperado = (apariciones[a] * apariciones[b]) / max(len(parrafos), 1)
        fuerza = round(min(1.0, n / max(esperado, 0.5)) if esperado else 0.5, 2)
        salida.append({
            "concept_ids": [a, b],
            "parrafos_compartidos": n,
            "fuerza": fuerza,
            "tipo": "co_ocurrencia",
        })

    salida.sort(key=lambda x: (-x["fuerza"], -x["parrafos_compartidos"]))
    return salida[:max_pares]


def _norm_texto(t: str) -> str:
    t = unicodedata.normalize("NFKD", str(t or ""))
    t = "".join(c for c in t if not unicodedata.combining(c)).lower()
    return " ".join(re.sub(r"[^\w\s]", " ", t).split())


def validar_descripciones(relations: list[dict], concepts: list[dict]) -> int:
    """Marca las aristas cuya descripción no nombra a sus dos extremos.

    Una descripción como "extiende el concepto de apego digital" habla de un
    solo concepto, y la pregunta es sobre la relación ENTRE dos: el estudiante
    lee algo que no responde a lo que se le preguntó.

    No se descarta la arista —la relación puede ser correcta aunque esté mal
    redactada— pero el consumidor sabe que ese texto no sirve como explicación.
    """
    por_id = {c["id"]: c for c in concepts}
    incompletas = 0
    for r in relations or []:
        desc = _norm_texto(r.get("description") or "")
        if not desc:
            r["descripcion_incompleta"] = True
            incompletas += 1
            continue
        menciona = 0
        for cid in (r.get("from_concept_id"), r.get("to_concept_id")):
            c = por_id.get(cid)
            if not c:
                continue
            titulo = c.get("title") or ""
            base = _norm_texto(re.sub(r"\s*\([^)]*\)\s*$", "", titulo))
            formas = [f for f in [base] + [_norm_texto(s) for s in (c.get("sinonimos") or [])]
                      if f and len(f) >= 4]
            # La forma completa presente cuenta: "apego digital" vale aunque el
            # texto diga "el apego digital del usuario".
            if any(f in desc for f in formas):
                menciona += 1
                continue
            # Si no, se exigen TODAS las palabras significativas del título.
            #
            # El umbral era "la mitad", y con títulos que comparten una palabra
            # —"Digital attachment" y "Attachment theory"— una sola coincidencia
            # bastaba para dar por mencionados a los dos. Así, la descripción
            # «extend the concept of digital attachment», que solo habla de uno,
            # pasaba el control. Pedir todas las palabras evita ese cruce.
            tokens = {w for w in base.split() if len(w) > 3}
            if tokens and tokens <= set(desc.split()):
                menciona += 1
        r["descripcion_incompleta"] = menciona < 2
        if menciona < 2:
            incompletas += 1
    return incompletas
