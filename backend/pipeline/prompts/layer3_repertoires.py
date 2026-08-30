"""
pipeline/prompts/layer3_repertoires.py — v2.9

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

COBERTURA ESPERADA: apunta a UNA intuición por cada concepto que la admita.
En la última corrida salieron 3 para 29 conceptos, y esta es la capa más
valiosa de todo el material: es la que permite responder un error con "eso
funciona en otros contextos, acá el criterio es otro" en vez de "está mal".
Tres intuiciones para veintinueve conceptos deja el resto sin nada que decir.

No fuerces una intuición donde no la hay —un concepto puramente técnico puede
no tener versión cotidiana— pero recorré la lista completa antes de decidir que
no aplica. Las fuentes de intuición más frecuentes, por si ayudan a buscar:
  · el término técnico coincide con una palabra del habla común con otro sentido
  · el concepto contradice algo que la experiencia diaria sugiere
  · el fenómeno tiene una explicación popular más simple y plausible
  · se confunde con otro concepto del mismo curso que suena parecido
  · el sentido común invierte la dirección de la causa

PRINCIPIO: un repertorio cotidiano NO es un error. Es conocimiento que funciona
en su contexto de origen y deja de funcionar en el contexto científico. Tu tarea
es describir ambos contextos, no descalificar el primero.

REGLAS:
- 'por_que_es_intuitiva': qué hace que esta idea sea razonable para alguien que
  no ha estudiado el tema. Debe ser una explicación empática y real, no un
  diagnóstico de error.
- 'contexto_donde_funciona': situaciones concretas en las que esta intuición
  produce predicciones ACERTADAS. No escribas "en contextos cotidianos": nombra
  una situación real donde alguien que piense así acierte.
- 'contraste_cientifico': ES EL CAMPO MÁS IMPORTANTE y no puede quedar vacío ni
  resolverse en una frase genérica. Debe nombrar EL CRITERIO CONCRETO que cambia
  entre la intuición y el concepto científico.
  Mal: "la teoría lo explica de forma más precisa" (no dice qué cambia).
  Mal: "es una simplificación" (no dice de qué).
  Bien: "la intuición atribuye el efecto a la repetición del mensaje; el marco
  lo atribuye a quién es percibido como autor de la interpretación. El criterio
  que cambia es la fuente de autoridad, no la frecuencia."
  Escribe dos o tres frases. De este campo sale, palabra por palabra, la
  explicación que recibe el estudiante cuando se equivoca: sin él el sistema
  puede detectar la confusión pero no responderla.
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
