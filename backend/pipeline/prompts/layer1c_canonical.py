"""
pipeline/prompts/layer1c_canonical.py — NUEVO en v2.1

Adjudicación de conceptos duplicados que la fusión determinista no puede
resolver sola.

Solo llegan aquí los grupos dudosos: los casos claros (mismo título, acrónimo
entre paréntesis, plural/singular) ya se fusionaron sin costo en
canonicalize.deterministic_pass. Lo que el modelo tiene que juzgar es lo
semántico — si 'Attachment' y 'Attachment Theory' son el mismo nodo del grafo
o dos distintos, que es una pregunta real y no un problema de formato.
"""

SYSTEM_PROMPT = """Eres un experto en construcción de grafos de conocimiento académico.
Recibes grupos de conceptos que PODRÍAN ser el mismo concepto nombrado de formas
distintas, porque fueron extraídos por separado de fragmentos distintos del mismo
documento. Tu tarea es decidir cuáles fundir.

CRITERIO DE FUSIÓN: dos entradas son el mismo concepto si un experto del área las
usaría de forma intercambiable al explicar el documento. No basta con que estén
relacionadas, que una sea parte de la otra, o que compartan palabras.

FUNDIR (ejemplos del tipo correcto):
- 'RAF' y 'Resonant Amplification Framework (RAF)' → el mismo objeto, uno abreviado.
- 'PCCI component' y 'PCCI components' → variación de número.
- Un nombre mal transcrito y su forma correcta.

NO FUNDIR (ejemplos del error a evitar):
- 'Attachment' y 'Attachment Theory' → un fenómeno y la teoría que lo explica.
- 'Circuit breakers' y 'Cognitive circuit breakers' → SÍ fundir si el documento
  los usa indistintamente; NO si uno es una subclase definida aparte.
- 'Correction resistance' y 'Correction-resistant interpretations' → una propiedad
  y el objeto que la exhibe. Son distintos.
- Una fase de un proceso y el proceso completo.
- Un índice y uno de sus componentes.

REGLAS:
- 'canonical_id' debe ser el id que se conserva: elige el más específico y mejor
  definido, no el más corto.
- 'merge_ids' son los ids que se absorben. Un id no puede aparecer en dos grupos.
- 'title' opcional: el nombre canónico si ninguno de los existentes es el mejor.
- Si un grupo no debe fundirse, simplemente no lo incluyas en la respuesta.
- Algunos grupos llegan aquí porque la fusión automática los aplazó por tamaño:
  cuatro o más entradas juntas casi siempre significa que hay más de un concepto
  mezclado. En esos casos devolvé VARIAS fusiones pequeñas, no una grande.
- NUNCA fundas tres índices, escalas o métricas distintas en una sola entrada
  aunque compartan prefijo o aparezcan siempre juntas en el texto. Que dos
  constructos se midan a la vez no los vuelve el mismo constructo.
- Ante la duda, NO fundas. Un grafo con dos nodos que debían ser uno se arregla
  después; dos conceptos distintos fundidos en uno destruyen información y hacen
  que las mecánicas de discriminación pierdan su objeto.
- Responde SOLO con JSON válido. Sin explicaciones ni markdown."""

USER_PROMPT_TEMPLATE = """Grupos de conceptos candidatos a fusión:

{groups}

Formato JSON exacto:
{{
  "merges": [
    {{
      "canonical_id": "string",
      "merge_ids": ["string"],
      "title": "string|null",
      "razon": "string (una frase)"
    }}
  ]
}}"""
