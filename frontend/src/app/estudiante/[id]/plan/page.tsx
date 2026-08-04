"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";

/* El plan de estudios completo: todos los documentos articulados en uno.

   Es la vista que responde "¿qué hay acá y en qué orden?", con el progreso
   pegado. La diferencia con la página de revisión del extractor es el
   destinatario: aquella la lee el profesor para verificar la extracción, esta
   la lee el estudiante para saber dónde está parado. */

const DIM_LABEL: Record<string, string> = {
  recuperacion: "Recuperación", relacion: "Relación", transferencia: "Transferencia",
  anclaje: "Anclaje", automatizacion: "Automatización", calibracion: "Calibración",
  srl_planeacion: "Planeación", srl_accion: "Acción reguladora",
  srl_autorreflexion: "Autorreflexión", articulacion: "Articulación",
  persistencia: "Persistencia", engagement: "Compromiso",
};

const CARGA_LABEL: Record<string, string> = {
  memorizar: "hay que retener", discriminar: "se confunde", 
  integrar: "hay que integrar", inferir: "hay que inferir",
};

export default function PlanPage() {
  const { id } = useParams<{ id: string }>();
  const backendUrl = process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:7860";
  const [plan, setPlan] = useState<any>(null);
  const [tab, setTab] = useState<"secuencia" | "mapa" | "intuiciones" | "cobertura">("secuencia");

  useEffect(() => {
    fetch(`${backendUrl}/students/${id}/plan`)
      .then((r) => r.json()).then(setPlan).catch(() => setPlan({ vacio: true }));
  }, [backendUrl, id]);

  if (!plan) {
    return <main className="flex min-h-screen items-center justify-center bg-[#0F0F13] text-gray-400">Cargando…</main>;
  }
  if (plan.vacio) {
    return (
      <main className="flex min-h-screen flex-col items-center justify-center gap-3 bg-[#0F0F13] text-gray-400">
        <p>Todavía no hay material.</p>
        <a href={`/estudiante/${id}`} className="text-sm text-indigo-400 underline">Volver al perfil</a>
      </main>
    );
  }

  const conceptos = plan.concepts ?? {};
  const unidades = plan.study_plan?.unidades ?? [];
  const repertorios = plan.content?.repertoires ?? [];
  const TABS = [
    ["secuencia", "Secuencia", unidades.length],
    ["mapa", "Conexiones", plan.stats?.aristas],
    ["intuiciones", "Ideas previas", repertorios.length],
    ["cobertura", "Qué se puede medir", (plan.readiness ?? []).filter((r: any) => r.medible).length],
  ] as const;

  return (
    <main className="min-h-screen bg-[#0F0F13] text-white">
      <header className="border-b border-gray-800 px-4 py-4 sm:px-6">
        <div className="mx-auto max-w-4xl">
          <a href={`/estudiante/${id}`} className="text-xs text-indigo-400">← Perfil</a>
          <h1 className="mt-1 text-xl font-semibold">Tu plan de estudios</h1>
          <p className="mt-0.5 text-xs text-gray-500">
            {(plan.fuentes ?? []).length} documento(s) · {plan.stats?.conceptos} conceptos
            {plan.fusion?.conceptos_totales > plan.stats?.conceptos && (
              <> · {plan.fusion.conceptos_totales - plan.stats.conceptos} unificados entre lecturas</>
            )}
          </p>
        </div>
      </header>

      <nav className="sticky top-0 z-10 border-b border-gray-800 bg-[#0F0F13]/95 px-4 backdrop-blur sm:px-6">
        <div className="mx-auto flex max-w-4xl gap-1 overflow-x-auto">
          {TABS.map(([k, label, n]) => (
            <button
              key={k}
              onClick={() => setTab(k as typeof tab)}
              className={`whitespace-nowrap border-b-2 px-3 py-2.5 text-sm ${
                tab === k ? "border-indigo-400 text-white" : "border-transparent text-gray-500 hover:text-gray-300"
              }`}
            >
              {label}<span className="ml-1.5 font-mono text-[11px] text-gray-600">{n}</span>
            </button>
          ))}
        </div>
      </nav>

      <div className="mx-auto max-w-4xl space-y-4 px-4 py-6 sm:px-6">
        {tab === "secuencia" && unidades.map((u: any) => (
          <div key={u.id} className="rounded-lg border border-gray-800 bg-gray-900/40 p-4">
            <div className="mb-2 flex flex-wrap items-center gap-2">
              <span className="font-mono text-xs text-gray-600">Unidad {u.numero}</span>
              {u.tiene_puerta && <Chip cls="border-indigo-500/30 bg-indigo-500/10 text-indigo-300">tiene concepto puerta</Chip>}
              {u.tiene_umbral && <Chip cls="border-fuchsia-500/30 bg-fuchsia-500/10 text-fuchsia-300">tiene umbral</Chip>}
            </div>
            <div className="space-y-2">
              {u.concept_ids.map((cid: string) => {
                const c = conceptos[cid];
                if (!c) return null;
                const p = c.progreso ?? {};
                return (
                  <div key={cid} className="border-l-2 border-gray-800 pl-3">
                    <div className="flex flex-wrap items-baseline gap-2">
                      <span className="font-mono text-[11px] text-gray-600">{c.posicion}</span>
                      <span className="text-sm">{c.titulo}</span>
                      {(c.carga_cognitiva ?? []).map((k: string) => (
                        <span key={k} className="rounded border border-gray-700 px-1.5 text-[11px] text-gray-500">
                          {CARGA_LABEL[k] ?? k}
                        </span>
                      ))}
                      {c.n_fuentes > 1 && (
                        <span className="rounded border border-sky-500/30 bg-sky-500/10 px-1.5 text-[11px] text-sky-300">
                          {c.n_fuentes} lecturas
                        </span>
                      )}
                      <span className="ml-auto font-mono text-[11px] text-gray-600">
                        {p.n_observaciones ? `${Math.round((p.recuperacion ?? 0) * 100)}%` : "sin ver"}
                      </span>
                    </div>
                    <p className="mt-0.5 text-xs text-gray-500">{c.definicion_corta ?? c.definicion}</p>
                    {p.n_observaciones > 0 && (
                      <div className="mt-1.5 h-1 w-full overflow-hidden rounded-full bg-gray-800">
                        <div
                          className={`h-full ${
                            (p.recuperacion ?? 0) >= 0.7 ? "bg-emerald-400"
                            : (p.recuperacion ?? 0) >= 0.4 ? "bg-amber-400" : "bg-rose-400"
                          }`}
                          style={{ width: `${Math.round((p.recuperacion ?? 0) * 100)}%` }}
                        />
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        ))}

        {tab === "mapa" && Object.entries(plan.graph?.por_tipo ?? {}).map(([tipo, aristas]: [string, any]) => (
          <div key={tipo} className="rounded-lg border border-gray-800 bg-gray-900/40 p-4">
            <p className="mb-2 font-mono text-xs text-gray-400">{tipo}<span className="ml-2 text-gray-600">{aristas.length}</span></p>
            <div className="space-y-1">
              {aristas.slice(0, 12).map((a: any, i: number) => (
                <p key={i} className="text-sm text-gray-300">
                  {conceptos[a.from]?.titulo ?? a.from}
                  <span className="mx-2 text-gray-600">→</span>
                  {conceptos[a.to]?.titulo ?? a.to}
                </p>
              ))}
            </div>
          </div>
        ))}

        {tab === "intuiciones" && (
          repertorios.length === 0
            ? <Vacio>No se detectaron intuiciones cotidianas en este material.</Vacio>
            : repertorios.map((r: any) => (
              <div key={r.id} className="rounded-lg border border-gray-800 bg-gray-900/40 p-4">
                <p className="text-sm font-medium">{r.label}</p>
                <p className="mt-0.5 text-xs text-gray-500">sobre {conceptos[r.concept_id]?.titulo ?? r.concept_id}</p>
                {r.example && <p className="mt-2 text-sm text-gray-400">“{r.example}”</p>}
                {r.contexto_donde_funciona && (
                  <p className="mt-2 text-xs text-gray-500">
                    <span className="text-gray-400">Dónde sí funciona: </span>{r.contexto_donde_funciona}
                  </p>
                )}
                {r.contraste_cientifico && (
                  <p className="mt-1.5 text-xs text-gray-400">{r.contraste_cientifico}</p>
                )}
              </div>
            ))
        )}

        {tab === "cobertura" && (
          <div className="rounded-lg border border-gray-800 bg-gray-900/40 divide-y divide-gray-800">
            {(plan.readiness ?? []).map((r: any) => (
              <div key={r.dimension} className="px-4 py-2.5">
                <div className="flex flex-wrap items-center gap-2 text-sm">
                  <span className="w-44 shrink-0 text-gray-300">{DIM_LABEL[r.dimension] ?? r.dimension}</span>
                  <Chip cls={r.medible
                    ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-300"
                    : "border-gray-700 text-gray-500"}>
                    {r.medible ? "medible" : "no medible"}
                  </Chip>
                  <span className="font-mono text-[11px] text-gray-600">
                    {r.mecanicas_disponibles.join(" ")}
                  </span>
                </div>
                {!r.medible && r.motivo && (
                  <p className="mt-1 text-xs text-amber-300/80">{r.motivo}</p>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </main>
  );
}

function Chip({ children, cls }: { children: React.ReactNode; cls: string }) {
  return <span className={`inline-flex items-center rounded border px-1.5 py-0.5 text-[11px] ${cls}`}>{children}</span>;
}
function Vacio({ children }: { children: React.ReactNode }) {
  return <div className="rounded-lg border border-gray-800 bg-gray-900/40 p-4 text-sm text-gray-500">{children}</div>;
}
