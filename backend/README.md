---
title: EdTech Extractor
emoji: 📚
colorFrom: indigo
colorTo: green
sdk: docker
app_port: 7860
pinned: false
---
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

