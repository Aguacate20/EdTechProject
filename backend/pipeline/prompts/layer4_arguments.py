"""
pipeline/prompts/layer4_arguments.py — v2.1 (ahora se invoca por lotes)

Cambio estructural: de "una posición por concepto" a tesis + marcos teóricos.

Motivos concretos, no estéticos:
  · F3 REFUTAR emite `relacion` sobre un cluster de argumentos solo si la
    refutación contrasta dos marcos. Sin 'rivales' esa señal nunca puede existir.
  · El Juez de F2 ARGUMENTAR califica contra 'criterios_defensa_valida'. Sin
    ellos califica con criterio propio en vez de con el criterio del curso.
  · Una tesis suele abarcar varios conceptos; amarrarla a uno solo mutilaba
    justo las tesis más interesantes.
"""

SYSTEM_PROMPT = """Eres un experto en análisis argumentativo de textos académicos.
Identifica los MARCOS TEÓRICOS en disputa y las TESIS defendibles que el paper
plantea, debate o sustenta.

Un marco teórico es una posición general con principios propios, que compite con
otras formas de explicar el mismo fenómeno.
Una tesis es una afirmación concreta que:
- puede defenderse con evidencia o razones del texto,
- admite contraargumentos reales (no de paja),
- y sobre la que dos personas informadas podrían discrepar.

REGLAS:
- 'rivales' son ids de OTROS marcos de esta misma lista que compiten con este.
  Si el paper presenta un solo marco sin alternativa, deja 'rivales' vacío: no
  inventes una rivalidad que el texto no plantea.
- 'criterios_defensa_valida': qué tendría que mostrar una defensa de esta tesis
  para contar como buena EN ESTE CAMPO. Son criterios de calidad, no la respuesta.
- 'criterios_refutacion_valida': qué tendría que mostrar una refutación legítima.
  Estos dos campos se usan como rúbrica, así que sé específico y operativo.
- 'concept_ids': todos los conceptos que la tesis involucra, no solo el principal.
- 'criterios_conceptos' y 'contraargumentos_conceptos': para cada criterio de
  refutación y cada contraargumento, EN EL MISMO ORDEN, la lista de IDs de los
  conceptos que ese texto invoca (los que pone a prueba o de los que habla).
  Un contraargumento como "no todos los lectores jóvenes internalizan los
  mensajes críticos" invoca literatura_juvenil, critica_social y empoderamiento.
  Con esto el juego puede juzgar cuando el estudiante enlaza una objeción con
  un marco o con un concepto; sin esto, esa jugada vale cero.
- Máximo 6 tesis y 4 marcos en total. Prefiere pocas y buenas.
- Si el texto es puramente expositivo y no hay debate, devuelve listas vacías.
  Es una respuesta válida y preferible a inventar controversia.
- 'confidence_extraction' entre 0.0 y 1.0.
- El texto que recibes es UN FRAGMENTO del documento, no el documento entero.
  Extrae solo lo que este fragmento sostiene; otro fragmento aportará lo demás.
- Los ids deben ser DETERMINISTAS y derivados del contenido (ej: 'tesis_atribucion_temprana'),
  nunca correlativos como 'tesis_1'. Fragmentos distintos que hablen de la misma
  tesis deben producir el mismo id para que se puedan unificar.
- Responde SOLO con JSON válido. Sin explicaciones ni markdown."""

USER_PROMPT_TEMPLATE = """Texto del paper:
{text}

Conceptos del curso:
{concepts_json}

Formato JSON exacto:
{{
  "frameworks": [
    {{
      "id": "string (ej: framework_constructivista)",
      "label": "string",
      "principios_centrales": ["string"],
      "rivales": ["string (id de otro framework de esta lista)"],
      "concept_ids": ["string"],
      "confidence_extraction": 0.0
    }}
  ],
  "theses": [
    {{
      "id": "string (ej: tesis_atribucion_temprana)",
      "statement": "string (afirmación defendible en una frase)",
      "concept_ids": ["string"],
      "framework_id": "string|null",
      "supporting_arguments": ["string"],
      "counterarguments": ["string"],
      "criterios_defensa_valida": ["string"],
      "criterios_refutacion_valida": ["string"],
      "criterios_conceptos": [["string"]],
      "contraargumentos_conceptos": [["string"]],
      "theoretical_source": "string|null",
      "confidence_extraction": 0.0
    }}
  ]
}}"""
