"""
pipeline/prompts/layer5_cases.py — v2.1 (ahora se invoca por lotes)

Cuatro cambios, cada uno por una razón concreta del catálogo de mecánicas:

  · 'concept_ids' como lista: E5 RESOLVER exige combinar varios conceptos y con
    un solo concept_id no era instanciable.
  · 'resolucion_esperada': es el gold contra el que E1 PREDECIR, E2 DIAGNOSTICAR
    y E3 APLICAR califican. Sin él la familia E no tiene contra qué comparar.
  · 'dominio': permite calcular la distancia de transferencia de los escenarios
    derivados. Sin dominio no se distingue transferencia real de reconocimiento
    de superficie.
  · 'error_embebido' + 'repertoire_id': D3 CRITICAR y E2 DIAGNOSTICAR necesitan
    casos con error plantado, y el contrato de E2 pide que el error ENCARNE un
    repertorio documentado — no detectarlo es señal positiva de anclaje. Un error
    arbitrario produce un puzzle; un error que encarna un repertorio produce un
    diagnóstico.
"""

SYSTEM_PROMPT = """Eres un experto en análisis de evidencia empírica en textos académicos.
Identifica los casos, experimentos, ejemplos y datos que ilustran o sustentan los conceptos.

TIPOS DE CASO:
- 'experimento'       : estudio controlado con participantes
- 'dato_empirico'     : estadística o resultado medido
- 'ejemplo_cotidiano' : situación de la vida real usada para ilustrar
- 'caso_clinico'      : caso particular analizado en profundidad
- 'contraejemplo'     : caso que desafía o limita la aplicación del concepto
- 'caso_limite'       : caso en la frontera donde el concepto deja de aplicarse

REGLAS:
- 'concept_ids': TODOS los conceptos que el caso pone en juego. Los casos que
  involucran varios conceptos son los más valiosos: no los reduzcas a uno.
- 'primary_concept_id': el concepto que el caso ilustra principalmente.
- 'resolucion_esperada': qué diría un experto sobre este caso — el análisis
  correcto, no solo el desenlace. Es el criterio de calificación, así que debe
  ser autosuficiente y no depender de leer el paper.
- 'dominio': campo al que pertenece la situación, en dos o tres palabras
  (ej: 'psicología del desarrollo', 'economía doméstica', 'medicina clínica').
  Sé consistente: el mismo dominio debe escribirse igual en todos los casos.
- 'variables_clave': los factores que hay que atender para resolverlo bien.
- 'es_paradigmatico': true si es EL caso con el que el paper enseña el concepto.
- 'prediction_enabled': true si el estudiante puede predecir el resultado antes de verlo.
- 'error_embebido': solo si el caso contiene un razonamiento defectuoso;
  descríbelo. Si además ese error coincide con una intuición cotidiana común,
  pon su descripción en el mismo campo. Si no hay error, null.
- Solo evidencia presente en el texto. No inventes casos.
- 'confidence_extraction' entre 0.0 y 1.0.
- El texto que recibes es UN FRAGMENTO del documento, no el documento entero.
- Los ids deben ser DETERMINISTAS y derivados del contenido (ej: 'case_sally_anne'),
  nunca correlativos como 'case_1'. Dos fragmentos que describan el mismo
  experimento deben producir el mismo id.
- Máximo 6 casos por fragmento. Prefiere pocos y completos: un caso sin
  `resolucion_esperada` no sirve para nada aguas abajo.
- Responde SOLO con JSON válido. Sin explicaciones ni markdown."""

USER_PROMPT_TEMPLATE = """Texto del paper:
{text}

Conceptos del curso:
{concepts_json}

Formato JSON exacto:
{{
  "cases": [
    {{
      "id": "string (ej: case_sally_anne_1)",
      "concept_ids": ["string"],
      "primary_concept_id": "string",
      "kind": "experimento|dato_empirico|ejemplo_cotidiano|caso_clinico|contraejemplo|caso_limite",
      "description": "string (la situación, sin revelar el análisis)",
      "resolucion_esperada": "string (el análisis correcto)",
      "dominio": "string",
      "variables_clave": ["string"],
      "es_paradigmatico": false,
      "prediction_enabled": false,
      "error_embebido": "string|null",
      "source_pages": [1],
      "confidence_extraction": 0.0
    }}
  ]
}}"""
