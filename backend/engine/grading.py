"""
engine/grading.py — v3.5

Calificación y emisión de señales cognitivas.

Es la implementación del CONTRATO DE SEÑAL del documento 08: qué dimensión
emite cada mecánica, con qué peso, y bajo qué condiciones.

## El peso evidencial se calcula acá, no aguas abajo

Porque acá está toda la información necesaria: cuántas opciones tenía el ítem y
qué tan plausibles eran, cuántas pistas se usaron, cuánto andamiaje había
activo. Un acierto de opción múltiple con tres distractores flojos y dos pistas
no vale lo mismo que una respuesta escrita sin ayuda, y si el peso se calculara
después esa diferencia ya se habría perdido.

    peso = peso_base(modalidad) × f_azar × f_hints × f_scaffold × f_via

Los coeficientes son priors de arranque, no verdad medida. Están para
calibrarse contra datos reales, que es justamente lo que esta fase busca
producir.

## Pedir ayuda no baja el score

Baja el peso de la evidencia. La diferencia importa: el sistema deja de estar
seguro sobre lo que el estudiante sabe, no pasa a estar seguro de que no sabe.
Castigar la petición de ayuda enseña a no pedirla, que es lo contrario de lo
que el andamiaje busca.
"""
from __future__ import annotations

import logging
import re
import unicodedata
from typing import Any

logger = logging.getLogger(__name__)

PESO_MODALIDAD = {
    "reconocimiento": 0.35,
    "produccion_guiada": 0.60,
    "accion_estructural": 0.70,
    "produccion_libre": 0.85,
}

MODALIDAD_POR_MECANICA = {
    "A1": "reconocimiento",
    "A3": "produccion_guiada",
    "B1": "reconocimiento",
    "B2": "reconocimiento",
    "C1": "reconocimiento",
    "E1": "produccion_guiada",
    "E3": "produccion_guiada",
}


def _norm(t: str) -> str:
    t = unicodedata.normalize("NFKD", str(t or ""))
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"[^\w\s]", " ", t.lower()).strip()


def _tokens(t: str) -> set[str]:
    return {w for w in _norm(t).split() if len(w) > 2}


# ─────────────────────────────────────────────
# Calificación por mecánica
# ─────────────────────────────────────────────

def calificar(mechanic_id: str, item: dict, respuesta: Any) -> dict:
    """Devuelve correcto, puntaje parcial y qué distractor se eligió.

    El distractor elegido importa tanto como el acierto: es lo que permite
    saber qué idea previa activó el estudiante al equivocarse, que es más
    informativo que el hecho de que falló.
    """
    if mechanic_id in ("A1", "B2"):
        opciones = item.get("opciones", [])
        if mechanic_id == "A1":
            elegida = next((o for o in opciones if o.get("id") == respuesta), None)
            correcto = bool(elegida and elegida.get("es_correcta"))
            return {
                "correcto": correcto,
                "partial_score": 1.0 if correcto else 0.0,
                "distractor": None if correcto else elegida,
                "n_efectivo": item.get("n_efectivo", len(opciones)),
            }
        correcto = respuesta == item.get("respuesta_correcta")
        return {
            "correcto": correcto,
            "partial_score": 1.0 if correcto else 0.0,
            "distractor": None,
            "concepto_elegido": respuesta,
            "n_efectivo": item.get("n_efectivo", len(opciones)),
        }

    if mechanic_id == "B1":
        # El ítem afirma algo falso sobre el concepto: lo correcto es decir "no".
        correcto = (respuesta == "no")
        return {
            "correcto": correcto,
            "partial_score": 1.0 if correcto else 0.0,
            "distractor": None if correcto else {
                "repertoire_id": item.get("repertoire_id"),
                "concepto_confundido": item.get("concepto_confundido"),
                "feedback": item.get("feedback"),
            },
            "n_efectivo": 2.0,
        }

    if mechanic_id == "C1":
        # Un par puede tener varios vínculos ciertos a la vez. Si el documento
        # dice que A extiende a B y también que lo requiere, quien elija
        # cualquiera de los dos acertó: exigir uno solo sería castigar por no
        # adivinar cuál teníamos en mente.
        validas = item.get("respuestas_correctas") or [item.get("respuesta_correcta", "")]
        dada = _norm(str(respuesta))
        correcto = any(dada == _norm(v) for v in validas if v)
        return {
            "correcto": correcto,
            "partial_score": 1.0 if correcto else 0.0,
            "distractor": None if correcto else {"tipo_elegido": respuesta},
            "n_efectivo": item.get("n_efectivo", 8),
            # Una arista inferida sostiene menos que una afirmada por el texto.
            "confianza_calificacion": round(0.5 + 0.5 * float(item.get("confianza", 0.6)), 2),
            "otras_validas": [v for v in validas if _norm(v) != dada] if correcto else [],
        }

    if mechanic_id == "A3":
        # Tolerancia en la calificación, no en el material.
        #
        # Ahora se aceptan conceptos con una sola forma registrada —antes se
        # exigían dos y eso descartaba material evaluable— así que la tolerancia
        # tiene que estar acá: quien sabe el concepto pero escribe la sigla, o el
        # nombre sin el paréntesis, o con una palabra de más, acertó.
        #
        # El criterio es la coincidencia de palabras significativas. Un acierto
        # contado como fallo es el peor error posible en aprendizaje: enseña que
        # responder bien no sirve.
        dada_raw = str(respuesta or "")
        dada = _norm(dada_raw)
        if not dada:
            return {"correcto": False, "partial_score": 0.0,
                    "distractor": None, "n_efectivo": 1.0}

        aceptadas = [_norm(a) for a in (item.get("respuestas_aceptadas") or []) if a]

        def sin_parentesis(x: str) -> str:
            return _norm(re.sub(r"\([^)]*\)", " ", x))

        variantes: set[str] = set(aceptadas)
        for a in (item.get("respuestas_aceptadas") or []):
            base = sin_parentesis(a)
            if base:
                variantes.add(base)
            # La sigla entre paréntesis, sola, también cuenta.
            m = re.search(r"\(([^)]{2,12})\)", a)
            if m:
                variantes.add(_norm(m.group(1)))
        variantes = {v for v in variantes if v}

        exacto = dada in variantes
        contenido = (not exacto) and any(
            v and (v in dada or dada in v) for v in variantes
        )

        # Coincidencia por palabras: "vigilancia epistemica" contra
        # "indice de vigilancia epistemica" comparte lo esencial.
        solape = 0.0
        if not exacto and not contenido:
            tokens_dada = _tokens(dada_raw)
            for v in variantes:
                tv = {w for w in v.split() if len(w) > 2}
                if tv and tokens_dada:
                    solape = max(solape, len(tv & tokens_dada) / len(tv))

        if exacto:
            score, correcto = 1.0, True
        elif contenido:
            score, correcto = 0.85, True
        elif solape >= 0.6:
            score, correcto = 0.7, True
        elif solape >= 0.35:
            score, correcto = 0.4, False
        else:
            score, correcto = 0.0, False

        # Si escribió una forma que otro concepto también reclama, no es un
        # error: es una respuesta ambigua y merece que se lo diga.
        ambigua = any(
            _norm(a) == dada for a in (item.get("respuestas_ambiguas") or [])
        )

        return {
            "correcto": correcto,
            "partial_score": score,
            "distractor": None,
            "n_efectivo": 1.0,
            "ambigua": ambigua,
            "confianza_calificacion": 0.85 if exacto else 0.6,
        }

    if mechanic_id in ("E1", "E3"):
        # Sin juez en runtime, se compara contra la resolución esperada por
        # solapamiento de términos. Es una aproximación honesta: sirve para
        # detectar respuestas vacías o completamente fuera de tema, y su
        # confianza se declara baja para que el perfil no se apoye en ella.
        gold = _tokens(item.get("resolucion_esperada", ""))
        dada = _tokens(str(respuesta))
        if not gold or len(dada) < 5:
            score = 0.0 if len(dada) < 5 else 0.5
        else:
            score = round(len(gold & dada) / max(len(gold), 1), 2)
        return {
            "correcto": score >= 0.35,
            "partial_score": min(1.0, score / 0.6) if score else 0.0,
            "distractor": None,
            "n_efectivo": 1.0,
            "confianza_calificacion": 0.4,   # aproximada, no de juez
        }

    return {"correcto": None, "partial_score": 0.0, "distractor": None, "n_efectivo": 1.0}


# ─────────────────────────────────────────────
# Peso evidencial
# ─────────────────────────────────────────────

def peso_evidencial(
    mechanic_id: str,
    n_efectivo: float,
    hints_used: int,
    scaffolds: int,
    via: str = "decision_declarada",
) -> float:
    modalidad = MODALIDAD_POR_MECANICA.get(mechanic_id, "reconocimiento")
    base = PESO_MODALIDAD.get(modalidad, 0.35)

    # Corrección de azar: un ítem de cuatro opciones con distractores flojos
    # tiene el azar de uno de dos. Por eso se usa n_efectivo y no el número
    # nominal de opciones.
    f_azar = (1 - 1 / max(n_efectivo, 1.01)) if modalidad == "reconocimiento" else 1.0
    f_hints = max(0.40, 1 - 0.15 * max(0, hints_used))
    f_scaffold = max(0.50, 1 - 0.10 * max(0, scaffolds))
    f_via = {"decision_declarada": 1.0, "mixta": 0.5, "ejecucion_motora": 0.0}.get(via, 1.0)

    return round(base * f_azar * f_hints * f_scaffold * f_via, 3)


# ─────────────────────────────────────────────
# Emisión de señales
# ─────────────────────────────────────────────

def emitir_senales(
    mechanic_id: str,
    item: dict,
    resultado: dict,
    concept_id: str,
    contexto: dict,
    hints_used: int,
    duration_ms: int,
    modo: str,
) -> list[dict]:
    """Las señales cognitivas de esta respuesta, según el contrato del doc 08.

    Una respuesta puede emitir varias: acertar un A1 emite recuperación, y si
    el distractor elegido traía repertorio, emite además anclaje sobre ese
    repertorio. Son dimensiones distintas del perfil y se guardan por separado.
    """
    senales: list[dict] = []
    correcto = resultado.get("correcto")
    parcial = resultado.get("partial_score", 0.0)
    n_ef = resultado.get("n_efectivo", 1.0)
    scaffolds = sum(1 for v in (contexto.get("andamiaje") or {}).values() if v)
    peso = peso_evidencial(mechanic_id, n_ef, hints_used, scaffolds)

    base = {
        "via": "decision_declarada",
        "peso_evidencial": peso,
        "confidence": resultado.get("confianza_calificacion", 0.8),
    }

    # ── Dimensión de habilidad ─────────────────────────────────────────────
    dimension = {
        "A1": "recuperacion", "A3": "recuperacion",
        "B1": "recuperacion", "B2": "transferencia",
        "C1": "relacion",
        "E1": "transferencia", "E3": "transferencia",
    }.get(mechanic_id)

    if dimension and correcto is not None:
        delta = round((parcial - 0.5) * 0.4, 3)   # −0.2 … +0.2
        target_ids = (
            item.get("par") if mechanic_id == "C1"
            else [concept_id]
        )
        senales.append({
            **base,
            "dimension": dimension,
            "forma": "escalar",
            "target_tipo": "arista" if mechanic_id == "C1" else "concepto",
            "target_ids": target_ids or [concept_id],
            "delta": delta,
        })

    # ── Anclaje: qué idea previa se activó ─────────────────────────────────
    d = resultado.get("distractor") or {}
    repertorio = d.get("repertoire_id") if isinstance(d, dict) else None
    if repertorio:
        senales.append({
            **base,
            "dimension": "anclaje",
            "forma": "observacional",
            "target_tipo": "repertorio",
            "target_ids": [repertorio],
            "se_activo": True,
            "confidence": 0.9,
            # El anclaje no lleva peso evidencial: no mueve un score, actualiza
            # una hipótesis sobre qué repertorio está activo.
            "peso_evidencial": None,
        })

    # Confundir dos conceptos es también evidencia sobre la arista que los une.
    confundido = d.get("concepto_confundido") if isinstance(d, dict) else None
    if confundido and confundido != concept_id:
        senales.append({
            **base,
            "dimension": "relacion",
            "forma": "escalar",
            "target_tipo": "arista",
            "target_ids": [concept_id, confundido],
            "delta": -0.1,
            "confidence": 0.6,
        })

    # ── Automatización: solo con decisión declarada y sin pistas ───────────
    if mechanic_id in ("A1", "A3", "C1") and duration_ms and hints_used == 0:
        senales.append({
            **base,
            "dimension": "automatizacion",
            "forma": "temporal",
            "target_tipo": "concepto",
            "target_ids": [concept_id],
            "latencia_ms": duration_ms,
            # La normalización contra el baseline del propio estudiante se hace
            # en el perfil, cuando hay suficientes observaciones. Guardar la
            # latencia cruda sin normalizar no significa nada por sí solo.
            "latencia_normalizada": None,
            "peso_evidencial": None,
        })

    # ── Acción reguladora: pedir ayuda ─────────────────────────────────────
    if hints_used > 0:
        senales.append({
            "dimension": "srl_accion",
            "forma": "observacional",
            "target_tipo": "sesion",
            "target_ids": [],
            "se_activo": True,
            "confidence": 0.9,
            "via": "decision_declarada",
            "peso_evidencial": None,
        })

    return senales


# ─────────────────────────────────────────────
# Retroalimentación
# ─────────────────────────────────────────────

def construir_feedback(
    mechanic_id: str, item: dict, resultado: dict, modo: str
) -> dict | None:
    """Qué se le devuelve al estudiante.

    En evaluación no se devuelve nada hasta el final: dar retroalimentación
    inmediata durante una evaluación la convierte en aprendizaje, y entonces
    deja de medir lo que dice medir.

    En aprendizaje, cuando el error viene de una intuición cotidiana, la
    respuesta NO es "está mal". Es "eso funciona cuando X, y acá el criterio es
    otro". Esa es la retroalimentación de coexistencia, y el `contraste_cientifico`
    del repertorio existe justamente para poder darla.
    """
    if modo == "evaluacion":
        return None

    correcto = resultado.get("correcto")
    d = resultado.get("distractor") or {}

    if correcto:
        return {"tipo": "acierto", "mensaje": "Correcto."}

    if isinstance(d, dict) and d.get("repertoire_id"):
        return {
            "tipo": "repertorio",
            "mensaje": d.get("feedback") or "",
            "donde_funciona": d.get("contexto_donde_funciona") or "",
            "nota": (
                "Esa idea no es un disparate: funciona en otros contextos. "
                "Lo que cambia acá es el criterio."
            ),
        }

    if isinstance(d, dict) and d.get("feedback"):
        return {"tipo": "distincion", "mensaje": d["feedback"]}

    if mechanic_id == "C1":
        validas = item.get("respuestas_correctas") or [item.get("respuesta_correcta", "")]
        return {
            "tipo": "explicacion",
            "mensaje": item.get("explicacion") or "",
            "correcta": ", ".join(v for v in validas if v),
            "nota": ("Este par admite más de un vínculo: "
                     f"{', '.join(validas)}." if len(validas) > 1 else ""),
        }

    if mechanic_id == "A3":
        aceptadas = item.get("respuestas_aceptadas") or []
        if resultado.get("ambigua"):
            return {
                "tipo": "ambigua",
                "mensaje": ("Ese término también describe a otro concepto de este "
                            "material, así que no alcanza para distinguirlos. "
                            f"Acá se buscaba: {aceptadas[0] if aceptadas else '—'}"),
            }
        if (resultado.get("partial_score") or 0) >= 0.35:
            return {
                "tipo": "cerca",
                "mensaje": (f"Vas por buen camino, pero falta precisión. "
                            f"Se esperaba: {aceptadas[0] if aceptadas else '—'}"),
            }
        return {"tipo": "correccion", "mensaje": f"Se esperaba: {aceptadas[0] if aceptadas else '—'}"}

    if mechanic_id in ("E1", "E3"):
        return {
            "tipo": "modelo",
            "mensaje": "Compará tu respuesta con este análisis:",
            "resolucion_esperada": item.get("resolucion_esperada", ""),
        }

    return {"tipo": "error", "mensaje": "No es correcto."}


# ─────────────────────────────────────────────
# Envolturas metacognitivas
# ─────────────────────────────────────────────
#
# No son ejercicios de contenido: no hay respuesta correcta. Producen las tres
# dimensiones que ninguna mecánica de habilidad puede producir —calibración,
# planeación y autorreflexión— y sin ellas el perfil quedaría con nueve de las
# doce dimensiones vacías para siempre.

def senal_calibracion(concept_id: str, declarado: float) -> dict:
    """G1 APOSTAR. La declaración se guarda sin resultado; se completa después.

    La calibración solo existe como relación entre dos momentos: lo que el
    estudiante creía y lo que pasó. Por eso la señal nace incompleta y el
    orquestador la cierra cuando el ejercicio vinculado se resuelve.
    """
    return {
        "dimension": "calibracion",
        "forma": "calibracion",
        "target_tipo": "concepto",
        "target_ids": [concept_id],
        "declarado": float(declarado),
        "resultado_real": None,
        "error_calibracion": None,
        "confidence": 0.9,
        "via": "decision_declarada",
        "peso_evidencial": None,
    }


def cerrar_calibracion(senal: dict, acerto: bool) -> dict:
    """Completa la señal con lo que efectivamente pasó."""
    real = 1.0 if acerto else 0.0
    declarado = float(senal.get("declarado") or 0.5)
    return {
        **senal,
        "resultado_real": real,
        "error_calibracion": round(abs(declarado - real), 3),
    }


def senal_planeacion(concept_id: str, era_lo_flojo: bool) -> dict:
    """I1 PLANEAR. Elegir por dónde empezar es una decisión medible.

    El criterio no es que elija "lo correcto" —no existe tal cosa— sino si su
    elección se corresponde con dónde tiene menos evidencia. Elegir siempre lo
    que ya domina es una estrategia de evitación, y es exactamente el tipo de
    patrón que la dimensión de planeación existe para detectar.
    """
    return {
        "dimension": "srl_planeacion",
        "forma": "escalar",
        "target_tipo": "sesion",
        "target_ids": [concept_id],
        "delta": 0.15 if era_lo_flojo else -0.05,
        "confidence": 0.5,   # una sola elección dice poco; el patrón dice mucho
        "via": "decision_declarada",
        "peso_evidencial": None,
    }


def senales_reflexion(elegido: str, mas_dificil_real: str | None) -> list[dict]:
    """I4 REFLEXIONAR. Emite autorreflexión y, de paso, calibración de sesión.

    Que el estudiante identifique bien qué le costó es en sí mismo una medida
    de cuánto se conoce. Por eso una sola respuesta produce dos señales: la
    autorreflexión como acto, y la calibración como acierto o desacierto sobre
    su propio desempeño.
    """
    if elegido == "_ninguno" or not mas_dificil_real:
        return [{
            "dimension": "srl_autorreflexion",
            "forma": "escalar",
            "target_tipo": "sesion",
            "target_ids": [],
            "delta": 0.0,
            "confidence": 0.3,
            "via": "decision_declarada",
            "peso_evidencial": None,
        }]

    acerto = elegido == mas_dificil_real
    return [
        {
            "dimension": "srl_autorreflexion",
            "forma": "escalar",
            "target_tipo": "sesion",
            "target_ids": [elegido],
            "delta": 0.15 if acerto else -0.05,
            "confidence": 0.6,
            "via": "decision_declarada",
            "peso_evidencial": None,
        },
        {
            "dimension": "calibracion",
            "forma": "calibracion",
            "target_tipo": "sesion",
            "target_ids": [elegido],
            "declarado": 1.0,
            "resultado_real": 1.0 if acerto else 0.0,
            "error_calibracion": 0.0 if acerto else 1.0,
            "confidence": 0.6,
            "via": "decision_declarada",
            "peso_evidencial": None,
        },
    ]
