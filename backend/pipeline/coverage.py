"""
pipeline/coverage.py — v2.2.4

Cálculo de la capa 6: densidades reales, cobertura de señal y disponibilidad
de familias de mecánicas.

En v1 `argumentative_richness` y `case_density` estaban fijados en 0.0. Cuando
las capas 4 y 5 no existían eso era un placeholder honesto; una vez que
producen datos, es un bug: la Decisión Q de 06_materia_prima (qué mecánicas se
activan para este curso) sigue sin poder tomarse aunque el input ya esté ahí.

`signal_coverage` responde una pregunta distinta y complementaria: no "qué
mecánicas se activan" sino **qué celdas del perfil van a quedar vacías y por
qué**. Es lo que permite avisarle al profesor antes de que sus estudiantes
generen datos que el sistema no puede interpretar.
"""
from __future__ import annotations


def _ratio(n: float, target: float) -> float:
    if target <= 0:
        return 0.0
    return max(0.0, min(1.0, n / target))


def compute_densities(data: dict) -> dict:
    concepts = data.get("concepts", [])
    relations = data.get("relations", [])
    repertoires = data.get("repertoires", [])
    theses = data.get("theses", [])
    cases = data.get("cases", [])
    scenarios = data.get("scenarios", [])
    n = max(len(concepts), 1)

    enriched = sum(1 for c in concepts if c.get("is_enriched"))

    return {
        # ~1.5 relaciones por concepto es un grafo sano
        "relational_density": _ratio(len(relations), n * 1.5),
        # ~0.5 tesis por concepto marca un paper con debate real
        "argumentative_richness": _ratio(len(theses), n * 0.5),
        # casos + escenarios derivados; ~1 por concepto para sostener la familia E
        "case_density": _ratio(len(cases) + len(scenarios), n * 1.0),
        # ~0.6 repertorios por concepto
        "repertoire_density": _ratio(len(repertoires), n * 0.6),
        "enrichment_coverage": _ratio(enriched, n),
    }


def compute_signal_coverage(data: dict) -> list[dict]:
    """Una entrada por cada una de las doce dimensiones del enum (doc 01 §2.0)."""
    concepts = data.get("concepts", [])
    relations = data.get("relations", [])
    repertoires = data.get("repertoires", [])
    theses = data.get("theses", [])
    frameworks = data.get("frameworks", [])
    cases = data.get("cases", [])
    scenarios = data.get("scenarios", [])
    axes = data.get("axes", [])
    n = max(len(concepts), 1)

    cases_con_gold = sum(1 for c in cases if (c.get("resolucion_esperada") or "").strip())
    reps_con_contraste = sum(1 for r in repertoires if (r.get("contraste_cientifico") or "").strip())
    conceptos_atomicos = sum(1 for c in concepts if c.get("difficulty") == "basico")
    conceptos_con_sinonimos = sum(
        1 for c in concepts if c.get("sinonimos") or c.get("variantes_terminologicas")
    )
    lejanos = sum(1 for s in scenarios if s.get("distancia") == "lejana")

    out: list[dict] = []

    def add(dim: str, cobertura: float, cuello: str = ""):
        out.append({
            "dimension": dim,
            "cobertura": round(max(0.0, min(1.0, cobertura)), 2),
            "cuello_de_botella": cuello if cobertura < 0.6 else "",
        })

    add("recuperacion", _ratio(len(concepts), 8),
        "Pocos conceptos extraídos: el documento puede ser demasiado corto o poco estructurado.")

    add("relacion", _ratio(len(relations), n * 1.5),
        "Grafo escaso: las familias C y D tendrán pocas aristas gold sobre las que calificar.")

    transfer = 0.6 * _ratio(cases_con_gold, n * 0.6) + 0.4 * _ratio(len(scenarios), n * 0.8)
    add("transferencia", transfer,
        "Faltan casos con `resolucion_esperada` o escenarios derivados: la familia E "
        "no tiene gold contra el que calificar y se agota en una pasada.")

    add("anclaje", _ratio(reps_con_contraste, n * 0.5),
        "Repertorios sin `contraste_cientifico`: la señal de anclaje se emite pero el "
        "Contextualizador no tiene con qué producir feedback de coexistencia.")

    add("automatizacion", _ratio(conceptos_atomicos, n * 0.3) * (0.5 + 0.5 * _ratio(conceptos_con_sinonimos, n)),
        "Pocos conceptos atómicos o sin sinónimos: A1 y A3 no pueden generar ítems "
        "rápidos y calificables, que es lo que la latencia necesita para ser interpretable.")

    # Las dimensiones de proceso no dependen del contenido extraído...
    for dim in ("calibracion", "srl_accion", "srl_autorreflexion",
                "persistencia", "engagement"):
        add(dim, 1.0)

    # ...salvo planeación, que sí depende. Elegir qué estudiar y en qué orden
    # solo es evaluable si existe un orden con sentido contra el que comparar.
    # Con un grafo de prerrequisitos casi vacío, la secuencia sugerida es
    # alfabética y declararla al 100% sería mentir sobre lo que se puede medir.
    calidad = data.get("_sequence_quality") or {}
    nivel = calidad.get("nivel", "buena")
    cobertura_plan = {"buena": 1.0, "parcial": 0.5, "no_confiable": 0.15}.get(nivel, 1.0)
    add("srl_planeacion", cobertura_plan,
        calidad.get("motivo") or
        "El grafo de prerrequisitos es demasiado escaso para ordenar el curso.")

    # Articulación depende de que haya objetos sobre los que producir.
    add("articulacion", min(1.0, 0.4 + 0.6 * _ratio(len(theses) + len(cases), n * 0.8)),
        "Poco material de producción abierta: la articulación solo la capturan las "
        "familias F y H, que necesitan tesis o casos sobre los que escribir.")

    # Señal extra útil aunque no sea dimensión: transferencia lejana.
    # Umbral absoluto: con dos o tres escenarios no se puede declarar cobertura
    # plena de transferencia lejana por mucho que la proporción salga alta.
    out.append({
        "dimension": "transferencia:lejana",
        "cobertura": round(_ratio(lejanos, max(3.0, len(scenarios) * 0.3)), 2),
        "cuello_de_botella": (
            "Sin escenarios de otro dominio no se puede distinguir transferencia real "
            "de reconocimiento de superficie."
            if lejanos < 3 else ""
        ),
    })

    if not axes:
        out.append({
            "dimension": "relacion:espacio_atributos",
            "cobertura": 0.0,
            "cuello_de_botella": "Sin ejes consolidados, C4 MAPEAR no es instanciable.",
        })
    if not frameworks:
        # Con tesis pero sin marcos, F2 es instanciable y F3 pierde su segunda
        # señal: la cobertura se topa a la mitad en vez de reportarse completa.
        out.append({
            "dimension": "relacion:argumento",
            "cobertura": round(min(0.5, _ratio(len(theses), n * 0.5)), 2),
            "cuello_de_botella": "Sin marcos rivales, F3 REFUTAR pierde su segunda señal.",
        })

    return out


def compute_family_availability(data: dict) -> list[dict]:
    """Qué familias del catálogo de mecánicas puede instanciar este curso."""
    concepts = data.get("concepts", [])
    relations = data.get("relations", [])
    repertoires = data.get("repertoires", [])
    theses = data.get("theses", [])
    frameworks = data.get("frameworks", [])
    cases = data.get("cases", [])
    scenarios = data.get("scenarios", [])
    axes = data.get("axes", [])
    clusters = data.get("clusters", [])

    enriched_with_distinctions = sum(1 for c in concepts if c.get("distinctions"))
    cases_con_gold = [c for c in cases if (c.get("resolucion_esperada") or "").strip()]
    ordenables = [r for r in relations if r.get("relation_type") in {"causa", "requiere"}]
    contrastes = [r for r in relations if r.get("relation_type") == "contrasta"]

    checks = [
        ("A", len(concepts) >= 4, ["A1", "A2", "A3", "A4"],
         "Necesita al menos 4 conceptos."),
        ("B", len(repertoires) >= 2 or enriched_with_distinctions >= 2, ["B1", "B2", "B3"],
         "Necesita repertorios o conceptos enriquecidos con `distinctions` para "
         "caracterizar distractores; sin eso B1 emite una sola dimensión."),
        ("C", len(relations) >= 5, ["C1", "C2", "C3", "C5"] + (["C4"] if axes else []),
         "Necesita al menos 5 relaciones." + ("" if axes else " C4 además requiere ejes consolidados.")),
        ("D", len(relations) >= 8 and len(clusters) >= 1, ["D1", "D2", "D3"],
         "Necesita un grafo con al menos 8 aristas y clusters calculados."),
        ("E", len(cases_con_gold) >= 3, ["E1", "E2", "E3", "E4", "E5"],
         "Necesita al menos 3 casos con `resolucion_esperada`. "
         + ("Sin escenarios derivados se agota en una pasada." if len(scenarios) < 3 else "")),
        ("F", len(theses) >= 2, ["F1", "F4", "F5"] + (["F2", "F3"] if frameworks else []),
         "F1/F4/F5 solo necesitan conceptos; F2 y F3 necesitan tesis y marcos rivales."),
        ("G", True, ["G1", "G2", "G3", "G4", "G5"],
         "Independiente del contenido: la calibración es metacognitiva."),
        ("H", len(theses) >= 1 or len(relations) >= 5, ["H1", "H2", "H3", "H4", "H5"],
         "Necesita un objeto en disputa: una tesis o un grafo con aristas discutibles."),
        ("I", True, ["I1", "I2", "I3", "I4", "I5"],
         "Independiente del contenido: la regulación es de sesión."),
    ]

    out = []
    for family, ok, mechanics, reason in checks:
        out.append({
            "family": family,
            "available": bool(ok),
            "reason": reason,
            "mechanic_ids": mechanics if ok else [],
        })
    # F1/F4/F5 siguen disponibles aunque no haya tesis.
    for entry in out:
        if entry["family"] == "F" and not entry["available"]:
            entry["available"] = len(concepts) >= 4
            entry["mechanic_ids"] = ["F1", "F4", "F5"] if entry["available"] else []
    return out


def recommend_modalities(data: dict) -> list[str]:
    concepts = data.get("concepts", [])
    relations = data.get("relations", [])
    theses = data.get("theses", [])
    frameworks = data.get("frameworks", [])

    modalities = ["individual"]
    if any(c.get("is_threshold") for c in concepts):
        modalities.append("colaborativo")
    if any(r.get("relation_type") in {"contradice", "contrasta"} for r in relations):
        modalities.append("debate")
    if len(theses) >= 2 and frameworks:
        modalities.append("argumentacion")
    return modalities
