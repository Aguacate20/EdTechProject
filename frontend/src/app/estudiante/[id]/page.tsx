"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useParams, useRouter } from "next/navigation";

/* Perfil del estudiante: un solo plan que crece con cada documento.

   Las cuatro acciones que pediste, en una pantalla:
     1. subir material nuevo         → se suma al plan solo
     2. revisar el plan actual       → todos los documentos articulados
     3. aprender                     → con andamiaje
     4. evaluar                      → sin andamiaje

   Y el estado del modelo cognitivo debajo, porque es lo que hace visible que
   el sistema recuerda entre sesiones. */

interface Fuente { id: string; title?: string }

export default function PerfilPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const backendUrl = process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:7860";
  const fileRef = useRef<HTMLInputElement>(null);

  const [nombre, setNombre] = useState("");
  const [plan, setPlan] = useState<any>(null);
  const [cargando, setCargando] = useState(true);
  const [subiendo, setSubiendo] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [iniciando, setIniciando] = useState(false);

  const cargar = useCallback(async () => {
    try {
      const [rEst, rPlan] = await Promise.all([
        fetch(`${backendUrl}/students/${id}`),
        fetch(`${backendUrl}/students/${id}/plan`),
      ]);
      if (rEst.ok) setNombre((await rEst.json()).student?.display_name ?? "");
      if (rPlan.ok) setPlan(await rPlan.json());
    } catch {
      setError("No se pudo cargar el perfil.");
    } finally {
      setCargando(false);
    }
  }, [backendUrl, id]);

  useEffect(() => { cargar(); }, [cargar]);

  async function subir(file: File) {
    setError(null);
    setSubiendo("Subiendo…");
    const fd = new FormData();
    fd.append("file", file);
    fd.append("student_id", String(id));
    try {
      const r = await fetch(`${backendUrl}/extract`, { method: "POST", body: fd });
      if (!r.ok) { setError("No se pudo subir el archivo."); setSubiendo(null); return; }
      const { job_id } = await r.json();
      setSubiendo("Procesando el documento… puede tardar unos minutos.");
      // Espera activa: el pipeline es largo y no hay websockets todavía.
      const t0 = Date.now();
      while (Date.now() - t0 < 20 * 60 * 1000) {
        await new Promise((res) => setTimeout(res, 5000));
        const j = await (await fetch(`${backendUrl}/jobs/${job_id}?incluir_bundle=false`)).json();
        if (j.status === "completed") {
          setSubiendo("Incorporando al plan…");
          await fetch(`${backendUrl}/students/${id}/plan?rehacer=true`);
          await cargar();
          setSubiendo(null);
          return;
        }
        if (j.status === "failed") {
          setError(j.error ?? "La extracción falló.");
          setSubiendo(null);
          return;
        }
      }
      setSubiendo(null);
      setError("La extracción está tardando más de lo esperado. Recargá en un rato.");
    } catch {
      setError("Error al subir.");
      setSubiendo(null);
    }
  }

  async function iniciar(modo: "aprendizaje" | "evaluacion") {
    setIniciando(true); setError(null);
    try {
      const r = await fetch(`${backendUrl}/sessions`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ student_id: id, modo }),
      });
      if (!r.ok) {
        setError((await r.json().catch(() => ({}))).detail ?? "No se pudo iniciar.");
        return;
      }
      const d = await r.json();
      router.push(`/sesion/${d.session_id}?student=${id}`);
    } finally {
      setIniciando(false);
    }
  }

  const vacio = !plan || plan.vacio;
  const fuentes: Fuente[] = plan?.fuentes ?? [];
  const stats = plan?.stats ?? {};
  const conceptos = Object.entries(plan?.concepts ?? {}) as [string, any][];
  const trabajados = conceptos.filter(([, c]) => (c.progreso?.n_observaciones ?? 0) > 0);
  const senales = plan?.perfil?.n_senales ?? 0;

  return (
    <main className="min-h-screen bg-[#0F0F13] text-white">
      <header className="border-b border-gray-800 px-4 py-4 sm:px-6">
        <div className="mx-auto max-w-4xl">
          <p className="text-[11px] uppercase tracking-widest text-gray-500">Perfil</p>
          <h1 className="text-xl font-semibold">{nombre || "…"}</h1>
          <p className="mt-0.5 font-mono text-[11px] text-gray-600">{id}</p>
        </div>
      </header>

      <div className="mx-auto max-w-4xl space-y-5 px-4 py-6 sm:px-6">
        {error && (
          <div className="rounded border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-sm text-rose-200">
            {error}
          </div>
        )}

        {/* 1 · Subir material */}
        <section className="rounded-lg border border-gray-800 bg-gray-900/40 p-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h2 className="text-sm font-medium">Material</h2>
              <p className="mt-0.5 text-xs text-gray-500">
                {vacio
                  ? "Subí un PDF para empezar tu plan."
                  : `${fuentes.length} documento(s) articulados en un solo plan.`}
              </p>
            </div>
            <input
              ref={fileRef}
              type="file"
              accept=".pdf"
              className="hidden"
              onChange={(e) => e.target.files?.[0] && subir(e.target.files[0])}
            />
            <button
              onClick={() => fileRef.current?.click()}
              disabled={!!subiendo}
              className="shrink-0 rounded border border-indigo-500/40 bg-indigo-500/10 px-3 py-1.5 text-xs text-indigo-300 hover:bg-indigo-500/20 disabled:opacity-50"
            >
              {subiendo ? "Procesando…" : "Añadir documento"}
            </button>
          </div>

          {subiendo && (
            <div className="mt-3 flex items-center gap-2 text-xs text-gray-400">
              <span className="h-3 w-3 rounded-full border-2 border-gray-700 border-t-indigo-400 motion-safe:animate-spin" />
              {subiendo}
            </div>
          )}

          {fuentes.length > 0 && (
            <ul className="mt-3 space-y-1">
              {fuentes.map((f) => (
                <li key={f.id} className="truncate text-xs text-gray-400">· {f.title}</li>
              ))}
            </ul>
          )}
        </section>

        {!vacio && (
          <>
            {/* 2 · Plan */}
            <section className="rounded-lg border border-gray-800 bg-gray-900/40 p-4">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <h2 className="text-sm font-medium">Tu plan de estudios</h2>
                  <p className="mt-0.5 text-xs text-gray-500">
                    {stats.conceptos} conceptos · {stats.unidades} unidades ·{" "}
                    {stats.aristas} conexiones
                    {plan?.fusion?.conceptos_totales > stats.conceptos && (
                      <> · {plan.fusion.conceptos_totales - stats.conceptos} unificados entre documentos</>
                    )}
                  </p>
                </div>
                <a
                  href={`/estudiante/${id}/plan`}
                  className="shrink-0 rounded border border-gray-700 px-3 py-1.5 text-xs text-gray-300 hover:border-gray-600"
                >
                  Ver el plan completo
                </a>
              </div>
            </section>

            {/* 3 y 4 · Los dos modos */}
            <section className="grid gap-3 sm:grid-cols-2">
              <div className="rounded-lg border border-emerald-500/25 bg-emerald-500/5 p-4">
                <h3 className="font-medium text-emerald-300">Aprender</h3>
                <p className="mt-1 text-xs text-gray-400">
                  Sin tiempo, sin puntaje. Se te expone lo nuevo, practicás con
                  apoyo y después sin él. Pedir ayuda no cuesta nada.
                </p>
                <button
                  onClick={() => iniciar("aprendizaje")}
                  disabled={iniciando}
                  className="mt-3 rounded bg-emerald-500/90 px-4 py-2 text-sm font-medium text-black hover:bg-emerald-400 disabled:opacity-50"
                >
                  Empezar sesión
                </button>
              </div>

              <div className="rounded-lg border border-amber-500/25 bg-amber-500/5 p-4">
                <h3 className="font-medium text-amber-300">Evaluar</h3>
                <p className="mt-1 text-xs text-gray-400">
                  Con tiempo, sin pistas y sin corrección durante la prueba.
                  El resultado aparece al final.
                </p>
                <button
                  onClick={() => iniciar("evaluacion")}
                  disabled={iniciando}
                  className="mt-3 rounded bg-amber-500/90 px-4 py-2 text-sm font-medium text-black hover:bg-amber-400 disabled:opacity-50"
                >
                  Empezar evaluación
                </button>
              </div>
            </section>

            {/* 5 · Estado del modelo cognitivo */}
            <section>
              <h2 className="mb-1 text-sm font-semibold uppercase tracking-wider text-gray-400">
                Lo que el sistema sabe de vos
              </h2>
              <p className="mb-3 text-xs text-gray-600">
                {senales === 0
                  ? "Todavía no hay señales. Después de una sesión, esto empieza a llenarse y las siguientes sesiones cambian."
                  : `${senales} señales acumuladas sobre ${trabajados.length} concepto(s). Esto decide qué te toca la próxima vez.`}
              </p>

              {trabajados.length > 0 && (
                <div className="space-y-2">
                  {trabajados.map(([cid, c]) => (
                    <div key={cid} className="rounded-lg border border-gray-800 bg-gray-900/40 p-3">
                      <div className="mb-1.5 flex flex-wrap items-baseline gap-2">
                        <span className="text-sm">{c.titulo}</span>
                        {(c.carga_cognitiva ?? []).map((k: string) => (
                          <span key={k} className="rounded border border-gray-700 px-1.5 text-[11px] text-gray-500">
                            {k}
                          </span>
                        ))}
                        {c.n_fuentes > 1 && (
                          <span className="rounded border border-sky-500/30 bg-sky-500/10 px-1.5 text-[11px] text-sky-300">
                            en {c.n_fuentes} lecturas
                          </span>
                        )}
                        <span className="ml-auto font-mono text-[11px] text-gray-600">
                          {c.progreso.n_observaciones} obs.
                        </span>
                      </div>
                      {["recuperacion", "relacion", "transferencia"].map((dim) =>
                        c.progreso[dim] != null ? (
                          <div key={dim} className="flex items-center gap-2">
                            <span className="w-28 shrink-0 text-[11px] capitalize text-gray-500">{dim}</span>
                            <div className="h-1 flex-1 overflow-hidden rounded-full bg-gray-800">
                              <div
                                className={`h-full ${
                                  c.progreso[dim] >= 0.7 ? "bg-emerald-400"
                                  : c.progreso[dim] >= 0.4 ? "bg-amber-400" : "bg-rose-400"
                                }`}
                                style={{ width: `${Math.round(c.progreso[dim] * 100)}%` }}
                              />
                            </div>
                            <span className="w-8 text-right font-mono text-[11px] text-gray-600">
                              {Math.round(c.progreso[dim] * 100)}%
                            </span>
                          </div>
                        ) : null
                      )}
                    </div>
                  ))}
                </div>
              )}

              {Object.keys(plan?.perfil?.repertorios_activos ?? {}).length > 0 && (
                <div className="mt-3 rounded-lg border border-amber-500/25 bg-amber-500/5 p-3">
                  <p className="text-xs uppercase tracking-wider text-amber-300">
                    Ideas previas detectadas
                  </p>
                  <p className="mt-1 text-sm text-gray-300">
                    {Object.keys(plan.perfil.repertorios_activos).length} intuición(es)
                    cotidiana(s) apareció al equivocarte. El sistema las usa para elegir
                    qué practicar.
                  </p>
                </div>
              )}
            </section>
          </>
        )}

        {cargando && <p className="text-sm text-gray-500">Cargando…</p>}
      </div>
    </main>
  );
}
