"""
engine/store.py — v2.5

Persistencia en Supabase y cálculo del perfil cognitivo.

## El perfil se calcula, no se guarda

Es la decisión de diseño que más va a agradecerse dentro de unos meses. Las
señales quedan en `cognitive_signals` con su peso evidencial, y el perfil se
deriva de ellas cada vez que se necesita. Cuando cambie la fórmula de
ponderación —y va a cambiar, porque los pesos de hoy son priors sin calibrar—
todo el histórico se reinterpreta solo.

Si el perfil se escribiera directamente, cada cambio de fórmula obligaría a
elegir entre datos viejos calculados mal o borrarlos.

## Degradación sin Supabase

Si faltan las credenciales, el módulo funciona en memoria. No es para
producción, pero permite probar el motor completo sin infraestructura, y evita
que la ausencia de una variable de entorno rompa el arranque del Space.
"""
from __future__ import annotations

import logging
import os
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY") or os.environ.get("SUPABASE_KEY")

_cliente = None
_sin_credenciales_avisado = False
_memoria: dict[str, list] = defaultdict(list)


def cliente():
    """Cliente de Supabase, o None si no hay credenciales."""
    global _cliente
    if _cliente is not None:
        return _cliente
    if not (SUPABASE_URL and SUPABASE_KEY):
        # Una sola vez: este aviso se dispara en cada operación y ahogaría el
        # resto del log, que es donde están los errores que sí importan.
        global _sin_credenciales_avisado
        if not _sin_credenciales_avisado:
            logger.warning(
                "[store] Sin credenciales de Supabase: todo vive en memoria y se "
                "pierde al reiniciar. Configurá SUPABASE_URL y SUPABASE_SERVICE_KEY."
            )
            _sin_credenciales_avisado = True
        return None
    try:
        from supabase import create_client
        _cliente = create_client(SUPABASE_URL, SUPABASE_KEY)
        logger.info("[store] Conectado a Supabase.")
        return _cliente
    except Exception as e:  # noqa: BLE001
        logger.error("[store] No se pudo conectar a Supabase: %s", e)
        return None


def _ahora() -> str:
    return datetime.now(timezone.utc).isoformat()


def _insertar(tabla: str, filas: list[dict] | dict) -> list[dict]:
    """Inserta y devuelve las filas con su id.

    El id se genera acá cuando no viene. En Supabase lo pone la base con
    `gen_random_uuid()`, pero en el modo memoria no hay tal cosa: sin esto las
    filas quedan sin id y todo lo que las busca después no las encuentra —el
    documento se guarda y es invisible, que es exactamente el síntoma de
    "subí un PDF y sigue diciendo que no hay material".
    """
    filas = filas if isinstance(filas, list) else [filas]
    con_llave_propia = {"course_materials", "student_plans", "concepts"}
    if tabla not in con_llave_propia:
        for f in filas:
            f.setdefault("id", str(uuid.uuid4()))
    c = cliente()
    if not c:
        _memoria[tabla].extend(filas)
        return filas
    try:
        return c.table(tabla).insert(filas).execute().data or filas
    except Exception as e:  # noqa: BLE001
        # El respaldo en memoria evita perder el dato, pero crea un riesgo:
        # si la escritura falla y la lectura sigue yendo a Supabase, el dato
        # existe y no se encuentra. Por eso `_seleccionar` consulta también la
        # memoria, y por eso este error se registra completo: un fallo de
        # esquema aparece acá antes que como un 404 confuso aguas abajo.
        logger.error("[store] INSERT en %s falló (%s). Se guarda en memoria como "
                     "respaldo, pero esto indica un problema de esquema.", tabla, e)
        _memoria[tabla].extend(filas)
        return filas


def _seleccionar(tabla: str, filtros: dict, orden: str | None = None,
                 limite: int | None = None) -> list[dict]:
    c = cliente()
    if not c:
        return [
            f for f in _memoria.get(tabla, [])
            if all(f.get(k) == v for k, v in filtros.items())
        ][: limite or 1000]
    def _de_memoria() -> list[dict]:
        return [
            f for f in _memoria.get(tabla, [])
            if all(f.get(k) == v for k, v in filtros.items())
        ][: limite or 1000]

    try:
        q = c.table(tabla).select("*")
        for k, v in filtros.items():
            q = q.eq(k, v)
        if orden:
            q = q.order(orden, desc=True)
        if limite:
            q = q.limit(limite)
        filas = q.execute().data or []
    except Exception as e:  # noqa: BLE001
        logger.error("[store] select en %s falló: %s", tabla, e)
        return _de_memoria()

    # Si Supabase no lo tiene, puede estar en el respaldo de memoria por una
    # escritura fallida anterior. Sin esta comprobación, un insert que falló
    # produce un 404 inexplicable en vez de degradar.
    return filas or _de_memoria()


# ─────────────────────────────────────────────
# Estudiantes y cursos
# ─────────────────────────────────────────────

def crear_estudiante(display_name: str) -> dict:
    fila = {"display_name": display_name, "created_at": _ahora()}
    resultado = _insertar("students", fila)
    return resultado[0] if resultado else fila


def obtener_estudiante(student_id: str) -> dict | None:
    filas = _seleccionar("students", {"id": student_id})
    return filas[0] if filas else None


def listar_estudiantes(limite: int = 50) -> list[dict]:
    c = cliente()
    if not c:
        return _memoria.get("students", [])[:limite]
    try:
        return c.table("students").select("*").order(
            "created_at", desc=True).limit(limite).execute().data or []
    except Exception:  # noqa: BLE001
        return []


def guardar_curso(
    owner_id: str | None, title: str, source_filename: str,
    materia_prima: dict, game_bundle: dict | None,
) -> dict:
    """Guarda el curso, su materia prima y los conceptos indexados."""
    curso = {
        "owner_id": owner_id,
        "title": title,
        "source_filename": source_filename,
        "status": "listo",
        "created_at": _ahora(),
        "completed_at": _ahora(),
    }
    # El id se genera acá si Supabase no lo devuelve. En memoria no hay
    # `default gen_random_uuid()`, así que sin esto el curso queda sin id y
    # `documentos_de` no lo encuentra nunca: el documento se guarda y es
    # invisible.
    creado = _insertar("courses", curso)
    curso_id = (creado[0] if creado else curso).get("id") or curso.get("id")
    curso["id"] = curso_id

    _insertar("course_materials", {
        "course_id": curso_id,
        "materia_prima": materia_prima,
        "game_bundle": game_bundle,
        "schema_version": materia_prima.get("schema_version"),
        "updated_at": _ahora(),
    })

    # Los conceptos se normalizan porque el selector los consulta por unidad y
    # por posición en cada sesión; el resto se guarda como documento.
    conceptos = (game_bundle or {}).get("concepts", {})
    filas = [{
        "course_id": curso_id,
        "concept_id": cid,
        "titulo": c.get("titulo"),
        "definicion": c.get("definicion"),
        "unidad_id": c.get("unidad_id"),
        "posicion": c.get("posicion"),
        "dificultad_objetivo": c.get("dificultad_objetivo"),
        "carga_cognitiva": c.get("carga_cognitiva") or [],
        "es_puerta": bool(c.get("es_puerta")),
        "es_umbral": bool(c.get("es_umbral")),
        "importancia": c.get("importancia"),
        "anclaje_textual": c.get("anclaje_textual"),
    } for cid, c in conceptos.items()]
    if filas:
        _insertar("concepts", filas)

    return {**curso, "id": curso_id}


def listar_cursos(owner_id: str | None = None) -> list[dict]:
    c = cliente()
    if not c:
        filas = _memoria.get("courses", [])
        return [f for f in filas if not owner_id or f.get("owner_id") == owner_id]
    try:
        q = c.table("courses").select("*").order("created_at", desc=True)
        if owner_id:
            q = q.eq("owner_id", owner_id)
        return q.execute().data or []
    except Exception:  # noqa: BLE001
        return []


def obtener_bundle(course_id: str) -> dict | None:
    filas = _seleccionar("course_materials", {"course_id": course_id})
    return filas[0].get("game_bundle") if filas else None


def obtener_materia_prima(course_id: str) -> dict | None:
    filas = _seleccionar("course_materials", {"course_id": course_id})
    return filas[0].get("materia_prima") if filas else None


# ─────────────────────────────────────────────
# Plan de estudios del estudiante
# ─────────────────────────────────────────────
#
# Un plan por estudiante, no uno por documento. Cada PDF que sube se fusiona
# con lo que ya tenía: los conceptos repetidos entre lecturas se unifican y el
# orden se recalcula sobre el conjunto.
#
# El plan fusionado se cachea porque fusionar veinte documentos no es gratis,
# pero se invalida en cuanto entra material nuevo. La caché nunca es fuente de
# verdad: se puede borrar entera y se reconstruye desde los documentos.

def documentos_de(student_id: str) -> list[dict]:
    """Los documentos que este estudiante subió, con su materia prima."""
    cursos = [c for c in listar_cursos() if c.get("owner_id") == student_id]
    salida = []
    for c in cursos:
        mp = obtener_materia_prima(c["id"])
        if mp and mp.get("concepts"):
            salida.append({"id": c["id"], "title": c.get("title"), "materia_prima": mp})
    return salida


def guardar_plan(student_id: str, bundle: dict, n_documentos: int) -> None:
    fila = {
        "student_id": student_id, "bundle": bundle,
        "n_documentos": n_documentos, "updated_at": _ahora(),
    }
    c = cliente()
    if not c:
        _memoria["student_plans"] = [
            p for p in _memoria.get("student_plans", []) if p.get("student_id") != student_id
        ]
        _memoria["student_plans"].append(fila)
        return
    try:
        c.table("student_plans").upsert(fila, on_conflict="student_id").execute()
    except Exception as e:  # noqa: BLE001
        logger.error("[store] no se pudo guardar el plan: %s", e)


def obtener_plan(student_id: str) -> tuple[dict | None, int]:
    """(bundle, cuántos documentos lo componen). El número dice si está al día."""
    filas = _seleccionar("student_plans", {"student_id": student_id})
    if not filas:
        return None, 0
    return filas[0].get("bundle"), int(filas[0].get("n_documentos") or 0)


def invalidar_plan(student_id: str) -> None:
    c = cliente()
    if not c:
        _memoria["student_plans"] = [
            p for p in _memoria.get("student_plans", []) if p.get("student_id") != student_id
        ]
        return
    try:
        c.table("student_plans").delete().eq("student_id", student_id).execute()
    except Exception:  # noqa: BLE001
        pass


# ─────────────────────────────────────────────
# Sesiones
# ─────────────────────────────────────────────

def crear_sesion(student_id: str, course_id: str, modo: str, plan: dict) -> dict:
    fila = {
        "student_id": student_id, "course_id": course_id, "modo": modo,
        "estado": "activa", "plan": plan, "paso_actual": 0, "started_at": _ahora(),
    }
    creado = _insertar("sessions", fila)
    return creado[0] if creado else fila


def obtener_sesion(session_id: str) -> dict | None:
    filas = _seleccionar("sessions", {"id": session_id})
    return filas[0] if filas else None


def actualizar_sesion(session_id: str, cambios: dict) -> None:
    """Actualiza la sesión en Supabase Y en el respaldo de memoria.

    Escribir solo en Supabase producía un fallo silencioso: si la sesión había
    quedado en memoria por un insert fallido, el UPDATE afectaba cero filas sin
    error, la lectura posterior caía al respaldo, y `paso_actual` seguía
    valiendo lo mismo. Desde la interfaz eso se veía como que responder una
    pregunta no hacía nada: el servidor devolvía el mismo paso una y otra vez.

    Actualizar los dos lados es barato y elimina la clase entera de bugs de
    "escribo en un sitio y leo de otro".
    """
    for s in _memoria.get("sessions", []):
        if s.get("id") == session_id:
            s.update(cambios)

    c = cliente()
    if not c:
        return
    try:
        c.table("sessions").update(cambios).eq("id", session_id).execute()
    except Exception as e:  # noqa: BLE001
        logger.error("[store] UPDATE de sesión %s falló: %s", session_id, e)


# ─────────────────────────────────────────────
# Eventos y señales
# ─────────────────────────────────────────────

def registrar_respuesta(
    student_id: str, course_id: str, session_id: str,
    evento: dict, senales: list[dict],
) -> None:
    """Guarda el evento y sus señales. El evento es la fuente de verdad."""
    fila_evento = {**evento, "student_id": student_id, "course_id": course_id,
                   "session_id": session_id, "ts": _ahora()}
    creado = _insertar("event_log", fila_evento)
    event_id = (creado[0] if creado else fila_evento).get("id")

    if not senales:
        return

    filas = [{
        **s, "student_id": student_id, "course_id": course_id, "ts": _ahora(),
        **({"event_id": event_id} if event_id else {}),
    } for s in senales]

    resultado = _insertar("cognitive_signals", filas)
    if not resultado:
        logger.error("[store] no se registraron señales del evento %s", event_id)
    else:
        logger.info("[store] %d señal(es) registradas: %s",
                    len(filas), [s.get("dimension") for s in senales])


def historial_concepto(student_id: str, course_id: str) -> dict[str, dict]:
    """Última vez que se vio cada concepto, para calcular reencuentros."""
    c = cliente()
    if not c:
        eventos = [
            e for e in _memoria.get("event_log", [])
            if e.get("student_id") == student_id and e.get("course_id") == course_id
        ]
    else:
        try:
            eventos = c.table("event_log").select(
                "concept_id, ts"
            ).eq("student_id", student_id).eq("course_id", course_id).execute().data or []
        except Exception:  # noqa: BLE001
            eventos = []

    ultima: dict[str, str] = {}
    for e in eventos:
        cid = e.get("concept_id")
        if cid and (cid not in ultima or (e.get("ts") or "") > ultima[cid]):
            ultima[cid] = e.get("ts") or ""
    return {cid: {"ultima": ts} for cid, ts in ultima.items()}


# ─────────────────────────────────────────────
# Perfil cognitivo · derivado, nunca almacenado
# ─────────────────────────────────────────────

def calcular_perfil(student_id: str, course_id: str | None = None) -> dict:
    """Perfil completo a partir de las señales acumuladas.

    Media ponderada por peso evidencial: una respuesta de opción múltiple con
    distractores flojos no cuenta lo mismo que una explicación escrita sin
    ayuda. Sin esa ponderación, veinte aciertos fáciles taparían tres errores
    en lo que de verdad importa.
    """
    # Sin course_id se leen todas las señales del estudiante: como el plan es
    # único, el perfil también lo es. El filtro por curso queda disponible para
    # analizar de qué documento vino cada evidencia.
    senales = _leer_senales(student_id, course_id)

    por_concepto: dict[str, dict[str, dict]] = defaultdict(lambda: defaultdict(
        lambda: {"suma": 0.0, "peso": 0.0, "n": 0}))
    anclajes: dict[str, int] = defaultdict(int)
    latencias: dict[str, list[int]] = defaultdict(list)
    calibraciones: list[dict] = []
    ayudas = 0

    for s in senales:
        dim = s.get("dimension")
        forma = s.get("forma")
        targets = s.get("target_ids") or []

        if forma == "escalar" and s.get("target_tipo") == "concepto":
            peso = s.get("peso_evidencial") or 0.35
            for t in targets:
                celda = por_concepto[t][dim]
                celda["suma"] += (s.get("delta") or 0) * peso
                celda["peso"] += peso
                celda["n"] += 1
        elif forma == "observacional" and dim == "anclaje":
            for t in targets:
                anclajes[t] += 1
        elif forma == "observacional" and dim == "srl_accion":
            ayudas += 1
        elif forma == "temporal":
            for t in targets:
                if s.get("latencia_ms"):
                    latencias[t].append(s["latencia_ms"])
        elif forma == "calibracion" and s.get("resultado_real") is not None:
            calibraciones.append(s)

    conceptos: dict[str, dict] = {}
    for cid, dims in por_concepto.items():
        entrada: dict[str, Any] = {"n_observaciones": 0}
        for dim, celda in dims.items():
            if celda["peso"] > 0:
                # El score parte de 0.5 (sin información) y se mueve con la
                # evidencia acumulada, acotado a [0, 1].
                bruto = 0.5 + (celda["suma"] / celda["peso"]) * 2.5
                entrada[dim] = round(max(0.0, min(1.0, bruto)), 3)
                entrada[f"{dim}_evidencia"] = round(celda["peso"], 2)
            entrada["n_observaciones"] += celda["n"]
        # Automatización: solo con baseline suficiente, si no es ruido.
        muestras = latencias.get(cid, [])
        if len(muestras) >= 5:
            media = sum(muestras) / len(muestras)
            entrada["latencia_media_ms"] = int(media)
        conceptos[cid] = entrada

    error_calib = (
        round(sum(abs(c.get("error_calibracion") or 0) for c in calibraciones)
              / len(calibraciones), 3)
        if calibraciones else None
    )

    return {
        "student_id": student_id,
        "course_id": course_id,
        "conceptos": conceptos,
        "repertorios_activos": dict(sorted(anclajes.items(), key=lambda kv: -kv[1])),
        "calibracion": {"n": len(calibraciones), "error_medio": error_calib},
        "peticiones_de_ayuda": ayudas,
        "n_senales": len(senales),
        "calculado_at": _ahora(),
    }


def _leer_senales(student_id: str, course_id: str | None = None) -> list[dict]:
    def _de_memoria() -> list[dict]:
        return [
            s for s in _memoria.get("cognitive_signals", [])
            if s.get("student_id") == student_id
            and (course_id is None or s.get("course_id") == course_id)
        ]

    c = cliente()
    if not c:
        return _de_memoria()
    try:
        q = c.table("cognitive_signals").select("*").eq("student_id", student_id)
        if course_id:
            q = q.eq("course_id", course_id)
        filas = q.execute().data or []
    except Exception as e:  # noqa: BLE001
        logger.error("[store] lectura de señales falló: %s", e)
        return _de_memoria()

    # Igual que en `_seleccionar`: si Supabase no tiene señales pero el
    # respaldo sí, es que una escritura falló. Sin esta comprobación el perfil
    # sale vacío después de una sesión completa y no hay forma de notarlo desde
    # la interfaz —que es exactamente lo que pasó.
    return filas or _de_memoria()


def resumen_sesiones(student_id: str, limite: int = 10) -> list[dict]:
    c = cliente()
    if not c:
        return [s for s in _memoria.get("sessions", [])
                if s.get("student_id") == student_id][:limite]
    try:
        return c.table("sessions").select("*").eq(
            "student_id", student_id).order("started_at", desc=True
        ).limit(limite).execute().data or []
    except Exception:  # noqa: BLE001
        return []
