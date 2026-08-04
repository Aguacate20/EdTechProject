"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";

/* Perfil del estudiante: sus cursos, su progreso, y los dos botones que
   arrancan cada modo. Es la pantalla que hace visible que el sistema recuerda
   entre sesiones, que es justamente lo que faltaba. */

interface Curso { id: string; title: string; source_filename?: string; status: string }
interface Sesion { id: string; modo: string; estado: string; started_at: string }

const DIM_LABEL: Record<string, string> = {
  recuperacion: "Recuperación",
  relacion: "Relación",
  transferencia: "Transferencia",
};

export default function EstudiantePage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const backendUrl = process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:7860";

  const [nombre, setNombre] = useState("");
  const [cursos, setCursos] = useState<Curso[]>([]);
  const [sesiones, setSesiones] = useState<Sesion[]>([]);
  const [cursoSel, setCursoSel] = useState<string>("");
  const [perfil, setPerfil] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  const [iniciando, setIniciando] = useState(false);

  const cargar = useCallback(async () => {
    const r = await fetch(`${backendUrl}/students/${id}`);
    if (!r.ok) { setError("Perfil no encontrado"); return; }
    const d = await r.json();
    setNombre(d.student?.display_name ?? "");
    setCursos(d.courses ?? []);
    setSesiones(d.sessions ?? []);
    if (!cursoSel && d.courses?.length) setCursoSel(d.courses[0].id);
  }, [backendUrl, id, cursoSel]);

  useEffect(() => { cargar(); }, [cargar]);

  useEffect(() => {
    if (!cursoSel) return;
    fetch(`${backendUrl}/students/${id}/profile?course_id=${cursoSel}`)
      .then((r) => r.json()).then(setPerfil).catch(() => setPerfil(null));
  }, [backendUrl, id, cursoSel]);

  async function iniciar(modo: "aprendizaje" | "evaluacion") {
    if (!cursoSel) return;
    setIniciando(true); setError(null);
    try {
      const r = await fetch(`${backendUrl}/sessions`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ student_id: id, course_id: cursoSel, modo }),
      });
      if (!r.ok) {
        const e = await r.json().catch(() => ({}));
        setError(e.detail ?? "No se pudo iniciar la sesión.");
        return;
      }
      const d = await r.json();
      router.push(`/sesion/${d.session_id}?student=${id}`);
    } finally {
      setIniciando(false);
    }
  }

  const conceptos = Object.entries(perfil?.conceptos ?? {}) as [string, any][];
  const vistos = conceptos.filter(([, c]) => (c.n_observaciones ?? 0) > 0);

  return (
    <main className="min-h-screen bg-[#0F0F13] text-white">
      <header className="border-b border-gray-800 px-4 py-4 sm:px-6">
        <div className="mx-auto max-w-4xl">
          <p className="text-[11px] uppercase tracking-widest text-gray-500">Perfil</p>
          <h1 className="text-xl font-semibold">{nombre || "…"}</h1>
          <p className="mt-0.5 font-mono text-[11px] text-gray-600">{id}</p>
        </div>
      </header>

      <div className="mx-auto max-w-4xl space-y-6 px-4 py-6 sm:px-6">
        {error && (
          <div className="rounded border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-sm text-rose-200">
            {error}
          </div>
        )}

        {/* Curso */}
        <section>
          <h2 className="mb-2 text-sm font-semibold uppercase tracking-wider text-gray-400">
            Material
          </h2>
          {cursos.length === 0 ? (
            <div className="rounded-lg border border-gray-800 bg-gray-900/40 p-4 text-sm text-gray-500">
              Todavía no hay material.{" "}
              <a href="/upload" className="text-indigo-400 underline">Subí un documento</a>{" "}
              y guardalo como curso.
            </div>
          ) : (
            <div className="space-y-2">
              {cursos.map((c) => (
                <button
                  key={c.id}
                  onClick={() => setCursoSel(c.id)}
                  className={`block w-full rounded-lg border p-3 text-left transition ${
                    cursoSel === c.id
                      ? "border-indigo-400 bg-indigo-500/10"
                      : "border-gray-800 bg-gray-900/40 hover:border-gray-700"
                  }`}
                >
                  <p className="text-sm font-medium">{c.title}</p>
                  <p className="mt-0.5 truncate text-xs text-gray-500">{c.source_filename}</p>
                </button>
              ))}
            </div>
          )}
        </section>

        {/* Los dos modos */}
        {cursoSel && (
          <section className="grid gap-3 sm:grid-cols-2">
            <div className="rounded-lg border border-emerald-500/25 bg-emerald-500/5 p-4">
              <h3 className="font-medium text-emerald-300">Estudiar</h3>
              <p className="mt-1 text-xs text-gray-400">
                Sin tiempo, sin puntaje, con apoyo que se retira a medida que
                avanzás. Pedir ayuda no cuesta nada.
              </p>
              <button
                onClick={() => iniciar("aprendizaje")}
                disabled={iniciando}
                className="mt-3 rounded bg-emerald-500/90 px-4 py-2 text-sm font-medium text-black hover:bg-emerald-400 disabled:opacity-50"
              >
                Empezar
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
                Empezar
              </button>
            </div>
          </section>
        )}

        {/* Perfil cognitivo */}
        {vistos.length > 0 && (
          <section>
            <h2 className="mb-1 text-sm font-semibold uppercase tracking-wider text-gray-400">
              Tu perfil
            </h2>
            <p className="mb-3 text-xs text-gray-600">
              Calculado desde {perfil?.n_senales ?? 0} señales. No es una nota: es
              cuánta evidencia hay sobre cada concepto.
            </p>
            <div className="space-y-2">
              {vistos.map(([cid, c]) => (
                <div key={cid} className="rounded-lg border border-gray-800 bg-gray-900/40 p-3">
                  <div className="mb-1.5 flex flex-wrap items-baseline gap-2">
                    <span className="text-sm">{c.titulo ?? cid}</span>
                    {(c.carga_cognitiva ?? []).map((k: string) => (
                      <span key={k} className="rounded border border-gray-700 px-1.5 text-[11px] text-gray-500">
                        {k}
                      </span>
                    ))}
                    <span className="ml-auto font-mono text-[11px] text-gray-600">
                      {c.n_observaciones} obs.
                    </span>
                  </div>
                  <div className="space-y-1">
                    {["recuperacion", "relacion", "transferencia"].map((dim) =>
                      c[dim] != null ? (
                        <div key={dim} className="flex items-center gap-2">
                          <span className="w-28 shrink-0 text-[11px] text-gray-500">
                            {DIM_LABEL[dim]}
                          </span>
                          <div className="h-1 flex-1 overflow-hidden rounded-full bg-gray-800">
                            <div
                              className={`h-full ${
                                c[dim] >= 0.7 ? "bg-emerald-400"
                                : c[dim] >= 0.4 ? "bg-amber-400" : "bg-rose-400"
                              }`}
                              style={{ width: `${Math.round(c[dim] * 100)}%` }}
                            />
                          </div>
                          <span className="w-8 text-right font-mono text-[11px] text-gray-600">
                            {Math.round(c[dim] * 100)}%
                          </span>
                        </div>
                      ) : null
                    )}
                  </div>
                </div>
              ))}
            </div>
          </section>
        )}

        {sesiones.length > 0 && (
          <section>
            <h2 className="mb-2 text-sm font-semibold uppercase tracking-wider text-gray-400">
              Historial
            </h2>
            <div className="rounded-lg border border-gray-800 bg-gray-900/40 divide-y divide-gray-800">
              {sesiones.map((s) => (
                <div key={s.id} className="flex items-center gap-3 px-3 py-2 text-xs">
                  <span className={s.modo === "aprendizaje" ? "text-emerald-300" : "text-amber-300"}>
                    {s.modo}
                  </span>
                  <span className="text-gray-500">{s.estado}</span>
                  <span className="ml-auto font-mono text-gray-600">
                    {new Date(s.started_at).toLocaleString()}
                  </span>
                </div>
              ))}
            </div>
          </section>
        )}
      </div>
    </main>
  );
}
