"""
pipeline/graph_utils.py — NUEVO en v2

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
from collections import defaultdict


# ─────────────────────────────────────────────
# Relaciones
# ─────────────────────────────────────────────

_SYMMETRIC = {"contrasta", "contradice"}


def dedupe_relations(relations: list[dict], valid_ids: set[str]) -> tuple[list[dict], dict]:
    """Deduplica por par (from, to) sin importar el tipo y resuelve conflictos.

    Devuelve (relaciones limpias, informe). El informe registra los conflictos
    en vez de esconderlos: dos tipos incompatibles sobre el mismo par suelen
    señalar que el LLM leyó dos segmentos que hablaban de cosas distintas.
    """
    by_pair: dict[tuple[str, str], list[dict]] = defaultdict(list)
    dropped_unknown = 0

    for r in relations:
        a, b = r.get("from_concept_id"), r.get("to_concept_id")
        if not a or not b or a == b:
            continue
        if a not in valid_ids or b not in valid_ids:
            dropped_unknown += 1
            continue
        rtype = (r.get("relation_type") or "").strip().lower()
        key = (b, a) if (rtype in _SYMMETRIC and (b, a) in by_pair) else (a, b)
        by_pair[key].append(r)

    clean: list[dict] = []
    conflicts: list[dict] = []

    for (a, b), group in by_pair.items():
        types = {(g.get("relation_type") or "").lower() for g in group}
        if len(types) > 1:
            conflicts.append({"from": a, "to": b, "types": sorted(types)})
        # Se queda la de mayor confianza; a igualdad, la primera.
        best = max(group, key=lambda g: _conf(g.get("confidence_extraction")))
        if len(types) > 1:
            best = dict(best)
            best["confidence_extraction"] = min(_conf(best.get("confidence_extraction")), 0.4)
            best["description"] = (best.get("description") or "") + \
                f" [conflicto de tipo detectado: {sorted(types)}]"
        clean.append(best)

    return clean, {
        "relations_dropped_unknown_concept": dropped_unknown,
        "relation_type_conflicts": conflicts,
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
) -> list[dict]:
    """Label propagation sobre el grafo no dirigido. Determinista vía seed."""
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
    for i, (label, members) in enumerate(sorted(groups.items(), key=lambda kv: -len(kv[1])), 1):
        if len(members) < 2:
            continue
        clusters.append({
            "id": f"cluster_{i}",
            "label": f"Grupo {i} ({label})",
            "concept_ids": sorted(members),
        })
    return clusters


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
