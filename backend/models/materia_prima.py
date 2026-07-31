"""
models/materia_prima.py — v2

Schema de la materia prima extraída de un PDF.
Refleja las 6 capas de 06_materia_prima.md y los contratos de señal de
08_fichas_tecnicas.md §0 (envelope v2).

Cambios v1 → v2:
  · RelationType pasa de 5 a 9 tipos (agrega causa, ejemplifica, generaliza, contrasta).
  · confidence_extraction pasa de enum categórico a float 0-1.
  · Concept gana sinonimos / variantes_terminologicas (A3 EVOCAR necesita con qué calificar).
  · CommonRepertoire gana por_que_es_intuitiva, contraste_cientifico, contexto_donde_funciona.
  · Capa 4 se reestructura en Thesis + Framework (F2/F3 necesitan marcos rivales y criterios).
  · EvidenceCase pasa a multi-concepto y gana resolucion_esperada, dominio, distancia.
  · Aparece GeneratedScenario (variantes derivadas: sin esto la familia E se agota en una pasada).
  · Aparece ConceptAxis (espacio de atributos: C4 MAPEAR no es instanciable sin él).
  · PedagogicalMeta gana signal_coverage y family_availability.
"""
from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator


# ─────────────────────────────────────────────
# Enums compartidos
# ─────────────────────────────────────────────

class RelationType(str, Enum):
    """Tipología de 9 tipos. La reducción a 5 dejaba sin input a C5 CONTRASTAR
    y hacía inalcanzable la condición de transferencia de C2 ORDENAR."""
    APOYA = "apoya"
    CONTRADICE = "contradice"
    MATIZA = "matiza"
    EXTIENDE = "extiende"
    REQUIERE = "requiere"
    CAUSA = "causa"              # habilita la señal de transferencia de C2
    EJEMPLIFICA = "ejemplifica"  # arista concepto ↔ caso
    GENERALIZA = "generaliza"
    CONTRASTA = "contrasta"      # input canónico de C5


class ConceptType(str, Enum):
    TEORICO = "teorico"
    EMPIRICO = "empirico"
    METODOLOGICO = "metodologico"
    APLICADO = "aplicado"


class DifficultyLevel(str, Enum):
    BASICO = "basico"
    INTERMEDIO = "intermedio"
    AVANZADO = "avanzado"


class RepertoireOrigin(str, Enum):
    DOCUMENTADO = "documentado_en_corpus"
    INFERIDO = "inferido_por_llm"
    AGREGADO = "agregado_por_profesor"


class CaseKind(str, Enum):
    EXPERIMENTO = "experimento"
    DATO_EMPIRICO = "dato_empirico"
    EJEMPLO_COTIDIANO = "ejemplo_cotidiano"
    CASO_CLINICO = "caso_clinico"
    CONTRAEJEMPLO = "contraejemplo"
    CASO_LIMITE = "caso_limite"


class TransferDistance(str, Enum):
    """Atributo obligatorio de toda señal de transferencia (doc 08 §0.4)."""
    CERCANA = "cercana"
    MEDIA = "media"
    LEJANA = "lejana"


# Mapeo de compatibilidad para outputs v1 con confianza categórica.
LEGACY_CONFIDENCE = {"alta": 0.9, "media": 0.6, "baja": 0.3}


class _ConfidenceMixin(BaseModel):
    confidence_extraction: float = Field(0.6, ge=0.0, le=1.0)

    @field_validator("confidence_extraction", mode="before")
    @classmethod
    def _coerce_confidence(cls, v):
        if isinstance(v, str):
            return LEGACY_CONFIDENCE.get(v.strip().lower(), 0.6)
        if v is None:
            return 0.6
        return v


# ─────────────────────────────────────────────
# Capa 1 — Diccionario conceptual
# ─────────────────────────────────────────────

class ConceptDimension(BaseModel):
    name: str
    description: str


class ConceptDistinction(BaseModel):
    """Materia prima directa del caracterizador de distractores.

    `from_concept` es el `concepto_confundido` que B1 necesita para emitir
    `relacion` sobre una arista además de `recuperacion` sobre el concepto.
    """
    from_concept: str
    difference: str


class Concept(_ConfidenceMixin):
    id: str
    title: str
    definition: str
    tipo: ConceptType = ConceptType.TEORICO
    difficulty: DifficultyLevel = DifficultyLevel.INTERMEDIO
    importance: float = Field(0.5, ge=0, le=1)
    is_gateway: bool = False
    is_threshold: bool = False
    source_pages: list[int] = Field(default_factory=list)
    source_section: Optional[str] = None

    # v2 — necesarios para calificar producción abierta (A3 EVOCAR, A2 COMPLETAR)
    sinonimos: list[str] = Field(default_factory=list)
    variantes_terminologicas: list[str] = Field(default_factory=list)

    # Enriquecimiento (paso 2.5)
    core_definition: Optional[str] = None
    subdimensions: list[ConceptDimension] = Field(default_factory=list)
    distinctions: list[ConceptDistinction] = Field(default_factory=list)
    measurement_approach: Optional[str] = None
    theoretical_role: Optional[str] = None
    key_tensions: list[str] = Field(default_factory=list)
    evolution_in_paper: Optional[str] = None
    is_enriched: bool = False


# ─────────────────────────────────────────────
# Capa 2 — Estructura relacional
# ─────────────────────────────────────────────

class ConceptRelation(_ConfidenceMixin):
    from_concept_id: str
    to_concept_id: str
    relation_type: RelationType
    description: str = ""
    bidirectional: bool = False


class ConceptCluster(BaseModel):
    """Calculado algorítmicamente (label propagation), no pedido al LLM.

    En v1 el LLM devolvía clusters por segmento y se acumulaban sin merge,
    produciendo N juegos solapados.
    """
    id: str
    label: str
    concept_ids: list[str]


class AxisPosition(BaseModel):
    concept_id: str
    position: float = Field(..., ge=0.0, le=1.0)
    justificacion: str = ""


class ConceptAxis(BaseModel):
    """Eje bipolar del dominio. Sin esto C4 MAPEAR no es instanciable.

    Se consolida a partir de las `subdimensions` que produce el enriquecimiento:
    subdimensiones sueltas por concepto → ejes compartidos entre conceptos.
    """
    id: str
    label: str
    polo_bajo: str
    polo_alto: str
    positions: list[AxisPosition] = Field(default_factory=list)
    confidence_extraction: float = Field(0.6, ge=0.0, le=1.0)


# ─────────────────────────────────────────────
# Capa 3 — Repertorios cotidianos
# ─────────────────────────────────────────────

class CommonRepertoire(_ConfidenceMixin):
    """Conocimiento previo cotidiano que puede interferir.

    Los tres campos v2 son los que el Contextualizador (rol 4) necesita para
    producir feedback de coexistencia en vez de corrección: nunca "está mal",
    sino "eso funciona cuando X, y aquí el criterio es otro" (doc 01 §3).
    """
    id: str
    concept_id: str
    label: str
    description: str
    example: str
    por_que_es_intuitiva: str = ""
    contraste_cientifico: str = ""
    contexto_donde_funciona: str = ""
    concepto_confundido: Optional[str] = None
    origin: RepertoireOrigin = RepertoireOrigin.INFERIDO
    status: str = Field("borrador", description="borrador hasta que el profesor apruebe")


# ─────────────────────────────────────────────
# Capa 4 — Argumentación
# ─────────────────────────────────────────────

class Framework(BaseModel):
    """Marco teórico. F3 REFUTAR emite `relacion` sobre cluster de argumentos
    solo si puede contrastar dos marcos: sin `rivales` esa señal nunca existe."""
    id: str
    label: str
    principios_centrales: list[str] = Field(default_factory=list)
    rivales: list[str] = Field(default_factory=list)
    concept_ids: list[str] = Field(default_factory=list)
    confidence_extraction: float = Field(0.6, ge=0.0, le=1.0)


class Thesis(_ConfidenceMixin):
    """Posición defendible. Objeto de tipo `argumento` para los targets de señal.

    `criterios_defensa_valida` y `criterios_refutacion_valida` son el ancla de
    rúbrica del Juez en F2 y F3. Sin ellos el Juez califica sin criterio del curso.
    """
    id: str
    statement: str
    concept_ids: list[str] = Field(default_factory=list)
    framework_id: Optional[str] = None
    supporting_arguments: list[str] = Field(default_factory=list)
    counterarguments: list[str] = Field(default_factory=list)
    criterios_defensa_valida: list[str] = Field(default_factory=list)
    criterios_refutacion_valida: list[str] = Field(default_factory=list)
    theoretical_source: Optional[str] = None


# ─────────────────────────────────────────────
# Capa 5 — Evidencia y casos
# ─────────────────────────────────────────────

class EvidenceCase(_ConfidenceMixin):
    """Caso extraído del paper.

    `concept_ids` es lista porque E5 RESOLVER exige combinar varios conceptos.
    `resolucion_esperada` es el gold contra el que E1/E2/E3 califican.
    `dominio` es lo que permite calcular `distancia` en los escenarios derivados.
    """
    id: str
    concept_ids: list[str] = Field(default_factory=list)
    primary_concept_id: Optional[str] = None
    kind: CaseKind = CaseKind.EJEMPLO_COTIDIANO
    description: str
    resolucion_esperada: str = ""
    dominio: str = ""
    variables_clave: list[str] = Field(default_factory=list)
    es_paradigmatico: bool = False
    prediction_enabled: bool = False
    error_embebido: Optional[str] = None
    repertoire_id: Optional[str] = None
    source_pages: list[int] = Field(default_factory=list)


class GeneratedScenario(BaseModel):
    """Variante derivada de un caso. Sin estas, cada caso es de un solo uso
    y la familia E se agota tras una pasada.

    `distancia` no se acepta a ciegas: validation.py la recalcula comparando
    `dominio` contra el del caso padre.
    """
    id: str
    parent_case_id: str
    concept_ids: list[str] = Field(default_factory=list)
    description: str
    resolucion_esperada: str = ""
    dominio: str = ""
    distancia: TransferDistance = TransferDistance.CERCANA
    habilidad_objetivo: str = "transferencia"
    error_embebido: Optional[str] = None
    repertoire_id: Optional[str] = None
    confidence_extraction: float = Field(0.6, ge=0.0, le=1.0)


# ─────────────────────────────────────────────
# Capa 6 — Meta-pedagógico
# ─────────────────────────────────────────────

class SignalCoverage(BaseModel):
    """Qué dimensiones del perfil puede medir este curso.

    Responde una pregunta que `argumentative_richness` y `case_density` no
    responden: no "qué mecánicas se activan" sino "qué celdas del perfil van a
    quedar vacías y por qué".
    """
    dimension: str
    cobertura: float = Field(0.0, ge=0.0, le=1.0)
    cuello_de_botella: str = ""


class FamilyAvailability(BaseModel):
    family: str
    available: bool
    reason: str = ""
    mechanic_ids: list[str] = Field(default_factory=list)


class PedagogicalMeta(BaseModel):
    gateway_concepts: list[str] = Field(default_factory=list)
    threshold_concepts: list[str] = Field(default_factory=list)
    prerequisite_graph: dict = Field(
        default_factory=dict,
        description="concepto → lista de sus prerequisitos (dirección corregida en v2)",
    )
    unlocks_graph: dict = Field(
        default_factory=dict,
        description="prerequisito → conceptos que habilita",
    )
    suggested_sequence: list[str] = Field(default_factory=list)
    difficulty_distribution: dict = Field(default_factory=dict)
    argumentative_richness: float = Field(0.0, ge=0, le=1)
    case_density: float = Field(0.0, ge=0, le=1)
    repertoire_density: float = Field(0.0, ge=0, le=1)
    relational_density: float = Field(0.0, ge=0, le=1)
    enrichment_coverage: float = Field(0.0, ge=0, le=1)
    recommended_modalities: list[str] = Field(default_factory=list)
    signal_coverage: list[SignalCoverage] = Field(default_factory=list)
    family_availability: list[FamilyAvailability] = Field(default_factory=list)


# ─────────────────────────────────────────────
# Output completo
# ─────────────────────────────────────────────

class LayerStatus(BaseModel):
    """Distingue 'el paper no tiene esto' de 'la extracción falló'.

    En v1 ambos casos producían una lista vacía y la misma pantalla para el profesor.
    """
    layer: str
    status: str  # 'ok' | 'empty' | 'failed' | 'skipped'
    items: int = 0
    detail: str = ""


class MateriaPrimaOutput(BaseModel):
    course_id: str
    source_filename: str
    extracted_at: str
    schema_version: str = "2.0.0"

    concepts: list[Concept] = Field(default_factory=list)
    relations: list[ConceptRelation] = Field(default_factory=list)
    clusters: list[ConceptCluster] = Field(default_factory=list)
    axes: list[ConceptAxis] = Field(default_factory=list)
    repertoires: list[CommonRepertoire] = Field(default_factory=list)
    frameworks: list[Framework] = Field(default_factory=list)
    theses: list[Thesis] = Field(default_factory=list)
    cases: list[EvidenceCase] = Field(default_factory=list)
    scenarios: list[GeneratedScenario] = Field(default_factory=list)
    meta: Optional[PedagogicalMeta] = None

    pipeline_stats: dict = Field(default_factory=dict)
    layer_status: list[LayerStatus] = Field(default_factory=list)
    validation_report: dict = Field(default_factory=dict)
    low_confidence_count: int = 0
    truncated: bool = False
    requires_professor_review: bool = True
