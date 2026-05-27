# EdTech Scaffolding — Plataforma de Aprendizaje con Gamificación

Plataforma adaptativa que convierte PDFs de profesores en actividades de aprendizaje con scaffolding cognitivo y gamificación.

## Arquitectura

```
GitHub (monorepo)
├── /frontend  →  Vercel (Next.js 14)
└── /backend   →  Hugging Face Spaces (FastAPI + Docker)
                  └── Llama via HF Inference API
```

Base de datos: **Supabase** (PostgreSQL)

## Stack

| Capa | Tecnología | Rol |
|------|-----------|-----|
| Frontend | Next.js 14, TypeScript, Tailwind | UI del profesor y estudiante |
| Backend | FastAPI, Python 3.11 | Pipeline de extracción PDF |
| LLM | HF Inference API (Llama 3.3 70B) | Roles 1 y 2 del extractor |
| DB | Supabase (Postgres + Storage) | Datos y almacenamiento de PDFs |
| Deploy frontend | Vercel | CI/CD automático desde `main` |
| Deploy backend | Hugging Face Spaces (Docker) | API del extractor |

## Pipeline de extracción (Fase 3)

El corazón del sistema. Convierte un PDF en materia prima pedagógica estructurada:

```
PDF
 │
 ▼  Paso 1: Segmentación (PyMuPDF)
 ▼  Paso 2: Capa 1 — Diccionario conceptual (LLM)
 ▼  Paso 3: Capa 2 — Relaciones tipadas (LLM)
 ▼  Paso 4: Capa 3 — Repertorios cotidianos (LLM)
 ▼  Paso 5: Capas 4+5 — Argumentación y casos (LLM)
 ▼  Paso 6: Capa 6 — Meta-pedagógico (algoritmo + LLM)
 ▼
JSON estructurado → Supabase
```

## Setup local

### Backend
```bash
cd backend
pip install -r requirements.txt
cp .env.example .env   # completar con HF_TOKEN y SUPABASE keys
uvicorn app:app --reload
```

### Frontend
```bash
cd frontend
npm install
cp .env.example .env.local  # completar con NEXT_PUBLIC_SUPABASE_URL, etc.
npm run dev
```

## Variables de entorno

### Backend (`.env`)
```
HF_TOKEN=hf_...
SUPABASE_URL=https://...supabase.co
SUPABASE_SERVICE_KEY=...
```

### Frontend (`.env.local`)
```
NEXT_PUBLIC_SUPABASE_URL=https://...supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=...
NEXT_PUBLIC_BACKEND_URL=https://tu-space.hf.space
```

## Estructura de carpetas

```
edtech-scaffolding/
├── frontend/
│   ├── src/app/
│   │   ├── upload/          # Subida de PDF por el profesor
│   │   ├── review/[id]/     # UI de revisión del contenido extraído
│   │   └── api/extract/     # Proxy hacia el backend HF
│   └── src/components/
│       ├── ConceptCard.tsx
│       ├── RelationGraph.tsx
│       └── ReviewPanel.tsx
└── backend/
    ├── app.py               # FastAPI entry point
    ├── pipeline/
    │   ├── extractor.py     # Orquestador principal
    │   ├── segmentation.py  # Paso 1: segmentación del PDF
    │   ├── layer1_concepts.py
    │   ├── layer2_relations.py
    │   ├── layer3_repertoires.py
    │   ├── layer4_5_arg_cases.py
    │   ├── layer6_meta.py
    │   └── prompts/         # Prompts para cada capa
    └── models/
        └── materia_prima.py # Schemas Pydantic del output
```
