"""
engine/session.py — NUEVO en v2.4

Motor de sesiones: arma la secuencia de ejercicios y aplica el andamiaje.

## Las dos fases no son la misma cosa con más o menos ayuda

Es la distinción que sostiene todo el proyecto y la más fácil de perder al
implementar. La evaluación tiene cuatro propiedades: presión temporal,
consecuencias, comparación con otros, y prohibición de pedir ayuda. El modo
aprendizaje **niega las cuatro**, no las suaviza:

| Propiedad          | Evaluación          | Aprendizaje              |
|--------------------|---------------------|--------------------------|
| Tiempo             | acotado             | libre                    |
| Consecuencias      | el resultado cuenta | nada cuenta              |
| Comparación        | hay puntaje         | no hay puntaje visible   |
| Pedir ayuda        | prohibido           | esperado y sin costo     |

"Evaluación blanda con pistas" no es aprendizaje: sigue midiendo bajo presión,
solo que con muletas. Por eso las dos fases producen secuencias distintas, con
retroalimentación distinta, y emiten señales con contexto de captura distinto.

## El ciclo de adquisición

En modo aprendizaje cada concepto pasa por tres pasos, no por un ejercicio
suelto:

  1. **Exposición** — se muestra el concepto. No se pregunta nada. Sin esto,
     el primer ejercicio evalúa lo que el estudiante trajo de casa.
  2. **Práctica guiada** — ejercicio con andamiaje disponible: pistas, opciones
     reducidas, retroalimentación inmediata que explica.
  3. **Práctica autónoma** — el mismo tipo de ejercicio con el andamiaje
     retirado.

El andamiaje se retira según lo que el perfil ya sabe, no según un cronograma
fijo. Un concepto con evidencia sólida entra directo al paso 3.

## Cómo se elige qué estudiar

El selector cruza tres cosas: el orden del plan de estudio (no proponer algo
cuyos prerrequisitos faltan), el perfil acumulado (priorizar lo flojo y lo no
visto), y la carga cognitiva del concepto (qué familia de ejercicio
corresponde). Eso último es lo que hace que un concepto que cuesta por
memorización reciba ejercicios distintos que uno que cuesta por confusión con
un vecino.
"""
from __future__ import annotations

import logging
import random
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# Configuración de las dos fases
# ─────────────────────────────────────────────

# Envolturas metacognitivas. No son ejercicios: rodean a otro ejercicio o
# cierran la sesión, y emiten dimensiones que ninguna mecánica de contenido
# puede producir.
#
# Sin ellas el perfil solo tendría habilidad (recuperación, relación,
# transferencia) y anclaje. Calibración, planeación y autorreflexión quedarían
# vacías para siempre, y son tres de las doce dimensiones del modelo.
MODOS = {
    "aprendizaje": {
        "ctx_temporal": "libre",
        "ctx_stakes": "privado",
        "ctx_social": "independiente",
        "permite_pistas": True,
        "feedback_inmediato": True,
        "muestra_puntaje": False,
        "ciclo_adquisicion": True,
        "conceptos_por_sesion": 4,
        # G1 APOSTAR: antes de responder, declarar cuánto se cree saber. En
        # aprendizaje se pregunta poco para no volverlo tedioso.
        "calibracion_cada": 3,
        # I1 PLANEAR al abrir e I4 REFLEXIONAR al cerrar.
        "planeacion_inicial": True,
        "reflexion_final": True,
    },
    "evaluacion": {
        "ctx_temporal": "cronometro_suave",
        "ctx_stakes": "visible_profesor",
        "ctx_social": "independiente",
        "permite_pistas": False,
        "feedback_inmediato": False,
        "muestra_puntaje": True,
        "ciclo_adquisicion": False,
        "conceptos_por_sesion": 8,
        # En evaluación se calibra en cada ítem: la brecha entre lo que el
        # estudiante cree saber y lo que le sale es justamente lo que una
        # evaluación puede medir bien.
        "calibracion_cada": 1,
        # No hay planeación —la evaluación no la elige el estudiante— pero sí
        # cierre reflexivo, que no contamina la medición porque va después.
        "planeacion_inicial": False,
        "reflexion_final": True,
    },
}

# Familias de mecánicas ordenadas por exigencia. El selector nunca propone algo
# de una familia muy por encima de lo que el perfil sostiene.
ESCALA_FAMILIAS = ["A", "B", "C", "D", "E", "F"]

# Qué mecánicas tienen ítems precompilados hoy. Las demás necesitan juez en
# runtime y quedan fuera de esta fase.
MECANICAS_JUGABLES = ["A1", "A3", "B1", "B2", "C1", "E1", "E3"]

# Formato de respuesta de cada mecánica. Se usa para no repetir el mismo tipo
# de interacción una y otra vez: una sesión entera de opción múltiple se siente
# igual aunque las preguntas cambien, y además solo ejercita reconocimiento,
# que es la modalidad de menor peso evidencial de todas.
FORMATO = {
    "A1": "opcion_multiple", "B1": "si_no", "B2": "opcion_multiple",
    "C1": "opcion_multiple", "A3": "texto_libre",
    "E1": "texto_libre", "E3": "texto_libre",
}


def _ahora() -> str:
    return datetime.now(timezone.utc).isoformat()


# ─────────────────────────────────────────────
# Selección de conceptos
# ─────────────────────────────────────────────

def seleccionar_conceptos(
    bundle: dict,
    perfil: dict[str, dict],
    modo: str,
    limite: int | None = None,
) -> list[str]:
    """Qué conceptos tocan en esta sesión.

    Tres criterios, en orden de peso: que sea el turno del concepto según el
    plan, que el perfil muestre debilidad o falta de evidencia, y que no se
    haya visto hace un minuto.

    En evaluación el criterio cambia: no se prioriza lo flojo (eso sería
    enseñar, no medir) sino que se busca cobertura del plan.
    """
    cfg = MODOS[modo]
    limite = limite or cfg["conceptos_por_sesion"]
    orden = bundle.get("study_plan", {}).get("orden", [])
    conceptos = bundle.get("concepts", {})

    if not orden:
        orden = list(conceptos.keys())

    # Frontera: hasta dónde puede avanzar. No tiene sentido proponer el concepto
    # 20 si los primeros 5 están en blanco.
    consolidados = sum(
        1 for cid in orden
        if (perfil.get(cid, {}).get("recuperacion", 0) or 0) >= 0.6
    )
    frontera = min(len(orden), consolidados + max(limite, 6))
    disponibles = orden[:frontera]

    if modo == "evaluacion":
        # Cobertura: repartir por unidades, sin favorecer lo flojo.
        por_unidad: dict[str, list[str]] = {}
        for cid in disponibles:
            u = conceptos.get(cid, {}).get("unidad_id") or "sin_unidad"
            por_unidad.setdefault(u, []).append(cid)
        elegidos: list[str] = []
        i = 0
        while len(elegidos) < limite and any(por_unidad.values()):
            for u in list(por_unidad):
                if por_unidad[u] and len(elegidos) < limite:
                    elegidos.append(por_unidad[u].pop(0))
            i += 1
            if i > 50:
                break
        return elegidos

    # Aprendizaje: prioriza lo que menos evidencia tiene y lo que peor va.
    def prioridad(cid: str) -> tuple:
        p = perfil.get(cid, {})
        n = p.get("n_observaciones", 0) or 0
        score = p.get("recuperacion", 0) or 0
        pos = conceptos.get(cid, {}).get("posicion", 999)
        return (
            0 if n == 0 else 1,        # lo nunca visto primero
            score,                      # después lo más flojo
            pos,                        # a igualdad, sigue el plan
        )

    return sorted(disponibles, key=prioridad)[:limite]


# ─────────────────────────────────────────────
# Selección de mecánica
# ─────────────────────────────────────────────

def elegir_mecanica(
    concepto: dict,
    perfil_concepto: dict,
    bundle: dict,
    paso_ciclo: str,
    formato_previo: str | None = None,
) -> str | None:
    """Qué tipo de ejercicio corresponde para este concepto y este estudiante.

    Aquí es donde la carga cognitiva deja de ser un dato y se vuelve una
    decisión. Un concepto que cuesta porque hay mucho que retener pide
    ejercicios de recuperación; uno que cuesta porque se confunde con su vecino
    pide discriminación. Antes esa diferencia existía en el JSON y nadie la
    usaba.
    """
    disponibles = {
        m for m in MECANICAS_JUGABLES
        if bundle.get("mechanics", {}).get(m, {}).get("disponible")
        and bundle.get("items", {}).get(m)
    }
    if not disponibles:
        return None

    familias = concepto.get("familias_recomendadas") or ["A"]
    recuperacion = perfil_concepto.get("recuperacion", 0) or 0

    # Techo por nivel de dominio: no se propone transferencia sobre algo que
    # todavía no se reconoce. El andamiaje no es solo dar pistas, es también
    # no exigir por encima de lo que la evidencia sostiene.
    if recuperacion < 0.4:
        familias = ["A"]
    elif recuperacion < 0.65:
        familias = [f for f in familias if f in ("A", "B", "C")] or ["A", "B"]

    # Tras exponer el concepto, el primer ejercicio es de reconocimiento: pedir
    # evocación libre de algo que se acaba de ver mide lectura reciente, no
    # aprendizaje.
    if paso_ciclo == "guiada":
        familias = ["A"] + [f for f in familias if f != "A"]

    candidatas = [
        m for f in familias for m in MECANICAS_JUGABLES
        if m.startswith(f) and m in disponibles
    ]
    if not candidatas:
        return sorted(disponibles)[0] if disponibles else None

    # Variedad de formato: si el paso anterior ya fue opción múltiple, se
    # prefiere una mecánica que pida otra cosa. La recuperación por evocación
    # (A3) pesa casi el doble que el reconocimiento, así que alternar no es
    # solo cuestión de que no aburra: mejora la calidad de la evidencia.
    if formato_previo:
        distintas = [m for m in candidatas if FORMATO.get(m) != formato_previo]
        if distintas:
            return distintas[0]
    return candidatas[0]


def buscar_item(
    bundle: dict, mechanic_id: str, concept_id: str, usados: set[str],
    conceptos_permitidos: set[str] | None = None,
) -> dict | None:
    """Un ítem de esa mecánica SOBRE ESE CONCEPTO que no se haya usado ya.

    La versión anterior, si no encontraba ítem para el concepto, aceptaba
    cualquiera de esa mecánica. Parecía razonable —mejor practicar algo que
    dejar el paso vacío— y era el origen de un problema serio: el estudiante
    recibía preguntas sobre conceptos que la sesión nunca le había explicado.
    Preguntar por algo no expuesto no mide aprendizaje, mide lo que traía de
    antes, y en modo aprendizaje eso es justamente lo que se quiere evitar.

    Ahora, si no hay ítem para este concepto, el paso no se genera. Una sesión
    más corta es mejor que una sesión que pregunta lo que no enseñó.

    `conceptos_permitidos` deja una puerta estrecha: en evaluación sí se puede
    usar un ítem de otro concepto, siempre que sea uno de los que la sesión
    incluye.
    """
    items = bundle.get("items", {}).get(mechanic_id, [])

    def toca(i: dict, cid: str) -> bool:
        return (i.get("concept_id") == cid
                or cid in (i.get("concept_ids") or [])
                or cid in (i.get("par") or []))

    candidatos = [i for i in items if i.get("id") not in usados and toca(i, concept_id)]
    if candidatos:
        return candidatos[0]

    if conceptos_permitidos:
        alternos = [
            i for i in items
            if i.get("id") not in usados
            and any(toca(i, c) for c in conceptos_permitidos)
        ]
        if alternos:
            return alternos[0]
    return None


# ─────────────────────────────────────────────
# Construcción del plan de sesión
# ─────────────────────────────────────────────

def construir_plan(
    bundle: dict,
    perfil: dict[str, dict],
    modo: str,
    limite_conceptos: int | None = None,
) -> dict:
    """Arma la secuencia completa de pasos de la sesión."""
    cfg = MODOS[modo]
    conceptos_ids = seleccionar_conceptos(bundle, perfil, modo, limite_conceptos)
    conceptos = bundle.get("concepts", {})
    pasos: list[dict] = []
    usados: set[str] = set()
    formato_previo: str | None = None

    for cid in conceptos_ids:
        c = conceptos.get(cid) or {}
        p = perfil.get(cid, {})
        visto = (p.get("n_observaciones", 0) or 0) > 0
        dominio = p.get("recuperacion", 0) or 0

        if cfg["ciclo_adquisicion"]:
            # Exposición solo si es nuevo o si va francamente mal: repetir la
            # ficha de algo que ya domina es ruido, no andamiaje.
            if not visto or dominio < 0.35:
                pasos.append({
                    "tipo": "exposicion",
                    "concept_id": cid,
                    "titulo": c.get("titulo"),
                    "definicion": c.get("definicion") or c.get("definicion_corta"),
                    "subdimensiones": c.get("subdimensiones") or [],
                    "carga_cognitiva": c.get("carga_cognitiva") or [],
                })

            secuencia = ["guiada"] if dominio >= 0.6 else ["guiada", "autonoma"]
        else:
            secuencia = ["evaluacion"]

        for paso_ciclo in secuencia:
            mech = elegir_mecanica(c, p, bundle, paso_ciclo, formato_previo)
            if not mech:
                continue
            # Solo ítems del concepto que la sesión acaba de trabajar. En
            # evaluación se admiten los de otros conceptos de la propia sesión.
            item = buscar_item(
                bundle, mech, cid, usados,
                conceptos_permitidos=set(conceptos_ids) if modo == "evaluacion" else None,
            )
            if not item:
                # Sin material para este concepto y esta mecánica: se prueba
                # con otra antes de rendirse.
                for alterna in MECANICAS_JUGABLES:
                    if alterna == mech:
                        continue
                    if not bundle.get("mechanics", {}).get(alterna, {}).get("disponible"):
                        continue
                    item = buscar_item(bundle, alterna, cid, usados)
                    if item:
                        mech = alterna
                        break
            if not item:
                continue
            usados.add(item["id"])
            formato_previo = FORMATO.get(mech)

            # G1 APOSTAR: la declaración va ANTES de ver el resultado, si no
            # no mide calibración sino memoria de lo que acaba de pasar.
            cada = cfg.get("calibracion_cada", 0)
            n_ejercicios = sum(1 for x in pasos if x["tipo"] == "ejercicio")
            if cada and n_ejercicios % cada == 0:
                pasos.append({
                    "tipo": "calibracion",
                    "mechanic_id": "G1",
                    "concept_id": cid,
                    "titulo": c.get("titulo"),
                    "vinculado_a": item["id"],
                })

            pasos.append({
                "tipo": "ejercicio",
                "paso_ciclo": paso_ciclo,
                "concept_id": cid,
                "mechanic_id": mech,
                "item_id": item["id"],
                # El andamiaje se retira en la práctica autónoma y no existe en
                # evaluación. Es la retirada gradual, aplicada por paso.
                "andamiaje": {
                    "pistas": cfg["permite_pistas"] and paso_ciclo == "guiada",
                    "feedback_inmediato": cfg["feedback_inmediato"],
                    "opciones_reducidas": paso_ciclo == "guiada" and dominio < 0.4,
                },
                "fading_level": 0 if paso_ciclo == "guiada" else 1,
            })

    if cfg.get("planeacion_inicial") and pasos:
        # I1 PLANEAR: elegir por dónde empezar es una decisión de planeación, y
        # es la única forma de medir esa dimensión sin inventarla.
        pasos.insert(0, {
            "tipo": "planeacion",
            "mechanic_id": "I1",
            "opciones": [
                {"id": cid, "titulo": (conceptos.get(cid) or {}).get("titulo", cid),
                 "visto": (perfil.get(cid, {}).get("n_observaciones", 0) or 0) > 0}
                for cid in conceptos_ids
            ],
        })

    if cfg.get("reflexion_final") and pasos:
        # I4 REFLEXIONAR: qué cree que le costó. Se contrasta después contra la
        # evidencia real de la sesión, lo que produce una segunda señal de
        # calibración a nivel sesión.
        pasos.append({
            "tipo": "reflexion",
            "mechanic_id": "I4",
            "conceptos": [
                {"id": cid, "titulo": (conceptos.get(cid) or {}).get("titulo", cid)}
                for cid in conceptos_ids
            ],
        })

    return {
        "modo": modo,
        "contexto": {
            "temporal": cfg["ctx_temporal"],
            "stakes": cfg["ctx_stakes"],
            "social": cfg["ctx_social"],
        },
        "muestra_puntaje": cfg["muestra_puntaje"],
        "conceptos": conceptos_ids,
        "pasos": pasos,
        "creado_at": _ahora(),
    }


# ─────────────────────────────────────────────
# Presentación de un paso
# ─────────────────────────────────────────────

def preparar_paso(paso: dict, bundle: dict) -> dict:
    """Devuelve el paso listo para mostrar, sin filtrar la respuesta correcta.

    Todo lo que revele la respuesta se quita acá, en el servidor. Mandar el
    ítem completo al navegador y confiar en que el frontend no lo mire sería
    regalar la respuesta a cualquiera que abra las herramientas de desarrollo.
    """
    if paso["tipo"] == "exposicion":
        return {**paso, "requiere_respuesta": False}

    if paso["tipo"] == "calibracion":
        return {
            "tipo": "calibracion",
            "mechanic_id": "G1",
            "concept_id": paso["concept_id"],
            "enunciado": f"Antes de responder sobre «{paso.get('titulo')}»: "
                         f"¿qué tan seguro estás de acertar?",
            "opciones": [
                {"id": "0.2", "texto": "Poco: estoy adivinando"},
                {"id": "0.5", "texto": "A medias"},
                {"id": "0.8", "texto": "Bastante seguro"},
                {"id": "0.95", "texto": "Seguro"},
            ],
            "requiere_respuesta": True,
        }

    if paso["tipo"] == "planeacion":
        return {
            "tipo": "planeacion",
            "mechanic_id": "I1",
            "enunciado": "¿Por dónde querés empezar?",
            "ayuda": "No hay respuesta correcta. Elegir bien qué trabajar "
                     "primero también es parte de aprender.",
            "opciones": [
                {"id": o["id"],
                 "texto": o["titulo"] + ("" if o["visto"] else "  · nuevo")}
                for o in paso.get("opciones", [])
            ],
            "requiere_respuesta": True,
        }

    if paso["tipo"] == "reflexion":
        return {
            "tipo": "reflexion",
            "mechanic_id": "I4",
            "enunciado": "¿Qué te costó más de esta sesión?",
            "ayuda": "Lo que elijas se compara con lo que realmente te costó. "
                     "No hay penalización: sirve para saber qué tan bien te conocés.",
            "opciones": [
                {"id": c["id"], "texto": c["titulo"]} for c in paso.get("conceptos", [])
            ] + [{"id": "_ninguno", "texto": "Nada en particular"}],
            "requiere_respuesta": True,
        }

    item = _buscar_item_por_id(bundle, paso["mechanic_id"], paso["item_id"])
    if not item:
        return {**paso, "error": "ítem no encontrado"}

    mech = paso["mechanic_id"]
    publico: dict[str, Any] = {
        "tipo": "ejercicio",
        "paso_ciclo": paso.get("paso_ciclo"),
        "mechanic_id": mech,
        "item_id": item["id"],
        "concept_id": paso["concept_id"],
        "enunciado": item.get("enunciado"),
        "andamiaje": paso.get("andamiaje", {}),
        "requiere_respuesta": True,
    }

    if mech in ("A1", "B2"):
        opciones = list(item.get("opciones", []))
        if mech == "A1":
            if paso.get("andamiaje", {}).get("opciones_reducidas") and len(opciones) > 3:
                # Reducir opciones es andamiaje real: baja la carga sin dar la
                # respuesta. Se conserva la correcta y los distractores más
                # plausibles, que son los que enseñan algo al fallar.
                correcta = [o for o in opciones if o.get("es_correcta")]
                otras = [o for o in opciones if not o.get("es_correcta")][:2]
                opciones = correcta + otras
            publico["opciones"] = [
                {"id": o["id"], "texto": o["texto"]}
                for o in _mezclar(opciones, item["id"])
            ]
        else:
            conceptos = bundle.get("concepts", {})
            publico["opciones"] = [
                {"id": cid, "texto": conceptos.get(cid, {}).get("titulo", cid)}
                for cid in _mezclar(list(opciones), item["id"])
            ]
    elif mech == "B1":
        publico["afirmacion"] = item.get("afirmacion")
        publico["opciones"] = [
            {"id": "si", "texto": "Sí, la describe"},
            {"id": "no", "texto": "No, describe otra cosa"},
        ]
    elif mech == "A3":
        publico["formato"] = "texto_libre"
    elif mech == "C1":
        conceptos = bundle.get("concepts", {})
        publico["par"] = [
            conceptos.get(c, {}).get("titulo", c) for c in item.get("par", [])
        ]
        publico["opciones"] = [
            {"id": t, "texto": t} for t in item.get("opciones", [])
        ]
    elif mech in ("E1", "E3"):
        publico["formato"] = "texto_libre"
        publico["variables_clave"] = item.get("variables_clave") or []
        publico["dominio"] = item.get("dominio")

    if paso.get("andamiaje", {}).get("pistas"):
        publico["pista_disponible"] = True

    return publico


def obtener_pista(item: dict, mechanic_id: str, bundle: dict) -> str:
    """Una pista que reduce el espacio de búsqueda sin dar la respuesta.

    Pedir ayuda no debe costar puntaje: el efecto viaja como menor peso
    evidencial, no como castigo. El sistema deja de estar seguro, no pasa a
    estar seguro de que el estudiante no sabe.
    """
    if mechanic_id == "A1":
        incorrectas = [o for o in item.get("opciones", []) if not o.get("es_correcta")]
        if incorrectas:
            return f"Puedes descartar esta: «{incorrectas[0]['texto'][:120]}…»"
    if mechanic_id == "A3":
        aceptadas = item.get("respuestas_aceptadas") or []
        if aceptadas:
            return f"Empieza por «{aceptadas[0][:3]}…» y tiene {len(aceptadas[0])} letras."
    if mechanic_id == "C1":
        return f"La explicación del texto dice: «{(item.get('explicacion') or '')[:150]}»"
    if mechanic_id in ("E1", "E3"):
        claves = item.get("variables_clave") or []
        if claves:
            return f"Fíjate en: {', '.join(claves[:3])}."
    return "Vuelve a leer el enunciado con atención al término principal."


def _buscar_item_por_id(bundle: dict, mechanic_id: str, item_id: str) -> dict | None:
    for i in bundle.get("items", {}).get(mechanic_id, []):
        if i.get("id") == item_id:
            return i
    return None


def _mezclar(seq: list, semilla: str) -> list:
    """Orden estable por ítem: el mismo ejercicio siempre presenta las opciones
    igual, para que reintentarlo no sea una lotería distinta."""
    r = random.Random(semilla)
    copia = list(seq)
    r.shuffle(copia)
    return copia


def reordenar_por_eleccion(plan: dict, concept_id: str) -> dict:
    """Mueve al frente los pasos del concepto que el estudiante eligió.

    Sin esto, I1 PLANEAR era decorativo: se preguntaba por dónde quería empezar
    y la sesión arrancaba por donde ya estaba planificada. Preguntar algo y
    después ignorarlo es peor que no preguntar, porque enseña que las
    decisiones del estudiante no cuentan —justo lo contrario de lo que la
    dimensión de planeación quiere fomentar.

    Se mueve el bloque completo del concepto (su exposición, su calibración y
    sus ejercicios) conservando el orden interno, que es el ciclo de
    adquisición y no se puede alterar.
    """
    pasos = plan.get("pasos", [])
    if not pasos or not concept_id:
        return plan

    fijos = [p for p in pasos if p["tipo"] in ("planeacion",)]
    finales = [p for p in pasos if p["tipo"] == "reflexion"]
    cuerpo = [p for p in pasos if p not in fijos and p not in finales]

    # La calibración se identifica por el ejercicio al que está atada.
    item_de_concepto = {
        p["item_id"] for p in cuerpo
        if p["tipo"] == "ejercicio" and p.get("concept_id") == concept_id
    }

    def es_del_concepto(p: dict) -> bool:
        if p.get("concept_id") == concept_id:
            return True
        return p.get("vinculado_a") in item_de_concepto

    elegidos = [p for p in cuerpo if es_del_concepto(p)]
    resto = [p for p in cuerpo if not es_del_concepto(p)]

    plan["pasos"] = fijos + elegidos + resto + finales
    plan["_reordenado_por"] = concept_id
    return plan
