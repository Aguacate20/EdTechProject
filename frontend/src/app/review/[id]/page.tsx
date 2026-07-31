"use client";

import { useEffect, useMemo, useState } from "react";
import { useParams } from "next/navigation";

/* ────────────────────────────────────────────────────────────
   Tipos — esquema 2.x del extractor.
   Se aceptan también los campos del esquema viejo donde cambiaron,
   para poder abrir extracciones anteriores sin que la página rompa.
   ──────────────────────────────────────────────────────────── */

type Confidence = number | "alta" | "media" | "baja";

interface Subdimension { name: string; description: string }
interface Distinction { from_concept: string; difference: string }

interface Concept {
  id: string;
  title: string;
  definition: string;
  tipo: string;
  difficulty: string;
  importance: number;
  is_gateway: boolean;
  is_threshold: boolean;
  confidence_extraction: Confidence;
  source_pages: number[];
  source_section?: string | null;
  sinonimos?: string[];
  variantes_terminologicas?: string[];
  is_enriched?: boolean;
  core_definition?: string | null;
  subdimensions?: Subdimension[];
  distinctions?: Distinction[];
  measurement_approach?: string | null;
  theoretical_role?: string | null;
  key_tensions?: string[];
  evolution_in_paper?: string | null;
}

interface Relation {
  from_concept_id: string;
  to_concept_id: string;
  relation_type: string;
  description: string;
  bidirectional?: boolean;
  confidence_extraction: Confidence;
}

interface Cluster { id: string; label: string; concept_ids: string[] }

interface AxisPosition { concept_id: string; position: number; justificacion?: string }
interface Axis {
  id: string; label: string; polo_bajo: string; polo_alto: string;
  positions: AxisPosition[]; confidence_extraction?: Confidence;
}

interface Repertoire {
  id: string; concept_id: string; label: string; description: string; example: string;
  por_que_es_intuitiva?: string;
  contraste_cientifico?: string;
  contexto_donde_funciona?: string;
  concepto_confundido?: string | null;
  origin: string; status: string; confidence_extraction: Confidence;
}

interface Framework {
  id: string; label: string;
  principios_centrales?: string[]; rivales?: string[]; concept_ids?: string[];
  confidence_extraction?: Confidence;
}

interface Thesis {
  id: string;
  statement?: string;
  position?: string;            // esquema viejo
  concept_ids?: string[];
  concept_id?: string;          // esquema viejo
  framework_id?: string | null;
  supporting_arguments?: string[];
  counterarguments?: string[];
  criterios_defensa_valida?: string[];
  criterios_refutacion_valida?: string[];
  theoretical_source?: string | null;
  confidence_extraction?: Confidence;
}

interface EvidenceCase {
  id: string;
  concept_ids?: string[];
  concept_id?: string;          // esquema viejo
  primary_concept_id?: string | null;
  kind: string; description: string;
  resolucion_esperada?: string;
  dominio?: string;
  variables_clave?: string[];
  es_paradigmatico?: boolean;
  prediction_enabled?: boolean;
  error_embebido?: string | null;
  source_pages?: number[];
  confidence_extraction?: Confidence;
}

interface Scenario {
  id: string; parent_case_id: string; concept_ids?: string[];
  description: string; resolucion_esperada?: string; dominio?: string;
  distancia: "cercana" | "media" | "lejana";
  habilidad_objetivo?: string; error_embebido?: string | null;
}

interface SignalCoverage { dimension: string; cobertura: number; cuello_de_botella: string }
interface FamilyAvailability { family: string; available: boolean; reason: string; mechanic_ids: string[] }

interface Meta {
  gateway_concepts?: string[];
  threshold_concepts?: string[];
  prerequisite_graph?: Record<string, string[]>;
  unlocks_graph?: Record<string, string[]>;
  suggested_sequence?: string[];
  difficulty_distribution?: Record<string, number>;
  argumentative_richness?: number;
  case_density?: number;
  repertoire_density?: number;
  relational_density?: number;
  enrichment_coverage?: number;
  recommended_modalities?: string[];
  signal_coverage?: SignalCoverage[];
  family_availability?: FamilyAvailability[];
}

interface LayerStatus { layer: string; status: string; items: number; detail: string }

interface JobResult {
  course_id: string;
  source_filename: string;
  extracted_at: string;
  schema_version?: string;
  concepts: Concept[];
  relations: Relation[];
  clusters?: Cluster[];
  axes?: Axis[];
  repertoires: Repertoire[];
  frameworks?: Framework[];
  theses?: Thesis[];
  arguments?: Thesis[];        // alias de compatibilidad
  cases: EvidenceCase[];
  scenarios?: Scenario[];
  meta?: Meta | null;
  pipeline_stats?: Record<string, unknown>;
  layer_status?: LayerStatus[];
  validation_report?: Record<string, unknown>;
  review_flags?: Record<string, unknown>;
  low_confidence_count?: number;
  truncated?: boolean;
}

interface Job {
  job_id: string; status: string; filename: string;
  result: JobResult | null; error: string | null;
}

type Tab = "diagnostico" | "conceptos" | "mapa" | "repertorios" | "debate" | "casos" | "plan";
type ReviewState = "pending" | "approved" | "rejected";

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

const CONF_CLASS: Record<string, string> = {
  alta: "bg-emerald-500/10 text-emerald-300 border-emerald-500/25",
  media: "bg-amber-500/10 text-amber-300 border-amber-500/25",
  baja: "bg-rose-500/10 text-rose-300 border-rose-500/25",
};

const DIFFICULTY_CLASS: Record<string, string> = {
  basico: "text-sky-300",
  intermedio: "text-violet-300",
  avanzado: "text-orange-300",
};

const RELATION_CLASS: Record<string, string> = {
  apoya: "text-emerald-300",
  contradice: "text-rose-300",
  matiza: "text-amber-300",
  extiende: "text-sky-300",
  requiere: "text-violet-300",
  causa: "text-fuchsia-300",
  ejemplifica: "text-teal-300",
  generaliza: "text-indigo-300",
  contrasta: "text-orange-300",
};

const DISTANCE_CLASS: Record<string, string> = {
  cercana: "bg-sky-500/10 text-sky-300 border-sky-500/25",
  media: "bg-violet-500/10 text-violet-300 border-violet-500/25",
  lejana: "bg-emerald-500/10 text-emerald-300 border-emerald-500/25",
};

const STATUS_CLASS: Record<string, string> = {
  ok: "bg-emerald-500/10 text-emerald-300 border-emerald-500/30",
  empty: "bg-gray-700/30 text-gray-400 border-gray-600/40",
  skipped: "bg-gray-700/30 text-gray-400 border-gray-600/40",
  failed: "bg-rose-500/15 text-rose-300 border-rose-500/40",
};

const LAYER_LABEL: Record<string, string> = {
  segmentation: "Segmentación",
  layer1_concepts: "Conceptos",
  layer1c_canonical: "Depuración",
  layer1b_enrichment: "Profundización",
  layer2_relations: "Relaciones",
  layer2b_axes: "Ejes",
  layer3_repertoires: "Intuiciones",
  layer4_arguments: "Debate",
  layer5_cases: "Casos",
  layer5b_scenarios: "Variantes",
  layer6_meta: "Plan",
};

const DIMENSION_LABEL: Record<string, string> = {
  recuperacion: "Recuperación",
  relacion: "Relación",
  transferencia: "Transferencia",
  "transferencia:lejana": "Transferencia lejana",
  "relacion:argumento": "Relación sobre argumentos",
  "relacion:espacio_atributos": "Espacio de atributos",
  anclaje: "Anclaje",
  automatizacion: "Automatización",
  calibracion: "Calibración",
  srl_planeacion: "Planeación",
  srl_accion: "Acción reguladora",
  srl_autorreflexion: "Autorreflexión",
  articulacion: "Articulación",
  persistencia: "Persistencia",
  engagement: "Compromiso",
};

const FAMILY_LABEL: Record<string, string> = {
  A: "Recuperar", B: "Discriminar", C: "Relacionar", D: "Estructurar",
  E: "Transferir", F: "Producir", G: "Calibrar", H: "Colaborar", I: "Regular",
};

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

/** Rail de capas: es el esqueleto del pipeline y también el diagnóstico.
 *  Distingue "el paper no traía esto" de "la extracción falló", que en una
 *  lista vacía se ven igual y significan cosas opuestas. */
function LayerRail({ layers }: { layers: LayerStatus[] }) {
  if (!layers.length) return null;
  return (
    <div className="flex flex-wrap gap-1.5">
      {layers.map((l) => (
        <div
          key={l.layer}
          title={l.detail || `${l.status} · ${l.items}`}
          className={`flex items-center gap-1.5 rounded border px-2 py-1 text-[11px] ${STATUS_CLASS[l.status] ?? STATUS_CLASS.empty}`}
        >
          <span>{LAYER_LABEL[l.layer] ?? l.layer}</span>
          <span className="font-mono opacity-70">{l.items}</span>
        </div>
      ))}
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
   Página
   ──────────────────────────────────────────────────────────── */

export default function ReviewPage() {
  const { id } = useParams<{ id: string }>();
  const [job, setJob] = useState<Job | null>(null);
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState<Tab>("diagnostico");
  const [onlyLow, setOnlyLow] = useState(false);
  const [query, setQuery] = useState("");
  const [reviews, setReviews] = useState<Record<string, ReviewState>>({});

  const backendUrl = process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:7860";

  useEffect(() => {
    let cancelled = false;
    async function fetchJob() {
      try {
        const res = await fetch(`${backendUrl}/jobs/${id}`);
        const data: Job = await res.json();
        if (cancelled) return;
        setJob(data);

        const initial: Record<string, ReviewState> = {};
        if (data.result) {
          data.result.concepts?.forEach((c) => {
            if (conf(c.confidence_extraction) >= 0.75) initial[c.id] = "approved";
          });
          data.result.repertoires?.forEach((r) => {
            if (conf(r.confidence_extraction) >= 0.75) initial[r.id] = "approved";
          });
        }
        setReviews(initial);
      } catch {
        if (!cancelled) setJob(null);
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    fetchJob();
    return () => { cancelled = true; };
  }, [id, backendUrl]);

  const setReview = (itemId: string, state: ReviewState) =>
    setReviews((prev) => ({ ...prev, [itemId]: state }));

  const result = job?.result ?? null;

  const conceptById = useMemo(() => {
    const map: Record<string, Concept> = {};
    result?.concepts?.forEach((c) => { map[c.id] = c; });
    return map;
  }, [result]);

  const name = (cid?: string | null) => (cid ? conceptById[cid]?.title ?? cid : "—");

  if (loading) {
    return <Centered><Spinner /><p className="text-sm text-gray-400">Cargando resultados…</p></Centered>;
  }

  if (!result) {
    return (
      <Centered>
        <p className="text-rose-300">{job?.error ?? "No hay resultados para este trabajo."}</p>
        <a href="/upload" className="text-sm text-indigo-400 underline">Subir otro documento</a>
      </Centered>
    );
  }

  const theses: Thesis[] = result.theses?.length ? result.theses : (result.arguments ?? []);
  const scenarios = result.scenarios ?? [];
  const layers = result.layer_status ?? [];
  const failed = layers.filter((l) => l.status === "failed");
  const meta = result.meta ?? null;

  const matches = (text: string) =>
    !query.trim() || text.toLowerCase().includes(query.trim().toLowerCase());

  const concepts = result.concepts.filter(
    (c) => (!onlyLow || conf(c.confidence_extraction) < 0.5) && matches(`${c.title} ${c.definition}`),
  );

  const TABS: { key: Tab; label: string; count?: number }[] = [
    { key: "diagnostico", label: "Diagnóstico" },
    { key: "conceptos", label: "Conceptos", count: result.concepts.length },
    { key: "mapa", label: "Mapa", count: result.relations.length },
    { key: "repertorios", label: "Intuiciones", count: result.repertoires.length },
    { key: "debate", label: "Debate", count: theses.length },
    { key: "casos", label: "Casos", count: result.cases.length + scenarios.length },
    { key: "plan", label: "Plan", count: meta?.signal_coverage?.length },
  ];

  return (
    <main className="min-h-screen bg-[#0F0F13] text-white">
      {/* ── Encabezado ── */}
      <header className="border-b border-gray-800 px-4 py-4 sm:px-6">
        <div className="mx-auto max-w-6xl space-y-3">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="min-w-0">
              <p className="text-[11px] uppercase tracking-widest text-gray-500">Revisión de materia prima</p>
              <h1 className="truncate text-lg font-semibold">{result.source_filename}</h1>
              <p className="mt-0.5 font-mono text-[11px] text-gray-600">
                esquema {result.schema_version ?? "1.x"} · {result.concepts.length} conceptos ·{" "}
                {result.relations.length} relaciones
              </p>
            </div>
            <a href="/upload" className="shrink-0 rounded border border-gray-700 px-3 py-1.5 text-xs text-gray-300 hover:border-gray-600 hover:text-white">
              Subir otro
            </a>
          </div>
          <LayerRail layers={layers} />
          {failed.length > 0 && (
            <div className="rounded border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">
              Fallaron {failed.length} {failed.length === 1 ? "capa" : "capas"}:{" "}
              {failed.map((f) => LAYER_LABEL[f.layer] ?? f.layer).join(", ")}. Lo que falta abajo no es
              lo que el documento no tenía, es lo que no se pudo extraer.
            </div>
          )}
        </div>
      </header>

      {/* ── Pestañas ── */}
      <nav className="sticky top-0 z-10 border-b border-gray-800 bg-[#0F0F13]/95 px-4 backdrop-blur sm:px-6">
        <div className="mx-auto flex max-w-6xl gap-1 overflow-x-auto">
          {TABS.map((t) => (
            <button
              key={t.key}
              onClick={() => setTab(t.key)}
              aria-current={tab === t.key ? "page" : undefined}
              className={`whitespace-nowrap border-b-2 px-3 py-2.5 text-sm transition focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-400 ${
                tab === t.key
                  ? "border-indigo-400 text-white"
                  : "border-transparent text-gray-500 hover:text-gray-300"
              }`}
            >
              {t.label}
              {t.count !== undefined && (
                <span className="ml-1.5 font-mono text-[11px] text-gray-600">{t.count}</span>
              )}
            </button>
          ))}
        </div>
      </nav>

      <div className="mx-auto max-w-6xl space-y-6 px-4 py-6 sm:px-6">
        {/* ── Diagnóstico ── */}
        {tab === "diagnostico" && (
          <Diagnostico result={result} layers={layers} />
        )}

        {/* ── Conceptos ── */}
        {tab === "conceptos" && (
          <>
            <div className="flex flex-wrap items-center gap-2">
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Buscar concepto…"
                className="min-w-0 flex-1 rounded border border-gray-800 bg-gray-900/60 px-3 py-1.5 text-sm placeholder:text-gray-600 focus:border-indigo-500 focus:outline-none"
              />
              <button
                onClick={() => setOnlyLow((v) => !v)}
                className={`rounded border px-3 py-1.5 text-xs transition ${
                  onlyLow ? "border-rose-500/40 bg-rose-500/10 text-rose-300" : "border-gray-700 text-gray-400"
                }`}
              >
                Solo confianza baja
              </button>
            </div>
            {concepts.length === 0 ? (
              <Empty>Ningún concepto coincide con el filtro.</Empty>
            ) : (
              <div className="space-y-2">
                {concepts.map((c) => (
                  <ConceptCard
                    key={c.id}
                    c={c}
                    name={name}
                    state={reviews[c.id] ?? "pending"}
                    onReview={setReview}
                  />
                ))}
              </div>
            )}
          </>
        )}

        {/* ── Mapa ── */}
        {tab === "mapa" && <Mapa result={result} name={name} />}

        {/* ── Intuiciones ── */}
        {tab === "repertorios" && (
          <Repertorios
            items={result.repertoires}
            name={name}
            reviews={reviews}
            onReview={setReview}
          />
        )}

        {/* ── Debate ── */}
        {tab === "debate" && (
          <Debate frameworks={result.frameworks ?? []} theses={theses} name={name} />
        )}

        {/* ── Casos ── */}
        {tab === "casos" && (
          <Casos cases={result.cases ?? []} scenarios={scenarios} name={name} />
        )}

        {/* ── Plan ── */}
        {tab === "plan" && <Plan meta={meta} name={name} />}
      </div>
    </main>
  );
}

/* ────────────────────────────────────────────────────────────
   Diagnóstico
   ──────────────────────────────────────────────────────────── */

function Diagnostico({ result, layers }: { result: JobResult; layers: LayerStatus[] }) {
  const stats = (result.pipeline_stats ?? {}) as Record<string, any>;
  const canon = stats.canonicalization as Record<string, any> | undefined;
  const timings = stats.timings_seconds as Record<string, number> | undefined;
  const usage = stats.model_usage as Record<string, any> | undefined;
  const flags = (result.review_flags ?? {}) as Record<string, any>;

  const counts: [string, number][] = [
    ["Conceptos", result.concepts?.length ?? 0],
    ["Relaciones", result.relations?.length ?? 0],
    ["Grupos", result.clusters?.length ?? 0],
    ["Ejes", result.axes?.length ?? 0],
    ["Intuiciones", result.repertoires?.length ?? 0],
    ["Marcos", result.frameworks?.length ?? 0],
    ["Tesis", (result.theses ?? result.arguments ?? []).length],
    ["Casos", result.cases?.length ?? 0],
    ["Variantes", result.scenarios?.length ?? 0],
  ];

  return (
    <div className="space-y-6">
      <div>
        <SectionTitle>Qué se extrajo</SectionTitle>
        <div className="grid grid-cols-3 gap-2 sm:grid-cols-5 lg:grid-cols-9">
          {counts.map(([label, n]) => (
            <Card key={label} className="p-3">
              <p className="font-mono text-xl">{n}</p>
              <p className="mt-0.5 text-[11px] text-gray-500">{label}</p>
            </Card>
          ))}
        </div>
      </div>

      {Boolean(flags.truncated || (flags.failed_layers as string[])?.length || result.low_confidence_count) && (
        <div>
          <SectionTitle>Avisos</SectionTitle>
          <div className="space-y-2 text-sm">
            {Boolean((flags.failed_layers as string[])?.length) && (
              <Card className="border-rose-500/30 bg-rose-500/5 text-rose-200">
                Capas que fallaron: {(flags.failed_layers as string[]).map((l) => LAYER_LABEL[l] ?? l).join(", ")}
              </Card>
            )}
            {flags.truncated ? (
              <Card className="border-amber-500/30 bg-amber-500/5 text-amber-200">
                El documento se recortó por presupuesto. Parte del texto no se leyó.
              </Card>
            ) : null}
            {Boolean(result.low_confidence_count) ? (
              <Card className="text-gray-300">
                <span className="font-mono">{result.low_confidence_count}</span> elementos con confianza
                baja. Revisalos primero en la pestaña Conceptos con el filtro activado.
              </Card>
            ) : null}
          </div>
        </div>
      )}

      {canon && (
        <div>
          <SectionTitle>Depuración de conceptos</SectionTitle>
          <Card className="space-y-3 text-sm">
            <p className="text-gray-300">
              <span className="font-mono text-white">{canon.input}</span> conceptos extraídos →{" "}
              <span className="font-mono text-white">{canon.output}</span> tras unificar variantes del
              mismo concepto.
            </p>
            {(canon.deterministic_fusions as any[])?.length > 0 && (
              <div>
                <p className="mb-1.5 text-xs uppercase tracking-wider text-gray-500">Se unificaron</p>
                <ul className="space-y-1">
                  {(canon.deterministic_fusions as any[]).map((f, i) => (
                    <li key={i} className="font-mono text-xs text-gray-400">
                      <span className="text-gray-200">{f.canonical_title ?? f.canonical}</span>
                      {" ← "}
                      {(f.absorbed ?? []).join(", ")}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {(canon.grupos_sobredimensionados as any[])?.length > 0 && (
              <div>
                <p className="mb-1.5 text-xs uppercase tracking-wider text-amber-400">
                  Sin unificar, para revisar a mano
                </p>
                <p className="mb-1.5 text-xs text-gray-500">
                  Grupos demasiado grandes para unificarlos sin riesgo de fundir conceptos distintos.
                </p>
                <ul className="space-y-1">
                  {(canon.grupos_sobredimensionados as string[][]).map((g, i) => (
                    <li key={i} className="font-mono text-xs text-gray-400">{g.join(" · ")}</li>
                  ))}
                </ul>
              </div>
            )}
            {(canon.acronimos_ambiguos as string[])?.length > 0 && (
              <p className="text-xs text-gray-500">
                Siglas usadas por más de un concepto:{" "}
                <span className="font-mono text-gray-300">{(canon.acronimos_ambiguos as string[]).join(", ")}</span>
              </p>
            )}
          </Card>
        </div>
      )}

      {layers.length > 0 && (
        <div>
          <SectionTitle>Estado por capa</SectionTitle>
          <Card className="divide-y divide-gray-800 p-0">
            {layers.map((l) => (
              <div key={l.layer} className="flex flex-wrap items-start gap-x-3 gap-y-1 px-4 py-2.5 text-sm">
                <span className="w-32 shrink-0 text-gray-300">{LAYER_LABEL[l.layer] ?? l.layer}</span>
                <Chip className={STATUS_CLASS[l.status] ?? STATUS_CLASS.empty}>{l.status}</Chip>
                <span className="font-mono text-xs text-gray-500">{l.items}</span>
                {l.detail && <span className="w-full text-xs text-gray-500 sm:w-auto sm:flex-1">{l.detail}</span>}
              </div>
            ))}
          </Card>
        </div>
      )}

      {timings && (
        <div>
          <SectionTitle>Tiempos</SectionTitle>
          <Card>
            <div className="grid grid-cols-2 gap-x-6 gap-y-1.5 text-sm sm:grid-cols-3">
              {Object.entries(timings).map(([k, v]) => (
                <div key={k} className="flex items-baseline justify-between gap-2">
                  <span className="text-gray-400">{LAYER_LABEL[k] ?? k}</span>
                  <span className="font-mono text-xs text-gray-300">{v}s</span>
                </div>
              ))}
            </div>
          </Card>
        </div>
      )}

      {usage && Object.keys(usage).length > 0 && (
        <div>
          <SectionTitle>Uso por modelo</SectionTitle>
          <Card className="divide-y divide-gray-800 p-0">
            {Object.entries(usage).map(([model, u]: [string, any]) => (
              <div key={model} className="flex flex-wrap items-baseline gap-x-4 px-4 py-2 text-xs">
                <span className="font-mono text-gray-300">{model}</span>
                <span className="text-gray-500">{u.llamadas} llamadas</span>
                <span className="text-gray-500">{u.espera_s}s de espera</span>
                {u.rechazos_429 > 0 && (
                  <span className="text-amber-400">{u.rechazos_429} rechazos por cuota</span>
                )}
              </div>
            ))}
          </Card>
        </div>
      )}
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

/* ────────────────────────────────────────────────────────────
   Plan
   ──────────────────────────────────────────────────────────── */

function Plan({ meta, name }: { meta: Meta | null; name: (id?: string | null) => string }) {
  if (!meta) return <Empty>No se calculó el plan pedagógico.</Empty>;

  const densities: [string, number | undefined][] = [
    ["Conexiones", meta.relational_density],
    ["Casos", meta.case_density],
    ["Debate", meta.argumentative_richness],
    ["Intuiciones", meta.repertoire_density],
    ["Conceptos profundizados", meta.enrichment_coverage],
  ];

  return (
    <div className="space-y-6">
      <div>
        <SectionTitle>Qué tan rico es este documento</SectionTitle>
        <Card className="space-y-2.5">
          {densities.map(([label, v]) => (
            <div key={label} className="flex items-center gap-3">
              <span className="w-44 shrink-0 text-sm text-gray-300">{label}</span>
              <div className="flex-1"><Bar value={v ?? 0} tone="auto" /></div>
              <span className="w-9 shrink-0 text-right font-mono text-[11px] text-gray-600">{pct(v)}</span>
            </div>
          ))}
        </Card>
      </div>

      {(meta.signal_coverage?.length ?? 0) > 0 && (
        <div>
          <SectionTitle>Qué se va a poder medir</SectionTitle>
          <p className="mb-3 -mt-1 text-xs text-gray-500">
            Las habilidades con cobertura baja van a quedar casi vacías en el perfil de los estudiantes.
            Al lado está el motivo.
          </p>
          <Card className="divide-y divide-gray-800 p-0">
            {meta.signal_coverage!.map((s) => (
              <div key={s.dimension} className="px-4 py-2.5">
                <div className="flex items-center gap-3">
                  <span className="w-48 shrink-0 text-sm text-gray-300">
                    {DIMENSION_LABEL[s.dimension] ?? s.dimension}
                  </span>
                  <div className="flex-1"><Bar value={s.cobertura} tone="auto" /></div>
                  <span className="w-9 shrink-0 text-right font-mono text-[11px] text-gray-600">
                    {pct(s.cobertura)}
                  </span>
                </div>
                {s.cuello_de_botella && (
                  <p className="mt-1.5 text-xs text-amber-300/80 sm:pl-[12.75rem]">{s.cuello_de_botella}</p>
                )}
              </div>
            ))}
          </Card>
        </div>
      )}

      {(meta.family_availability?.length ?? 0) > 0 && (
        <div>
          <SectionTitle>Actividades disponibles</SectionTitle>
          <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
            {meta.family_availability!.map((f) => (
              <Card key={f.family} className={f.available ? "" : "opacity-60"}>
                <div className="flex items-center gap-2">
                  <span className="font-mono text-xs text-gray-600">{f.family}</span>
                  <span className="text-sm font-medium">{FAMILY_LABEL[f.family] ?? f.family}</span>
                  <Chip className={f.available ? STATUS_CLASS.ok : STATUS_CLASS.empty}>
                    {f.available ? "disponible" : "no disponible"}
                  </Chip>
                </div>
                {f.mechanic_ids.length > 0 && (
                  <p className="mt-1.5 font-mono text-[11px] text-gray-600">{f.mechanic_ids.join(" · ")}</p>
                )}
                {!f.available && f.reason && <p className="mt-1.5 text-xs text-gray-500">{f.reason}</p>}
              </Card>
            ))}
          </div>
        </div>
      )}

      {(meta.suggested_sequence?.length ?? 0) > 0 && (
        <div>
          <SectionTitle count={meta.suggested_sequence!.length}>Orden de estudio sugerido</SectionTitle>
          <Card>
            <ol className="space-y-1">
              {meta.suggested_sequence!.map((cid, i) => {
                const prereqs = meta.prerequisite_graph?.[cid] ?? [];
                return (
                  <li key={cid} className="flex items-baseline gap-3 text-sm">
                    <span className="w-6 shrink-0 text-right font-mono text-xs text-gray-600">{i + 1}</span>
                    <span className="text-gray-200">{name(cid)}</span>
                    {prereqs.length > 0 && (
                      <span className="text-xs text-gray-600">
                        después de {prereqs.map((p) => name(p)).join(", ")}
                      </span>
                    )}
                  </li>
                );
              })}
            </ol>
          </Card>
        </div>
      )}
    </div>
  );
}
