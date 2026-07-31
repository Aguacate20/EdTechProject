"""
pipeline/prompts/layer1b_enrichment.py — v2

El prompt v1 pedía "sintetiza TODAS las apariciones de cada concepto en el
texto" mientras el orquestador le pasaba `full_text[:8000]`. La promesa era
estructuralmente incumplible, y `evolution_in_paper` —que por definición
necesita el arco completo— se generaba sobre el primer tramo del documento.
En v2 el orquestador enruta por secciones y pasa un presupuesto mucho mayor.

Cambio de contenido: 'distinctions' pasa a ser un campo de primera importancia,
porque es la materia prima del caracterizador de distractores. Se le pide
explícitamente que use ids del curso en 'from_concept'.
"""

SYSTEM_PROMPT = """Eres un experto en análisis conceptual de textos académicos.
Dado el texto de un paper y una lista de conceptos, construye fichas conceptuales
ricas sintetizando las apariciones de cada concepto a lo largo del texto.

REGLAS:
- No copies frases literales — sintetiza con tus propias palabras.
- 'core_definition' debe capturar la esencia más completa según el paper.
- 'subdimensions': aspectos o facetas internas del concepto. Se usan después para
  construir ejes de comparación entre conceptos, así que nómbralas de forma que
  puedan aplicarse a más de un concepto (ej: "grado de abstracción" y no
  "abstracción de este concepto").
- 'distinctions' es el campo más importante: con qué OTRO concepto del curso se
  confunde este, y cuál es exactamente la diferencia. Usa el id del otro concepto
  en 'from_concept'. Si dos conceptos se parecen y el paper los separa, dilo aquí.
- 'key_tensions': desacuerdos o problemas abiertos que el paper reconoce sobre el concepto.
- 'evolution_in_paper': cómo el concepto se desarrolla o cambia a lo largo del texto.
- Devuelve TODOS los conceptos de la lista aunque tengas poca información sobre alguno.
- Responde SOLO con JSON válido. Sin explicaciones ni markdown."""

USER_PROMPT_TEMPLATE_BATCH = """Texto del paper:
{full_text}

Conceptos a enriquecer:
{concepts_list}

Ids válidos para 'from_concept' en distinctions:
{valid_ids}

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
        {{"from_concept": "string (id de otro concepto)", "difference": "string"}}
      ],
      "measurement_approach": "string|null",
      "theoretical_role": "string|null",
      "key_tensions": ["string"],
      "evolution_in_paper": "string|null"
    }}
  ]
}}"""
