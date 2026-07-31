"""
pipeline/prompts/layer5b_scenarios.py — NUEVO en v2

Generación de escenarios derivados a partir de los casos extraídos.

Sin esta capa cada caso es de un solo uso y la familia E —la que mide
transferencia, que 00_marco_metateorico declara métrica última— se agota tras
una pasada. Es también la única forma de producir transferencia LEJANA: los
casos del paper están todos en el dominio del paper.

Nota sobre la distancia: lo que el modelo declara aquí no se acepta a ciegas.
validation.py la recalcula comparando el dominio del escenario contra el del
caso padre, porque cambiar de dominio es la definición operativa de lejanía y
los modelos tienden a sobredeclarar 'lejana' para escenarios que solo cambian
los nombres propios.
"""

SYSTEM_PROMPT = """Eres un experto en diseño de transferencia de aprendizaje.
Recibes casos extraídos de un paper y generas VARIANTES para que un estudiante
aplique el mismo concepto en situaciones nuevas.

TRES DISTANCIAS:
- 'cercana': mismo dominio, estructura superficial parecida al caso original.
- 'media'  : mismo dominio, estructura superficial distinta.
- 'lejana' : OTRO dominio. El concepto debe seguir aplicándose, pero nada de la
             superficie debe recordar al caso original.

REGLAS:
- Genera para cada caso: 1 cercana, 1 media y 1 lejana cuando el concepto lo permita.
- La distancia lejana es la más valiosa y la más difícil: cambia de campo por
  completo. Si el concepto es tan específico de su dominio que no puede viajar,
  no fuerces una lejana — omítela.
- Cambiar nombres, lugares o cifras NO es cambiar de dominio. Si solo cambiaste
  la superficie, es 'cercana'.
- 'resolucion_esperada' debe ser autosuficiente: quien califique no va a tener
  el paper delante.
- 'error_embebido': opcionalmente genera variantes que contengan un razonamiento
  defectuoso para mecánicas de diagnóstico. Si el error coincide con una
  intuición cotidiana, mucho mejor: descríbelo explícitamente.
- 'habilidad_objetivo': 'transferencia' por defecto; 'relacion' si la variante
  exige combinar dos conceptos.
- Responde SOLO con JSON válido. Sin explicaciones ni markdown."""

USER_PROMPT_TEMPLATE = """Conceptos del curso:
{concepts_json}

Casos originales:
{cases_json}

Genera las variantes. Formato JSON exacto:
{{
  "scenarios": [
    {{
      "id": "string (ej: scenario_sally_anne_lejana_1)",
      "parent_case_id": "string (id de un caso de la lista)",
      "concept_ids": ["string"],
      "description": "string (la situación nueva)",
      "resolucion_esperada": "string",
      "dominio": "string",
      "distancia": "cercana|media|lejana",
      "habilidad_objetivo": "transferencia|relacion",
      "error_embebido": "string|null",
      "confidence_extraction": 0.0
    }}
  ]
}}"""
