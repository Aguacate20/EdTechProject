"""
pipeline/registry.py — NUEVO en v2.3

Registro de las 40 mecánicas primarias: qué material necesita cada una y qué
señal emite.

Este archivo es la traducción a código de los CONTRATO DE SEÑAL del documento
08. Existe porque hasta ahora ese contrato vivía solo en prosa, y el juego no
tenía forma de saber —sin que alguien lo transcribiera a mano en cincuenta
sitios— qué dimensión emite A1, con qué peso, ni qué materia prima necesita
para poder instanciarse.

Cada entrada declara:
  · `requiere`: qué debe existir en la materia prima para que la mecánica sea
    instanciable. El compilador lo evalúa y produce un veredicto por mecánica,
    no por familia: dentro de la familia E, E1 puede estar lista y E5 no.
  · `señales`: las dimensiones que emite, con modalidad, vía y peso base. El
    peso evidencial real se calcula en tiempo de ejecución aplicando f_azar,
    f_hints, f_scaffold y f_via (doc 08 §0.4), pero el peso base y la modalidad
    se fijan acá.
"""
from __future__ import annotations

# Peso base por modalidad (doc 08 §0.4).
PESO_MODALIDAD = {
    "reconocimiento": 0.35,
    "produccion_guiada": 0.60,
    "accion_estructural": 0.70,
    "produccion_libre": 0.85,
    "declaracion_metacognitiva": None,  # no alimenta la matriz de contenido
}


def _s(dimension, forma="escalar", modalidad=None, via="decision_declarada",
       target="concepto", condicion=None, distancia=None):
    return {
        "dimension": dimension,
        "forma": forma,
        "modalidad": modalidad,
        "peso_base": PESO_MODALIDAD.get(modalidad) if modalidad else None,
        "via": via,
        "target_tipo": target,
        "condicion": condicion,
        "distancia": distancia,
    }


# `requiere` usa claves que el compilador sabe evaluar:
#   concepto            → al menos N conceptos con definición
#   sinonimos           → conceptos con sinónimos (para calificar texto abierto)
#   distractores        → pool de distractores caracterizados
#   arista              → relaciones tipadas
#   arista_tipo:<x>     → relaciones de un tipo concreto
#   cluster             → grupos calculados
#   eje                 → ejes de atributos
#   repertorio          → repertorios con contraste científico
#   caso_gold           → casos con resolución esperada
#   caso_multi          → casos con dos o más conceptos
#   caso_error          → casos o escenarios con error incrustado
#   escenario           → variantes derivadas
#   escenario_lejano    → variantes de otro dominio
#   tesis               → tesis con criterios de defensa
#   marco_rival         → marcos con al menos un rival válido
#   juez                → requiere evaluación por LLM en runtime
#   peer                → requiere co-presencia de otro estudiante
#   ninguno             → independiente del contenido

REGISTRY: dict[str, dict] = {
    # ── Familia A · Recuperación ──────────────────────────────────────────
    "A1": {"nombre": "RECONOCER", "familia": "A",
           "requiere": {"concepto": 4, "distractores": 1},
           "senales": [_s("recuperacion", modalidad="reconocimiento"),
                       _s("anclaje", forma="observacional", target="repertorio",
                          condicion="el distractor elegido trae repertoire_id"),
                       _s("automatizacion", forma="temporal",
                          condicion="baseline_n >= 5")]},
    "A2": {"nombre": "COMPLETAR", "familia": "A",
           "requiere": {"concepto": 4},
           "senales": [_s("recuperacion", modalidad="produccion_guiada")]},
    "A3": {"nombre": "EVOCAR", "familia": "A",
           "requiere": {"concepto": 4, "sinonimos": 1},
           "senales": [_s("recuperacion", modalidad="produccion_guiada"),
                       _s("automatizacion", forma="temporal",
                          condicion="baseline_n >= 5")]},
    "A4": {"nombre": "DEFINIR", "familia": "A",
           "requiere": {"concepto": 4, "juez": True},
           "senales": [_s("recuperacion", modalidad="produccion_libre"),
                       _s("relacion", modalidad="produccion_libre", target="arista",
                          condicion="el juez detecta conexión explícita"),
                       _s("anclaje", forma="observacional", target="repertorio",
                          condicion="el juez detecta un repertorio")]},

    # ── Familia B · Discriminación ────────────────────────────────────────
    "B1": {"nombre": "DISTINGUIR", "familia": "B",
           "requiere": {"distractores": 1},
           "senales": [_s("recuperacion", modalidad="reconocimiento"),
                       _s("relacion", modalidad="reconocimiento", target="arista",
                          condicion="el distractor encarna un concepto vecino"),
                       _s("anclaje", forma="observacional", target="repertorio")]},
    "B2": {"nombre": "CLASIFICAR", "familia": "B",
           "requiere": {"caso_gold": 3},
           "senales": [_s("recuperacion", modalidad="reconocimiento"),
                       _s("transferencia", modalidad="reconocimiento", target="caso"),
                       _s("anclaje", forma="observacional", target="repertorio")]},
    "B3": {"nombre": "TAGGEAR", "familia": "B",
           "requiere": {"caso_gold": 3},
           "senales": [_s("recuperacion", modalidad="produccion_guiada"),
                       _s("transferencia", modalidad="produccion_guiada",
                          distancia="cercana"),
                       _s("anclaje", forma="observacional", target="repertorio")]},

    # ── Familia C · Relación ──────────────────────────────────────────────
    "C1": {"nombre": "CONECTAR", "familia": "C",
           "requiere": {"arista": 5},
           "senales": [_s("relacion", modalidad="reconocimiento", target="arista"),
                       _s("anclaje", forma="observacional", target="repertorio"),
                       _s("automatizacion", forma="temporal", target="arista")]},
    "C2": {"nombre": "ORDENAR", "familia": "C",
           "requiere": {"arista_tipo:causa": 2},
           "senales": [_s("relacion", modalidad="produccion_guiada", target="arista"),
                       _s("relacion", modalidad="produccion_guiada", target="cluster"),
                       _s("transferencia", modalidad="produccion_guiada", target="cluster",
                          condicion="el orden es causal o lógico", distancia="cercana")]},
    "C3": {"nombre": "AGRUPAR", "familia": "C",
           "requiere": {"cluster": 1, "concepto": 6},
           "senales": [_s("relacion", modalidad="accion_estructural", target="cluster"),
                       _s("anclaje", forma="observacional", target="repertorio")]},
    "C4": {"nombre": "MAPEAR", "familia": "C",
           "requiere": {"eje": 2},
           "senales": [_s("relacion", modalidad="accion_estructural", target="cluster"),
                       _s("relacion", modalidad="accion_estructural", target="arista")]},
    "C5": {"nombre": "CONTRASTAR", "familia": "C",
           "requiere": {"arista_tipo:contrasta": 1, "juez": True},
           "senales": [_s("relacion", modalidad="produccion_libre", target="arista"),
                       _s("anclaje", forma="observacional", target="repertorio")]},

    # ── Familia D · Estructura ────────────────────────────────────────────
    "D1": {"nombre": "CONSTRUIR", "familia": "D",
           "requiere": {"arista": 8, "cluster": 1},
           "senales": [_s("relacion", modalidad="accion_estructural", target="arista"),
                       _s("relacion", modalidad="accion_estructural", target="cluster"),
                       _s("anclaje", forma="observacional", target="repertorio")]},
    "D2": {"nombre": "EXTENDER", "familia": "D",
           "requiere": {"arista": 8},
           "senales": [_s("relacion", modalidad="accion_estructural", target="arista"),
                       _s("transferencia", modalidad="accion_estructural",
                          condicion="el concepto agregado es externo", distancia="media")]},
    "D3": {"nombre": "CRITICAR", "familia": "D",
           "requiere": {"arista": 8, "juez": True},
           "senales": [_s("relacion", modalidad="produccion_libre", target="arista"),
                       _s("transferencia", modalidad="produccion_libre", target="cluster",
                          distancia="media"),
                       _s("articulacion", modalidad="produccion_libre", target="arista"),
                       _s("anclaje", forma="observacional", target="repertorio")]},

    # ── Familia E · Transferencia ─────────────────────────────────────────
    "E1": {"nombre": "PREDECIR", "familia": "E",
           "requiere": {"caso_gold": 2},
           "senales": [_s("transferencia", modalidad="produccion_guiada", target="caso"),
                       _s("anclaje", forma="observacional", target="repertorio")]},
    "E2": {"nombre": "DIAGNOSTICAR", "familia": "E",
           "requiere": {"caso_error": 1, "juez": True},
           "senales": [_s("transferencia", modalidad="produccion_libre", target="caso"),
                       _s("relacion", modalidad="produccion_libre", target="arista",
                          condicion="el error consiste en confundir dos conceptos"),
                       _s("articulacion", modalidad="produccion_libre", target="caso"),
                       _s("anclaje", forma="observacional", target="repertorio")]},
    "E3": {"nombre": "APLICAR", "familia": "E",
           "requiere": {"caso_gold": 3},
           "senales": [_s("transferencia", modalidad="produccion_guiada", target="caso"),
                       _s("anclaje", forma="observacional", target="repertorio")]},
    "E4": {"nombre": "GENERAR EJEMPLO", "familia": "E",
           "requiere": {"concepto": 4, "juez": True},
           "senales": [_s("transferencia", modalidad="produccion_libre", distancia="lejana"),
                       _s("articulacion", modalidad="produccion_libre"),
                       _s("anclaje", forma="observacional", target="repertorio")]},
    "E5": {"nombre": "RESOLVER", "familia": "E",
           "requiere": {"caso_multi": 1, "juez": True},
           "senales": [_s("transferencia", modalidad="produccion_libre", target="caso"),
                       _s("relacion", modalidad="produccion_libre", target="cluster"),
                       _s("articulacion", modalidad="produccion_libre", target="caso"),
                       _s("anclaje", forma="observacional", target="repertorio")]},

    # ── Familia F · Producción ────────────────────────────────────────────
    "F1": {"nombre": "EXPLICAR", "familia": "F",
           "requiere": {"concepto": 4, "juez": True},
           "senales": [_s("recuperacion", modalidad="produccion_libre"),
                       _s("relacion", modalidad="produccion_libre", target="arista"),
                       _s("articulacion", modalidad="produccion_libre"),
                       _s("anclaje", forma="observacional", target="repertorio")]},
    "F2": {"nombre": "ARGUMENTAR", "familia": "F",
           "requiere": {"tesis": 1, "juez": True},
           "senales": [_s("relacion", modalidad="produccion_libre", target="argumento"),
                       _s("articulacion", modalidad="produccion_libre", target="argumento"),
                       _s("transferencia", modalidad="produccion_libre", target="argumento",
                          distancia="media"),
                       _s("anclaje", forma="observacional", target="repertorio")]},
    "F3": {"nombre": "REFUTAR", "familia": "F",
           "requiere": {"tesis": 1, "marco_rival": 1, "juez": True},
           "senales": [_s("relacion", modalidad="produccion_libre", target="argumento"),
                       _s("relacion", modalidad="produccion_libre", target="cluster"),
                       _s("articulacion", modalidad="produccion_libre", target="argumento"),
                       _s("anclaje", forma="observacional", target="repertorio")]},
    "F4": {"nombre": "REFORMULAR", "familia": "F",
           "requiere": {"concepto": 4, "juez": True},
           "senales": [_s("articulacion", modalidad="produccion_libre"),
                       _s("recuperacion", modalidad="produccion_libre",
                          condicion="SOLO evidencia negativa: precisión perdida")]},
    "F5": {"nombre": "TRADUCIR", "familia": "F",
           "requiere": {"concepto": 4, "juez": True},
           "senales": [_s("transferencia", modalidad="produccion_libre", distancia="media"),
                       _s("articulacion", modalidad="produccion_libre"),
                       _s("anclaje", forma="observacional", target="repertorio")]},

    # ── Familia G · Calibración (independiente del contenido) ─────────────
    "G1": {"nombre": "APOSTAR", "familia": "G", "requiere": {"ninguno": True},
           "senales": [_s("calibracion", forma="calibracion",
                          modalidad="declaracion_metacognitiva")]},
    "G2": {"nombre": "ESTIMAR", "familia": "G", "requiere": {"ninguno": True},
           "senales": [_s("calibracion", forma="calibracion", target="sesion",
                          modalidad="declaracion_metacognitiva")]},
    "G3": {"nombre": "ANTICIPAR DIFICULTAD", "familia": "G", "requiere": {"ninguno": True},
           "senales": [_s("calibracion", forma="calibracion",
                          modalidad="declaracion_metacognitiva")]},
    "G4": {"nombre": "EXPLICAR ERROR PROPIO", "familia": "G", "requiere": {"ninguno": True},
           "senales": [_s("srl_autorreflexion", target="sesion",
                          modalidad="declaracion_metacognitiva"),
                       _s("anclaje", forma="observacional", target="repertorio"),
                       _s("articulacion", modalidad="produccion_libre")]},
    "G5": {"nombre": "MARCAR DIFICULTAD", "familia": "G", "requiere": {"ninguno": True},
           "senales": [_s("srl_autorreflexion", target="sesion",
                          modalidad="declaracion_metacognitiva"),
                       _s("calibracion", forma="calibracion",
                          modalidad="declaracion_metacognitiva")]},

    # ── Familia H · Social ────────────────────────────────────────────────
    "H1": {"nombre": "JUSTIFICAR A PEER", "familia": "H",
           "requiere": {"peer": True, "concepto": 4},
           "senales": [_s("articulacion", modalidad="produccion_libre"),
                       _s("recuperacion", modalidad="produccion_libre"),
                       _s("anclaje", forma="observacional", target="repertorio")]},
    "H2": {"nombre": "NEGOCIAR", "familia": "H",
           "requiere": {"peer": True, "arista": 5},
           "senales": [_s("articulacion", modalidad="produccion_libre"),
                       _s("relacion", modalidad="produccion_libre", target="arista",
                          condicion="el cierre NO fue por sumisión"),
                       _s("srl_accion", forma="observacional", target="sesion")]},
    "H3": {"nombre": "ENSEÑAR", "familia": "H",
           "requiere": {"peer": True, "concepto": 4},
           "senales": [_s("articulacion", modalidad="produccion_libre"),
                       _s("recuperacion", modalidad="produccion_libre")]},
    "H4": {"nombre": "EVALUAR PEER", "familia": "H",
           "requiere": {"peer": True, "tesis": 1},
           "senales": [_s("srl_autorreflexion", target="sesion",
                          modalidad="declaracion_metacognitiva"),
                       _s("transferencia", modalidad="produccion_guiada", target="argumento")]},
    "H5": {"nombre": "DEFENDER VS PEER", "familia": "H",
           "requiere": {"peer": True, "tesis": 1},
           "senales": [_s("relacion", modalidad="produccion_libre", target="argumento"),
                       _s("articulacion", modalidad="produccion_libre", target="argumento"),
                       _s("srl_autorreflexion", target="sesion",
                          modalidad="declaracion_metacognitiva"),
                       _s("persistencia", target="global")]},

    # ── Familia I · Regulación (independiente del contenido) ──────────────
    "I1": {"nombre": "PLANEAR", "familia": "I", "requiere": {"ninguno": True},
           "senales": [_s("srl_planeacion", target="sesion",
                          modalidad="declaracion_metacognitiva")]},
    "I2": {"nombre": "MONITOREAR", "familia": "I", "requiere": {"ninguno": True},
           "senales": [_s("srl_accion", forma="observacional", target="sesion")]},
    "I3": {"nombre": "PEDIR AYUDA", "familia": "I", "requiere": {"ninguno": True},
           "senales": [_s("srl_accion", forma="observacional", target="sesion")]},
    "I4": {"nombre": "REFLEXIONAR", "familia": "I", "requiere": {"ninguno": True},
           "senales": [_s("srl_autorreflexion", target="sesion",
                          modalidad="declaracion_metacognitiva"),
                       _s("articulacion", modalidad="produccion_libre")]},
    "I5": {"nombre": "CONSOLIDAR", "familia": "I", "requiere": {"ninguno": True},
           "senales": [_s("srl_autorreflexion", target="sesion",
                          modalidad="declaracion_metacognitiva"),
                       _s("articulacion", modalidad="produccion_libre", target="cluster"),
                       _s("recuperacion", modalidad="produccion_libre"),
                       _s("calibracion", forma="calibracion",
                          modalidad="declaracion_metacognitiva")]},
}

FAMILIAS = {
    "A": "Recuperar", "B": "Discriminar", "C": "Relacionar", "D": "Estructurar",
    "E": "Transferir", "F": "Producir", "G": "Calibrar", "H": "Colaborar",
    "I": "Regular",
}

# Etiqueta legible de cada requisito, para explicar por qué algo no está listo.
REQUISITO_LABEL = {
    "concepto": "conceptos con definición",
    "sinonimos": "conceptos con sinónimos",
    "distractores": "conceptos con distractores caracterizados",
    "arista": "relaciones entre conceptos",
    "cluster": "grupos temáticos",
    "eje": "ejes de atributos",
    "repertorio": "intuiciones cotidianas",
    "caso_gold": "casos con resolución esperada",
    "caso_multi": "casos que combinan varios conceptos",
    "caso_error": "casos con un error incrustado",
    "escenario": "variantes derivadas",
    "escenario_lejano": "variantes de otro dominio",
    "tesis": "tesis defendibles",
    "marco_rival": "marcos teóricos con rival",
    "juez": "evaluación por IA en tiempo de juego",
    "peer": "otro estudiante presente",
    "ninguno": "nada del documento",
}
