"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";

// ── Tipos ────────────────────────────────────────────────────
interface Concept {
  id: string;
  title: string;
  definition: string;
  tipo: string;
  difficulty: string;
  importance: number;
  is_gateway: boolean;
  is_threshold: boolean;
  confidence_extraction: "alta" | "media" | "baja";
  source_pages: number[];
  // Enriquecidos
  is_enriched?: boolean;
  core_definition?: string;
  subdimensions?: { name: string; description: string }[];
  distinctions?: { from_concept: string; difference: string }[];
  measurement_approach?: string;
  theoretical_role?: string;
  key_tensions?: string[];
  evolution_in_paper?: string;
}

interface Relation {
  from_concept_id: string;
  to_concept_id: string;
  relation_type: string;
  description: string;
  confidence_extraction: "alta" | "media" | "baja";
}

interface Repertoire {
  id: string;
  concept_id: string;
  label: string;
  description: string;
  example: string;
  origin: string;
  status: string;
  confidence_extraction: "alta" | "media" | "baja";
}

interface JobResult {
  course_id: string;
  source_filename: string;
  extracted_at: string;
  concepts: Concept[];
  relations: Relation[];
  repertoires: Repertoire[];
  pipeline_stats: Record<string, number>;
  low_confidence_count: number;
}

interface Job {
  job_id: string;
  status: string;
  filename: string;
  result: JobResult | null;
  error: string | null;
}

type Tab = "conceptos" | "relaciones" | "repertorios";
type ReviewState = "pending" | "approved" | "rejected";

// ── Helpers ──────────────────────────────────────────────────
const CONFIDENCE_COLORS = {
  alta:  "bg-green-500/10 text-green-400 border-green-500/20",
  media: "bg-yellow-500/10 text-yellow-400 border-yellow-500/20",
  baja:  "bg-red-500/10 text-red-400 border-red-500/20",
};

const DIFFICULTY_COLORS = {
  basico:      "text-blue-400",
  intermedio:  "text-purple-400",
  avanzado:    "text-orange-400",
};

const RELATION_COLORS: Record<string, string> = {
  apoya:      "text-green-400",
  contradice: "text-red-400",
  matiza:     "text-yellow-400",
  extiende:   "text-blue-400",
  requiere:   "text-purple-400",
};

// ── Componente principal ─────────────────────────────────────
export default function ReviewPage() {
  const { id } = useParams<{ id: string }>();
  const [job, setJob] = useState<Job | null>(null);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState<Tab>("conceptos");
  const [filter, setFilter] = useState<"todos" | "baja">("baja");
  const [reviews, setReviews] = useState<Record<string, ReviewState>>({});

  const backendUrl = process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:7860";

  useEffect(() => {
    async function fetchJob() {
      try {
        const res = await fetch(`${backendUrl}/jobs/${id}`);
        const data = await res.json();
        setJob(data);
  
        // Auto-aprobar elementos de confianza alta
        const initial: Record<string, ReviewState> = {};
        if (data.result) {
          data.result.concepts.forEach((c: Concept) => {
            if (c.confidence_extraction === "alta") initial[c.id] = "approved";
          });
          data.result.relations.forEach((r: Relation, i: number) => {
            if (r.confidence_extraction === "alta") initial[`rel_${i}`] = "approved";
          });
          data.result.repertoires.forEach((r: Repertoire) => {
            if (r.confidence_extraction === "alta") initial[r.id] = "approved";
          });
        }
        setReviews(initial);
  
      } catch {
        // silenciar
      } finally {
        setLoading(false);
      }
    }
    fetchJob();
  }, [id, backendUrl]);

  const setReview = (itemId: string, state: ReviewState) => {
    setReviews(prev => ({ ...prev, [itemId]: state }));
  };

  if (loading) {
    return <Centered><Spinner />Cargando resultados...</Centered>;
  }

  if (!job || !job.result) {
    return (
      <Centered>
        <p className="text-red-400">
          {job?.error ?? "No se encontraron resultados para este job."}
        </p>
        <a href="/upload" className="mt-4 text-sm text-indigo-400 underline">
          Volver a subir
        </a>
      </Centered>
    );
  }

  const { result } = job;

  const approvedCount = Object.values(reviews).filter(v => v === "approved").length;
  const rejectedCount = Object.values(reviews).filter(v => v === "rejected").length;
  const totalItems = result.concepts.length + result.relations.length + result.repertoires.length;

  const filteredConcepts = filter === "baja"
    ? result.concepts.filter(c => c.confidence_extraction === "baja")
    : result.concepts;

  const filteredRelations = filter === "baja"
    ? result.relations.filter(r => r.confidence_extraction === "baja")
    : result.relations;

  const filteredRepertoires = filter === "baja"
    ? result.repertoires.filter(r => r.confidence_extraction === "baja")
    : result.repertoires;

  return (
    <main className="min-h-screen bg-[#0F0F13] text-white">

      {/* Header */}
      <div className="border-b border-gray-800 px-6 py-4">
        <div className="max-w-5xl mx-auto flex items-start justify-between">
          <div>
            <p className="text-xs text-gray-500 mb-1">Revisión de extracción</p>
            <h1 className="text-xl font-medium">{result.source_filename}</h1>
            <p className="text-sm text-gray-400 mt-1">
              {result.concepts.length} conceptos · {result.relations.length} relaciones · {result.repertoires.length} repertorios
            </p>
          </div>

          {/* Stats */}
          <div className="flex gap-3 text-sm">
            <div className="bg-green-500/10 border border-green-500/20 rounded-lg px-3 py-2 text-center">
              <p className="text-green-400 font-medium">{approvedCount}</p>
              <p className="text-green-500/70 text-xs">aprobados</p>
            </div>
            <div className="bg-red-500/10 border border-red-500/20 rounded-lg px-3 py-2 text-center">
              <p className="text-red-400 font-medium">{rejectedCount}</p>
              <p className="text-red-500/70 text-xs">descartados</p>
            </div>
            <div className="bg-gray-800 rounded-lg px-3 py-2 text-center">
              <p className="text-gray-300 font-medium">{totalItems - approvedCount - rejectedCount}</p>
              <p className="text-gray-500 text-xs">pendientes</p>
            </div>
          </div>
        </div>
      </div>

      <div className="max-w-5xl mx-auto px-6 py-6">

        {/* Alerta de baja confianza */}
        {result.low_confidence_count > 0 && (
          <div className="mb-6 bg-yellow-500/10 border border-yellow-500/20 rounded-xl p-4 flex items-start gap-3">
            <span className="text-yellow-400 text-lg">⚠</span>
            <div>
              <p className="text-yellow-300 text-sm font-medium">
                {result.low_confidence_count} elementos con confianza baja
              </p>
              <p className="text-yellow-400/70 text-xs mt-0.5">
                Revísalos antes de habilitar las actividades para estudiantes.
              </p>
            </div>
          </div>
        )}

        {/* Tabs + filtro */}
        <div className="flex items-center justify-between mb-4">
          <div className="flex gap-1 bg-gray-900 rounded-lg p-1">
            {(["conceptos", "relaciones", "repertorios"] as Tab[]).map(tab => (
              <button
                key={tab}
                onClick={() => setActiveTab(tab)}
                className={`px-4 py-1.5 rounded-md text-sm transition-all capitalize ${
                  activeTab === tab
                    ? "bg-indigo-600 text-white"
                    : "text-gray-400 hover:text-white"
                }`}
              >
                {tab}
                <span className="ml-2 text-xs opacity-60">
                  {tab === "conceptos" && result.concepts.length}
                  {tab === "relaciones" && result.relations.length}
                  {tab === "repertorios" && result.repertoires.length}
                </span>
              </button>
            ))}
          </div>

          <button
            onClick={() => setFilter(f => f === "baja" ? "todos" : "baja")}
            className={`text-xs px-3 py-1.5 rounded-lg border transition-all ${
              filter === "baja"
                ? "bg-red-500/10 border-red-500/20 text-red-400"
                : "bg-gray-900 border-gray-700 text-gray-400"
            }`}
          >
            {filter === "baja" ? "Mostrando: confianza baja" : "Mostrando: todos"}
          </button>
        </div>

        {/* Contenido por tab */}
        {activeTab === "conceptos" && (
          <div className="space-y-3">
            {filteredConcepts.length === 0 && (
              <Empty mensaje="No hay conceptos con confianza baja." />
            )}
            {filteredConcepts.map(concept => (
              <ConceptCard
                key={concept.id}
                concept={concept}
                review={reviews[concept.id]}
                onReview={(state) => setReview(concept.id, state)}
              />
            ))}
          </div>
        )}

        {activeTab === "relaciones" && (
          <div className="space-y-3">
            {filteredRelations.length === 0 && (
              <Empty mensaje="No hay relaciones con confianza baja." />
            )}
            {filteredRelations.map((rel, i) => (
              <RelationCard
                key={i}
                relation={rel}
                review={reviews[`rel_${i}`]}
                onReview={(state) => setReview(`rel_${i}`, state)}
              />
            ))}
          </div>
        )}

        {activeTab === "repertorios" && (
          <div className="space-y-3">
            {filteredRepertoires.length === 0 && (
              <Empty mensaje="No hay repertorios con confianza baja." />
            )}
            {filteredRepertoires.map(rep => (
              <RepertoireCard
                key={rep.id}
                repertoire={rep}
                review={reviews[rep.id]}
                onReview={(state) => setReview(rep.id, state)}
              />
            ))}
          </div>
        )}

      </div>
    </main>
  );
}

// ── Cards ────────────────────────────────────────────────────

function ConceptCard({ concept, review, onReview }: {
  concept: Concept;
  review?: ReviewState;
  onReview: (s: ReviewState) => void;
}) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className={`rounded-xl border transition-all ${
      review === "approved" ? "border-green-500/30 bg-green-500/5" :
      review === "rejected" ? "border-red-500/30 bg-red-500/5 opacity-50" :
      "border-gray-800 bg-gray-900/50"
    }`}>
      {/* Header siempre visible */}
      <div className="flex items-start justify-between gap-4 p-4">
        <div className="flex-1">
          <div className="flex items-center gap-2 mb-1">
            <h3 className="font-medium">{concept.title}</h3>
            {concept.is_gateway && (
              <span className="text-xs bg-indigo-500/10 text-indigo-400 border border-indigo-500/20 px-2 py-0.5 rounded-full">puerta</span>
            )}
            {concept.is_threshold && (
              <span className="text-xs bg-purple-500/10 text-purple-400 border border-purple-500/20 px-2 py-0.5 rounded-full">umbral</span>
            )}
            {concept.is_enriched && (
              <span className="text-xs bg-blue-500/10 text-blue-400 border border-blue-500/20 px-2 py-0.5 rounded-full">enriquecido</span>
            )}
          </div>
          <p className="text-sm text-gray-400 mb-2">
            {concept.core_definition ?? concept.definition}
          </p>
          <div className="flex items-center gap-3 text-xs">
            <span className={DIFFICULTY_COLORS[concept.difficulty as keyof typeof DIFFICULTY_COLORS] ?? "text-gray-400"}>
              {concept.difficulty}
            </span>
            <span className="text-gray-600">·</span>
            <span className="text-gray-500">{concept.tipo}</span>
            <span className="text-gray-600">·</span>
            <span className="text-gray-500">importancia {Math.round(concept.importance * 100)}%</span>
            {concept.source_pages?.length > 0 && (
              <>
                <span className="text-gray-600">·</span>
                <span className="text-gray-500">p. {concept.source_pages.join(", ")}</span>
              </>
            )}
          </div>
        </div>
        <div className="flex flex-col items-end gap-2">
          <span className={`text-xs px-2 py-0.5 rounded-full border ${CONFIDENCE_COLORS[concept.confidence_extraction]}`}>
            {concept.confidence_extraction}
          </span>
          <ReviewButtons review={review} onReview={onReview} />
          {concept.is_enriched && (
            <button
              onClick={() => setExpanded(e => !e)}
              className="text-xs text-gray-500 hover:text-gray-300 transition-colors mt-1"
            >
              {expanded ? "▲ menos" : "▼ más"}
            </button>
          )}
        </div>
      </div>

      {/* Detalle expandido */}
      {expanded && concept.is_enriched && (
        <div className="border-t border-gray-800 p-4 space-y-4">

          {(concept.subdimensions ?? []).length > 0 && (
            <div>
              <p className="text-xs text-gray-500 uppercase tracking-wider mb-2">Subdimensiones</p>
              <div className="space-y-1">
                {(concept.subdimensions ?? []).map((s, i) => (
                  <div key={i} className="text-sm">
                    <span className="text-indigo-400">{s.name}</span>
                    <span className="text-gray-500"> — {s.description}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {(concept.distinctions ?? []).length > 0 && (
            <div>
              <p className="text-xs text-gray-500 uppercase tracking-wider mb-2">Distinciones</p>
              <div className="space-y-1">
                {(concept.distinctions ?? []).map((d, i) => (
                  <div key={i} className="text-sm">
                    <span className="text-yellow-400">{d.from_concept}</span>
                    <span className="text-gray-500"> → {d.difference}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {concept.theoretical_role && (
            <div>
              <p className="text-xs text-gray-500 uppercase tracking-wider mb-1">Rol teórico</p>
              <p className="text-sm text-gray-400">{concept.theoretical_role}</p>
            </div>
          )}

          {concept.measurement_approach && (
            <div>
              <p className="text-xs text-gray-500 uppercase tracking-wider mb-1">Cómo se mide</p>
              <p className="text-sm text-gray-400">{concept.measurement_approach}</p>
            </div>
          )}

          {(concept.key_tensions ?? []).length > 0 && (
            <div>
              <p className="text-xs text-gray-500 uppercase tracking-wider mb-2">Tensiones clave</p>
              <ul className="space-y-1">
                {(concept.key_tensions ?? []).map((t, i) => (
                  <li key={i} className="text-sm text-gray-400 flex gap-2">
                    <span className="text-red-400 mt-0.5">⚡</span>{t}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {concept.evolution_in_paper && (
            <div>
              <p className="text-xs text-gray-500 uppercase tracking-wider mb-1">Evolución en el texto</p>
              <p className="text-sm text-gray-400 italic border-l-2 border-gray-700 pl-3">
                {concept.evolution_in_paper}
              </p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function RelationCard({ relation, review, onReview }: {
  relation: Relation;
  review?: ReviewState;
  onReview: (s: ReviewState) => void;
}) {
  return (
    <div className={`rounded-xl border p-4 transition-all ${
      review === "approved" ? "border-green-500/30 bg-green-500/5" :
      review === "rejected" ? "border-red-500/30 bg-red-500/5 opacity-50" :
      "border-gray-800 bg-gray-900/50"
    }`}>
      <div className="flex items-start justify-between gap-4">
        <div className="flex-1">
          <div className="flex items-center gap-2 mb-1 text-sm">
            <span className="text-gray-300">{relation.from_concept_id}</span>
            <span className={`font-medium ${RELATION_COLORS[relation.relation_type] ?? "text-gray-400"}`}>
              → {relation.relation_type} →
            </span>
            <span className="text-gray-300">{relation.to_concept_id}</span>
          </div>
          <p className="text-sm text-gray-400">{relation.description}</p>
        </div>
        <div className="flex flex-col items-end gap-2">
          <span className={`text-xs px-2 py-0.5 rounded-full border ${CONFIDENCE_COLORS[relation.confidence_extraction]}`}>
            {relation.confidence_extraction}
          </span>
          <ReviewButtons review={review} onReview={onReview} />
        </div>
      </div>
    </div>
  );
}

function RepertoireCard({ repertoire, review, onReview }: {
  repertoire: Repertoire;
  review?: ReviewState;
  onReview: (s: ReviewState) => void;
}) {
  return (
    <div className={`rounded-xl border p-4 transition-all ${
      review === "approved" ? "border-green-500/30 bg-green-500/5" :
      review === "rejected" ? "border-red-500/30 bg-red-500/5 opacity-50" :
      "border-gray-800 bg-gray-900/50"
    }`}>
      <div className="flex items-start justify-between gap-4">
        <div className="flex-1">
          <div className="flex items-center gap-2 mb-1">
            <h3 className="font-medium text-sm">{repertoire.label}</h3>
            <span className="text-xs bg-gray-800 text-gray-400 px-2 py-0.5 rounded-full">
              {repertoire.origin === "inferido_por_llm" ? "inferido" : "documentado"}
            </span>
            <span className="text-xs text-gray-500">→ {repertoire.concept_id}</span>
          </div>
          <p className="text-sm text-gray-400 mb-2">{repertoire.description}</p>
          {repertoire.example && (
            <p className="text-xs text-gray-500 italic border-l-2 border-gray-700 pl-3">
              {repertoire.example}
            </p>
          )}
        </div>
        <div className="flex flex-col items-end gap-2">
          <span className={`text-xs px-2 py-0.5 rounded-full border ${CONFIDENCE_COLORS[repertoire.confidence_extraction]}`}>
            {repertoire.confidence_extraction}
          </span>
          <ReviewButtons review={review} onReview={onReview} />
        </div>
      </div>
    </div>
  );
}

// ── Sub-componentes ──────────────────────────────────────────

function ReviewButtons({ review, onReview }: {
  review?: ReviewState;
  onReview: (s: ReviewState) => void;
}) {
  return (
    <div className="flex gap-1">
      <button
        onClick={() => onReview(review === "approved" ? "pending" : "approved")}
        className={`w-7 h-7 rounded-lg flex items-center justify-center text-sm transition-all ${
          review === "approved"
            ? "bg-green-500 text-white"
            : "bg-gray-800 text-gray-400 hover:bg-green-500/20 hover:text-green-400"
        }`}
      >✓</button>
      <button
        onClick={() => onReview(review === "rejected" ? "pending" : "rejected")}
        className={`w-7 h-7 rounded-lg flex items-center justify-center text-sm transition-all ${
          review === "rejected"
            ? "bg-red-500 text-white"
            : "bg-gray-800 text-gray-400 hover:bg-red-500/20 hover:text-red-400"
        }`}
      >✕</button>
    </div>
  );
}

function Empty({ mensaje }: { mensaje: string }) {
  return (
    <div className="text-center py-12 text-gray-500 text-sm">{mensaje}</div>
  );
}

function Spinner() {
  return (
    <div className="w-8 h-8 rounded-full border-2 border-indigo-500/30 border-t-indigo-400 animate-spin mb-4" />
  );
}

function Centered({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen bg-[#0F0F13] flex flex-col items-center justify-center text-white">
      {children}
    </div>
  );
}
