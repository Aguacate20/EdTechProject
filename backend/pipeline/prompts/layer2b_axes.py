"""
pipeline/prompts/layer2b_axes.py — v2.2.4

Los ejes se piden ahora en DOS FASES, con prompts separados.

Por qué: en v2.2.2 una sola llamada tenía que definir los ejes y ubicar todos
los conceptos en todos ellos. Con 31 conceptos y 4 ejes son ~124 entradas con
justificación, y la respuesta se truncaba antes del primer eje completo. Ni el
rescate podía salvar nada, así que la capa quedaba en cero y C4 MAPEAR sin
poder instanciarse.

Fase 1 define los ejes: respuesta corta, una sola llamada.
Fase 2 ubica los conceptos: un eje por llamada, en tandas. Cada respuesta es
una lista plana de posiciones, que es lo que el rescate de JSON truncado sabe
recuperar parcialmente si aun así se pasa.
"""

# ─────────────────────────────────────────────
# Fase 1 — definir los ejes
# ─────────────────────────────────────────────

SYSTEM_PROMPT_DEFINE = """Eres un experto en análisis conceptual.
Recibes los conceptos de un curso con sus subdimensiones. Tu tarea es definir
unos pocos EJES BIPOLARES compartidos que sirvan para ubicar los conceptos en un
espacio común. En esta fase NO ubicas conceptos: solo defines los ejes.

REGLAS:
- Entre 2 y 4 ejes. Menos de 2 no define un espacio; más de 4 no es usable.
- Un eje es bipolar: dos polos opuestos y nombrados (por ejemplo "concreto" ↔
  "abstracto", "individual" ↔ "colectivo", "descriptivo" ↔ "normativo").
- Los ejes deben ser del DOMINIO de este material, no genéricos. Prefiere un eje
  que solo tenga sentido en este campo antes que uno aplicable a cualquier cosa.
- Un buen eje distingue: si casi todos los conceptos caerían en el mismo polo,
  no sirve.
- 'id' en snake_case, derivado de los dos polos.
- Sé BREVE. Esta respuesta debe caber holgadamente: nombres de polos de una o
  dos palabras, sin justificaciones ni explicaciones. La respuesta completa no
  debería pasar de veinte líneas.
- Responde SOLO con JSON válido. Sin explicaciones ni markdown."""

USER_PROMPT_DEFINE = """Conceptos con sus subdimensiones:
{concepts_with_subdimensions}

Formato JSON exacto:
{{
  "axes": [
    {{
      "id": "string (ej: 'concreto_abstracto')",
      "label": "string",
      "polo_bajo": "string",
      "polo_alto": "string",
      "confidence_extraction": 0.0
    }}
  ]
}}"""


# ─────────────────────────────────────────────
# Fase 2 — ubicar los conceptos
# ─────────────────────────────────────────────

SYSTEM_PROMPT_PLACE = """Eres un experto en análisis conceptual.
Recibes UN eje bipolar y una lista de conceptos. Ubica cada concepto en ese eje.

REGLAS:
- 'position' entre 0.0 (polo bajo) y 1.0 (polo alto).
- Usa el rango completo. Si todo queda entre 0.4 y 0.6 el eje no aporta nada.
- Si un concepto no se puede ubicar en este eje con criterio, OMÍTELO de la
  respuesta. Es preferible a inventar un 0.5.
- 'justificacion' en una frase corta.
- Usa exactamente los IDs que se te dan. No inventes IDs ni agregues conceptos.
- Responde SOLO con JSON válido. Sin explicaciones ni markdown."""

USER_PROMPT_PLACE = """Eje: {axis_label}
  0.0 = {polo_bajo}
  1.0 = {polo_alto}

Conceptos a ubicar:
{concepts_list}

Formato JSON exacto:
{{
  "positions": [
    {{"concept_id": "string", "position": 0.0, "justificacion": "string"}}
  ]
}}"""


# Compatibilidad con la versión de una sola fase.
SYSTEM_PROMPT = SYSTEM_PROMPT_DEFINE
USER_PROMPT_TEMPLATE = USER_PROMPT_DEFINE
