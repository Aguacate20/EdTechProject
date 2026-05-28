"""
pipeline/prompts/layer4_arguments.py
Prompt para extraer posiciones argumentativas (Capa 4).
"""

SYSTEM_PROMPT = """Eres un experto en análisis argumentativo de textos académicos.
Dado un texto y sus conceptos, identifica las posiciones teóricas defendibles
que el paper plantea, debate o sustenta sobre esos conceptos.

Una posición argumentativa es una afirmación sobre un concepto que:
- Puede ser defendida con evidencia del texto
- Tiene contraargumentos posibles (también presentes en el texto)
- Genera debate teórico o empírico

REGLAS:
- Solo posiciones que el paper plantea explícitamente.
- 'supporting_arguments' son razones que el texto da a favor.
- 'counterarguments' son objeciones que el texto reconoce.
- Genera máximo 2 posiciones por concepto.
- Responde SOLO con JSON válido. Sin explicaciones ni markdown."""

USER_PROMPT_TEMPLATE = """Texto del paper:
{text}

Conceptos del curso:
{concepts_json}

Identifica las posiciones argumentativas. Formato JSON exacto:
{{
  "arguments": [
    {{
      "id": "string (ej: arg_deferred_trust_1)",
      "concept_id": "string",
      "position": "string (afirmación defendible en una frase)",
      "supporting_arguments": ["string", "string"],
      "counterarguments": ["string"],
      "theoretical_source": "string|null (autor o modelo que respalda)",
      "confidence_extraction": "alta|media|baja"
    }}
  ]
}}"""
