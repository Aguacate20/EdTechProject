"""
pipeline/canonicalize.py — v2.2.4

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


def acronym_candidates(concepts: list[dict]) -> list[list[dict]]:
    """Agrupa los conceptos que declaran la MISMA sigla.

    Este agrupamiento existe por un fallo medido. La fusión automática se niega
    a unir dos conceptos que reclaman la misma sigla si sus títulos base
    difieren —es la protección que impide fundir EVI con PCCI— y deja el caso
    para adjudicación. Pero la adjudicación agrupaba por tokens compartidos del
    título, y `Epistemic Vigilance Index (EVI)` con `Índice de Vigilancia
    Epistémica (EVI)` no comparten NINGÚN token: uno está en inglés y otro en
    español. Nunca llegaban a la misma tanda, así que nadie los resolvía.

    Resultado en la corrida real: EVI, EDS, IRM y RAF quedaron duplicados, y
    eran exactamente las cuatro siglas marcadas como ambiguas.

    La sigla es una señal mucho más fuerte que el vocabulario compartido, y es
    inmune al idioma. Estos grupos van primero a adjudicación.
    """
    by_acronym: dict[str, list[int]] = defaultdict(list)
    for i, concept in enumerate(concepts):
        title = concept.get("title") or ""
        _, acronym = _parenthetical(title)
        claves = set()
        if acronym:
            claves.add(normalize(acronym))
        # Un título que ES la sigla suelta ('RAF', 'PCCI') también cuenta.
        norm = normalize(title)
        if norm and " " not in norm and len(norm) <= 8:
            claves.add(norm)
        # Y una sigla declarada como sinónimo, que es donde el modelo suele
        # dejarla cuando el título va en el otro idioma.
        for alias in (concept.get("sinonimos") or []):
            alias = str(alias).strip()
            if 2 <= len(alias) <= 8 and alias.isupper():
                claves.add(normalize(alias))
        for clave in claves:
            if clave:
                by_acronym[clave].append(i)

    groups: list[list[int]] = []
    vistos: set[tuple] = set()
    for _, members in sorted(by_acronym.items(), key=lambda kv: -len(kv[1])):
        if not (2 <= len(members) <= 6):
            continue
        key = tuple(sorted(members))
        if key in vistos:
            continue
        vistos.add(key)
        groups.append(list(members))
    return [[concepts[i] for i in group] for group in groups]


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


def dedupe_group_list(groups: list[list[dict]]) -> list[list[dict]]:
    """Quita grupos repetidos o contenidos en otro, preservando el orden."""
    salida: list[list[dict]] = []
    firmas: list[set[str]] = []
    for group in groups:
        ids = {c.get("id", "") for c in group}
        if any(ids <= previa for previa in firmas):
            continue
        salida.append(group)
        firmas.append(ids)
    return salida


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
        # El ganador de _merge_group puede ser cualquiera del grupo, así que su
        # `id` puede no coincidir con la clave canónica. En la corrida medida eso
        # dejó un concepto guardado bajo la clave `parasocial_co_creation_index_pcci`
        # cuyo campo id decía `parasocial_co_creation`: el id_map apuntaba a un id
        # inexistente en la salida.
        winner["id"] = canonical
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


def _tokens(text: str) -> set[str]:
    return {tok for tok in normalize(text).split() if len(tok) >= 4}


def dedupe_by_text(
    items: list[dict],
    text_fields: list[str],
    threshold: float = 0.75,
    min_tokens: int = 4,
    merge_lists: tuple[str, ...] = (),
    max_items: int | None = None,
    score_key=None,
) -> tuple[list[dict], int]:
    """Unifica items que dicen esencialmente lo mismo, aunque tengan ids distintos.

    Nace de un problema medido: la capa 4 corre por lotes y el tope de tesis del
    prompt es POR LOTE, así que con nueve lotes salieron 34 tesis y 20 marcos
    para un paper de doce páginas. El dedup por id no ayuda, porque dos
    fragmentos que hablan de la misma tesis la nombran distinto.

    Se comparan los tokens significativos del enunciado con índice de Jaccard.
    Cuando dos items se parecen por encima del umbral, se conserva el mejor y se
    fusionan sus listas (argumentos a favor, en contra, criterios).

    El umbral es alto a propósito. Dos formulaciones de la misma tesis puntúan
    entre 0.8 y 1.0 porque son reordenamientos del mismo enunciado; dos tesis
    distintas sobre los mismos conceptos comparten vocabulario sin llegar ahí.
    Bajarlo a 0.6 en pruebas fusionaba afirmaciones que no decían lo mismo, y
    ese error es peor que dejar un duplicado: borra una posición defendible.

    Los enunciados con menos de `min_tokens` palabras distintivas no se unifican
    POR PARECIDO, pero sí por coincidencia exacta normalizada.

    Esa distinción es el arreglo de v2.2.4. En la corrida medida salieron tres
    marcos con la etiqueta IDÉNTICA "Resonant Amplification Framework (RAF)" y
    ninguno se unió: esa etiqueta produce solo tres tokens de cuatro o más
    caracteres (resonant, amplification, framework), quedaba por debajo de
    `min_tokens` y se saltaba el dedup entero. La guarda que existía para no
    fusionar enunciados cortos ambiguos terminó desactivando la unificación de
    marcos por completo, porque los nombres de marco son cortos por naturaleza.

    Ahora una coincidencia exacta de la forma normalizada siempre unifica: dos
    etiquetas idénticas no son un caso dudoso.

    Devuelve (items, cuántos se descartaron).
    """
    if not items:
        return [], 0

    def texto(item: dict) -> str:
        return " ".join(str(item.get(f) or "") for f in text_fields)

    ordenados = sorted(items, key=score_key, reverse=True) if score_key else list(items)

    conservados: list[dict] = []
    firmas: list[set[str]] = []
    exactas: list[str] = []
    fusionados = 0

    for item in ordenados:
        crudo = normalize(texto(item))
        firma = _tokens(texto(item))
        encontrado = None

        # Coincidencia exacta: unifica siempre, sin importar la longitud.
        if crudo:
            for i, previo in enumerate(exactas):
                if previo and previo == crudo:
                    encontrado = i
                    break

        # Parecido: solo con suficiente texto para decidir con criterio.
        if encontrado is None and len(firma) >= min_tokens:
            for i, previa in enumerate(firmas):
                if len(previa) < min_tokens:
                    continue
                union = firma | previa
                if not union:
                    continue
                if len(firma & previa) / len(union) >= threshold:
                    encontrado = i
                    break

        if encontrado is None:
            conservados.append(dict(item))
            firmas.append(firma)
            exactas.append(crudo)
            continue

        destino = conservados[encontrado]
        # Quien absorbe hereda el id: cualquier referencia al id absorbido
        # tiene que poder reescribirse. Sin esto, al unir tres marcos RAF los
        # rivales de los otros marcos seguían apuntando al id que desapareció.
        alias = item.get("id")
        if alias and alias != destino.get("id"):
            destino.setdefault("_alias_ids", []).append(alias)
        for campo in merge_lists:
            existentes = list(destino.get(campo) or [])
            vistos = {normalize(str(v)) for v in existentes}
            for valor in (item.get(campo) or []):
                if normalize(str(valor)) not in vistos:
                    existentes.append(valor)
                    vistos.add(normalize(str(valor)))
            destino[campo] = existentes
        firmas[encontrado] = firmas[encontrado] | firma
        fusionados += 1

    # Reescribir las referencias cruzadas hacia los ids que sobrevivieron.
    remap: dict[str, str] = {}
    for item in conservados:
        for alias in item.pop("_alias_ids", []):
            remap[alias] = item.get("id")
    if remap:
        for item in conservados:
            for campo in merge_lists:
                valor = item.get(campo)
                if isinstance(valor, list):
                    vistos, nuevo = set(), []
                    for v in valor:
                        destino_id = remap.get(v, v)
                        if destino_id != item.get("id") and destino_id not in vistos:
                            vistos.add(destino_id)
                            nuevo.append(destino_id)
                    item[campo] = nuevo

    descartados = fusionados
    if max_items is not None and len(conservados) > max_items:
        descartados += len(conservados) - max_items
        conservados = conservados[:max_items]

    return conservados, descartados


def strip_dangling_refs(
    items: list[dict],
    fields: list[str],
    valid_ids: set[str],
) -> int:
    """Quita referencias a ids inexistentes. Devuelve cuántas quitó.

    Nace de un defecto medido: un marco declaraba tres rivales
    (`framework_relational_hci`, `framework_third_wave_hci`, `framework_casa`)
    que no existen en ninguna parte del documento. La capa 4 corre por lotes,
    cada lote inventa ids que otro lote no produjo, y después el tope global
    descarta marcos dejando más referencias huérfanas.

    Un consumidor que elija pares de marcos rivales para una actividad de debate
    recibiría un marco enfrentado a un id inexistente.
    """
    quitadas = 0
    for item in items or []:
        for field in fields:
            valor = item.get(field)
            if not isinstance(valor, list):
                continue
            limpio = [v for v in valor if v in valid_ids and v != item.get("id")]
            quitadas += len(valor) - len(limpio)
            item[field] = limpio
    return quitadas


def normalize_domain(text: str) -> str:
    """Forma canónica de un dominio, para poder compararlos de verdad.

    En la corrida medida convivían "interacción humano‑computadora" con guion no
    separable (U+2011) y "interacción humano-computadora" con guion normal
    (U+002D). Se ven iguales y no lo son. La verificación de distancia de
    transferencia compara dominios, así que las etiquetas cercana/media/lejana
    se calculaban contra cadenas que solo parecían coincidir.
    """
    if not text:
        return ""
    limpio = unicodedata.normalize("NFKC", str(text))
    for guion in ("\u2010", "\u2011", "\u2012", "\u2013", "\u2014", "\u2212"):
        limpio = limpio.replace(guion, "-")
    limpio = limpio.replace("\u00a0", " ")
    limpio = " ".join(limpio.split()).strip(" .,;:")
    return limpio.lower()
