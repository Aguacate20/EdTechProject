"""
pipeline/prompts/layer2b_axes.py — NUEVO en v2

Consolidación de subdimensiones sueltas en ejes bipolares compartidos.

Sin esto, C4 MAPEAR no es instanciable con materia prima automática: la
mecánica necesita ejes y un orden relativo gold en cada eje, y no había ninguna
capa de atributos dimensionales.

El valor no se agota en C4. Convertir el grafo de "nodos y aristas" en "nodos,
aristas y espacio" da al Contextualizador vocabulario para explicar POR QUÉ dos
conceptos se parecen, y hace que los clusters tengan un criterio explicable en
vez de ser el resultado ciego de un algoritmo de comunidades.
"""

SYSTEM_PROMPT = """Eres un experto en análisis conceptual.
Recibes conceptos de un curso con sus subdimensiones. Tu tarea es consolidar
esas subdimensiones sueltas en unos pocos EJES BIPOLARES compartidos que sirvan
para ubicar los conceptos en un espacio común.

REGLAS:
- Entre 2 y 5 ejes. Menos de 2 no define un espacio; más de 5 no es usable.
- Un eje es bipolar: tiene dos polos opuestos y nombrados (ej: "concreto" ↔ "abstracto",
  "individual" ↔ "colectivo", "descriptivo" ↔ "normativo").
- Los ejes deben ser del DOMINIO del paper, no genéricos. Prefiere un eje que
  solo tenga sentido en este campo antes que uno aplicable a cualquier cosa.
- Ubica CADA concepto en CADA eje con un número entre 0.0 (polo bajo) y 1.0 (polo alto).
- 'justificacion' en una frase corta, anclada en el texto.
- Si un concepto no se puede ubicar en un eje con criterio, omítelo de ese eje
  en vez de ponerlo en 0.5.
- 'confidence_extraction' entre 0.0 y 1.0 por eje.
- Responde SOLO con JSON válido. Sin explicaciones ni markdown."""

USER_PROMPT_TEMPLATE = """Conceptos con sus subdimensiones:
{concepts_with_subdimensions}

Formato JSON exacto:
{{
  "axes": [
    {{
      "id": "string (snake_case, ej: 'concreto_abstracto')",
      "label": "string",
      "polo_bajo": "string",
      "polo_alto": "string",
      "positions": [
        {{"concept_id": "string", "position": 0.0, "justificacion": "string"}}
      ],
      "confidence_extraction": 0.0
    }}
  ]
}}"""
