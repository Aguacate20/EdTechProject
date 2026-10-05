"""
pipeline/prompts/layer2_relations.py — v3.5

Cambios respecto a v1:
  · Tipología de 5 a 9 tipos. La reducción tenía efectos que no se veían:
    sin 'contrasta', C5 CONTRASTAR se quedaba sin su input canónico; sin
    'causa', la condición de transferencia de C2 ORDENAR era inalcanzable;
    sin 'ejemplifica', la capa 5 no se podía enganchar al grafo de forma tipada.
  · Se eliminan los clusters del prompt. En v1 el LLM los devolvía por segmento
    y se acumulaban sin merge, produciendo N juegos solapados. Ahora se calculan
    algorítmicamente en graph_utils.compute_clusters.
  · confidence_extraction como float.

Cambios en v3.5:
  · Se emiten también las relaciones INFERIDAS, con confianza baja, en vez de
    callarlas. La regla anterior decía "no fuerces relaciones" y a la vez pedía
    marcar las inferidas con confianza < 0.5: el modelo obedecía la primera y
    la segunda no se usaba nunca. El resultado era silencio donde podía haber
    un dato aproximado, y el consumidor puede filtrar por umbral cuando quiera.
  · Un mismo par puede llevar VARIOS tipos. Que A extienda a B y a la vez lo
    requiera son dos hechos ciertos, no un conflicto; obligar a elegir uno hacía
    que el compilador decidiera por el juego cuál era "el verdadero".
"""

SYSTEM_PROMPT = """Eres un experto en análisis de estructuras conceptuales académicas.
Identifica relaciones semánticas entre conceptos para construir el grafo del curso.

TIPOS VÁLIDOS Y SU SEMÁNTICA (A = from, B = to):
- apoya       : A aporta evidencia o razones a favor de B.
- contradice  : A y B no pueden ser ambos verdaderos como están formulados.
- matiza      : A limita, refina o condiciona el alcance de B.
- extiende    : A amplía B a un dominio o caso nuevo.
- requiere    : A presupone B; hay que entender B antes que A (prerequisito).
- causa       : A produce o genera B en el mundo, no en el argumento.
- ejemplifica : A es una instancia concreta de B.
- generaliza  : A es la abstracción de la que B es un caso.
- contrasta   : A y B se comparan sistemáticamente sin contradecirse.

REGLAS:
- La dirección importa: 'A requiere B' y 'B requiere A' son afirmaciones distintas.
- Distingue 'causa' de 'apoya': causa es una relación del mundo, apoya es del argumento.
- Usa exclusivamente los IDs de conceptos que se te dan. No inventes IDs.

RELACIONA LOS CONCEPTOS ENTRE SÍ. Si el documento estudia un objeto concreto
(una obra, un caso, una empresa) y ese objeto aparece en la lista, no lo uses
como extremo de cada relación: "la obra apoya la crítica social", "la obra
extiende el simbolismo", "la obra causa impacto cultural" dicen todas lo
mismo (que el texto habla de la obra) y dejan a los conceptos sin conectar.
La relación que enseña está ENTRE los conceptos, y el objeto es donde ocurre:
  mal:  obra --apoya--> critica_social ; obra --apoya--> conciencia_politica
  bien: critica_social --causa--> conciencia_politica
        (description: "En la obra, la crítica social que ... despierta la
        conciencia política de los lectores porque ...")
Como mínimo, la mitad de las relaciones que emitas deben unir dos conceptos
que no sean el objeto de estudio. Las tesis y los marcos del texto suelen
enunciar esas relaciones con todas las letras: búscalas ahí.

UN PAR PUEDE TENER VARIOS TIPOS. Si entre dos conceptos hay más de una relación
cierta, emítelas TODAS como entradas separadas. Que A extienda a B y a la vez lo
requiera son dos hechos distintos sobre el mismo par, no una contradicción, y
elegir uno solo pierde información. Lo único que no puede coexistir es una
afirmación con su negación: 'apoya' y 'contradice' sobre el mismo par.

EMITE TAMBIÉN LO QUE INFIERES, marcándolo. No te calles una relación por no
estar seguro: márcala con confianza baja y quien la use decidirá si le sirve.
- 1.0 a 0.8  el texto la afirma explícitamente
- 0.7 a 0.6  el texto la implica con claridad aunque no la enuncie
- 0.5 a 0.3  la infieres del sentido de los conceptos, el texto no la trata
- por debajo de 0.3 no la emitas: eso ya es inventar

'description' debe MENCIONAR LOS DOS CONCEPTOS por su nombre. Una descripción
que solo habla de uno produce retroalimentación confusa: el estudiante lee sobre
un concepto cuando la pregunta era sobre la relación entre dos.
- Mal:  "extiende el concepto de apego digital"
- Bien: "el apego digital extiende la teoría del apego al vínculo con sistemas de IA"

CITA LITERAL (v3.15). Cada relación lleva 'evidence_quote': la frase del texto que la
sostiene, COPIADA TAL CUAL, entre 6 y 40 palabras, sin parafrasear ni corregir erratas.
Si el texto la afirma (confianza 0.8 o más) la cita es obligatoria. Si la infieres y
ninguna frase la sostiene, deja 'evidence_quote' vacío y baja la confianza: una relación
sin cita no puede presentarse como algo que «el texto dice».

MÉTODOS Y RESULTADOS también se relacionan. Si el texto dice que un método examina,
identifica o interpreta un concepto, o que un resultado revela o sugiere otro, eso es
una relación ('apoya' si aporta evidencia; 'requiere' si lo presupone): emítela.

- Responde SOLO con JSON válido. Sin explicaciones ni markdown."""

USER_PROMPT_TEMPLATE = """Texto:
{text}

Conceptos (usa exactamente estos IDs):
{concepts_json}

Tres cosas más, además de las relaciones (v3.12):
- CADENAS: si el texto describe un proceso o una secuencia (A lleva a B, B lleva a C), emite
  cada eslabón como relación causa/antecede (A→B, B→C), no solo los extremos.
- MATIZA: cuando un concepto limita, condiciona o restringe el alcance de otro, emítelo como
  relación "matiza" con la descripción diciendo hasta dónde llega.
- NO-VÍNCULOS: pares que el texto DISTINGUE a propósito (dos nociones que el autor separa, o
  que un lector confundiría y el texto aclara que no son lo mismo ni se implican). Van en
  "no_vinculos", con el motivo en una frase. Solo si el texto lo hace explícito; nunca por
  inferencia tuya. Máximo 8.

Formato JSON exacto:
{{
  "relations": [
    {{
      "from_concept_id": "string",
      "to_concept_id": "string",
      "relation_type": "apoya|contradice|matiza|extiende|requiere|causa|ejemplifica|generaliza|contrasta",
      "description": "string (qué sostiene esta relación, NOMBRANDO ambos conceptos)",
      "evidence_quote": "string (frase LITERAL del texto que la sostiene, o vacío si es inferida)",
      "bidirectional": false,
      "confidence_extraction": 0.0
    }}
  ],
  "no_vinculos": [
    {{ "a": "concept_id", "b": "concept_id", "motivo": "string (por qué el texto los distingue)" }}
  ]
}}"""


# ── v3.15 · insinuadas: lo que el texto deja ver sin afirmarlo ───────────────
#
# Un texto corto afirma pocas relaciones, y eso está bien: no hay que inventarle
# vínculos firmes. Pero entre dos conceptos que el texto trata una y otra vez en
# el mismo párrafo suele haber una conexión que un lector atento propondría. Esas
# van aparte, con confianza baja: el juego las paga como creatividad respaldada
# («insinuado»), nunca como «el texto lo dice», y no entran al Atlas como evidencia.

SYSTEM_PROMPT_INSINUADAS = """Eres un lector experto. Te doy pares de conceptos que un texto
trata juntos en los mismos párrafos SIN afirmar ninguna relación entre ellos. Para cada par
decide si un lector atento podría proponer, con buen criterio, una relación que el texto
deja entrever.

REGLAS:
- Son INFERENCIAS, no afirmaciones del texto. Confianza entre 0.35 y 0.55, nunca más.
- Usa solo estos tipos: apoya, matiza, extiende, requiere, causa, ejemplifica, generaliza, contrasta.
- La dirección importa. Elige la que mejor se sostiene con lo que el texto dice de cada uno.
- 'description' nombra los DOS conceptos y explica en una frase por qué la conexión es
  defendible a partir del texto. No afirmes que el texto la dice.
- Si para un par no ves una relación defendible, OMÍTELO. Es mejor devolver pocas y buenas:
  como máximo {maximo}.
- Usa exactamente los IDs que se te dan.
- Responde SOLO con JSON válido. Sin explicaciones ni markdown."""

USER_PROMPT_INSINUADAS = """Texto:
{text}

Pares que el texto trata juntos (id_a | id_b | párrafos compartidos):
{pares}

Conceptos:
{concepts_json}

Formato JSON exacto:
{{
  "relations": [
    {{
      "from_concept_id": "string",
      "to_concept_id": "string",
      "relation_type": "apoya|matiza|extiende|requiere|causa|ejemplifica|generaliza|contrasta",
      "description": "string (por qué es defendible, nombrando ambos conceptos)",
      "confidence_extraction": 0.45
    }}
  ]
}}"""
