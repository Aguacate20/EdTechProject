"""
pipeline/canonicalize.py — v2.2

Consolidación de conceptos duplicados.

## El bug que corrige esta versión

En v2.1 la etapa "determinista" usaba como claves de fusión los sinónimos
generados por el LLM:

    for alias in concept["sinonimos"] + concept["variantes_terminologicas"]:
        keys.add(normalize(alias))

Eso no tenía nada de determinista: era salida de modelo alimentando un
union-find, que es transitivo. Bastaba un concepto tipo "Operational indices"
con sinónimos ["EVI","PCCI","IRM"] para encadenar los tres índices en un solo
nodo. En la corrida medida, EVI, PCCI e IRM terminaron fusionados en un único
concepto con la definición de uno solo — justo los tres constructos que el
paper define por separado y cuya sección de limitaciones advierte que no hay
que confundir.

Un solo sinónimo flojo arrastraba un clúster entero.

## Reglas de la v2.2

  1. Las claves salen SOLO de la estructura del título: título normalizado,
     título sin paréntesis, y la sigla del paréntesis. Nunca de sinónimos.
  2. Un paréntesis con comas no es una sigla: "Operational indices (EVI, PCCI,
     IRM)" es una enumeración, no una abreviatura.
  3. Una sigla solo funde si es inequívoca en el corpus. Si dos títulos base
     distintos reclaman la misma sigla, ninguno funde por ella.
  4. Tope de grupo: si el union-find junta más de tres conceptos, no se funde
     nada — se manda entero a adjudicación. Un grupo grande casi siempre
     significa que una clave está encadenando de más.
  5. El desempate prioriza cuántas veces se extrajo cada variante y la página
     más temprana, por encima de la confianza declarada por el modelo.
"""
from __future__ import annotations

import logging
import re
import unicodedata
from collections import defaultdict

logger = logging.getLogger(__name__)

MAX_AUTO_GROUP = 3

_GENERIC_TOKENS = {
    "like", "base", "based", "using", "type", "kind", "form", "level", "part",
    "component", "componente", "tipo", "nivel", "parte", "proceso", "process",
    "system", "sistema", "model", "modelo", "effect", "efecto", "study", "estudio",
    "data", "dato", "value", "valor", "user", "usuario", "human", "humano",
    "index", "indice", "scale", "escala", "metric", "metrica", "phase", "fase",
}

_STOPWORDS = {
    "the", "a", "an", "of", "and", "or", "in", "on", "for", "to",
    "el", "la", "los", "las", "un", "una", "de", "del", "y", "o", "en",
}


def normalize(text: str) -> str:
    if not text:
        return ""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.lower()
    text = re.sub(r"[^\w\s]", " ", text)
    tokens = [t for t in text.split() if t and t not in _STOPWORDS]
    tokens = [t[:-1] if len(t) > 3 and t.endswith("s") else t for t in tokens]
    return " ".join(tokens)


def _parenthetical(title: str) -> tuple[str, str | None]:
    """Devuelve (título sin paréntesis, sigla) — sigla solo si lo parece.

    'Epistemic Vigilance Index (EVI)'          → ('Epistemic Vigilance Index', 'EVI')
    'Operational indices (EVI, PCCI, IRM)'     → (título completo, None)
    'Attachment-awareness (Phase 1)'           → (título completo, None)
    """
    match = re.search(r"^(.*?)\s*\(([^)]{2,24})\)\s*$", (title or "").strip())
    if not match:
        return (title or "").strip(), None
    base, inner = match.group(1).strip(), match.group(2).strip()
    if not base:
        return (title or "").strip(), None
    # Una enumeración no es una sigla.
    if "," in inner or "/" in inner or " y " in inner or " and " in inner:
        return (title or "").strip(), None
    # Una sigla no tiene espacios y es mayoritariamente mayúsculas o dígitos.
    if " " in inner:
        return (title or "").strip(), None
    letras = [c for c in inner if c.isalpha()]
    if not letras:
        return (title or "").strip(), None
    if sum(1 for c in letras if c.isupper()) / len(letras) < 0.6:
        return (title or "").strip(), None
    return base, inner


def _score(concept: dict) -> tuple:
    """Cuál variante se queda como canónica.

    El orden importa: en la corrida medida, 'Relational AI Framework (RAF)'
    —nombre que el modelo inventó— ganó sobre 'Resonant Amplification Framework
    (RAF)' porque traía más confianza declarada. La confianza del modelo sobre
    sí mismo es la señal más débil de todas y baja al final.
    """
    title = concept.get("title") or ""
    _, acronym = _parenthetical(title)
    pages = concept.get("source_pages") or []
    earliest = min(pages) if pages else 999
    return (
        1 if concept.get("is_enriched") else 0,
        int(concept.get("_extraction_count") or 1),   # cuántos lotes lo nombraron así
        -earliest,                                    # el paper nombra bien su aporte temprano
        1 if acronym else 0,
        len(concept.get("definition") or ""),
        float(concept.get("importance") or 0),
        float(concept.get("confidence_extraction") or 0.6),
    )


def _merge_group(group: list[dict]) -> dict:
    group = sorted(group, key=_score, reverse=True)
    winner = dict(group[0])

    aliases = set(winner.get("sinonimos") or [])
    variants = set(winner.get("variantes_terminologicas") or [])
    pages = set(winner.get("source_pages") or [])

    for other in group[1:]:
        title = (other.get("title") or "").strip()
        if title and normalize(title) != normalize(winner.get("title", "")):
            aliases.add(title)
        aliases.update(other.get("sinonimos") or [])
        variants.update(other.get("variantes_terminologicas") or [])
        pages.update(other.get("source_pages") or [])
        if len(other.get("definition") or "") > len(winner.get("definition") or "") * 2:
            winner["definition"] = other["definition"]
        winner["importance"] = max(
            float(winner.get("importance") or 0), float(other.get("importance") or 0)
        )
        for field in ("core_definition", "measurement_approach", "theoretical_role",
                      "evolution_in_paper"):
            if not winner.get(field) and other.get(field):
                winner[field] = other[field]
        for field in ("subdimensions", "distinctions", "key_tensions"):
            if not winner.get(field) and other.get(field):
                winner[field] = other[field]
        winner["is_gateway"] = winner.get("is_gateway") or other.get("is_gateway")
        winner["is_threshold"] = winner.get("is_threshold") or other.get("is_threshold")

    winner["sinonimos"] = sorted(aliases)
    winner["variantes_terminologicas"] = sorted(variants)
    winner["source_pages"] = sorted(pages)
    return winner


def deterministic_pass(
    concepts: list[dict],
) -> tuple[list[dict], dict[str, str], dict, list[list[dict]]]:
    """Fusiona solo lo estructuralmente indiscutible.

    Devuelve (conceptos, mapa_de_ids, informe, grupos_para_adjudicar).
    Los grupos que superan el tope de tamaño NO se fusionan: se devuelven para
    que los juzgue el LLM.
    """
    n = len(concepts)
    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    # ── Claves estructurales. Nada que venga del LLM como sinónimo.
    strong_index: dict[str, list[int]] = defaultdict(list)
    acronym_bases: dict[str, set[str]] = defaultdict(set)
    acronym_owners: dict[str, list[int]] = defaultdict(list)
    title_index: dict[str, list[int]] = defaultdict(list)

    for i, concept in enumerate(concepts):
        title = concept.get("title") or ""
        base, acronym = _parenthetical(title)
        norm_title = normalize(title)
        norm_base = normalize(base)

        title_index[norm_title].append(i)
        strong_index[norm_title].append(i)
        if norm_base and norm_base != norm_title:
            strong_index[norm_base].append(i)
        if acronym:
            key = normalize(acronym)
            acronym_bases[key].add(norm_base)
            acronym_owners[key].append(i)

    for members in strong_index.values():
        for other in members[1:]:
            union(members[0], other)

    # ── Siglas: solo si son inequívocas en el corpus.
    ambiguous: list[str] = []
    for acronym_key, bases in acronym_bases.items():
        if len(bases) > 1:
            ambiguous.append(acronym_key)
            continue
        for owner in acronym_owners[acronym_key]:
            for bare in title_index.get(acronym_key, []):
                union(owner, bare)

    components: dict[int, list[int]] = defaultdict(list)
    for i in range(n):
        components[find(i)].append(i)

    merged: list[dict] = []
    id_map: dict[str, str] = {}
    fusions: list[dict] = []
    oversized: list[list[dict]] = []

    for members in components.values():
        group = [concepts[i] for i in members]
        if len(group) > MAX_AUTO_GROUP:
            # Un grupo grande casi siempre significa que una clave encadenó de
            # más. No se funde: se manda entero a adjudicación.
            oversized.append(group)
            for concept in group:
                merged.append(concept)
                id_map[concept.get("id", "")] = concept.get("id", "")
            continue

        winner = _merge_group(group)
        merged.append(winner)
        for concept in group:
            id_map[concept.get("id", "")] = winner["id"]
        if len(group) > 1:
            fusions.append({
                "canonical": winner["id"],
                "canonical_title": winner.get("title"),
                "absorbed": [c.get("id") for c in group if c.get("id") != winner["id"]],
            })

    report = {
        "input": n,
        "output": len(merged),
        "deterministic_fusions": fusions,
        "acronimos_ambiguos": sorted(ambiguous),
        "grupos_sobredimensionados": [
            [c.get("id") for c in g] for g in oversized
        ],
    }
    logger.info(
        "[canonicalize] determinista: %d → %d conceptos (%d grupos aplazados por tamaño)",
        n, len(merged), len(oversized),
    )
    return merged, id_map, report, oversized


def similarity_candidates(
    concepts: list[dict], max_groups: int = 25
) -> list[list[dict]]:
    """Agrupa conceptos que comparten un token distintivo, para adjudicación."""
    by_token: dict[str, list[int]] = defaultdict(list)
    for i, concept in enumerate(concepts):
        for token in set(normalize(concept.get("title", "")).split()):
            if len(token) >= 4 and token not in _GENERIC_TOKENS:
                by_token[token].append(i)

    seen: set[tuple] = set()
    groups: list[list[int]] = []
    for _, members in sorted(by_token.items(), key=lambda kv: len(kv[1])):
        if not (2 <= len(members) <= 6):
            continue
        key = tuple(sorted(members))
        if key in seen:
            continue
        seen.add(key)
        groups.append(list(members))
        if len(groups) >= max_groups:
            break
    return [[concepts[i] for i in group] for group in groups]


def apply_llm_decisions(
    concepts: list[dict], decisions: list[dict],
) -> tuple[list[dict], dict[str, str], list[dict]]:
    by_id = {c.get("id"): c for c in concepts}
    id_map: dict[str, str] = {cid: cid for cid in by_id}
    applied: list[dict] = []
    consumed: set[str] = set()

    for decision in decisions or []:
        canonical = decision.get("canonical_id")
        merge_ids = [m for m in (decision.get("merge_ids") or []) if m != canonical]
        if canonical not in by_id:
            continue
        group = [by_id[canonical]] + [by_id[m] for m in merge_ids if m in by_id]
        if len(group) < 2:
            continue
        if any(c.get("id") in consumed for c in group):
            continue
        if len(group) > MAX_AUTO_GROUP + 1:
            logger.warning("[canonicalize] fusión de %d conceptos rechazada por tamaño: %s",
                           len(group), [c.get("id") for c in group])
            continue

        winner = _merge_group(group)
        if decision.get("title"):
            winner["title"] = decision["title"]
        by_id[canonical] = winner
        for concept in group[1:]:
            cid = concept.get("id")
            consumed.add(cid)
            id_map[cid] = canonical
        applied.append({
            "canonical": canonical,
            "absorbed": [c.get("id") for c in group[1:]],
            "razon": decision.get("razon", ""),
        })

    survivors = [c for cid, c in by_id.items() if cid not in consumed]
    logger.info("[canonicalize] LLM: %d fusiones aplicadas, quedan %d conceptos",
                len(applied), len(survivors))
    return survivors, id_map, applied


def remap_ids(items: list[dict], id_map: dict[str, str], fields: list[str]) -> list[dict]:
    for item in items or []:
        for field in fields:
            value = item.get(field)
            if isinstance(value, str) and value in id_map:
                item[field] = id_map[value]
            elif isinstance(value, list):
                item[field] = [id_map.get(v, v) for v in value]
    return items
