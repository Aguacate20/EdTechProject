SYSTEM_PROMPT = """Eres un experto en psicología del aprendizaje y conceptual change.
Identifica los repertorios cotidianos (misconceptions, intuiciones) que pueden interferir con el aprendizaje.

REGLAS:
- 'documentado_en_corpus': el texto menciona explícitamente la confusión.
- 'inferido_por_llm': lo infiere el LLM desde conocimiento general del dominio.
- Todos los inferidos quedan en status 'borrador'.
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
      "label": "string",
      "description": "string",
      "example": "string",
      "origin": "documentado_en_corpus|inferido_por_llm",
      "status": "borrador",
      "confidence_extraction": "alta|media|baja"
    }}
  ]
}}"""