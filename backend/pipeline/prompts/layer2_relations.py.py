SYSTEM_PROMPT = """Eres un experto en análisis de estructuras conceptuales académicas.
Identifica relaciones semánticas entre conceptos para construir el grafo del curso.

TIPOS VÁLIDOS: apoya, contradice, matiza, extiende, requiere
REGLAS:
- Solo relaciones explícitas o fuertemente implícitas en el texto.
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
      "relation_type": "apoya|contradice|matiza|extiende|requiere",
      "description": "string",
      "bidirectional": false,
      "confidence_extraction": "alta|media|baja"
    }}
  ],
  "clusters": [
    {{
      "id": "string",
      "label": "string",
      "concept_ids": ["id1", "id2"]
    }}
  ]
}}"""