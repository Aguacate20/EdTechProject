"""
pipeline/prompts/layer1b_enrichment.py
Prompts para enriquecer conceptos con todas sus apariciones en el paper.
"""

SYSTEM_PROMPT = """Eres un experto en análisis conceptual de textos académicos.
Dado el texto de un paper y una lista de conceptos, construye fichas conceptuales
ricas sintetizando TODAS las apariciones de cada concepto en el texto.

REGLAS:
- No copies frases literales — sintetiza con tus propias palabras.
- 'core_definition' debe capturar la esencia más completa según el paper.
- 'subdimensions' solo si el paper las define explícitamente.
- 'distinctions' solo con conceptos que el paper diferencia explícitamente.
- 'evolution_in_paper' describe cómo el concepto se desarrolla a lo largo del texto.
- Devuelve TODOS los conceptos de la lista aunque tengas poca información.
- Responde SOLO con JSON válido. Sin explicaciones ni markdown."""

USER_PROMPT_TEMPLATE_BATCH = """Texto del paper:
{full_text}

Conceptos a enriquecer:
{concepts_list}

Enriquece TODOS los conceptos anteriores. Formato JSON exacto:
{{
  "concepts": [
    {{
      "id": "string (mismo id recibido)",
      "core_definition": "string",
      "subdimensions": [
        {{"name": "string", "description": "string"}}
      ],
      "distinctions": [
        {{"from_concept": "string", "difference": "string"}}
      ],
      "measurement_approach": "string|null",
      "theoretical_role": "string|null",
      "key_tensions": ["string"],
      "evolution_in_paper": "string|null"
    }}
  ]
}}"""
