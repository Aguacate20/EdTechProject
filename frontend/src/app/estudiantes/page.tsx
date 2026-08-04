"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

/* Entrada al sistema. Sin contraseña a propósito: en esta fase solo hace falta
   un id estable para que el perfil acumule historial entre sesiones. */

export default function EstudiantesPage() {
  const router = useRouter();
  const backendUrl = process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:7860";
  const [lista, setLista] = useState<{ id: string; display_name: string }[]>([]);
  const [nombre, setNombre] = useState("");
  const [creando, setCreando] = useState(false);

  useEffect(() => {
    fetch(`${backendUrl}/students`).then((r) => r.json())
      .then((d) => setLista(d.students ?? [])).catch(() => setLista([]));
  }, [backendUrl]);

  async function crear() {
    if (!nombre.trim()) return;
    setCreando(true);
    try {
      const r = await fetch(`${backendUrl}/students`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ display_name: nombre.trim() }),
      });
      const d = await r.json();
      if (d.id) router.push(`/estudiante/${d.id}`);
    } finally {
      setCreando(false);
    }
  }

  return (
    <main className="min-h-screen bg-[#0F0F13] text-white">
      <div className="mx-auto max-w-lg space-y-6 px-4 py-16">
        <div>
          <h1 className="text-2xl font-semibold">¿Quién sos?</h1>
          <p className="mt-1 text-sm text-gray-500">
            Sin contraseña. Solo hace falta un nombre para que el sistema
            recuerde tu progreso entre sesiones.
          </p>
        </div>

        <div className="flex gap-2">
          <input
            value={nombre}
            onChange={(e) => setNombre(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && crear()}
            placeholder="Tu nombre"
            className="min-w-0 flex-1 rounded border border-gray-800 bg-gray-900/60 px-3 py-2 text-sm placeholder:text-gray-600 focus:border-indigo-500 focus:outline-none"
          />
          <button
            onClick={crear}
            disabled={creando || !nombre.trim()}
            className="shrink-0 rounded bg-indigo-500 px-4 py-2 text-sm font-medium hover:bg-indigo-400 disabled:opacity-40"
          >
            Entrar
          </button>
        </div>

        {lista.length > 0 && (
          <div>
            <p className="mb-2 text-xs uppercase tracking-wider text-gray-500">
              O continuá con un perfil existente
            </p>
            <div className="space-y-1">
              {lista.map((s) => (
                <button
                  key={s.id}
                  onClick={() => router.push(`/estudiante/${s.id}`)}
                  className="block w-full rounded border border-gray-800 bg-gray-900/40 px-3 py-2 text-left text-sm hover:border-gray-700"
                >
                  {s.display_name}
                  <span className="ml-2 font-mono text-[11px] text-gray-600">
                    {s.id.slice(0, 8)}
                  </span>
                </button>
              ))}
            </div>
          </div>
        )}

        <a href="/upload" className="block text-sm text-indigo-400 underline">
          Subir material nuevo
        </a>
      </div>
    </main>
  );
}
