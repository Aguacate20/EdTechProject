"use client";

import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import { useParams, useRouter, useSearchParams } from "next/navigation";

/* ────────────────────────────────────────────────────────────
   Sesión de estudio o evaluación.

   Una sola página para los dos modos, porque la diferencia no está en la
   interfaz sino en lo que el servidor manda: en aprendizaje llegan pasos de
   exposición, botón de pista y retroalimentación inmediata; en evaluación no
   llega nada de eso y aparece el cronómetro. La página se limita a mostrar lo
   que recibe.
   ──────────────────────────────────────────────────────────── */

interface Opcion { id: string; texto: string }

interface Paso {
  // Los cuatro tipos que no son ejercicio son envolturas metacognitivas:
  // producen calibración, planeación y autorreflexión, que son tres
  // dimensiones del perfil que ninguna pregunta de contenido puede medir.
  tipo: "exposicion" | "ejercicio" | "calibracion" | "planeacion" | "reflexion";
  requiere_respuesta: boolean;
  concept_id: string;
  // exposición
  titulo?: string;
  definicion?: string;
  subdimensiones?: { name: string; description: string }[];
  carga_cognitiva?: string[];
  // ejercicio
  paso_ciclo?: string;
  mechanic_id?: string;
  item_id?: string;
  enunciado?: string;
  afirmacion?: string;
  par?: string[];
  opciones?: Opcion[];
  formato?: string;
  variables_clave?: string[];
  dominio?: string;
  pista_disponible?: boolean;
  andamiaje?: Record<string, boolean>;
  ayuda?: string;
}

interface Feedback {
  tipo: string;
  mensaje?: string;
  nota?: string;
  donde_funciona?: string;
  correcta?: string;
  resolucion_esperada?: string;
}

interface Respuesta {
  correcto: boolean | null;
  feedback: Feedback | null;
  senales_emitidas: { dimension: string; forma: string }[];
  indice: number;
  terminada: boolean;
}

const CARGA_LABEL: Record<string, string> = {
  memorizar: "hay bastante que retener",
  discriminar: "se confunde con otro concepto",
  integrar: "hay que sostener varias piezas a la vez",
  inferir: "no basta con recordarlo, hay que deducir",
};

const MECANICA_LABEL: Record<string, string> = {
  A1: "Reconocer", A3: "Evocar", B1: "Distinguir", B2: "Clasificar",
  C1: "Conectar", E1: "Predecir", E3: "Aplicar",
  G1: "Calibrar", I1: "Planear", I4: "Reflexionar",
};

const META_TITULO: Record<string, string> = {
  calibracion: "Antes de responder",
  planeacion: "Planificá tu sesión",
  reflexion: "Para cerrar",
};

/* Mismo caso que /upload: esta página lee `?student=` de la URL, así que
   necesita su límite de Suspense para poder pre-renderizarse. */

export default function SesionPage() {
  return (
    <Suspense
      fallback={
        <main className="flex min-h-screen items-center justify-center bg-[#0F0F13] text-sm text-gray-500">
          Cargando…
        </main>
      }
    >
      <SesionInner />
    </Suspense>
  );
}

function SesionInner() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const params = useSearchParams();
  const backendUrl = process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:7860";
  const studentId = params.get("student") ?? "";

  const [paso, setPaso] = useState<Paso | null>(null);
  const [indice, setIndice] = useState(0);
  const [total, setTotal] = useState(0);
  const [modo, setModo] = useState<string>("aprendizaje");
  const [seleccion, setSeleccion] = useState<string>("");
  const [texto, setTexto] = useState("");
  const [respuesta, setRespuesta] = useState<Respuesta | null>(null);
  const [pista, setPista] = useState<string | null>(null);
  const [cargando, setCargando] = useState(true);
  const [terminada, setTerminada] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inicioRef = useRef<number>(Date.now());

  const cargarPaso = useCallback(async () => {
    setCargando(true);
    setError(null);
    try {
      const r = await fetch(`${backendUrl}/sessions/${id}/next`);
      const d = await r.json();
      if (d.terminada) { setTerminada(true); return; }
      setPaso(d.paso);
      setIndice(d.indice);
      setTotal(d.total_pasos);
      setModo(d.modo);
      setSeleccion(""); setTexto(""); setRespuesta(null); setPista(null);
      inicioRef.current = Date.now();
    } catch {
      setError("No se pudo cargar el siguiente paso.");
    } finally {
      setCargando(false);
    }
  }, [backendUrl, id]);

  useEffect(() => { cargarPaso(); }, [cargarPaso]);

  async function enviar() {
    if (!paso) return;
    const valor = paso.formato === "texto_libre" ? texto : seleccion;
    if (!valor) return;
    setCargando(true);
    try {
      const r = await fetch(`${backendUrl}/sessions/${id}/answer`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          respuesta: valor,
          duration_ms: Date.now() - inicioRef.current,
        }),
      });
      const d: Respuesta = await r.json();
      setRespuesta(d);
      // En evaluación no hay retroalimentación: se avanza sin pausa.
      if (!d.feedback) {
        if (d.terminada) setTerminada(true); else await cargarPaso();
      }
    } catch {
      setError("No se pudo enviar la respuesta.");
    } finally {
      setCargando(false);
    }
  }

  async function avanzarExposicion() {
    setCargando(true);
    await fetch(`${backendUrl}/sessions/${id}/answer`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ respuesta: null }),
    });
    await cargarPaso();
  }

  async function responderMeta(valor: string) {
    setCargando(true);
    try {
      const r = await fetch(`${backendUrl}/sessions/${id}/answer`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ respuesta: valor, duration_ms: Date.now() - inicioRef.current }),
      });
      const d = await r.json();
      // La reflexión final cierra la sesión: su respuesta lleva al resumen.
      if (paso?.tipo === "reflexion") {
        setRespuesta({ ...d, correcto: null, senales_emitidas: [] });
        return;
      }
      if (d.terminada) setTerminada(true); else await cargarPaso();
    } catch {
      setError("No se pudo registrar la respuesta.");
    } finally {
      setCargando(false);
    }
  }

  async function pedirPista() {
    const r = await fetch(`${backendUrl}/sessions/${id}/hint`, { method: "POST" });
    if (!r.ok) return;
    const d = await r.json();
    setPista(d.pista);
  }

  if (terminada) return <Resumen id={String(id)} backendUrl={backendUrl} studentId={studentId} router={router} />;

  return (
    <main className="min-h-screen bg-[#0F0F13] text-white">
      <header className="border-b border-gray-800 px-4 py-3 sm:px-6">
        <div className="mx-auto flex max-w-3xl items-center gap-4">
          <span className={`rounded border px-2 py-0.5 text-[11px] font-medium ${
            modo === "aprendizaje"
              ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-300"
              : "border-amber-500/30 bg-amber-500/10 text-amber-300"
          }`}>
            {modo === "aprendizaje" ? "Aprendizaje" : "Evaluación"}
          </span>
          <div className="h-1 flex-1 overflow-hidden rounded-full bg-gray-800">
            <div
              className="h-full bg-indigo-400 transition-all"
              style={{ width: `${total ? ((indice) / total) * 100 : 0}%` }}
            />
          </div>
          <span className="font-mono text-xs text-gray-600">{indice + 1}/{total}</span>
        </div>
        {modo === "aprendizaje" && (
          <p className="mx-auto mt-1.5 max-w-3xl text-[11px] text-gray-600">
            Sin tiempo, sin puntaje. Pedir ayuda no te resta nada.
          </p>
        )}
      </header>

      <div className="mx-auto max-w-3xl px-4 py-8 sm:px-6">
        {error && (
          <div className="mb-4 rounded border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-sm text-rose-200">
            {error}
          </div>
        )}

        {!paso && cargando && <p className="text-sm text-gray-500">Cargando…</p>}

        {/* ── Exposición ── */}
        {paso?.tipo === "exposicion" && (
          <div className="space-y-4">
            <p className="text-[11px] uppercase tracking-widest text-gray-500">Concepto nuevo</p>
            <h1 className="text-2xl font-semibold">{paso.titulo}</h1>
            <p className="text-gray-300">{paso.definicion}</p>

            {(paso.carga_cognitiva?.length ?? 0) > 0 && (
              <div className="rounded border border-gray-800 bg-gray-900/40 p-3">
                <p className="mb-1 text-[11px] uppercase tracking-wider text-gray-500">
                  Por qué suele costar
                </p>
                <ul className="space-y-0.5 text-sm text-gray-400">
                  {paso.carga_cognitiva!.map((c) => (
                    <li key={c}>· {CARGA_LABEL[c] ?? c}</li>
                  ))}
                </ul>
              </div>
            )}

            {(paso.subdimensiones?.length ?? 0) > 0 && (
              <div>
                <p className="mb-1.5 text-[11px] uppercase tracking-wider text-gray-500">Facetas</p>
                <ul className="space-y-1.5 text-sm">
                  {paso.subdimensiones!.map((s, i) => (
                    <li key={i} className="text-gray-400">
                      <span className="text-gray-200">{s.name}</span> — {s.description}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            <button
              onClick={avanzarExposicion}
              disabled={cargando}
              className="rounded bg-indigo-500 px-4 py-2 text-sm font-medium hover:bg-indigo-400 disabled:opacity-50"
            >
              Entendido, seguir
            </button>
          </div>
        )}

        {/* ── Pasos metacognitivos ──
             No hay respuesta correcta: lo que se mide es la decisión en sí.
             Por eso no muestran corrección ni puntaje. */}
        {paso && ["calibracion", "planeacion", "reflexion"].includes(paso.tipo) && (
          <div className="space-y-5">
            <div className="flex items-center gap-2">
              <span className="font-mono text-[11px] text-gray-600">{paso.mechanic_id}</span>
              <span className="text-[11px] uppercase tracking-wider text-gray-500">
                {META_TITULO[paso.tipo]}
              </span>
            </div>

            <h2 className="text-lg">{paso.enunciado}</h2>
            {paso.ayuda && <p className="text-sm text-gray-500">{paso.ayuda}</p>}

            <div className="space-y-2">
              {(paso.opciones ?? []).map((o) => (
                <button
                  key={o.id}
                  onClick={() => !respuesta && responderMeta(o.id)}
                  disabled={cargando || !!respuesta}
                  className={`block w-full rounded border px-3 py-2.5 text-left text-sm transition ${
                    seleccion === o.id
                      ? "border-indigo-400 bg-indigo-500/10"
                      : "border-gray-800 hover:border-gray-700"
                  } disabled:opacity-70`}
                >
                  {o.texto}
                </button>
              ))}
            </div>

            {respuesta?.feedback && (
              <div className="space-y-3 border-t border-gray-800 pt-4">
                <p className="text-sm text-gray-300">{respuesta.feedback.mensaje}</p>
                <button
                  onClick={() => (respuesta.terminada ? setTerminada(true) : cargarPaso())}
                  className="rounded bg-indigo-500 px-4 py-2 text-sm font-medium hover:bg-indigo-400"
                >
                  {respuesta.terminada ? "Ver resumen" : "Siguiente"}
                </button>
              </div>
            )}
          </div>
        )}

        {/* ── Ejercicio ── */}
        {paso?.tipo === "ejercicio" && (
          <div className="space-y-5">
            <div className="flex items-center gap-2">
              <span className="font-mono text-[11px] text-gray-600">{paso.mechanic_id}</span>
              <span className="text-[11px] text-gray-500">
                {MECANICA_LABEL[paso.mechanic_id ?? ""] ?? ""}
              </span>
              {paso.paso_ciclo === "guiada" && (
                <span className="rounded border border-gray-700 px-1.5 py-0.5 text-[11px] text-gray-500">
                  con apoyo
                </span>
              )}
            </div>

            <h2 className="text-lg">{paso.enunciado}</h2>

            {paso.afirmacion && (
              <blockquote className="border-l-2 border-gray-700 pl-3 text-sm text-gray-300">
                {paso.afirmacion}
              </blockquote>
            )}

            {paso.par && (
              <p className="font-mono text-sm text-gray-400">
                {paso.par[0]} → {paso.par[1]}
              </p>
            )}

            {(paso.variables_clave?.length ?? 0) > 0 && (
              <p className="text-xs text-gray-500">
                Variables clave: {paso.variables_clave!.join(" · ")}
              </p>
            )}

            {paso.formato === "texto_libre" ? (
              <textarea
                value={texto}
                onChange={(e) => setTexto(e.target.value)}
                disabled={!!respuesta}
                rows={5}
                placeholder="Escribí tu respuesta…"
                className="w-full rounded border border-gray-800 bg-gray-900/60 px-3 py-2 text-sm placeholder:text-gray-600 focus:border-indigo-500 focus:outline-none disabled:opacity-60"
              />
            ) : (
              <div className="space-y-2">
                {(paso.opciones ?? []).map((o) => (
                  <button
                    key={o.id}
                    onClick={() => !respuesta && setSeleccion(o.id)}
                    disabled={!!respuesta}
                    className={`block w-full rounded border px-3 py-2.5 text-left text-sm transition ${
                      seleccion === o.id
                        ? "border-indigo-400 bg-indigo-500/10"
                        : "border-gray-800 hover:border-gray-700"
                    } disabled:opacity-70`}
                  >
                    {o.texto}
                  </button>
                ))}
              </div>
            )}

            {pista && (
              <div className="rounded border border-sky-500/30 bg-sky-500/5 px-3 py-2 text-sm text-sky-200">
                {pista}
              </div>
            )}

            {!respuesta && (
              <div className="flex items-center gap-2">
                <button
                  onClick={enviar}
                  disabled={cargando || (!seleccion && !texto)}
                  className="rounded bg-indigo-500 px-4 py-2 text-sm font-medium hover:bg-indigo-400 disabled:opacity-40"
                >
                  Responder
                </button>
                {paso.pista_disponible && !pista && (
                  <button
                    onClick={pedirPista}
                    className="rounded border border-gray-700 px-3 py-2 text-xs text-gray-400 hover:text-gray-200"
                  >
                    Necesito una pista
                  </button>
                )}
              </div>
            )}

            {/* ── Retroalimentación (solo en aprendizaje) ── */}
            {respuesta?.feedback && (
              <div className="space-y-3 border-t border-gray-800 pt-4">
                <p className={`text-sm font-medium ${
                  respuesta.correcto ? "text-emerald-300" : "text-amber-300"
                }`}>
                  {respuesta.correcto ? "Correcto" : "Todavía no"}
                </p>

                {respuesta.feedback.tipo === "repertorio" ? (
                  <div className="space-y-2 rounded border border-amber-500/25 bg-amber-500/5 p-3 text-sm">
                    <p className="text-amber-200">{respuesta.feedback.nota}</p>
                    {respuesta.feedback.donde_funciona && (
                      <p className="text-gray-400">
                        <span className="text-gray-300">Dónde sí funciona: </span>
                        {respuesta.feedback.donde_funciona}
                      </p>
                    )}
                    <p className="text-gray-300">{respuesta.feedback.mensaje}</p>
                  </div>
                ) : (
                  <div className="space-y-1.5 text-sm text-gray-300">
                    <p>{respuesta.feedback.mensaje}</p>
                    {respuesta.feedback.correcta && (
                      <p className="text-gray-400">Era: {respuesta.feedback.correcta}</p>
                    )}
                    {respuesta.feedback.resolucion_esperada && (
                      <blockquote className="border-l-2 border-gray-700 pl-3 text-gray-400">
                        {respuesta.feedback.resolucion_esperada}
                      </blockquote>
                    )}
                  </div>
                )}

                {respuesta.senales_emitidas.length > 0 && (
                  <p className="font-mono text-[11px] text-gray-600">
                    señal: {respuesta.senales_emitidas.map((s) => s.dimension).join(" · ")}
                  </p>
                )}

                <button
                  onClick={() => (respuesta.terminada ? setTerminada(true) : cargarPaso())}
                  className="rounded bg-indigo-500 px-4 py-2 text-sm font-medium hover:bg-indigo-400"
                >
                  {respuesta.terminada ? "Ver resumen" : "Siguiente"}
                </button>
              </div>
            )}
          </div>
        )}
      </div>
    </main>
  );
}

/* ────────────────────────────────────────────────────────────
   Resumen de cierre
   ──────────────────────────────────────────────────────────── */

function Resumen({
  id, backendUrl, studentId, router,
}: { id: string; backendUrl: string; studentId: string; router: ReturnType<typeof useRouter> }) {
  const [datos, setDatos] = useState<any>(null);

  useEffect(() => {
    fetch(`${backendUrl}/sessions/${id}/summary`)
      .then((r) => r.json()).then(setDatos).catch(() => setDatos({ error: true }));
  }, [backendUrl, id]);

  if (!datos) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-[#0F0F13] text-gray-400">
        Calculando…
      </main>
    );
  }

  const conceptos = datos.conceptos ?? [];
  const s = datos.resumen_sesion ?? {};
  const trabajados = conceptos.filter((c: any) => (c.en_esta_sesion?.intentos ?? 0) > 0);
  const calib = datos.calibracion ?? {};

  return (
    <main className="min-h-screen bg-[#0F0F13] text-white">
      <div className="mx-auto max-w-3xl space-y-6 px-4 py-10 sm:px-6">
        <div>
          <p className="text-[11px] uppercase tracking-widest text-gray-500">
            Sesión de {datos.modo}
          </p>
          <h1 className="mt-1 text-2xl font-semibold">
            {datos.modo === "evaluacion" ? "Resultado" : "Cómo te fue"}
          </h1>
        </div>

        {/* Lo que pasó en ESTA sesión. El resumen anterior mostraba solo el
            perfil acumulado y salía en blanco si las señales no habían llegado
            a la base: se terminaba una sesión completa y no se veía nada. */}
        <div className="grid grid-cols-3 gap-2">
          {[
            ["Ejercicios", s.intentos ?? 0],
            [datos.modo === "evaluacion" ? "Aciertos" : "Bien a la primera", s.aciertos ?? 0],
            ["Conceptos", s.conceptos_trabajados ?? 0],
          ].map(([l, v]) => (
            <div key={String(l)} className="rounded-lg border border-gray-800 bg-gray-900/40 p-3">
              <p className="font-mono text-2xl">{String(v)}</p>
              <p className="mt-0.5 text-[11px] text-gray-500">{l}</p>
            </div>
          ))}
        </div>

        {s.intentos === 0 && (
          <div className="rounded-lg border border-amber-500/25 bg-amber-500/5 p-4 text-sm text-amber-200">
            No se registró ninguna respuesta en esta sesión. Si respondiste
            ejercicios, algo falló al guardarlos: revisá{" "}
            <span className="font-mono text-xs">/students/{studentId}/diagnostico</span>.
          </div>
        )}

        {trabajados.length > 0 && (
          <div className="rounded-lg border border-gray-800 bg-gray-900/40 p-4">
            <p className="mb-3 text-xs uppercase tracking-wider text-gray-500">
              Por concepto
            </p>
            <div className="space-y-3">
              {trabajados.map((c: any) => {
                const e = c.en_esta_sesion;
                const tasa = e.intentos ? e.aciertos / e.intentos : 0;
                return (
                  <div key={c.concept_id}>
                    <div className="mb-1 flex flex-wrap items-baseline gap-2">
                      <span className="text-sm text-gray-200">{c.titulo}</span>
                      <span className="font-mono text-[11px] text-gray-600">
                        {e.aciertos}/{e.intentos}
                      </span>
                      {e.mecanicas.length > 0 && (
                        <span className="font-mono text-[11px] text-gray-700">
                          {e.mecanicas.join(" ")}
                        </span>
                      )}
                      {c.recuperacion != null && (
                        <span className="ml-auto font-mono text-[11px] text-gray-500">
                          acumulado {Math.round(c.recuperacion * 100)}%
                        </span>
                      )}
                    </div>
                    <div className="h-1.5 w-full overflow-hidden rounded-full bg-gray-800">
                      <div
                        className={`h-full ${
                          tasa >= 0.7 ? "bg-emerald-400"
                          : tasa >= 0.4 ? "bg-amber-400" : "bg-rose-400"
                        }`}
                        style={{ width: `${Math.round(tasa * 100)}%` }}
                      />
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {calib.n > 0 && (
          <div className="rounded-lg border border-gray-800 bg-gray-900/40 p-4">
            <p className="mb-1 text-xs uppercase tracking-wider text-gray-500">
              Qué tan bien te conocés
            </p>
            <p className="text-sm text-gray-300">
              Sobre {calib.n} predicción(es), tu error medio fue de{" "}
              <span className="font-mono text-white">
                {Math.round((calib.error_medio ?? 0) * 100)}%
              </span>
              .{" "}
              {(calib.error_medio ?? 0) < 0.2
                ? "Predecís bien tu propio desempeño."
                : "Hay distancia entre lo que creés saber y lo que te sale — eso también se entrena."}
            </p>
          </div>
        )}

        {Object.keys(datos.repertorios_activos ?? {}).length > 0 && (
          <div className="rounded-lg border border-amber-500/25 bg-amber-500/5 p-4">
            <p className="mb-2 text-xs uppercase tracking-wider text-amber-300">
              Ideas previas que aparecieron
            </p>
            <p className="text-sm text-gray-300">
              Al equivocarte activaste {Object.keys(datos.repertorios_activos).length}{" "}
              intuición(es) cotidiana(s). No son errores tontos: son ideas que
              funcionan en otros contextos y que acá siguen otro criterio.
            </p>
          </div>
        )}

        {datos.peticiones_de_ayuda > 0 && (
          <p className="text-xs text-gray-500">
            Pediste ayuda {datos.peticiones_de_ayuda} vez/veces. Eso no baja tu
            resultado: solo hace que el sistema tenga menos certeza sobre esos puntos.
          </p>
        )}

        <p className="text-xs text-gray-600">
          {datos.n_senales_totales} señal(es) acumuladas en total. La próxima
          sesión se arma con esto.
        </p>

        <button
          onClick={() => router.push(`/estudiante/${studentId}`)}
          className="rounded bg-indigo-500 px-4 py-2 text-sm font-medium hover:bg-indigo-400"
        >
          Volver al perfil
        </button>
      </div>
    </main>
  );
}
