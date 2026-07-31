"""
pipeline/prompts/layer3_repertoires.py — v2

Cambios respecto a v1: se agregan los tres campos que el Contextualizador
(rol 4) necesita para producir feedback de coexistencia en vez de corrección.

Sin 'contraste_cientifico' y 'contexto_donde_funciona', la señal observacional
de anclaje se emite correctamente pero no hay con qué responderle al estudiante
lo que 01_modelo_cognitivo §3 exige: nunca "está mal", sino "eso funciona
cuando X, y aquí el criterio es otro".

'concepto_confundido' alimenta la caracterización de distractores: es lo que
permite que B1 emita `relacion` sobre una arista además de `recuperacion`.
"""

SYSTEM_PROMPT = """Eres un experto en psicología del aprendizaje y cambio conceptual.
Identifica los repertorios cotidianos (intuiciones previas) que pueden interferir
con el aprendizaje de estos conceptos.

PRINCIPIO: un repertorio cotidiano NO es un error. Es conocimiento que funciona
en su contexto de origen y deja de funcionar en el contexto científico. Tu tarea
es describir ambos contextos, no descalificar el primero.

REGLAS:
- 'por_que_es_intuitiva': qué hace que esta idea sea razonable para alguien que
  no ha estudiado el tema. Debe ser una explicación empática y real, no un
  diagnóstico de error.
- 'contexto_donde_funciona': situaciones concretas en las que esta intuición
  produce predicciones acertadas.
- 'contraste_cientifico': qué distingue exactamente al concepto científico de la
  intuición. Debe nombrar el criterio que cambia, no solo decir que difieren.
- 'concepto_confundido': si la intuición consiste en confundir este concepto con
  otro concepto del curso, pon el id de ese otro concepto. Si no, null.
- 'documentado_en_corpus': el texto menciona explícitamente la confusión.
- 'inferido_por_llm': lo infieres desde conocimiento general del dominio.
- Todos los inferidos quedan en status 'borrador'.
- 'confidence_extraction' entre 0.0 y 1.0.
- Responde SOLO con JSON válido. Sin explicaciones ni markdown."""

USER_PROMPT_TEMPLATE = """Texto:
{text}

Conceptos del curso:
{concepts_json}

Formato JSON exacto:
{{
  "repertoires": [
    {{
      "id": "string (ej: repertoire_falsa_creencia_1)",
      "concept_id": "string",
      "label": "string (nombre corto de la intuición)",
      "description": "string",
      "example": "string (una situación concreta donde el estudiante la usaría)",
      "por_que_es_intuitiva": "string",
      "contexto_donde_funciona": "string",
      "contraste_cientifico": "string",
      "concepto_confundido": "string|null",
      "origin": "documentado_en_corpus|inferido_por_llm",
      "status": "borrador",
      "confidence_extraction": 0.0
    }}
  ]
}}"""
