"""
pipeline/prompts/layer1_concepts.py — v3.0

Tres correcciones medidas sobre una extracción real:

  · ATOMICIDAD. Salieron pseudo-conceptos que son fragmentos de oración:
    'EVI, PCCI, and IRM' (una enumeración), 'Persistent, memoryful relational
    AI systems' (un enunciado de alcance), 'PCCI component'. Un nodo del grafo
    tiene que ser algo que se pueda definir, no cualquier sintagma nominal.

  · DISTRIBUCIÓN DE IMPORTANCIA. Ocho conceptos salieron con importancia 1.0,
    lo que vuelve inútil el ranking: el paso de enriquecimiento elige por
    importancia y con empates masivos elige casi al azar.

  · IDIOMA. Los últimos lotes devolvieron definiciones en español y el resto en
    inglés, porque nada lo fijaba. La deriva entre lotes rompe el emparejamiento
    de sinónimos.

  · IDIOMA DEL TÍTULO (v2.2.3). Este era la causa raíz de un problema mayor. Al
    dejar el título "en el idioma del documento", el modelo alternaba: salieron
    a la vez `Circuit breakers` e `Interruptores Cognitivos`, `Epistemic
    Vigilance Index (EVI)` e `Índice de Vigilancia Epistémica (EVI)`. Como la
    depuración agrupa por tokens compartidos, dos títulos del mismo concepto en
    idiomas distintos no comparten NINGÚN token y nunca se comparan. El
    resultado fueron cuatro conceptos duplicados en el grafo final.

Nota: aunque este prompt ya pide nombres canónicos, la deduplicación real la
hace canonicalize.py — un lote no puede saber cómo bautizó otro lote al mismo
concepto.
"""
import os

# Idioma de las definiciones. Los títulos conservan el término del documento
# para no romper el emparejamiento con el texto original.
OUTPUT_LANGUAGE = os.environ.get("OUTPUT_LANGUAGE", "español")

SYSTEM_PROMPT = f"""Eres un experto en análisis pedagógico de textos académicos.
Extrae los conceptos clave del fragmento y estructúralos como nodos de un grafo de conocimiento.

QUÉ CUENTA COMO CONCEPTO:
- Algo que se puede definir en una oración y que reaparece en el texto.
- Prueba: ¿un examen podría pedir "explica X"? Si no, no es un concepto.

EL OBJETO DE ESTUDIO NO ES UN CONCEPTO. Si el documento analiza UNA obra, UN
caso, UNA empresa, UN dataset o UN evento concreto (una novela, una sentencia,
una campaña, un experimento), eso es el material sobre el que el texto piensa,
no una idea que se explique. "Explica Los Juegos del Hambre" no es una pregunta
de examen; "explica cómo la distopía funciona como crítica social" sí. Cuando
lo conviertes en concepto, todo el grafo cuelga de él como una estrella y las
ideas del texto quedan sin relación entre sí. Regla:
- No emitas el objeto de estudio como concepto. Emítelo una sola vez en el
  campo 'objeto_de_estudio' del resultado (title + una línea), para que las
  capas siguientes lo usen como caso y como contexto de los ejemplos. El
  'title' es el nombre de la obra, el caso o la empresa ("Los Juegos del
  Hambre"), NO el título del documento que la analiza.
- Los conceptos son las ideas con las que el texto lo analiza (los métodos,
  las categorías, los efectos, las tensiones), y se relacionan ENTRE SÍ.

ANCLAJE OBLIGATORIO:
- 'evidencia_textual': COPIA LITERAL de una frase del fragmento donde el
  concepto aparece. Entre 10 y 40 palabras, copiada carácter por carácter.
  No la parafrasees, no la traduzcas, no la resumas: se compara automáticamente
  contra el documento y si no aparece, el concepto se descarta.
- Si no encuentras una frase literal que respalde el concepto, ES QUE EL
  CONCEPTO NO ESTÁ EN EL FRAGMENTO. No lo extraigas.
- No completes siglas por tu cuenta. Si el texto dice "PCCI" sin desarrollarla,
  el título es "PCCI" y nada más. Inventar el desarrollo de una sigla a partir
  de lo que suena plausible es el error más costoso que puedes cometer aquí,
  porque produce un concepto que parece real y no existe.

QUÉ NO CUENTA (errores frecuentes que debes evitar):
- Enumeraciones: 'EVI, PCCI e IRM' son TRES conceptos, no uno.
- Frases enteras del texto. Un título como "indices for epistemic vigilance,
  parasocial co-creation and internalization resistance" no es un concepto: es
  una oración que menciona tres. Si el título no cabe en seis palabras, casi
  seguro estás extrayendo una frase y no un concepto.
- Un concepto y su sigla suelta son EL MISMO concepto, no dos. Si el texto usa
  ambas formas, el título es la extendida con la sigla entre paréntesis y la
  sigla suelta va en 'sinonimos'. Extraer "IRM" y "Internalization Resistance
  Metric" por separado produce dos entradas que compiten entre sí como opciones
  de una misma pregunta.
- Enunciados de alcance o de método: 'sistemas persistentes con memoria' como
  descripción del ámbito de aplicación no es un concepto.
- Componentes sin entidad propia: si 'componente de X' solo tiene sentido dentro
  de X, extrae X.
- Frases del autor sobre su propio artículo.

REGLAS:
- 'title': el nombre canónico y completo, SIEMPRE en el idioma original del
  documento. No traduzcas los títulos: si el paper dice "circuit breakers",
  el título es "Circuit breakers", no "Interruptores cognitivos". Traducir
  produce dos entradas para el mismo concepto y rompe el grafo.
- Si el texto usa una sigla, escribe la forma extendida con la sigla entre
  paréntesis: 'Epistemic Vigilance Index (EVI)'. Y pon la sigla suelta en
  'sinonimos'. La traducción al español, si la querés incluir, va también en
  'sinonimos' — nunca en 'title'.
- 'id' en snake_case sin tildes, derivado del título extendido.
- 'sinonimos': otras formas con las que el texto nombra EXACTAMENTE lo mismo,
  incluida la sigla suelta. Se usan para calificar respuestas abiertas, así que
  sé generoso con las variantes pero no incluyas conceptos distintos.
  IMPORTANTE: un sinónimo no puede pertenecer a dos conceptos. Si dos conceptos
  comparten sigla, esa sigla no va como sinónimo de ninguno: el sistema la
  descarta y la pregunta abierta se vuelve incalificable.
- 'variantes_terminologicas': flexiones, plurales, traducciones aceptables.
- 'definition' en {OUTPUT_LANGUAGE}. 'title' SIEMPRE en el idioma del documento.
- 'difficulty' es la dificultad para quien ve el tema por primera vez, no la
  complejidad del texto.
- 'carga_cognitiva' es POR QUÉ cuesta, no cuánto. Elige uno o más de estos
  cuatro, y solo los que apliquen de verdad:
    · 'memorizar'   — hay bastante que retener: nombres, componentes, pasos.
    · 'discriminar' — se confunde fácil con otro concepto parecido del curso.
    · 'integrar'    — hay que sostener varias piezas a la vez para entenderlo.
    · 'inferir'     — no basta con recordarlo, hay que deducir o aplicar.
  Este campo determina qué tipo de ejercicio se le propone al estudiante: no es
  lo mismo un concepto que cuesta porque hay mucho que retener que uno que
  cuesta porque se parece a otro. Si marcas los cuatro en todos los conceptos,
  el campo deja de servir.
  NO PUEDE QUEDAR VACÍO: todo concepto cuesta por algún motivo. Si dudás, para
  un concepto básico y descriptivo pon 'memorizar'; para uno que se aplica a
  casos, 'inferir'.
- 'importance' DEBE distribuirse: como mucho dos o tres conceptos del fragmento
  pueden pasar de 0.9, y la mayoría debe quedar entre 0.3 y 0.7. Si todo es
  importante, nada lo es y el sistema no puede priorizar.
- 'is_gateway': hay que entenderlo antes de avanzar.
- 'is_threshold': una vez entendido, reorganiza la comprensión del resto.
- 'confidence_extraction' entre 0.0 y 1.0. Usa menos de 0.5 si el concepto
  aparece de pasada o su definición no es clara en el fragmento.
- Responde SOLO con JSON válido. Sin explicaciones ni markdown."""

USER_PROMPT_TEMPLATE = """Texto (sección: {section_title}, páginas {pages}):

{text}

Formato JSON exacto:
{{
  "objeto_de_estudio": {{"title": "string | null", "descripcion": "string | null"}},
  "concepts": [
    {{
      "id": "string",
      "title": "string",
      "definition": "string",
      "sinonimos": ["string"],
      "variantes_terminologicas": ["string"],
      "tipo": "teorico|empirico|metodologico|aplicado",
      "difficulty": "basico|intermedio|avanzado",
      "carga_cognitiva": ["memorizar|discriminar|integrar|inferir"],
      "importance": 0.0,
      "is_gateway": false,
      "is_threshold": false,
      "source_pages": [1],
      "source_section": "string|null",
      "evidencia_textual": "string (COPIA LITERAL del fragmento)",
      "confidence_extraction": 0.0
    }}
  ]
}}"""
