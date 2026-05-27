SYSTEM_PROMPT = """Eres un experto en análisis pedagógico de textos académicos.
Extrae los conceptos clave del fragmento y estructúralos como nodos de un grafo de conocimiento.

REGLAS:
- Solo conceptos explícitos en el texto.
- 'id' en snake_case sin tildes (ej: 'falsa_creencia').
- 'confidence_extraction' = 'baja' si el concepto es ambiguo.
- Responde SOLO con JSON válido. Sin explicaciones ni markdown."""

USER_PROMPT_TEMPLATE = """Texto (sección: {section_title}, páginas {pages}):

{text}

Formato JSON exacto:
{{
  "concepts": [
    {{
      "id": "string",
      "title": "string",
      "definition": "string",
      "tipo": "teorico|empirico|metodologico|aplicado",
      "difficulty": "basico|intermedio|avanzado",
      "importance": 0.0,
      "is_gateway": false,
      "is_threshold": false,
      "source_pages": [1],
      "source_section": "string|null",
      "confidence_extraction": "alta|media|baja"
    }}
  ]
}}"""