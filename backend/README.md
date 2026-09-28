---
title: EdTech Extractor
emoji: 📚
colorFrom: indigo
colorTo: green
sdk: docker
app_port: 7860
pinned: false
---
## v3.13 · pool limpio, casos con reintento, capa 4 con aire

- Fuera del pool `zai-glm-4.7`, `gemma-4-31b`, `qwen3.6-27b` y `gemma-4-26b`: devolvían 404 y
  se llevaban capas enteras (en la corrida de v3.12, la canonicalización y **los casos**).
- La capa 5 (casos) reintenta los lotes fallidos, como ya hacían relaciones y repertorios.
- `MT_CAPA4` pasa de 6500 a 9000 por defecto: la argumentación se truncaba.

## v3.12 · el extractor al 100 % de lo que el juego sabe usar

- **Capa 2**: `no_vinculos` (pares que el texto distingue a propósito, con motivo; máx. 8, solo
  explícitos), **cadenas** eslabón por eslabón (causa/antecede A→B, B→C) y **matiza** explícito
  cuando un concepto limita el alcance de otro. Los no-vínculos viajan al bundle en
  `graph.no_vinculos`; el juego ya los juzga.
- **Completar**: los conceptos sin ningún vínculo se repescan con una llamada enfocada
  (`capa2_completar`; `stats.completar_relaciones`).
- **Capa 2b**: reintento único cuando no sale ningún eje con 8+ conceptos
  (`stats.capa2b_reintentada`).
- **Capa 4**: una objeción que nombra algo observable se redacta como criterio de refutación
  («si se observara que…»); en `counterarguments` quedan solo las retóricas.
- **Jobs persistentes**: tabla `jobs` (SQL en `supabase_jobs.sql`); el estado de cada trabajo se
  guarda al empezar, terminar o fallar, y se recarga al arrancar (los que quedaron a medias
  vuelven como fallidos con aviso).

Reprocesar un PDF regenera su bundle con los campos nuevos; el plan fusionado del perfil se
rehace solo; el Atlas y las constelaciones no cambian (van por id de concepto).

