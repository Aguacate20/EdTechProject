"use client";

import { useEffect, useMemo, useState } from "react";
import { useParams } from "next/navigation";

/* ────────────────────────────────────────────────────────────
   El plan de estudios completo.

   Es la misma profundidad que la página de revisión del extractor, pero sobre
   el plan FUSIONADO: todos los documentos del estudiante articulados en uno.
   Reutiliza los mismos componentes de presentación porque los objetos son los
   mismos —conceptos, relaciones, repertorios, casos, tesis— y mantener dos
   renders distintos del mismo material solo garantiza que se desincronicen.

   Lo que cambia respecto a la revisión de un documento suelto:
     · el diagnóstico es por documento, no uno solo
     · cada concepto muestra en cuántas lecturas aparece
     · se ve el progreso del estudiante pegado al plan
     · aparece qué se puede jugar y qué está bloqueado
   ──────────────────────────────────────────────────────────── */


/* Tipos de la materia prima. Se aceptan las dos formas de `confidence` porque
   pasó de etiqueta a número entre versiones del esquema, y el plan puede
   fusionar documentos extraídos en momentos distintos. */

type Confidence = number | "alta" | "media" | "baja";

interface Subdimension { name: string; description: string }
interface Distinction { from_concept: string; difference: string }

interface Concept {
  id: string; title: string; definition: string; tipo: string; difficulty: string;
  importance: number; is_gateway: boolean; is_threshold: boolean;
  confidence_extraction: Confidence; source_pages: number[]; source_section?: string | null;
  sinonimos?: string[]; variantes_terminologicas?: string[]; is_enriched?: boolean;
  core_definition?: string | null; subdimensions?: Subdimension[]; distinctions?: Distinction[];
  measurement_approach?: string | null; theoretical_role?: string | null;
  key_tensions?: string[]; evolution_in_paper?: string | null;
  carga_cognitiva?: string[]; fuentes?: string[]; n_fuentes?: number;
}

interface Relation {
  from_concept_id: string; to_concept_id: string; relation_type: string;
  description: string; bidirectional?: boolean; confidence_extraction: Confidence;
}

interface Cluster { id: string; label: string; concept_ids: string[] }
interface AxisPosition { concept_id: string; position: number; justificacion?: string }
interface Axis {
  id: string; label: string; polo_bajo: string; polo_alto: string;
  positions: AxisPosition[]; confidence_extraction?: Confidence;
}

interface Repertoire {
  id: string; concept_id: string; label: string; description: string; example: string;
  por_que_es_intuitiva?: string; contraste_cientifico?: string;
  contexto_donde_funciona?: string; concepto_confundido?: string | null;
  origin: string; status: string; confidence_extraction: Confidence;
}

interface Framework {
  id: string; label: string; principios_centrales?: string[];
  rivales?: string[]; concept_ids?: string[]; confidence_extraction?: Confidence;
}

interface Thesis {
  id: string; statement?: string; position?: string;
  concept_ids?: string[]; concept_id?: string; framework_id?: string | null;
  supporting_arguments?: string[]; counterarguments?: string[];
  criterios_defensa_valida?: string[]; criterios_refutacion_valida?: string[];
  theoretical_source?: string | null; confidence_extraction?: Confidence;
}

interface EvidenceCase {
  id: string; concept_ids?: string[]; concept_id?: string;
  primary_concept_id?: string | null; kind: string; description: string;
  resolucion_esperada?: string; dominio?: string; variables_clave?: string[];
  es_paradigmatico?: boolean; prediction_enabled?: boolean;
  error_embebido?: string | null; source_pages?: number[];
  confidence_extraction?: Confidence;
}

interface Scenario {
  id: string; parent_case_id: string; concept_ids?: string[]; description: string;
  resolucion_esperada?: string; dominio?: string;
  distancia: "cercana" | "media" | "lejana";
  habilidad_objetivo?: string; error_embebido?: string | null;
}

interface JobResult {
  relations: Relation[]; clusters?: Cluster[]; axes?: Axis[];
}

type Tab =
  | "resumen" | "secuencia" | "conceptos" | "mapa"
  | "intuiciones" | "debate" | "casos" | "juego" | "diagnostico";

type ReviewState = "pending" | "approved" | "rejected";

const DIMENSION_LABEL: Record<string, string> = {
  recuperacion: "Recuperación", relacion: "Relación", transferencia: "Transferencia",
  "transferencia:lejana": "Transferencia lejana",
  "relacion:argumento": "Relación sobre argumentos",
  "relacion:espacio_atributos": "Espacio de atributos",
  anclaje: "Anclaje", automatizacion: "Automatización", calibracion: "Calibración",
  srl_planeacion: "Planeación", srl_accion: "Acción reguladora",
  srl_autorreflexion: "Autorreflexión", articulacion: "Articulación",
  persistencia: "Persistencia", engagement: "Compromiso",
};

const FAMILY_LABEL: Record<string, string> = {
  A: "Recuperar", B: "Discriminar", C: "Relacionar", D: "Estructurar",
  E: "Transferir", F: "Producir", G: "Calibrar", H: "Colaborar", I: "Regular",
};

const CARGA_LABEL: Record<string, string> = {
  memorizar: "hay que retener", discriminar: "se confunde con otro",
  integrar: "hay que integrar piezas", inferir: "hay que inferir",
};

const LAYER_LABEL: Record<string, string> = {
  segmentation: "Segmentación", layer1_concepts: "Conceptos",
  layer1c_canonical: "Depuración", layer1b_enrichment: "Profundización",
  layer2_relations: "Relaciones", layer2b_axes: "Ejes",
  layer3_repertoires: "Intuiciones", layer4_arguments: "Debate",
  layer5_cases: "Casos", layer5b_scenarios: "Variantes", layer6_meta: "Plan",
  compiler: "Compilación",
};

const STATUS_CLASS: Record<string, string> = {
  ok: "bg-emerald-500/10 text-emerald-300 border-emerald-500/30",
  empty: "bg-gray-700/30 text-gray-400 border-gray-600/40",
  skipped: "bg-gray-700/30 text-gray-400 border-gray-600/40",
  failed: "bg-rose-500/15 text-rose-300 border-rose-500/40",
};

const CONF_CLASS: Record<string, string> = {
  alta: "bg-emerald-500/10 text-emerald-300 border-emerald-500/25",
  media: "bg-amber-500/10 text-amber-300 border-amber-500/25",
  baja: "bg-rose-500/10 text-rose-300 border-rose-500/25",
};

const DIFFICULTY_CLASS: Record<string, string> = {
  basico: "text-sky-300", intermedio: "text-violet-300", avanzado: "text-orange-300",
};

const RELATION_CLASS: Record<string, string> = {
  apoya: "text-emerald-300", contradice: "text-rose-300", matiza: "text-amber-300",
  extiende: "text-sky-300", requiere: "text-violet-300", causa: "text-fuchsia-300",
  ejemplifica: "text-teal-300", generaliza: "text-indigo-300", contrasta: "text-orange-300",
};

const DISTANCE_CLASS: Record<string, string> = {
  cercana: "bg-sky-500/10 text-sky-300 border-sky-500/25",
  media: "bg-violet-500/10 text-violet-300 border-violet-500/25",
  lejana: "bg-emerald-500/10 text-emerald-300 border-emerald-500/25",
};

const FUENTE_LABEL: Record<string, string> = {
  distincion: "distinción explícita", repertorio: "intuición cotidiana",
  vecino_grafo: "vecino en el mapa",
};

export default function PlanPage() {
  const { id } = useParams<{ id: string }>();
  const backendUrl = process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:7860";
  const [plan, setPlan] = useState<any>(null);
  const [cargando, setCargando] = useState(true);
  const [tab, setTab] = useState<Tab>("resumen");
  const [query, setQuery] = useState("");
  const [onlyLow, setOnlyLow] = useState(false);
  const [reviews, setReviews] = useState<Record<string, ReviewState>>({});

  useEffect(() => {
    fetch(`${backendUrl}/students/${id}/plan`)
      .then((r) => r.json()).then(setPlan)
      .catch(() => setPlan({ vacio: true }))
      .finally(() => setCargando(false));
  }, [backendUrl, id]);

  const mp = plan?.materia_prima ?? {};
  const conceptById = useMemo(() => {
    const m: Record<string, any> = {};
    (mp.concepts ?? []).forEach((c: any) => { m[c.id] = c; });
    return m;
  }, [mp]);
  const name = (cid?: string | null) => (cid ? conceptById[cid]?.title ?? cid : "—");
  const setReview = (i: string, s: ReviewState) =>
    setReviews((p) => ({ ...p, [i]: s }));

  if (cargando) {
    return <Centered><Spinner /><p className="text-sm text-gray-400">Cargando el plan…</p></Centered>;
  }
  if (!plan || plan.vacio) {
    return (
      <Centered>
        <p className="text-gray-400">Todavía no hay material en tu plan.</p>
        <a href={`/estudiante/${id}`} className="text-sm text-indigo-400 underline">Volver al perfil</a>
      </Centered>
    );
  }

  const stats = plan.stats ?? {};
  const docs = plan.diagnostico_documentos ?? [];
  const fallos = docs.flatMap((d: any) =>
    (d.layer_status ?? []).filter((l: any) => l.status === "failed").map((l: any) => ({ ...l, doc: d.title }))
  );

  const matches = (t: string) =>
    !query.trim() || t.toLowerCase().includes(query.trim().toLowerCase());
  const conceptos = (mp.concepts ?? []).filter(
    (c: any) => (!onlyLow || conf(c.confidence_extraction) < 0.5)
      && matches(`${c.title} ${c.definition}`)
  );

  const TABS: [Tab, string, number | undefined][] = [
    ["resumen", "Resumen", undefined],
    ["secuencia", "Secuencia", plan.study_plan?.unidades?.length],
    ["conceptos", "Conceptos", (mp.concepts ?? []).length],
    ["mapa", "Mapa", (mp.relations ?? []).length],
    ["intuiciones", "Intuiciones", (mp.repertoires ?? []).length],
    ["debate", "Debate", (mp.theses ?? []).length],
    ["casos", "Casos", (mp.cases ?? []).length + (mp.scenarios ?? []).length],
    ["juego", "Qué se puede jugar", stats.items_precompilados],
    ["diagnostico", "Diagnóstico", docs.length],
  ];

  return (
    <main className="min-h-screen bg-[#0F0F13] text-white">
      <header className="border-b border-gray-800 px-4 py-4 sm:px-6">
        <div className="mx-auto max-w-6xl space-y-3">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="min-w-0">
              <a href={`/estudiante/${id}`} className="text-xs text-indigo-400">← Perfil</a>
              <h1 className="mt-1 text-lg font-semibold">Tu plan de estudios</h1>
              <p className="mt-0.5 font-mono text-[11px] text-gray-600">
                {(plan.fuentes ?? []).length} documento(s) · {stats.conceptos} conceptos ·{" "}
                {stats.aristas} conexiones
                {plan.fusion?.conceptos_totales > stats.conceptos &&
                  ` · ${plan.fusion.conceptos_totales - stats.conceptos} unificados entre lecturas`}
              </p>
            </div>
          </div>
          {fallos.length > 0 && (
            <div className="rounded border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">
              {fallos.length} capa(s) fallaron al extraer:{" "}
              {fallos.map((f: any) => `${LAYER_LABEL[f.layer] ?? f.layer} (${f.doc})`).join(", ")}.
              Lo que falte abajo puede no ser ausencia en el documento sino fallo de extracción.
            </div>
          )}
        </div>
      </header>

      <nav className="sticky top-0 z-10 border-b border-gray-800 bg-[#0F0F13]/95 px-4 backdrop-blur sm:px-6">
        <div className="mx-auto flex max-w-6xl gap-1 overflow-x-auto">
          {TABS.map(([k, label, n]) => (
            <button
              key={k}
              onClick={() => setTab(k)}
              aria-current={tab === k ? "page" : undefined}
              className={`whitespace-nowrap border-b-2 px-3 py-2.5 text-sm transition ${
                tab === k ? "border-indigo-400 text-white"
                  : "border-transparent text-gray-500 hover:text-gray-300"
              }`}
            >
              {label}
              {n !== undefined && <span className="ml-1.5 font-mono text-[11px] text-gray-600">{n}</span>}
            </button>
          ))}
        </div>
      </nav>

      <div className="mx-auto max-w-6xl space-y-6 px-4 py-6 sm:px-6">
        {tab === "resumen" && <Resumen plan={plan} name={name} />}

        {tab === "secuencia" && <Secuencia plan={plan} />}

        {tab === "conceptos" && (
          <>
            <div className="flex flex-wrap items-center gap-2">
              <input
                value={query} onChange={(e) => setQuery(e.target.value)}
                placeholder="Buscar concepto…"
                className="min-w-0 flex-1 rounded border border-gray-800 bg-gray-900/60 px-3 py-1.5 text-sm placeholder:text-gray-600 focus:border-indigo-500 focus:outline-none"
              />
              <button
                onClick={() => setOnlyLow((v) => !v)}
                className={`rounded border px-3 py-1.5 text-xs ${
                  onlyLow ? "border-rose-500/40 bg-rose-500/10 text-rose-300" : "border-gray-700 text-gray-400"
                }`}
              >
                Solo confianza baja
              </button>
            </div>
            {conceptos.length === 0 ? <Empty>Nada coincide con el filtro.</Empty> : (
              <div className="space-y-2">
                {conceptos.map((c: any) => (
                  <ConceptCard key={c.id} c={c} name={name}
                    state={reviews[c.id] ?? "pending"} onReview={setReview} />
                ))}
              </div>
            )}
          </>
        )}

        {tab === "mapa" && (
          <Mapa result={{ relations: mp.relations ?? [], clusters: plan.graph?.clusters ?? [],
                          axes: plan.graph?.ejes ?? [] } as any} name={name} />
        )}

        {tab === "intuiciones" && (
          <Repertorios items={mp.repertoires ?? []} name={name}
            reviews={reviews} onReview={setReview} />
        )}

        {tab === "debate" && (
          <Debate frameworks={mp.frameworks ?? []} theses={mp.theses ?? []} name={name} />
        )}

        {tab === "casos" && (
          <Casos cases={mp.cases ?? []} scenarios={mp.scenarios ?? []} name={name} />
        )}

        {tab === "juego" && <Juego plan={plan} />}

        {tab === "diagnostico" && <DiagnosticoDocs docs={docs} plan={plan} />}
      </div>
    </main>
  );
}

/* ────────────────────────────────────────────────────────────
   Resumen
   ──────────────────────────────────────────────────────────── */

function Resumen({ plan, name }: { plan: any; name: (id?: string | null) => string }) {
  const s = plan.stats ?? {};
  const mp = plan.materia_prima ?? {};
  const perfil = plan.perfil ?? {};
  const trabajados = Object.values(perfil.conceptos ?? {}).filter(
    (c: any) => (c.n_observaciones ?? 0) > 0
  ).length;

  const cifras: [string, any][] = [
    ["Conceptos", s.conceptos], ["Conexiones", s.aristas],
    ["Unidades", s.unidades], ["Intuiciones", (mp.repertoires ?? []).length],
    ["Casos", (mp.cases ?? []).length], ["Variantes", (mp.scenarios ?? []).length],
    ["Tesis", (mp.theses ?? []).length], ["Ítems listos", s.items_precompilados],
  ];

  return (
    <div className="space-y-6">
      <div>
        <SectionTitle>Qué hay en tu plan</SectionTitle>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-8">
          {cifras.map(([l, v]) => (
            <Card key={l} className="p-3">
              <p className="font-mono text-xl">{v ?? 0}</p>
              <p className="mt-0.5 text-[11px] text-gray-500">{l}</p>
            </Card>
          ))}
        </div>
      </div>

      <div>
        <SectionTitle count={(plan.fuentes ?? []).length}>Documentos</SectionTitle>
        <Card className="divide-y divide-gray-800 p-0">
          {(plan.diagnostico_documentos ?? []).map((d: any) => (
            <div key={d.id} className="flex flex-wrap items-center gap-x-4 gap-y-1 px-4 py-2.5 text-sm">
              <span className="min-w-0 flex-1 truncate text-gray-200">{d.title}</span>
              <span className="font-mono text-[11px] text-gray-600">
                {d.conceptos} conceptos · {d.relaciones} rel · {d.repertorios} int · {d.casos} casos
              </span>
            </div>
          ))}
        </Card>
      </div>

      {plan.fusion && (
        <div>
          <SectionTitle>Unificación entre lecturas</SectionTitle>
          <Card className="space-y-2 text-sm">
            <p className="text-gray-300">
              <span className="font-mono text-white">{plan.fusion.conceptos_totales}</span> conceptos
              extraídos en total →{" "}
              <span className="font-mono text-white">{plan.fusion.conceptos_unificados}</span> tras
              unificar los que aparecen en más de un documento.
            </p>
            {(plan.fusion.fusiones ?? []).length > 0 && (
              <div>
                <p className="mb-1 text-xs uppercase tracking-wider text-gray-500">Se unificaron</p>
                <ul className="space-y-0.5">
                  {plan.fusion.fusiones.slice(0, 15).map((f: any, i: number) => (
                    <li key={i} className="font-mono text-xs text-gray-400">
                      {f.absorbido} → <span className="text-gray-200">{f.canonico}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {(plan.fusion.fusiones_rechazadas ?? []).length > 0 && (
              <div>
                <p className="mb-1 text-xs uppercase tracking-wider text-amber-400">
                  Parecían el mismo y no lo son
                </p>
                {plan.fusion.fusiones_rechazadas.map((f: any, i: number) => (
                  <div key={i} className="text-xs text-gray-400">
                    <span className="text-gray-200">{f.a}</span> ≠ <span className="text-gray-200">{f.b}</span>
                    <p className="text-gray-600">{f.motivo}</p>
                  </div>
                ))}
              </div>
            )}
          </Card>
        </div>
      )}

      <div>
        <SectionTitle>Tu avance</SectionTitle>
        <Card className="text-sm text-gray-300">
          {perfil.n_senales
            ? <>Se han registrado <span className="font-mono text-white">{perfil.n_senales}</span> señales
               sobre <span className="font-mono text-white">{trabajados}</span> concepto(s).
               Eso decide qué te toca en la próxima sesión.</>
            : "Todavía no hiciste ninguna sesión. Cuando la hagas, esta sección muestra qué sabe el sistema de vos."}
        </Card>
      </div>
    </div>
  );
}

/* ────────────────────────────────────────────────────────────
   Secuencia
   ──────────────────────────────────────────────────────────── */

function Secuencia({ plan }: { plan: any }) {
  const conceptos = plan.concepts ?? {};
  const unidades = plan.study_plan?.unidades ?? [];
  const calidad = plan.study_plan?.calidad;

  if (!unidades.length) return <Empty>No se pudo calcular una secuencia.</Empty>;

  return (
    <div className="space-y-3">
      {calidad && calidad.nivel !== "buena" && (
        <Card className="border-amber-500/30 bg-amber-500/5 text-xs text-amber-200">
          Orden {calidad.nivel}: {calidad.motivo}
        </Card>
      )}
      {unidades.map((u: any) => (
        <Card key={u.id}>
          <div className="mb-2 flex flex-wrap items-center gap-2">
            <span className="font-mono text-xs text-gray-600">Unidad {u.numero}</span>
            {u.tiene_puerta && <Chip className="border-indigo-500/30 bg-indigo-500/10 text-indigo-300">puerta</Chip>}
            {u.tiene_umbral && <Chip className="border-fuchsia-500/30 bg-fuchsia-500/10 text-fuchsia-300">umbral</Chip>}
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
                      <Chip key={k} className="border-gray-700 text-gray-500">
                        {CARGA_LABEL[k] ?? k}
                      </Chip>
                    ))}
                    {c.n_fuentes > 1 && (
                      <Chip className="border-sky-500/30 bg-sky-500/10 text-sky-300">
                        en {c.n_fuentes} lecturas
                      </Chip>
                    )}
                    <span className="ml-auto font-mono text-[11px] text-gray-600">
                      {c.n_distractores} distractores
                    </span>
                  </div>
                  <p className="mt-0.5 text-xs text-gray-500">{c.definicion_corta ?? c.definicion}</p>
                  {p.n_observaciones > 0 && (
                    <div className="mt-1.5 flex items-center gap-2">
                      <div className="h-1 flex-1 overflow-hidden rounded-full bg-gray-800">
                        <div className={`h-full ${
                          (p.recuperacion ?? 0) >= 0.7 ? "bg-emerald-400"
                          : (p.recuperacion ?? 0) >= 0.4 ? "bg-amber-400" : "bg-rose-400"
                        }`} style={{ width: `${Math.round((p.recuperacion ?? 0) * 100)}%` }} />
                      </div>
                      <span className="font-mono text-[11px] text-gray-600">
                        {Math.round((p.recuperacion ?? 0) * 100)}%
                      </span>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </Card>
      ))}
    </div>
  );
}

/* ────────────────────────────────────────────────────────────
   Qué se puede jugar
   ──────────────────────────────────────────────────────────── */

function Juego({ plan }: { plan: any }) {
  const [familia, setFamilia] = useState<string | null>(null);
  const mechs: any[] = Object.values(plan.mechanics ?? {});
  const porFamilia: Record<string, any[]> = {};
  mechs.forEach((m) => { (porFamilia[m.familia] ??= []).push(m); });
  const visibles = familia ? porFamilia[familia] ?? [] : mechs;

  return (
    <div className="space-y-6">
      <div>
        <SectionTitle>Qué puede medir tu plan</SectionTitle>
        <p className="mb-3 -mt-1 text-xs text-gray-500">
          Las dimensiones sin cobertura van a quedar vacías en tu perfil. Al lado está el motivo.
        </p>
        <Card className="divide-y divide-gray-800 p-0">
          {(plan.readiness ?? []).map((r: any) => (
            <div key={r.dimension} className="px-4 py-2">
              <div className="flex flex-wrap items-center gap-2 text-sm">
                <span className="w-48 shrink-0 text-gray-300">
                  {DIMENSION_LABEL[r.dimension] ?? r.dimension}
                </span>
                <Chip className={r.medible ? STATUS_CLASS.ok : STATUS_CLASS.empty}>
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
        </Card>
      </div>

      <div>
        <SectionTitle count={mechs.length}>Mecánicas</SectionTitle>
        <div className="mb-2 flex flex-wrap gap-1">
          <button onClick={() => setFamilia(null)}
            className={`rounded border px-2 py-1 text-xs ${familia === null
              ? "border-indigo-500/40 bg-indigo-500/10 text-indigo-300" : "border-gray-700 text-gray-500"}`}>
            Todas
          </button>
          {Object.keys(porFamilia).sort().map((f) => (
            <button key={f} onClick={() => setFamilia(f)}
              className={`rounded border px-2 py-1 text-xs ${familia === f
                ? "border-indigo-500/40 bg-indigo-500/10 text-indigo-300" : "border-gray-700 text-gray-500"}`}>
              {f} · {FAMILY_LABEL[f] ?? f}
            </button>
          ))}
        </div>
        <Card className="divide-y divide-gray-800 p-0">
          {visibles.map((m: any) => (
            <div key={m.mechanic_id} className={`px-4 py-2.5 ${m.disponible ? "" : "opacity-60"}`}>
              <div className="flex flex-wrap items-center gap-2">
                <span className="w-8 shrink-0 font-mono text-xs text-gray-600">{m.mechanic_id}</span>
                <span className="text-sm">{m.nombre}</span>
                <Chip className={m.disponible ? STATUS_CLASS.ok : STATUS_CLASS.empty}>
                  {m.disponible ? "lista" : "bloqueada"}
                </Chip>
                {m.items_precompilados > 0 && (
                  <Chip className="border-gray-700 text-gray-400">{m.items_precompilados} ítems</Chip>
                )}
                {m.requiere_juez && <Chip className="border-gray-700 text-gray-500">necesita IA</Chip>}
                <span className="ml-auto font-mono text-[11px] text-gray-600">
                  {(m.senales ?? []).map((s: any) => s.dimension).join(" · ")}
                </span>
              </div>
              {!m.disponible && (m.faltantes ?? []).length > 0 && (
                <p className="mt-1 pl-10 text-xs text-amber-300/80">{m.faltantes.join(" · ")}</p>
              )}
            </div>
          ))}
        </Card>
      </div>

      <div>
        <SectionTitle count={Object.keys(plan.distractor_pools ?? {}).length}>
          Distractores compilados
        </SectionTitle>
        <p className="mb-2 -mt-1 text-xs text-gray-500">
          Los caracterizados permiten saber qué idea previa activaste al equivocarte;
          los de vecindad solo registran el fallo.
        </p>
        <div className="space-y-2">
          {Object.entries(plan.distractor_pools ?? {}).slice(0, 15).map(([cid, pool]: [string, any]) => (
            <Card key={cid}>
              <p className="mb-1.5 text-sm font-medium">
                {plan.concepts?.[cid]?.titulo ?? cid}
              </p>
              <div className="space-y-1">
                {pool.map((d: any) => (
                  <div key={d.id} className="flex items-center gap-2 text-xs">
                    <Chip className={d.fuente === "vecino_grafo"
                      ? "border-gray-700 text-gray-500"
                      : "border-emerald-500/25 bg-emerald-500/10 text-emerald-300"}>
                      {FUENTE_LABEL[d.fuente] ?? d.fuente}
                    </Chip>
                    <span className="min-w-0 flex-1 truncate text-gray-400">{d.etiqueta}</span>
                    <span className="shrink-0 font-mono text-gray-600">{d.plausibilidad}</span>
                  </div>
                ))}
              </div>
            </Card>
          ))}
        </div>
      </div>
    </div>
  );
}

/* ────────────────────────────────────────────────────────────
   Diagnóstico por documento
   ──────────────────────────────────────────────────────────── */

function DiagnosticoDocs({ docs, plan }: { docs: any[]; plan: any }) {
  if (!docs.length) return <Empty>Sin información de diagnóstico.</Empty>;
  return (
    <div className="space-y-5">
      {docs.map((d) => {
        const canon = d.pipeline_stats?.canonicalization;
        const grounding = d.pipeline_stats?.grounding;
        const timings = d.pipeline_stats?.timings_seconds;
        return (
          <div key={d.id} className="space-y-3">
            <h2 className="text-sm font-semibold text-gray-200">{d.title}</h2>

            <div className="grid grid-cols-3 gap-2 sm:grid-cols-6">
              {[["Conceptos", d.conceptos], ["Relaciones", d.relaciones],
                ["Intuiciones", d.repertorios], ["Casos", d.casos],
                ["Variantes", d.escenarios], ["Tesis", d.tesis]].map(([l, v]) => (
                <Card key={String(l)} className="p-3">
                  <p className="font-mono text-lg">{String(v ?? 0)}</p>
                  <p className="mt-0.5 text-[11px] text-gray-500">{l}</p>
                </Card>
              ))}
            </div>

            {(d.layer_status ?? []).length > 0 && (
              <Card className="divide-y divide-gray-800 p-0">
                {d.layer_status.map((l: any) => (
                  <div key={l.layer} className="flex flex-wrap items-start gap-x-3 gap-y-1 px-4 py-2 text-sm">
                    <span className="w-32 shrink-0 text-gray-300">{LAYER_LABEL[l.layer] ?? l.layer}</span>
                    <Chip className={STATUS_CLASS[l.status] ?? STATUS_CLASS.empty}>{l.status}</Chip>
                    <span className="font-mono text-xs text-gray-500">{l.items}</span>
                    {l.detail && <span className="w-full text-xs text-gray-500 sm:w-auto sm:flex-1">{l.detail}</span>}
                  </div>
                ))}
              </Card>
            )}

            {grounding && (
              <Card className="space-y-2 text-sm">
                <p className="text-xs uppercase tracking-wider text-gray-500">Anclaje en el texto</p>
                <p className="text-gray-300">
                  Tasa de verificación:{" "}
                  <span className="font-mono text-white">{grounding.tasa_verificacion ?? "—"}</span>
                  {grounding.conceptos_descartados > 0 && (
                    <> · <span className="text-rose-300">{grounding.conceptos_descartados} descartados</span> por
                    no aparecer en el documento</>
                  )}
                </p>
                {(grounding.descartados ?? []).slice(0, 6).map((x: any, i: number) => (
                  <p key={i} className="text-xs text-gray-500">
                    <span className="text-gray-300">{x.title}</span> — {x.motivo}
                  </p>
                ))}
              </Card>
            )}

            {canon && (
              <Card className="space-y-2 text-sm">
                <p className="text-xs uppercase tracking-wider text-gray-500">Depuración de conceptos</p>
                <p className="text-gray-300">
                  <span className="font-mono text-white">{canon.input}</span> →{" "}
                  <span className="font-mono text-white">{canon.output}</span> tras unificar variantes.
                </p>
                {(canon.deterministic_fusions ?? []).slice(0, 8).map((f: any, i: number) => (
                  <p key={i} className="font-mono text-xs text-gray-400">
                    <span className="text-gray-200">{f.canonical_title ?? f.canonical}</span> ←{" "}
                    {(f.absorbed ?? []).join(", ")}
                  </p>
                ))}
                {(canon.acronimos_ambiguos ?? []).length > 0 && (
                  <p className="text-xs text-gray-500">
                    Siglas usadas por más de un concepto:{" "}
                    <span className="font-mono text-gray-300">{canon.acronimos_ambiguos.join(", ")}</span>
                  </p>
                )}
              </Card>
            )}

            {timings && (
              <Card>
                <p className="mb-2 text-xs uppercase tracking-wider text-gray-500">Tiempos</p>
                <div className="grid grid-cols-2 gap-x-6 gap-y-1 text-sm sm:grid-cols-3">
                  {Object.entries(timings).map(([k, v]) => (
                    <div key={k} className="flex items-baseline justify-between gap-2">
                      <span className="text-gray-400">{LAYER_LABEL[k] ?? k}</span>
                      <span className="font-mono text-xs text-gray-300">{String(v)}s</span>
                    </div>
                  ))}
                </div>
              </Card>
            )}
          </div>
        );
      })}

      {(plan.items_descartados ?? []).length > 0 && (
        <div>
          <SectionTitle count={plan.items_descartados.length}>Ejercicios descartados</SectionTitle>
          <p className="mb-2 -mt-1 text-xs text-gray-500">
            El compilador no los emitió porque no discriminaban: preguntas donde la
            respuesta correcta y la incorrecta decían lo mismo.
          </p>
          <Card className="divide-y divide-gray-800 p-0">
            {plan.items_descartados.slice(0, 20).map((d: any, i: number) => (
              <div key={i} className="flex flex-wrap gap-x-3 px-4 py-2 text-xs">
                <span className="font-mono text-gray-400">{d.item}</span>
                <span className="text-gray-500">{d.motivo}</span>
              </div>
            ))}
          </Card>
        </div>
      )}
    </div>
  );
}

/* ────────────────────────────────────────────────────────────
   Utilidades
   ──────────────────────────────────────────────────────────── */

/** La confianza pasó de etiqueta a número. Se acepta cualquiera de las dos. */
function conf(value: Confidence | undefined): number {
  if (typeof value === "number") return value;
  if (value === "alta") return 0.9;
  if (value === "media") return 0.6;
  if (value === "baja") return 0.3;
  return 0.6;
}

function confLabel(value: Confidence | undefined): "alta" | "media" | "baja" {
  const n = conf(value);
  return n >= 0.75 ? "alta" : n >= 0.5 ? "media" : "baja";
}









function pct(n: number | undefined): string {
  return `${Math.round((n ?? 0) * 100)}%`;
}

/* ────────────────────────────────────────────────────────────
   Piezas de interfaz
   ──────────────────────────────────────────────────────────── */

function Centered({ children }: { children: React.ReactNode }) {
  return (
    <main className="min-h-screen bg-[#0F0F13] text-white flex flex-col items-center justify-center gap-3 px-6 text-center">
      {children}
    </main>
  );
}

function Spinner() {
  return (
    <div
      aria-hidden
      className="h-5 w-5 rounded-full border-2 border-gray-700 border-t-indigo-400 motion-safe:animate-spin"
    />
  );
}

function Chip({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return (
    <span className={`inline-flex items-center rounded border px-1.5 py-0.5 text-[11px] font-medium ${className}`}>
      {children}
    </span>
  );
}

function Card({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return (
    <div className={`rounded-lg border border-gray-800 bg-gray-900/40 p-4 ${className}`}>{children}</div>
  );
}

function SectionTitle({ children, count }: { children: React.ReactNode; count?: number }) {
  return (
    <h2 className="mb-3 flex items-baseline gap-2 text-sm font-semibold uppercase tracking-wider text-gray-400">
      {children}
      {count !== undefined && <span className="font-mono text-xs text-gray-600">{count}</span>}
    </h2>
  );
}

function Empty({ children }: { children: React.ReactNode }) {
  return (
    <Card className="text-sm text-gray-500">{children}</Card>
  );
}

function Bar({ value, tone = "indigo" }: { value: number; tone?: string }) {
  const width = Math.max(2, Math.min(100, Math.round(value * 100)));
  const color =
    value >= 0.75 ? "bg-emerald-400" : value >= 0.4 ? "bg-amber-400" : "bg-rose-400";
  return (
    <div className="h-1.5 w-full overflow-hidden rounded-full bg-gray-800">
      <div className={`h-full ${tone === "auto" ? color : "bg-indigo-400"}`} style={{ width: `${width}%` }} />
    </div>
  );
}


function ReviewButtons({
  id, state, onChange,
}: { id: string; state: ReviewState; onChange: (id: string, s: ReviewState) => void }) {
  return (
    <div className="flex shrink-0 gap-1">
      <button
        onClick={() => onChange(id, state === "approved" ? "pending" : "approved")}
        aria-pressed={state === "approved"}
        aria-label="Aprobar"
        className={`rounded border px-2 py-0.5 text-xs transition focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-400 ${
          state === "approved"
            ? "border-emerald-500/40 bg-emerald-500/15 text-emerald-300"
            : "border-gray-700 text-gray-500 hover:text-gray-300"
        }`}
      >
        Aprobar
      </button>
      <button
        onClick={() => onChange(id, state === "rejected" ? "pending" : "rejected")}
        aria-pressed={state === "rejected"}
        aria-label="Descartar"
        className={`rounded border px-2 py-0.5 text-xs transition focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-400 ${
          state === "rejected"
            ? "border-rose-500/40 bg-rose-500/15 text-rose-300"
            : "border-gray-700 text-gray-500 hover:text-gray-300"
        }`}
      >
        Descartar
      </button>
    </div>
  );
}

/* ────────────────────────────────────────────────────────────
   Conceptos
   ──────────────────────────────────────────────────────────── */

function ConceptCard({
  c, name, state, onReview,
}: {
  c: Concept;
  name: (id?: string | null) => string;
  state: ReviewState;
  onReview: (id: string, s: ReviewState) => void;
}) {
  const [open, setOpen] = useState(false);
  const label = confLabel(c.confidence_extraction);
  const hasDetail =
    c.is_enriched || (c.sinonimos?.length ?? 0) > 0 || (c.subdimensions?.length ?? 0) > 0;

  return (
    <Card className={state === "rejected" ? "opacity-50" : ""}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-1.5">
            <h3 className="font-medium">{c.title}</h3>
            {c.is_gateway && <Chip className="border-indigo-500/30 bg-indigo-500/10 text-indigo-300">puerta</Chip>}
            {c.is_threshold && <Chip className="border-fuchsia-500/30 bg-fuchsia-500/10 text-fuchsia-300">umbral</Chip>}
            {c.is_enriched && <Chip className="border-gray-700 text-gray-400">profundizado</Chip>}
            <Chip className={CONF_CLASS[label]}>{label}</Chip>
          </div>
          <p className="mt-1.5 text-sm text-gray-300">{c.definition}</p>
          <p className="mt-1.5 font-mono text-[11px] text-gray-600">
            <span className={DIFFICULTY_CLASS[c.difficulty] ?? ""}>{c.difficulty}</span>
            {" · "}{c.tipo}{" · "}importancia {pct(c.importance)}
            {c.source_pages?.length ? ` · p. ${c.source_pages.join(", ")}` : ""}
          </p>
        </div>
        <ReviewButtons id={c.id} state={state} onChange={onReview} />
      </div>

      {hasDetail && (
        <button
          onClick={() => setOpen((v) => !v)}
          className="mt-2 text-xs text-indigo-400 hover:text-indigo-300 focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-400"
        >
          {open ? "Ocultar detalle" : "Ver detalle"}
        </button>
      )}

      {open && (
        <div className="mt-3 space-y-3 border-t border-gray-800 pt-3 text-sm">
          {c.core_definition && (
            <Field label="Definición ampliada">{c.core_definition}</Field>
          )}
          {(c.sinonimos?.length ?? 0) > 0 && (
            <Field label="Sinónimos">
              <span className="font-mono text-xs text-gray-400">{c.sinonimos!.join(" · ")}</span>
            </Field>
          )}
          {(c.subdimensions?.length ?? 0) > 0 && (
            <Field label="Facetas">
              <ul className="space-y-1">
                {c.subdimensions!.map((s, i) => (
                  <li key={i} className="text-gray-400">
                    <span className="text-gray-200">{s.name}</span> — {s.description}
                  </li>
                ))}
              </ul>
            </Field>
          )}
          {(c.distinctions?.length ?? 0) > 0 && (
            <Field label="Se confunde con">
              <ul className="space-y-1">
                {c.distinctions!.map((d, i) => (
                  <li key={i} className="text-gray-400">
                    <span className="text-gray-200">{name(d.from_concept)}</span> — {d.difference}
                  </li>
                ))}
              </ul>
            </Field>
          )}
          {c.theoretical_role && <Field label="Rol teórico">{c.theoretical_role}</Field>}
          {c.measurement_approach && <Field label="Cómo se mide">{c.measurement_approach}</Field>}
          {(c.key_tensions?.length ?? 0) > 0 && (
            <Field label="Tensiones abiertas">
              <ul className="list-disc space-y-0.5 pl-4 text-gray-400">
                {c.key_tensions!.map((t, i) => <li key={i}>{t}</li>)}
              </ul>
            </Field>
          )}
          {c.evolution_in_paper && <Field label="Evolución en el texto">{c.evolution_in_paper}</Field>}
        </div>
      )}
    </Card>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <p className="mb-0.5 text-[11px] uppercase tracking-wider text-gray-500">{label}</p>
      <div className="text-sm text-gray-300">{children}</div>
    </div>
  );
}

/* ────────────────────────────────────────────────────────────
   Mapa
   ──────────────────────────────────────────────────────────── */

function Mapa({ result, name }: { result: JobResult; name: (id?: string | null) => string }) {
  const axes = result.axes ?? [];
  const clusters = result.clusters ?? [];

  return (
    <div className="space-y-6">
      <div>
        <SectionTitle count={result.relations.length}>Conexiones</SectionTitle>
        {result.relations.length === 0 ? (
          <Empty>No se encontraron conexiones entre conceptos.</Empty>
        ) : (
          <Card className="divide-y divide-gray-800 p-0">
            {result.relations.map((r, i) => (
              <div key={i} className="px-4 py-2.5">
                <p className="text-sm">
                  <span className="text-gray-200">{name(r.from_concept_id)}</span>
                  <span className={`mx-2 font-mono text-xs ${RELATION_CLASS[r.relation_type] ?? "text-gray-400"}`}>
                    {r.relation_type}
                  </span>
                  <span className="text-gray-200">{name(r.to_concept_id)}</span>
                </p>
                {r.description && <p className="mt-1 text-xs text-gray-500">{r.description}</p>}
              </div>
            ))}
          </Card>
        )}
      </div>

      <div>
        <SectionTitle count={clusters.length}>Grupos temáticos</SectionTitle>
        {clusters.length === 0 ? (
          <Empty>No se calcularon grupos. Hacen falta más conexiones.</Empty>
        ) : (
          <div className="grid gap-2 sm:grid-cols-2">
            {clusters.map((cl) => (
              <Card key={cl.id}>
                <p className="text-sm font-medium">{cl.label}</p>
                <p className="mt-1 text-xs text-gray-400">
                  {cl.concept_ids.map((cid) => name(cid)).join(" · ")}
                </p>
              </Card>
            ))}
          </div>
        )}
      </div>

      <div>
        <SectionTitle count={axes.length}>Ejes de comparación</SectionTitle>
        {axes.length === 0 ? (
          <Empty>
            Sin ejes. Se construyen a partir de las facetas de los conceptos profundizados, y hacen
            falta al menos tres.
          </Empty>
        ) : (
          <div className="space-y-3">
            {axes.map((a) => (
              <Card key={a.id}>
                <div className="mb-2 flex items-baseline justify-between gap-3">
                  <p className="text-sm font-medium">{a.label}</p>
                  <p className="font-mono text-[11px] text-gray-600">
                    {a.polo_bajo} → {a.polo_alto}
                  </p>
                </div>
                <div className="space-y-1.5">
                  {a.positions.map((p, i) => (
                    <div key={i} className="flex items-center gap-3">
                      <span className="w-40 shrink-0 truncate text-xs text-gray-300" title={name(p.concept_id)}>
                        {name(p.concept_id)}
                      </span>
                      <div className="flex-1"><Bar value={p.position} /></div>
                      <span className="w-9 shrink-0 text-right font-mono text-[11px] text-gray-600">
                        {pct(p.position)}
                      </span>
                    </div>
                  ))}
                </div>
              </Card>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

/* ────────────────────────────────────────────────────────────
   Intuiciones
   ──────────────────────────────────────────────────────────── */

function Repertorios({
  items, name, reviews, onReview,
}: {
  items: Repertoire[];
  name: (id?: string | null) => string;
  reviews: Record<string, ReviewState>;
  onReview: (id: string, s: ReviewState) => void;
}) {
  if (!items.length) {
    return <Empty>No se encontraron intuiciones cotidianas asociadas a estos conceptos.</Empty>;
  }
  return (
    <div className="space-y-2">
      {items.map((r) => {
        const state = reviews[r.id] ?? "pending";
        return (
          <Card key={r.id} className={state === "rejected" ? "opacity-50" : ""}>
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-1.5">
                  <h3 className="font-medium">{r.label}</h3>
                  <Chip className="border-gray-700 text-gray-400">
                    {r.origin === "documentado_en_corpus" ? "en el texto" : "inferida"}
                  </Chip>
                  <Chip className={CONF_CLASS[confLabel(r.confidence_extraction)]}>
                    {confLabel(r.confidence_extraction)}
                  </Chip>
                </div>
                <p className="mt-0.5 text-xs text-gray-500">sobre {name(r.concept_id)}</p>
                <p className="mt-1.5 text-sm text-gray-300">{r.description}</p>
              </div>
              <ReviewButtons id={r.id} state={state} onChange={onReview} />
            </div>
            <div className="mt-3 space-y-2 border-t border-gray-800 pt-3">
              {r.example && <Field label="Cómo suena en un estudiante">“{r.example}”</Field>}
              {r.por_que_es_intuitiva && <Field label="Por qué es razonable">{r.por_que_es_intuitiva}</Field>}
              {r.contexto_donde_funciona && <Field label="Dónde sí funciona">{r.contexto_donde_funciona}</Field>}
              {r.contraste_cientifico && <Field label="Qué cambia en el marco científico">{r.contraste_cientifico}</Field>}
              {r.concepto_confundido && (
                <Field label="Confunde este concepto con">{name(r.concepto_confundido)}</Field>
              )}
            </div>
          </Card>
        );
      })}
    </div>
  );
}

/* ────────────────────────────────────────────────────────────
   Debate
   ──────────────────────────────────────────────────────────── */

function Debate({
  frameworks, theses, name,
}: { frameworks: Framework[]; theses: Thesis[]; name: (id?: string | null) => string }) {
  const fwById: Record<string, Framework> = {};
  frameworks.forEach((f) => { fwById[f.id] = f; });

  return (
    <div className="space-y-6">
      <div>
        <SectionTitle count={frameworks.length}>Marcos en disputa</SectionTitle>
        {frameworks.length === 0 ? (
          <Empty>
            Sin marcos teóricos. Las actividades de refutar necesitan al menos dos marcos rivales.
          </Empty>
        ) : (
          <div className="grid gap-2 sm:grid-cols-2">
            {frameworks.map((f) => (
              <Card key={f.id}>
                <p className="font-medium">{f.label}</p>
                {(f.principios_centrales?.length ?? 0) > 0 && (
                  <ul className="mt-1.5 list-disc space-y-0.5 pl-4 text-xs text-gray-400">
                    {f.principios_centrales!.map((p, i) => <li key={i}>{p}</li>)}
                  </ul>
                )}
                {(f.rivales?.length ?? 0) > 0 && (
                  <p className="mt-2 text-xs text-gray-500">
                    Rival de:{" "}
                    <span className="text-gray-300">
                      {f.rivales!.map((r) => fwById[r]?.label ?? r).join(", ")}
                    </span>
                  </p>
                )}
              </Card>
            ))}
          </div>
        )}
      </div>

      <div>
        <SectionTitle count={theses.length}>Tesis defendibles</SectionTitle>
        {theses.length === 0 ? (
          <Empty>
            Sin tesis. Puede ser correcto: un texto puramente expositivo no plantea nada discutible.
          </Empty>
        ) : (
          <div className="space-y-2">
            {theses.map((t) => {
              const ids = t.concept_ids ?? (t.concept_id ? [t.concept_id] : []);
              return (
                <Card key={t.id}>
                  <p className="text-sm font-medium">{t.statement ?? t.position ?? t.id}</p>
                  {ids.length > 0 && (
                    <p className="mt-1 text-xs text-gray-500">
                      Sobre {ids.map((c) => name(c)).join(", ")}
                      {t.framework_id ? ` · marco ${fwById[t.framework_id]?.label ?? t.framework_id}` : ""}
                    </p>
                  )}
                  <div className="mt-3 grid gap-3 sm:grid-cols-2">
                    <div>
                      <p className="mb-1 text-[11px] uppercase tracking-wider text-emerald-400">A favor</p>
                      <ul className="list-disc space-y-0.5 pl-4 text-xs text-gray-400">
                        {(t.supporting_arguments ?? []).map((a, i) => <li key={i}>{a}</li>)}
                      </ul>
                    </div>
                    <div>
                      <p className="mb-1 text-[11px] uppercase tracking-wider text-rose-400">En contra</p>
                      <ul className="list-disc space-y-0.5 pl-4 text-xs text-gray-400">
                        {(t.counterarguments ?? []).map((a, i) => <li key={i}>{a}</li>)}
                      </ul>
                    </div>
                  </div>
                  {((t.criterios_defensa_valida?.length ?? 0) > 0 ||
                    (t.criterios_refutacion_valida?.length ?? 0) > 0) && (
                    <div className="mt-3 grid gap-3 border-t border-gray-800 pt-3 sm:grid-cols-2">
                      {(t.criterios_defensa_valida?.length ?? 0) > 0 && (
                        <Field label="Qué cuenta como buena defensa">
                          <ul className="list-disc space-y-0.5 pl-4 text-xs text-gray-400">
                            {t.criterios_defensa_valida!.map((c, i) => <li key={i}>{c}</li>)}
                          </ul>
                        </Field>
                      )}
                      {(t.criterios_refutacion_valida?.length ?? 0) > 0 && (
                        <Field label="Qué cuenta como buena objeción">
                          <ul className="list-disc space-y-0.5 pl-4 text-xs text-gray-400">
                            {t.criterios_refutacion_valida!.map((c, i) => <li key={i}>{c}</li>)}
                          </ul>
                        </Field>
                      )}
                    </div>
                  )}
                </Card>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

/* ────────────────────────────────────────────────────────────
   Casos
   ──────────────────────────────────────────────────────────── */

function Casos({
  cases, scenarios, name,
}: { cases: EvidenceCase[]; scenarios: Scenario[]; name: (id?: string | null) => string }) {
  const byParent: Record<string, Scenario[]> = {};
  scenarios.forEach((s) => {
    (byParent[s.parent_case_id] ??= []).push(s);
  });

  const sinGold = cases.filter((c) => !(c.resolucion_esperada ?? "").trim()).length;

  if (!cases.length) {
    return (
      <Empty>
        Sin casos. Las actividades de aplicar y transferir no se van a poder armar con este documento.
      </Empty>
    );
  }

  return (
    <div className="space-y-4">
      {sinGold > 0 && (
        <Card className="border-amber-500/30 bg-amber-500/5 text-sm text-amber-200">
          {sinGold} {sinGold === 1 ? "caso no trae" : "casos no traen"} la resolución esperada. Sin ella
          no hay contra qué calificar la respuesta del estudiante, y tampoco se pueden derivar variantes.
        </Card>
      )}
      {cases.map((c) => {
        const ids = c.concept_ids ?? (c.concept_id ? [c.concept_id] : []);
        const variants = byParent[c.id] ?? [];
        return (
          <Card key={c.id}>
            <div className="flex flex-wrap items-center gap-1.5">
              <Chip className="border-gray-700 text-gray-400">{c.kind}</Chip>
              {c.es_paradigmatico && (
                <Chip className="border-indigo-500/30 bg-indigo-500/10 text-indigo-300">de enseñanza</Chip>
              )}
              {c.prediction_enabled && (
                <Chip className="border-gray-700 text-gray-400">permite predecir</Chip>
              )}
              {c.error_embebido && (
                <Chip className="border-rose-500/30 bg-rose-500/10 text-rose-300">con error incrustado</Chip>
              )}
              {c.dominio && <Chip className="border-gray-700 text-gray-500">{c.dominio}</Chip>}
            </div>
            <p className="mt-2 text-sm text-gray-200">{c.description}</p>
            {ids.length > 0 && (
              <p className="mt-1 text-xs text-gray-500">Pone en juego: {ids.map((i) => name(i)).join(", ")}</p>
            )}
            <div className="mt-3 space-y-2 border-t border-gray-800 pt-3">
              {c.resolucion_esperada && <Field label="Resolución esperada">{c.resolucion_esperada}</Field>}
              {(c.variables_clave?.length ?? 0) > 0 && (
                <Field label="Variables clave">
                  <span className="text-xs text-gray-400">{c.variables_clave!.join(" · ")}</span>
                </Field>
              )}
              {c.error_embebido && <Field label="Error incrustado">{c.error_embebido}</Field>}
            </div>

            {variants.length > 0 && (
              <div className="mt-3 border-t border-gray-800 pt-3">
                <p className="mb-2 text-[11px] uppercase tracking-wider text-gray-500">
                  Variantes generadas <span className="font-mono">{variants.length}</span>
                </p>
                <div className="space-y-2">
                  {variants.map((v) => (
                    <div key={v.id} className="rounded border border-gray-800 bg-gray-900/40 p-3">
                      <div className="mb-1.5 flex flex-wrap items-center gap-1.5">
                        <Chip className={DISTANCE_CLASS[v.distancia]}>{v.distancia}</Chip>
                        {v.dominio && <Chip className="border-gray-700 text-gray-500">{v.dominio}</Chip>}
                      </div>
                      <p className="text-sm text-gray-300">{v.description}</p>
                      {v.resolucion_esperada && (
                        <p className="mt-1.5 text-xs text-gray-500">
                          <span className="text-gray-400">Se espera:</span> {v.resolucion_esperada}
                        </p>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}
          </Card>
        );
      })}
    </div>
  );
}
