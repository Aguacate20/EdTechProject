"""
pipeline/prompts/layer1b_enrichment.py
Prompt para enriquecer un concepto con todas sus apariciones en el paper.
"""

SYSTEM_PROMPT = """Eres un experto en análisis conceptual de textos académicos.
Dado el texto completo de un paper y un concepto ya identificado, tu tarea es
construir una ficha conceptual rica sintetizando TODAS las apariciones del concepto.

REGLAS:
- No copies frases literales — sintetiza con tus propias palabras.
- 'core_definition' debe capturar la esencia más completa del concepto según el paper.
- 'subdimensions' solo si el paper las define explícitamente.
- 'distinctions' solo con conceptos que el paper diferencia explícitamente de este.
- 'evolution_in_paper' describe cómo el concepto se desarrolla a lo largo del texto.
- Responde SOLO con JSON válido. Sin explicaciones ni markdown."""

USER_PROMPT_TEMPLATE = """Texto completo del paper:
{full_text}

Concepto a enriquecer:
ID: {concept_id}
Título: {concept_title}
Definición inicial extraída: {concept_definition}

Construye la ficha enriquecida. Formato JSON exacto:
{{
  "core_definition": "string (síntesis completa, no copia literal)",
  "subdimensions": [
    {{"name": "string", "description": "string"}}
  ],
  "distinctions": [
    {{"from_concept": "string", "difference": "string"}}
  ],
  "measurement_approach": "string|null (cómo se mide o operacionaliza en el paper)",
  "theoretical_role": "string|null (qué rol cumple en el marco teórico del paper)",
  "key_tensions": ["string"],
  "evolution_in_paper": "string|null (cómo evoluciona el concepto a lo largo del texto)"
}}"""
