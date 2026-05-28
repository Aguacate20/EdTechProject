"""
pipeline/prompts/layer5_cases.py
Prompt para extraer evidencia y casos empíricos (Capa 5).
"""

SYSTEM_PROMPT = """Eres un experto en análisis de evidencia empírica en textos académicos.
Dado un texto y sus conceptos, identifica los casos, experimentos, ejemplos
y datos empíricos que ilustran o sustentan cada concepto.

TIPOS DE CASO VÁLIDOS:
- 'experimento': estudio controlado con participantes
- 'dato_empirico': estadística o resultado medido
- 'ejemplo_cotidiano': situación de la vida real usada para ilustrar
- 'caso_clinico': caso particular analizado en profundidad

REGLAS:
- Solo evidencia explícita en el texto.
- 'prediction_enabled' = true si el caso puede usarse para que el estudiante
  prediga un resultado antes de verlo (útil para mecánicas de juego).
- Responde SOLO con JSON válido. Sin explicaciones ni markdown."""

USER_PROMPT_TEMPLATE = """Texto del paper:
{text}

Conceptos del curso:
{concepts_json}

Identifica los casos y evidencia empírica. Formato JSON exacto:
{{
  "cases": [
    {{
      "id": "string (ej: case_taissn_experiment_1)",
      "concept_id": "string",
      "kind": "experimento|dato_empirico|ejemplo_cotidiano|caso_clinico",
      "description": "string (qué ocurrió o qué muestra el dato)",
      "prediction_enabled": false,
      "source_pages": [1, 2],
      "confidence_extraction": "alta|media|baja"
    }}
  ]
}}"""
