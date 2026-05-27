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
):
    """
    Inicia el pipeline de extracción de forma asíncrona.
    Retorna un job_id para consultar el progreso con GET /jobs/{job_id}.
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
async def get_job(job_id: str):
    """Consulta el estado y resultado de un job de extracción."""
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job no encontrado")
    return job


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
    except Exception as e:
        logger.error(f"[job:{job_id}] Error: {e}", exc_info=True)
        _jobs[job_id]["status"] = "failed"
        _jobs[job_id]["error"] = str(e)
        _jobs[job_id]["failed_at"] = datetime.now(timezone.utc).isoformat()
