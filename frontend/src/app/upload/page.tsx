"use client";

import { useState, useCallback, useRef } from "react";
import { useRouter } from "next/navigation";

type JobStatus = "idle" | "uploading" | "pending" | "running" | "completed" | "failed";

interface UploadState {
  status: JobStatus;
  jobId: string | null;
  filename: string | null;
  error: string | null;
  progress: string | null;
}

const STATUS_LABELS: Record<JobStatus, string> = {
  idle: "",
  uploading: "Subiendo archivo...",
  pending: "En cola de procesamiento...",
  running: "Analizando el documento...",
  completed: "¡Extracción completada!",
  failed: "Error en el procesamiento",
};

const STATUS_DESCRIPTIONS: Record<JobStatus, string> = {
  idle: "",
  uploading: "Enviando el PDF al servidor",
  pending: "El pipeline está a punto de comenzar",
  running: "El LLM está extrayendo conceptos, relaciones y repertorios cognitivos del documento. Este proceso tarda entre 2 y 10 minutos.",
  completed: "El contenido está listo para tu revisión.",
  failed: "Revisa el error y vuelve a intentarlo.",
};

export default function UploadPage() {
  const router = useRouter();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const [state, setState] = useState<UploadState>({
    status: "idle",
    jobId: null,
    filename: null,
    error: null,
    progress: null,
  });

  const [dragOver, setDragOver] = useState(false);

  const handleFile = useCallback(async (file: File) => {
    if (!file.name.toLowerCase().endsWith(".pdf")) {
      setState(s => ({ ...s, error: "Solo se aceptan archivos PDF" }));
      return;
    }

    if (file.size > 20 * 1024 * 1024) {
      setState(s => ({ ...s, error: "El archivo supera el límite de 20MB" }));
      return;
    }

    setState({
      status: "uploading",
      jobId: null,
      filename: file.name,
      error: null,
      progress: null,
    });

    try {
      const formData = new FormData();
      formData.append("file", file);

      const backendUrl = process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:7860";
      const res = await fetch(`${backendUrl}/extract`, {
        method: "POST",
        body: formData,
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(err.detail ?? "Error al subir el archivo");
      }

      const data = await res.json();
      setState(s => ({ ...s, status: "pending", jobId: data.job_id }));

      // Polling cada 5 segundos
      pollingRef.current = setInterval(async () => {
        try {
          const pollRes = await fetch(`${backendUrl}/jobs/${data.job_id}`);
          const job = await pollRes.json();

          setState(s => ({ ...s, status: job.status as JobStatus }));

          if (job.status === "completed") {
            clearInterval(pollingRef.current!);
            // Navegar a la UI de revisión
            router.push(`/review/${data.job_id}`);
          } else if (job.status === "failed") {
            clearInterval(pollingRef.current!);
            setState(s => ({ ...s, error: job.error ?? "Error desconocido" }));
          }
        } catch {
          // Error de red — seguir intentando
        }
      }, 5000);

    } catch (err: unknown) {
      setState(s => ({
        ...s,
        status: "failed",
        error: err instanceof Error ? err.message : "Error desconocido",
      }));
    }
  }, [router]);

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    const file = e.dataTransfer.files[0];
    if (file) handleFile(file);
  }, [handleFile]);

  const isProcessing = ["uploading", "pending", "running"].includes(state.status);

  return (
    <main className="min-h-screen bg-[#0F0F13] text-white flex flex-col items-center justify-center p-6">
      
      {/* Header */}
      <div className="text-center mb-12">
        <div className="inline-flex items-center gap-2 bg-indigo-500/10 border border-indigo-500/20 rounded-full px-4 py-1.5 text-sm text-indigo-300 mb-6">
          <span className="w-1.5 h-1.5 bg-indigo-400 rounded-full animate-pulse" />
          Extractor de Materia Prima
        </div>
        <h1 className="text-4xl font-light tracking-tight mb-3">
          Sube el documento del curso
        </h1>
        <p className="text-gray-400 max-w-md">
          El sistema extraerá conceptos, relaciones y repertorios cognitivos
          del PDF para construir el banco de actividades.
        </p>
      </div>

      {/* Drop zone */}
      <div
        className={`relative w-full max-w-lg rounded-2xl border-2 border-dashed transition-all duration-200 cursor-pointer
          ${dragOver
            ? "border-indigo-400 bg-indigo-500/10"
            : "border-gray-700 bg-gray-900/50 hover:border-gray-500 hover:bg-gray-900"
          }
          ${isProcessing ? "pointer-events-none opacity-60" : ""}
        `}
        onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
        onDragLeave={() => setDragOver(false)}
        onDrop={handleDrop}
        onClick={() => !isProcessing && fileInputRef.current?.click()}
      >
        <input
          ref={fileInputRef}
          type="file"
          accept=".pdf"
          className="hidden"
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) handleFile(file);
          }}
        />
        
        <div className="flex flex-col items-center justify-center py-16 px-8 text-center">
          {state.status === "idle" ? (
            <>
              <div className="w-14 h-14 rounded-xl bg-gray-800 flex items-center justify-center mb-4">
                <svg className="w-7 h-7 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
                    d="M9 13h6m-3-3v6m5 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                </svg>
              </div>
              <p className="text-gray-300 font-medium mb-1">
                Arrastra el PDF aquí o haz clic
              </p>
              <p className="text-sm text-gray-500">PDF · máximo 20MB</p>
            </>
          ) : (
            <ProcessingIndicator state={state} />
          )}
        </div>
      </div>

      {/* Error */}
      {state.error && (
        <div className="mt-4 w-full max-w-lg rounded-xl bg-red-500/10 border border-red-500/20 p-4 text-sm text-red-300">
          {state.error}
          <button
            className="ml-3 underline"
            onClick={() => setState({ status: "idle", jobId: null, filename: null, error: null, progress: null })}
          >
            Reintentar
          </button>
        </div>
      )}

      {/* Capas que se extraen */}
      {state.status === "idle" && (
        <div className="mt-12 w-full max-w-lg">
          <p className="text-xs text-gray-500 uppercase tracking-wider mb-4">
            Qué extrae el sistema
          </p>
          <div className="grid grid-cols-2 gap-2">
            {LAYERS.map((layer) => (
              <div key={layer.id} className="flex items-start gap-3 bg-gray-900/50 rounded-xl p-3">
                <span className="text-xs font-mono text-indigo-400 mt-0.5">C{layer.id}</span>
                <div>
                  <p className="text-sm text-gray-200">{layer.name}</p>
                  <p className="text-xs text-gray-500">{layer.desc}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </main>
  );
}

function ProcessingIndicator({ state }: { state: UploadState }) {
  const isRunning = ["uploading", "pending", "running"].includes(state.status);
  
  return (
    <div className="flex flex-col items-center gap-4">
      {isRunning && (
        <div className="w-10 h-10 rounded-full border-2 border-indigo-500/30 border-t-indigo-400 animate-spin" />
      )}
      {state.status === "completed" && (
        <div className="w-10 h-10 rounded-full bg-green-500/20 flex items-center justify-center">
          <svg className="w-5 h-5 text-green-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
          </svg>
        </div>
      )}
      <div className="text-center">
        <p className="text-gray-200 font-medium">
          {STATUS_LABELS[state.status]}
        </p>
        {state.filename && (
          <p className="text-xs text-gray-500 mt-1">{state.filename}</p>
        )}
        <p className="text-sm text-gray-400 mt-2 max-w-xs">
          {STATUS_DESCRIPTIONS[state.status]}
        </p>
      </div>
    </div>
  );
}

const LAYERS = [
  { id: 1, name: "Diccionario conceptual", desc: "Nodos del grafo del curso" },
  { id: 2, name: "Relaciones", desc: "Estructura entre conceptos" },
  { id: 3, name: "Repertorios", desc: "Misconceptions cognitivos" },
  { id: 4, name: "Argumentación", desc: "Posiciones teóricas" },
  { id: 5, name: "Evidencia y casos", desc: "Ejemplos y datos empíricos" },
  { id: 6, name: "Meta-pedagógico", desc: "Rutas y secuenciación" },
];
