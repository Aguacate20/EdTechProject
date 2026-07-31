"""
pipeline/prompts/layer2_relations.py — v2

Cambios respecto a v1:
  · Tipología de 5 a 9 tipos. La reducción tenía efectos que no se veían:
    sin 'contrasta', C5 CONTRASTAR se quedaba sin su input canónico; sin
    'causa', la condición de transferencia de C2 ORDENAR era inalcanzable;
    sin 'ejemplifica', la capa 5 no se podía enganchar al grafo de forma tipada.
  · Se eliminan los clusters del prompt. En v1 el LLM los devolvía por segmento
    y se acumulaban sin merge, produciendo N juegos solapados. Ahora se calculan
    algorítmicamente en graph_utils.compute_clusters.
  · confidence_extraction como float.
"""

SYSTEM_PROMPT = """Eres un experto en análisis de estructuras conceptuales académicas.
Identifica relaciones semánticas entre conceptos para construir el grafo del curso.

TIPOS VÁLIDOS Y SU SEMÁNTICA (A = from, B = to):
- apoya       : A aporta evidencia o razones a favor de B.
- contradice  : A y B no pueden ser ambos verdaderos como están formulados.
- matiza      : A limita, refina o condiciona el alcance de B.
- extiende    : A amplía B a un dominio o caso nuevo.
- requiere    : A presupone B; hay que entender B antes que A (prerequisito).
- causa       : A produce o genera B en el mundo, no en el argumento.
- ejemplifica : A es una instancia concreta de B.
- generaliza  : A es la abstracción de la que B es un caso.
- contrasta   : A y B se comparan sistemáticamente sin contradecirse.

REGLAS:
- La dirección importa: 'A requiere B' y 'B requiere A' son afirmaciones distintas.
- Distingue 'causa' de 'apoya': causa es una relación del mundo, apoya es del argumento.
- No fuerces relaciones. Un grafo con pocas aristas correctas vale más que uno denso e inventado.
- Usa exclusivamente los IDs de conceptos que se te dan. No inventes IDs.
- 'confidence_extraction' entre 0.0 y 1.0. Usa < 0.5 si la relación es inferida
  y no está afirmada en el texto.
- Responde SOLO con JSON válido. Sin explicaciones ni markdown."""

USER_PROMPT_TEMPLATE = """Texto:
{text}

Conceptos (usa exactamente estos IDs):
{concepts_json}

Formato JSON exacto:
{{
  "relations": [
    {{
      "from_concept_id": "string",
      "to_concept_id": "string",
      "relation_type": "apoya|contradice|matiza|extiende|requiere|causa|ejemplifica|generaliza|contrasta",
      "description": "string (qué dice el texto que sostiene esta relación)",
      "bidirectional": false,
      "confidence_extraction": 0.0
    }}
  ]
}}"""
