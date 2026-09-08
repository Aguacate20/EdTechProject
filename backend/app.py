"""
app.py
FastAPI entry point. Se despliega en Hugging Face Spaces con Docker.
Puerto 7860 (requerido por HF Spaces).
"""
import asyncio
import logging
import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile

# El motor cognitivo se importa arriba: el runner del pipeline lo usa para
# incorporar el documento al plan, y ese código corre antes de que Python
# llegue a la sección de endpoints de perfil que está más abajo.
from engine import grading, merge, session as session_engine, store
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from pipeline import run_pipeline

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────
# Job store en memoria (en producción reemplazar con Redis/Supabase)
# ─────────────────────────────────────────────────────────────
_jobs: dict[str, dict[str, Any]] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("EdTech Extractor backend iniciado")
    yield
    logger.info("Shutdown")


app = FastAPI(
    title="EdTech Extractor API",
    description="Pipeline de extracción de materia prima pedagógica desde PDFs",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS: permite peticiones desde Vercel (frontend)
ALLOWED_ORIGINS = os.environ.get(
    "ALLOWED_ORIGINS",
    "http://localhost:3000,https://*.vercel.app"
).split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Ajustar en producción con ALLOWED_ORIGINS
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─────────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}


@app.post("/extract", status_code=202)
async def extract_pdf(
    file: UploadFile = File(..., description="PDF del profesor"),
    course_id: str | None = Form(None, description="ID del curso en Supabase (opcional)"),
    student_id: str | None = Form(None, description="Si viene, el documento se suma solo al plan"),
):
    """
    Inicia el pipeline de extracción de forma asíncrona.
    Retorna un job_id para consultar el progreso con GET /jobs/{job_id}.

    Con `student_id`, el documento se guarda y se suma al plan del estudiante en
    cuanto termina: no hace falta un paso manual de "guardar como curso". Es lo
    que hace que subir un PDF sea una sola acción desde el perfil.
    """
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Solo se aceptan archivos PDF")
    
    max_size_mb = 20
    contents = await file.read()
    if len(contents) > max_size_mb * 1024 * 1024:
        raise HTTPException(
            status_code=413,
            detail=f"El archivo supera el límite de {max_size_mb}MB"
        )
    
    job_id = str(uuid.uuid4())
    _jobs[job_id] = {
        "job_id": job_id,
        "status": "pending",
        "filename": file.filename,
        "course_id": course_id,
        "student_id": student_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "result": None,
        "error": None,
    }
    
    # Lanzar pipeline en background sin bloquear la respuesta
    asyncio.create_task(
        _run_pipeline_job(job_id, contents, file.filename, course_id)
    )
    
    return {
        "job_id": job_id,
        "status": "pending",
        "message": "Pipeline iniciado. Consulta el progreso en GET /jobs/{job_id}",
    }


@app.get("/jobs/{job_id}")
async def get_job(job_id: str, incluir_bundle: bool = True):
    """Estado y resultado de un job de extracción.

    Con `?incluir_bundle=false` se omite el paquete de juego, que puede pesar
    bastante y no hace falta para la página de revisión docente.
    """
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job no encontrado")
    if incluir_bundle or not job.get("result"):
        return job
    resultado = {k: v for k, v in job["result"].items() if k != "game_bundle"}
    return {**job, "result": resultado}


@app.get("/jobs/{job_id}/bundle")
async def get_bundle(job_id: str):
    """Paquete listo para el juego.

    Es la salida que consume el motor de juego: conceptos indexados por id,
    grafo con adyacencia precalculada, plan de estudio con unidades y curva de
    dificultad, pools de distractores ya caracterizados, ítems precompilados y
    un veredicto por mecánica.

    Se sirve aparte de `/jobs/{job_id}` a propósito. La materia prima está
    organizada por etapa del pipeline, con procedencia y confianza en cada
    pieza, porque su lector es el profesor; el paquete de juego está organizado
    por búsqueda. Son dos consumidores con necesidades opuestas y un solo
    documento no sirve bien a ninguno.
    """
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job no encontrado")
    if job.get("status") != "completed":
        raise HTTPException(
            status_code=409,
            detail=f"El job está en estado '{job.get('status')}'; todavía no hay paquete.",
        )
    bundle = (job.get("result") or {}).get("game_bundle")
    if not bundle:
        raise HTTPException(
            status_code=422,
            detail="La extracción no produjo material suficiente para compilar un paquete.",
        )
    return bundle


@app.post("/compile")
async def compile_existing(payload: dict[str, Any]):
    """Compila una materia prima ya extraída, sin volver a procesar el PDF.

    Útil para recompilar tras editar el material a mano, o para probar cambios
    del compilador sobre una extracción guardada sin gastar cuota de LLM.
    """
    from pipeline.compiler import compile_bundle

    data = payload.get("result", payload)
    if not data.get("concepts"):
        raise HTTPException(status_code=400, detail="El cuerpo no trae `concepts`.")
    try:
        return compile_bundle(
            data,
            permitir_juez=bool(payload.get("permitir_juez", True)),
            permitir_peer=bool(payload.get("permitir_peer", False)),
        )
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Fallo al compilar: {e}") from e


@app.get("/jobs")
async def list_jobs():
    """Lista todos los jobs (para debugging)."""
    return {
        "jobs": [
            {k: v for k, v in job.items() if k != "result"}
            for job in _jobs.values()
        ]
    }


# ─────────────────────────────────────────────────────────────
# Background task
# ─────────────────────────────────────────────────────────────

async def _run_pipeline_job(
    job_id: str,
    pdf_bytes: bytes,
    filename: str,
    course_id: str | None,
) -> None:
    """Ejecuta el pipeline y actualiza el job store."""
    _jobs[job_id]["status"] = "running"
    _jobs[job_id]["started_at"] = datetime.now(timezone.utc).isoformat()
    
    try:
        result = await run_pipeline(
            pdf_bytes=pdf_bytes,
            filename=filename,
            course_id=course_id,
        )
        _jobs[job_id]["status"] = "completed"
        _jobs[job_id]["result"] = result
        _jobs[job_id]["completed_at"] = datetime.now(timezone.utc).isoformat()
        logger.info(f"[job:{job_id}] Completado exitosamente")

        # Si la subida vino desde el perfil de alguien, el documento se
        # incorpora a su plan acá mismo. Sin esto la extracción termina bien y
        # el material no aparece en ninguna parte: el estudiante vuelve al
        # perfil y ve el mismo mensaje de "subí un PDF para empezar".
        sid = _jobs[job_id].get("student_id")
        if sid and result.get("concepts"):
            try:
                curso = store.guardar_curso(
                    owner_id=sid,
                    title=result.get("source_filename") or "Documento",
                    source_filename=result.get("source_filename", ""),
                    materia_prima={k: v for k, v in result.items() if k != "game_bundle"},
                    game_bundle=result.get("game_bundle"),
                )
                store.invalidar_plan(sid)
                _jobs[job_id]["course_id"] = curso.get("id")
                logger.info("[job:%s] incorporado al plan de %s (curso %s)",
                            job_id, sid, curso.get("id"))
            except Exception as e:  # noqa: BLE001
                _jobs[job_id]["warning"] = f"No se pudo incorporar al plan: {e}"
                logger.error("[job:%s] fallo al incorporar al plan: %s",
                             job_id, e, exc_info=True)
    except Exception as e:
        logger.error(f"[job:{job_id}] Error: {e}", exc_info=True)
        _jobs[job_id]["status"] = "failed"
        _jobs[job_id]["error"] = str(e)
        _jobs[job_id]["failed_at"] = datetime.now(timezone.utc).isoformat()

# ============================================================================
# Perfil, cursos y sesiones
#
# Esta sección implementa el ciclo completo sin mecánicas de juego: subir
# material, estudiar con andamiaje, evaluar sin él, y acumular el perfil.
# El objetivo es comprobar que el modelo cognitivo funciona antes de montarle
# un juego encima.
# ============================================================================



@app.post("/students")
async def crear_estudiante(payload: dict[str, Any]):
    """Perfil mínimo: solo un nombre. Sin contraseña.

    Para esta fase basta con un id estable que permita acumular historial. La
    autenticación real se añade después sin tocar nada de esto.
    """
    nombre = (payload.get("display_name") or "").strip()
    if not nombre:
        raise HTTPException(status_code=400, detail="Falta `display_name`.")
    # v3.9: con `codigo_jugador` se recupera un perfil existente (otro
    # dispositivo); sin él se crea uno nuevo. El código vuelve siempre.
    codigo = (payload.get("codigo_jugador") or "").strip()
    est = store.buscar_estudiante(nombre, codigo) if codigo else None
    if codigo and not est:
        raise HTTPException(status_code=404, detail="No hay un perfil con ese nombre y ese código de jugador.")
    if not est:
        est = store.crear_estudiante(nombre)
    return {**est, "codigo_jugador": store.codigo_de(str(est.get("id", "")))}


@app.get("/campos/{codigo}")
async def campo_por_codigo(codigo: str):
    """El campo temático detrás de un código de 6 caracteres, con su bundle.
    Es lo que el juego carga al entrar."""
    curso = store.curso_por_codigo(codigo)
    if not curso:
        raise HTTPException(status_code=404, detail="No hay un campo con ese código.")
    bundle = store.obtener_bundle(str(curso.get("id")))
    if not bundle:
        raise HTTPException(status_code=409, detail="El campo existe pero todavía no tiene material publicado.")
    return {"course_id": curso.get("id"), "nombre": curso.get("title") or curso.get("nombre") or curso.get("name"), "bundle": bundle}


@app.get("/students/{student_id}/atlas")
async def leer_atlas(student_id: str, campo: str):
    fila = store.obtener_atlas(student_id, campo)
    if not fila:
        return {"atlas": None, "updated_at": None}
    return {"atlas": fila.get("atlas"), "updated_at": fila.get("updated_at")}


@app.post("/students/{student_id}/atlas")
async def escribir_atlas(student_id: str, payload: dict[str, Any]):
    campo = (payload.get("campo") or "").strip()
    atlas = payload.get("atlas")
    if not campo or not isinstance(atlas, dict):
        raise HTTPException(status_code=400, detail="Faltan `campo` y `atlas`.")
    return store.guardar_atlas(student_id, campo, atlas)


@app.get("/students")
async def listar_estudiantes():
    """Los perfiles existentes, con su código de jugador, para elegir uno al entrar
    (como el menú del extractor). Sin contraseña: es un piloto en aula."""
    return {"students": [
        {**e, "codigo_jugador": store.codigo_de(str(e.get("id", "")))}
        for e in store.listar_estudiantes()
    ]}


@app.get("/campos")
async def listar_campos():
    """Los campos temáticos publicados: código, nombre y tamaño. Es la lista que
    ve el estudiante al entrar; un campo sin material publicado no aparece."""
    campos = []
    for curso in store.listar_cursos()[:40]:
        cid = str(curso.get("id", ""))
        bundle = store.obtener_bundle(cid)
        if not bundle:
            continue
        stats = bundle.get("stats") or {}
        campos.append({
            "codigo": store.codigo_de(cid),
            "course_id": cid,
            "nombre": curso.get("title") or curso.get("nombre") or curso.get("name") or bundle.get("source_filename") or cid,
            "conceptos": stats.get("conceptos"),
            "aristas": stats.get("aristas"),
        })
    return {"campos": campos}


@app.get("/students/{student_id}")
async def obtener_estudiante(student_id: str):
    est = store.obtener_estudiante(student_id)
    if not est:
        raise HTTPException(status_code=404, detail="Estudiante no encontrado")
    return {
        "student": est,
        "courses": store.listar_cursos(),
        "sessions": store.resumen_sesiones(student_id),
    }


def _plan_del_estudiante(student_id: str, forzar: bool = False) -> dict | None:
    """El plan fusionado, reconstruyéndolo si entró material nuevo.

    El número de documentos guardado con la caché es lo que dice si está al
    día: si el estudiante subió algo desde la última fusión, no coincide y se
    rehace. Así no hace falta invalidar a mano en cada punto de escritura.
    """
    documentos = store.documentos_de(student_id)
    if not documentos:
        return None
    cacheado, n = store.obtener_plan(student_id)
    if cacheado and n == len(documentos) and not forzar:
        return cacheado
    bundle = merge.fusionar_documentos(documentos)
    store.guardar_plan(student_id, bundle, len(documentos))
    return bundle


@app.get("/students/{student_id}/biblioteca")
async def biblioteca(student_id: str):
    """Los documentos del perfil, sin la materia prima: título, tamaño y cuántos
    conceptos aportó. Es la lista que ve el estudiante en Biblioteca."""
    docs = []
    for d in store.documentos_de(student_id):
        mp = d.get("materia_prima") or {}
        docs.append({
            "id": d.get("id"), "titulo": d.get("title") or d.get("id"),
            "conceptos": len(mp.get("concepts") or []),
            "relaciones": len(mp.get("relations") or []),
            "objeto_de_estudio": (mp.get("objeto_de_estudio") or {}).get("title"),
        })
    return {"documentos": docs}


@app.get("/students/{student_id}/bundle")
async def bundle_del_plan(student_id: str):
    """El paquete de juego del plan completo, listo para el motor.

    Es el equivalente de `/jobs/{id}/bundle` pero sobre el plan fusionado en
    vez de un documento suelto: conceptos indexados por id, grafo con
    adyacencia precalculada, plan de estudio con unidades y curva de
    dificultad, pools de distractores caracterizados, ítems precompilados y el
    veredicto por mecánica.

    Se sirve sin la materia prima ni el diagnóstico, que son vistas para
    humanos y solo abultan lo que el juego tiene que descargar.
    """
    bundle = _plan_del_estudiante(student_id)
    if not bundle:
        raise HTTPException(
            status_code=404,
            detail="Este estudiante no tiene material todavía.",
        )
    return {k: v for k, v in bundle.items()
            if k not in ("materia_prima", "diagnostico_documentos")}


@app.get("/students/{student_id}/diagnostico")
async def diagnostico(student_id: str):
    """Dónde está cada pieza del estudiante.

    Existe porque cuando un documento no aparece en el plan, el fallo puede
    estar en cinco sitios distintos —Supabase sin credenciales, el curso sin
    guardar, la materia prima vacía, el plan sin refrescar— y desde la interfaz
    todos se ven igual: la misma pantalla vacía.
    """
    hay_supabase = store.cliente() is not None
    cursos = store.listar_cursos()
    mios = [c for c in cursos if c.get("owner_id") == student_id]
    documentos = store.documentos_de(student_id)
    cacheado, n_cache = store.obtener_plan(student_id)

    return {
        "supabase_conectado": hay_supabase,
        "aviso": None if hay_supabase else (
            "Sin credenciales de Supabase: todo vive en memoria y se pierde al "
            "reiniciar el Space. Configurá SUPABASE_URL y SUPABASE_SERVICE_KEY."
        ),
        "estudiante": store.obtener_estudiante(student_id),
        "cursos_totales": len(cursos),
        "cursos_de_este_estudiante": [
            {"id": c.get("id"), "title": c.get("title"), "owner_id": c.get("owner_id")}
            for c in mios
        ],
        "documentos_con_materia_prima": [
            {"id": d["id"], "title": d.get("title"),
             "conceptos": len(d["materia_prima"].get("concepts", []))}
            for d in documentos
        ],
        "plan_cacheado": bool(cacheado),
        "documentos_en_cache": n_cache,
        "jobs_recientes": [
            {"job_id": j.get("job_id"), "status": j.get("status"),
             "student_id": j.get("student_id"), "course_id": j.get("course_id"),
             "warning": j.get("warning"),
             "conceptos": len((j.get("result") or {}).get("concepts", []))}
            for j in list(_jobs.values())[-5:]
        ],
    }


@app.get("/students/{student_id}/plan")
async def plan_de_estudios(student_id: str, rehacer: bool = False):
    """El plan de estudios completo del estudiante, con todos sus documentos
    articulados en uno solo."""
    bundle = _plan_del_estudiante(student_id, forzar=rehacer)
    if not bundle:
        return {"vacio": True, "documentos": [], "mensaje": "Todavía no subiste material."}
    perfil = store.calcular_perfil(student_id)
    conceptos = bundle.get("concepts", {})
    # El progreso se pega al plan para que la página lo muestre sin otra llamada.
    for cid, c in conceptos.items():
        p = perfil.get("conceptos", {}).get(cid, {})
        c["progreso"] = {
            "recuperacion": p.get("recuperacion"),
            "relacion": p.get("relacion"),
            "transferencia": p.get("transferencia"),
            "n_observaciones": p.get("n_observaciones", 0),
        }
    mp = bundle.get("materia_prima") or {}
    return {
        "vacio": False,
        "fuentes": bundle.get("fuentes", []),
        "fusion": bundle.get("fusion"),
        "diagnostico_documentos": bundle.get("diagnostico_documentos", []),
        "study_plan": bundle.get("study_plan"),
        "concepts": conceptos,
        "graph": bundle.get("graph", {}),
        "content": bundle.get("content", {}),
        "items": {k: len(v) for k, v in (bundle.get("items") or {}).items()},
        "distractor_pools": bundle.get("distractor_pools", {}),
        "mechanics": bundle.get("mechanics", {}),
        "readiness": bundle.get("readiness", []),
        "stats": bundle.get("stats", {}),
        "items_descartados": bundle.get("items_descartados", []),
        # El compilador produce estos dos y el endpoint los estaba tirando: la
        # respuesta enumeraba claves una por una y estas quedaron fuera. Desde
        # la interfaz se veía como si el compilador no los generara.
        #
        # `capabilities` es lo que el motor de juego consulta en vez de contar
        # cosas por su cuenta: anclas, condiciones instanciables con su motivo,
        # rareza por tipo de relación, conceptos sin pool.
        "capabilities": bundle.get("capabilities", {}),
        "conceptos_con_problemas": bundle.get("conceptos_con_problemas", []),
        # La materia prima fusionada: es lo que permite mostrar definiciones
        # completas, relaciones con su descripción y el detalle de cada capa,
        # igual que la página de revisión del extractor.
        "materia_prima": {
            "concepts": mp.get("concepts", []),
            "relations": mp.get("relations", []),
            "repertoires": mp.get("repertoires", []),
            "cases": mp.get("cases", []),
            "scenarios": mp.get("scenarios", []),
            "theses": mp.get("theses", []),
            "frameworks": mp.get("frameworks", []),
        },
        "perfil": {"n_senales": perfil.get("n_senales", 0),
                   "repertorios_activos": perfil.get("repertorios_activos", {}),
                   "conceptos": perfil.get("conceptos", {})},
    }


@app.post("/courses/from-job/{job_id}")
async def guardar_curso_desde_job(job_id: str, payload: dict[str, Any] | None = None):
    """Persiste una extracción ya hecha como curso jugable.

    Se separa de /extract a propósito: la extracción puede repetirse o
    descartarse, y solo el resultado que el usuario decide conservar se
    convierte en curso.
    """
    job = _jobs.get(job_id)
    if not job or job.get("status") != "completed":
        raise HTTPException(status_code=404, detail="Job no encontrado o incompleto")
    resultado = job.get("result") or {}
    bundle = resultado.get("game_bundle")
    if not bundle:
        raise HTTPException(status_code=422, detail="La extracción no produjo paquete de juego")
    student_id = (payload or {}).get("student_id")
    if student_id:
        # El plan cacheado deja de estar al día en cuanto entra material nuevo.
        store.invalidar_plan(student_id)
    return store.guardar_curso(
        owner_id=student_id,
        title=(payload or {}).get("title") or resultado.get("source_filename", "Curso"),
        source_filename=resultado.get("source_filename", ""),
        materia_prima={k: v for k, v in resultado.items() if k != "game_bundle"},
        game_bundle=bundle,
    )


@app.get("/courses")
async def listar_cursos(student_id: str | None = None):
    return {"courses": store.listar_cursos(student_id)}


@app.get("/courses/{course_id}/plan")
async def plan_del_curso(course_id: str):
    bundle = store.obtener_bundle(course_id)
    if not bundle:
        raise HTTPException(status_code=404, detail="Curso no encontrado")
    return {
        "study_plan": bundle.get("study_plan"),
        "concepts": bundle.get("concepts"),
        "stats": bundle.get("stats"),
    }


@app.post("/sessions")
async def iniciar_sesion(payload: dict[str, Any]):
    """Arranca una sesión de aprendizaje o de evaluación.

    Las dos no son la misma cosa con más o menos ayuda: la evaluación tiene
    presión temporal, consecuencias y prohibición de pedir ayuda, y el modo
    aprendizaje niega las tres. Por eso producen secuencias distintas.
    """
    student_id = payload.get("student_id")
    modo = payload.get("modo", "aprendizaje")
    if modo not in session_engine.MODOS:
        raise HTTPException(status_code=400, detail="modo debe ser 'aprendizaje' o 'evaluacion'")
    if not student_id:
        raise HTTPException(status_code=400, detail="Falta `student_id`.")

    # La sesión corre sobre el plan completo del estudiante, no sobre un
    # documento. Es lo que permite que un concepto que aparece en dos lecturas
    # se practique una vez y cuente para las dos.
    bundle = _plan_del_estudiante(student_id)
    if not bundle:
        raise HTTPException(
            status_code=422,
            detail="Todavía no hay material. Subí un documento primero.",
        )
    # La sesión recorre el plan completo, que fusiona varios documentos, así
    # que no pertenece a ninguno en particular. Antes se inventaba un
    # identificador tipo "plan_7a4ffe3a" que no es un uuid válido: el insert
    # fallaba en silencio y la sesión quedaba escrita solo en memoria mientras
    # la lectura iba a Supabase. De ahí el "sesión no encontrada".
    course_id = None
    perfil = store.calcular_perfil(student_id)
    plan = session_engine.construir_plan(
        bundle, perfil.get("conceptos", {}), modo,
        payload.get("limite_conceptos"),
    )
    if not plan["pasos"]:
        raise HTTPException(
            status_code=422,
            detail="No hay ejercicios disponibles para este curso todavía.",
        )
    # El plan viaja dentro de la sesión: así, si el estudiante sube material
    # nuevo a mitad de camino, la sesión en curso sigue siendo coherente.
    ses = store.crear_sesion(student_id, course_id, modo, plan)
    return {
        "session_id": ses.get("id"),
        "modo": modo,
        "total_pasos": len(plan["pasos"]),
        "conceptos": plan["conceptos"],
        "muestra_puntaje": plan["muestra_puntaje"],
    }


@app.get("/sessions/{session_id}/next")
async def siguiente_paso(session_id: str):
    ses = store.obtener_sesion(session_id)
    if not ses:
        raise HTTPException(status_code=404, detail="Sesión no encontrada")
    plan = ses["plan"]
    idx = ses.get("paso_actual", 0)
    if idx >= len(plan["pasos"]):
        return {"terminada": True, "total_pasos": len(plan["pasos"])}

    bundle = _plan_del_estudiante(ses["student_id"])
    paso = session_engine.preparar_paso(plan["pasos"][idx], bundle)
    return {
        "terminada": False,
        "indice": idx,
        "total_pasos": len(plan["pasos"]),
        "modo": plan["modo"],
        "paso": paso,
    }


@app.post("/sessions/{session_id}/hint")
async def pedir_pista(session_id: str):
    """Una pista. No baja el puntaje: baja el peso de la evidencia.

    La diferencia importa. Castigar la petición de ayuda enseña a no pedirla,
    que es lo contrario de lo que el andamiaje busca. Lo que ocurre es que el
    sistema deja de estar seguro sobre lo que el estudiante sabe.
    """
    ses = store.obtener_sesion(session_id)
    if not ses:
        raise HTTPException(status_code=404, detail="Sesión no encontrada")
    plan = ses["plan"]
    idx = ses.get("paso_actual", 0)
    if idx >= len(plan["pasos"]):
        raise HTTPException(status_code=409, detail="La sesión ya terminó")
    paso = plan["pasos"][idx]
    if not paso.get("andamiaje", {}).get("pistas"):
        raise HTTPException(status_code=403, detail="Este paso no admite pistas")

    bundle = _plan_del_estudiante(ses["student_id"])
    item = session_engine._buscar_item_por_id(bundle, paso["mechanic_id"], paso["item_id"])
    if not item:
        raise HTTPException(status_code=404, detail="Ítem no encontrado")

    usadas = int((ses.get("plan", {}).get("_hints") or {}).get(str(idx), 0)) + 1
    plan.setdefault("_hints", {})[str(idx)] = usadas
    store.actualizar_sesion(session_id, {"plan": plan})
    return {
        "pista": session_engine.obtener_pista(item, paso["mechanic_id"], bundle),
        "pistas_usadas": usadas,
    }


@app.post("/sessions/{session_id}/answer")
async def responder(session_id: str, payload: dict[str, Any]):
    """Califica, emite las señales cognitivas y avanza la sesión."""
    ses = store.obtener_sesion(session_id)
    if not ses:
        raise HTTPException(status_code=404, detail="Sesión no encontrada")
    plan = ses["plan"]
    idx = ses.get("paso_actual", 0)
    if idx >= len(plan["pasos"]):
        raise HTTPException(status_code=409, detail="La sesión ya terminó")

    paso = plan["pasos"][idx]
    bundle = _plan_del_estudiante(ses["student_id"])

    respuesta = payload.get("respuesta")
    duration_ms = int(payload.get("duration_ms") or 0)

    # ── Exposición: no se responde, se marca como vista ───────────────────
    if paso["tipo"] == "exposicion":
        store.actualizar_sesion(session_id, {"paso_actual": idx + 1})
        return {"avanzado": True, "indice": idx + 1,
                "terminada": idx + 1 >= len(plan["pasos"])}

    # ── G1 APOSTAR: la declaración se guarda y se cierra cuando el ejercicio
    #    vinculado se resuelve. Sin ese cierre no hay calibración, solo una
    #    opinión suelta.
    if paso["tipo"] == "calibracion":
        plan.setdefault("_apuestas", {})[paso["vinculado_a"]] = {
            "declarado": float(respuesta or 0.5),
            "concept_id": paso["concept_id"],
        }
        store.actualizar_sesion(session_id, {"paso_actual": idx + 1, "plan": plan})
        return {"avanzado": True, "indice": idx + 1,
                "terminada": idx + 1 >= len(plan["pasos"]),
                "feedback": {"tipo": "registrado",
                             "mensaje": "Anotado. Veamos cómo te va."}}

    # ── I1 PLANEAR ────────────────────────────────────────────────────────
    if paso["tipo"] == "planeacion":
        perfil = store.calcular_perfil(ses["student_id"])
        elegidos = perfil.get("conceptos", {})
        scores = {o["id"]: (elegidos.get(o["id"], {}).get("recuperacion") or 0.0)
                  for o in paso.get("opciones", [])}
        # ¿Eligió donde menos evidencia tiene? Ese es el criterio, no acertar.
        minimo = min(scores.values()) if scores else 0.0
        era_lo_flojo = scores.get(str(respuesta), 1.0) <= minimo + 0.05
        senal = grading.senal_planeacion(str(respuesta), era_lo_flojo)
        store.registrar_respuesta(
            ses["student_id"], None, session_id,
            {"event_type": "mechanic.completed", "mechanic_id": "I1",
             "concept_id": str(respuesta), "modo": plan["modo"],
             "posicion_en_sesion": idx + 1, "via": "decision_declarada"},
            [senal])
        # La elección se aplica: los pasos del concepto elegido pasan al
        # frente. Preguntar por dónde empezar y arrancar por otro lado enseña
        # que las decisiones del estudiante no cuentan.
        plan["_eleccion_inicial"] = str(respuesta)
        plan = session_engine.reordenar_por_eleccion(plan, str(respuesta))
        store.actualizar_sesion(session_id, {"paso_actual": idx + 1, "plan": plan})
        return {"avanzado": True, "indice": idx + 1,
                "terminada": idx + 1 >= len(plan["pasos"]),
                "feedback": {"tipo": "planeacion",
                             "mensaje": "Buena elección: ahí es donde menos evidencia hay."
                             if era_lo_flojo else
                             "Anotado. Ojo: hay conceptos con menos evidencia que ese."}}

    # ── I4 REFLEXIONAR ────────────────────────────────────────────────────
    if paso["tipo"] == "reflexion":
        # Qué le costó de verdad: el concepto con peor desempeño en ESTA sesión.
        fallos: dict[str, list[int]] = {}
        for p_ in plan["pasos"][:idx]:
            if p_.get("tipo") != "ejercicio":
                continue
            r_ = (plan.get("_resultados") or {}).get(p_.get("item_id"))
            if r_ is not None:
                fallos.setdefault(p_["concept_id"], []).append(int(bool(r_)))
        peor = min(fallos, key=lambda k: sum(fallos[k]) / len(fallos[k])) if fallos else None
        senales = grading.senales_reflexion(str(respuesta), peor)
        store.registrar_respuesta(
            ses["student_id"], None, session_id,
            {"event_type": "mechanic.completed", "mechanic_id": "I4",
             "concept_id": None if respuesta == "_ninguno" else str(respuesta),
             "modo": plan["modo"], "posicion_en_sesion": idx + 1,
             "via": "decision_declarada"},
            senales)
        store.actualizar_sesion(session_id, {"paso_actual": idx + 1, "plan": plan})
        acerto = peor is not None and str(respuesta) == peor
        bundle_c = (bundle or {}).get("concepts", {})
        return {
            "avanzado": True, "indice": idx + 1, "terminada": True,
            "feedback": {
                "tipo": "reflexion",
                "mensaje": ("Coincide con lo que muestran tus respuestas."
                            if acerto else
                            (f"Tus respuestas sugieren que lo que más costó fue "
                             f"«{bundle_c.get(peor, {}).get('titulo', peor)}»."
                             if peor else "Gracias. Sin suficientes datos para contrastarlo.")),
            },
        }

    item = session_engine._buscar_item_por_id(bundle, paso["mechanic_id"], paso["item_id"])
    if not item:
        raise HTTPException(status_code=404, detail="Ítem no encontrado")

    hints = int((plan.get("_hints") or {}).get(str(idx), 0))

    resultado = grading.calificar(paso["mechanic_id"], item, respuesta)
    contexto = {**plan["contexto"], "andamiaje": paso.get("andamiaje", {})}
    senales = grading.emitir_senales(
        paso["mechanic_id"], item, resultado, paso["concept_id"],
        contexto, hints, duration_ms, plan["modo"],
    )

    # Si hubo una apuesta sobre este ejercicio, ahora se puede cerrar: la
    # calibración solo existe como relación entre lo declarado y lo ocurrido.
    apuesta = (plan.get("_apuestas") or {}).pop(item["id"], None)
    if apuesta:
        senales.append(grading.cerrar_calibracion(
            grading.senal_calibracion(apuesta["concept_id"], apuesta["declarado"]),
            bool(resultado.get("correcto")),
        ))

    # Se registra el resultado para poder contrastar la reflexión final.
    plan.setdefault("_resultados", {})[item["id"]] = bool(resultado.get("correcto"))

    evento = {
        "event_type": "mechanic.completed",
        "mechanic_id": paso["mechanic_id"],
        "item_id": item["id"],
        "concept_id": paso["concept_id"],
        "is_correct": resultado.get("correcto"),
        "partial_score": resultado.get("partial_score"),
        "duration_ms": duration_ms,
        "respuesta": {"valor": respuesta},
        "modo": plan["modo"],
        "ctx_temporal": plan["contexto"]["temporal"],
        "ctx_stakes": plan["contexto"]["stakes"],
        "ctx_social": plan["contexto"]["social"],
        "fading_level": paso.get("fading_level", 0),
        "hints_used": hints,
        "posicion_en_sesion": idx + 1,
        "via": "decision_declarada",
        "modalidad": grading.MODALIDAD_POR_MECANICA.get(paso["mechanic_id"]),
        "peso_evidencial": next(
            (s.get("peso_evidencial") for s in senales if s.get("peso_evidencial")), None),
        "n_efectivo": resultado.get("n_efectivo"),
    }
    store.registrar_respuesta(
        ses["student_id"], ses["course_id"], session_id, evento, senales)

    nuevo_idx = idx + 1
    terminada = nuevo_idx >= len(plan["pasos"])
    store.actualizar_sesion(session_id, {
        "paso_actual": nuevo_idx,
        "plan": plan,
        **({"estado": "completada", "completed_at": datetime.now(timezone.utc).isoformat()}
           if terminada else {}),
    })

    return {
        "correcto": resultado.get("correcto"),
        # En evaluación no se devuelve retroalimentación: darla convertiría la
        # evaluación en aprendizaje y dejaría de medir lo que dice medir.
        "feedback": grading.construir_feedback(
            paso["mechanic_id"], item, resultado, plan["modo"]),
        "senales_emitidas": [
            {"dimension": s["dimension"], "forma": s["forma"]} for s in senales
        ],
        "indice": nuevo_idx,
        "terminada": terminada,
    }


@app.get("/sessions/{session_id}/summary")
async def resumen_sesion(session_id: str):
    """Cierre de sesión. En evaluación, es acá donde aparece el resultado."""
    ses = store.obtener_sesion(session_id)
    if not ses:
        raise HTTPException(status_code=404, detail="Sesión no encontrada")
    perfil = store.calcular_perfil(ses["student_id"])
    bundle = _plan_del_estudiante(ses["student_id"]) or {}
    conceptos = bundle.get("concepts", {})
    plan = ses["plan"]

    # Lo que pasó EN ESTA SESIÓN, no el perfil acumulado. El resumen anterior
    # leía solo el perfil global y salía vacío cuando las señales no habían
    # llegado a la base: el estudiante terminaba una sesión completa y veía
    # estadísticas en blanco, sin forma de saber si había fallado él o el
    # sistema.
    resultados = plan.get("_resultados") or {}
    por_concepto: dict[str, dict] = {}
    for paso in plan.get("pasos", []):
        if paso.get("tipo") != "ejercicio":
            continue
        cid = paso.get("concept_id")
        if not cid:
            continue
        e = por_concepto.setdefault(cid, {"intentos": 0, "aciertos": 0, "mecanicas": []})
        if paso.get("item_id") in resultados:
            e["intentos"] += 1
            e["aciertos"] += int(bool(resultados[paso["item_id"]]))
            e["mecanicas"].append(paso.get("mechanic_id"))

    detalle = []
    for cid in plan.get("conceptos", []):
        p = perfil.get("conceptos", {}).get(cid, {})
        s = por_concepto.get(cid, {"intentos": 0, "aciertos": 0, "mecanicas": []})
        detalle.append({
            "concept_id": cid,
            "titulo": conceptos.get(cid, {}).get("titulo", cid),
            "en_esta_sesion": {
                "intentos": s["intentos"],
                "aciertos": s["aciertos"],
                "mecanicas": sorted(set(m for m in s["mecanicas"] if m)),
            },
            "recuperacion": p.get("recuperacion"),
            "relacion": p.get("relacion"),
            "transferencia": p.get("transferencia"),
            "n_observaciones": p.get("n_observaciones", 0),
        })

    total_int = sum(d["en_esta_sesion"]["intentos"] for d in detalle)
    total_ok = sum(d["en_esta_sesion"]["aciertos"] for d in detalle)

    # Calibración de la sesión: qué tan bien predijo su propio desempeño.
    apuestas = [
        s for s in perfil.get("_calibraciones", [])
    ] if perfil.get("_calibraciones") else []

    return {
        "modo": plan["modo"],
        "muestra_puntaje": plan.get("muestra_puntaje"),
        "conceptos": detalle,
        "resumen_sesion": {
            "intentos": total_int,
            "aciertos": total_ok,
            "conceptos_trabajados": sum(
                1 for d in detalle if d["en_esta_sesion"]["intentos"] > 0),
            "eleccion_inicial": plan.get("_eleccion_inicial"),
        },
        "calibracion": perfil.get("calibracion", {}),
        "repertorios_activos": perfil.get("repertorios_activos", {}),
        "peticiones_de_ayuda": perfil.get("peticiones_de_ayuda", 0),
        "n_senales_totales": perfil.get("n_senales", 0),
    }


@app.get("/students/{student_id}/profile")
async def perfil_cognitivo(student_id: str, course_id: str | None = None):
    """El perfil se calcula desde las señales, nunca se lee almacenado.

    Así, cuando cambie la fórmula de ponderación —y va a cambiar, porque los
    pesos evidenciales de hoy son priors sin calibrar— todo el histórico se
    reinterpreta solo.
    """
    perfil = store.calcular_perfil(student_id, course_id)
    bundle = _plan_del_estudiante(student_id) or {}
    conceptos = bundle.get("concepts", {})
    for cid, datos in perfil.get("conceptos", {}).items():
        datos["titulo"] = conceptos.get(cid, {}).get("titulo", cid)
        datos["carga_cognitiva"] = conceptos.get(cid, {}).get("carga_cognitiva", [])
    return perfil
