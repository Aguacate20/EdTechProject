"""
pipeline/prompts/layer1_concepts.py — v2.1

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

QUÉ NO CUENTA (errores frecuentes que debes evitar):
- Enumeraciones: 'EVI, PCCI e IRM' son TRES conceptos, no uno.
- Enunciados de alcance o de método: 'sistemas persistentes con memoria' como
  descripción del ámbito de aplicación no es un concepto.
- Componentes sin entidad propia: si 'componente de X' solo tiene sentido dentro
  de X, extrae X.
- Frases del autor sobre su propio artículo.

REGLAS:
- 'title': el nombre canónico y completo. Si el texto usa una sigla, escribe la
  forma extendida con la sigla entre paréntesis: 'Índice de Vigilancia Epistémica (EVI)'.
- 'id' en snake_case sin tildes, derivado del título extendido.
- 'sinonimos': otras formas con las que el texto nombra EXACTAMENTE lo mismo,
  incluida la sigla suelta. Se usan para calificar respuestas abiertas, así que
  sé generoso con las variantes pero no incluyas conceptos distintos.
- 'variantes_terminologicas': flexiones, plurales, traducciones aceptables.
- 'definition' en {OUTPUT_LANGUAGE}. 'title' en el idioma del documento.
- 'difficulty' es la dificultad para quien ve el tema por primera vez, no la
  complejidad del texto.
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
  "concepts": [
    {{
      "id": "string",
      "title": "string",
      "definition": "string",
      "sinonimos": ["string"],
      "variantes_terminologicas": ["string"],
      "tipo": "teorico|empirico|metodologico|aplicado",
      "difficulty": "basico|intermedio|avanzado",
      "importance": 0.0,
      "is_gateway": false,
      "is_threshold": false,
      "source_pages": [1],
      "source_section": "string|null",
      "confidence_extraction": 0.0
    }}
  ]
}}"""
