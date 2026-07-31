# Página de revisión — nueva versión

> **Un solo archivo**: `frontend/src/app/review/[id]/page.tsx`.
> Se aplica sobre el repo de **GitHub** (`EdTechProject`), no sobre el Space.
> Vercel redespliega solo al hacer push.

```bash
cd /c/Proyectos/EdTechProject
git pull
cp -rv /c/Users/sebas/Downloads/patchui/. .
git status      # debe mostrar UN archivo modificado
git add -A
git commit -m "Pagina de revision: muestra todo lo que produce el extractor v2.2"
git push
```

## Qué mostraba antes y qué muestra ahora

Antes consumía siete campos: `concepts`, `relations`, `repertoires`, `arguments`, `cases`, `low_confidence_count` y `source_filename`. Todo lo demás que produce el extractor se perdía en el camino.

Ahora hay siete pestañas.

**Diagnóstico** (nueva, y es la que abre por defecto). Conteo de todo lo extraído, avisos de capas fallidas y truncamiento, el detalle de la depuración de conceptos —cuántos entraron, cuántos salieron, qué se unificó con qué, qué grupos quedaron sin unificar por ser demasiado grandes, qué siglas resultaron ambiguas—, el estado de cada capa, los tiempos y el uso por modelo.

Es la pestaña que te habría mostrado el problema de EVI/PCCI/IRM sin tener que leer el JSON a mano.

**Conceptos**. Ahora despliega el detalle de los profundizados: definición ampliada, facetas, con qué otros conceptos se confunde, rol teórico, cómo se mide, tensiones abiertas y evolución en el texto. Con buscador y filtro de confianza baja.

**Mapa** (nueva). Las conexiones con sus nueve tipos, los grupos temáticos calculados y los ejes de comparación con la posición de cada concepto.

**Intuiciones**. Antes mostraba solo nombre, descripción y ejemplo. Ahora también por qué es razonable, dónde sí funciona, qué cambia en el marco científico y con qué concepto se confunde — que es justo lo que necesita el profesor para dar retroalimentación sin descalificar.

**Debate** (reescrita). Marcos teóricos con sus rivales, y tesis con argumentos a favor, en contra y los criterios de rúbrica.

**Casos** (ampliada). Resolución esperada, dominio, variables clave, error incrustado, y las variantes generadas anidadas bajo cada caso con su distancia. Avisa cuántos casos vienen sin resolución esperada, porque esos no sirven para calificar.

**Plan** (nueva). Densidades del documento, qué habilidades se van a poder medir con el motivo cuando la cobertura es baja, qué familias de actividades quedan disponibles, y el orden de estudio sugerido con sus prerrequisitos.

## Dos correcciones

**La confianza cambió de tipo.** Era la etiqueta `"alta"`/`"media"`/`"baja"` y ahora es un número de 0 a 1. La página anterior comparaba contra los textos, así que con el esquema nuevo ninguna comparación daba verdadera y el auto-aprobado de los elementos confiables no funcionaba. Ahora acepta las dos formas.

**Las tesis cambiaron de forma.** Antes cada una tenía `concept_id` (uno) y `position`; ahora tiene `concept_ids` (lista) y `statement`. Por eso aparecían encabezadas con el título de un concepto en vez de con la tesis. Se lee `theses` primero y se cae a `arguments` si no está, así que abre extracciones viejas y nuevas.

## Verificación

Compila con TypeScript en modo estricto sin errores. Cada sección se renderizó con datos reales y con casos borde: listas vacías, `meta` nulo, campos del esquema viejo mezclados con los nuevos. Ninguna lanza excepción.

No la vi corriendo en el navegador, así que el ajuste fino de espaciado puede necesitar un repaso.
