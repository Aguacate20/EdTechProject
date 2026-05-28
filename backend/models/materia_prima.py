"""
models/materia_prima.py
Schema completo de la materia prima extraída de un PDF.
Refleja las 6 capas definidas en 06_materia_prima.md
"""
from __future__ import annotations
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


# ─────────────────────────────────────────────
# Enums compartidos
# ─────────────────────────────────────────────

class RelationType(str, Enum):
    APOYA = "apoya"
    CONTRADICE = "contradice"
    MATIZA = "matiza"
    EXTIENDE = "extiende"
    REQUIERE = "requiere"

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

class ExtractionConfidence(str, Enum):
    ALTA = "alta"
    MEDIA = "media"
    BAJA = "baja"


# ─────────────────────────────────────────────
# Capa 1 — Diccionario conceptual
# ─────────────────────────────────────────────

class ConceptDimension(BaseModel):
    name: str
    description: str

class ConceptDistinction(BaseModel):
    from_concept: str
    difference: str

class Concept(BaseModel):
    """Nodo del grafo conceptual del curso."""
    id: str
    title: str
    definition: str
    tipo: ConceptType
    difficulty: DifficultyLevel
    importance: float = Field(..., ge=0, le=1)
    is_gateway: bool = False
    is_threshold: bool = False
    source_pages: list[int] = Field(default_factory=list)
    source_section: Optional[str] = None
    confidence_extraction: ExtractionConfidence = ExtractionConfidence.MEDIA

    # Campos enriquecidos (se llenan en Paso 2.5)
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

class ConceptRelation(BaseModel):
    """Arista tipada entre dos conceptos."""
    from_concept_id: str
    to_concept_id: str
    relation_type: RelationType
    description: str
    bidirectional: bool = False
    confidence_extraction: ExtractionConfidence = ExtractionConfidence.MEDIA


class ConceptCluster(BaseModel):
    """Agrupación temática de conceptos."""
    id: str
    label: str
    concept_ids: list[str]


# ─────────────────────────────────────────────
# Capa 3 — Repertorios cotidianos
# ─────────────────────────────────────────────

class CommonRepertoire(BaseModel):
    """
    Conocimiento previo cotidiano que puede interferir con el aprendizaje.
    Cuando un estudiante activa este repertorio, el Contextualizador (Rol 4)
    genera feedback contextualizado específico.
    """
    id: str
    concept_id: str
    label: str
    description: str
    example: str
    origin: RepertoireOrigin
    status: str = Field("borrador", description="borrador hasta que el profesor apruebe")
    confidence_extraction: ExtractionConfidence = ExtractionConfidence.MEDIA


# ─────────────────────────────────────────────
# Capa 4 — Argumentación
# ─────────────────────────────────────────────

class ArgumentativePosition(BaseModel):
    """Posición teórica defendible sobre un concepto."""
    id: str
    concept_id: str
    position: str
    supporting_arguments: list[str]
    counterarguments: list[str]
    theoretical_source: Optional[str] = None
    confidence_extraction: ExtractionConfidence = ExtractionConfidence.MEDIA


# ─────────────────────────────────────────────
# Capa 5 — Evidencia y casos
# ─────────────────────────────────────────────

class EvidenceCase(BaseModel):
    """Caso empírico o ejemplo que ilustra un concepto."""
    id: str
    concept_id: str
    kind: str
    description: str
    prediction_enabled: bool = False
    source_pages: list[int] = Field(default_factory=list)
    confidence_extraction: ExtractionConfidence = ExtractionConfidence.MEDIA


# ─────────────────────────────────────────────
# Capa 6 — Meta-pedagógico
# ─────────────────────────────────────────────

class PedagogicalMeta(BaseModel):
    """Metadatos sobre cómo enseñar el curso. Alimenta el selector adaptativo."""
    gateway_concepts: list[str] = Field(default_factory=list)
    threshold_concepts: list[str] = Field(default_factory=list)
    prerequisite_graph: dict = Field(default_factory=dict)
    suggested_sequence: list[str] = Field(default_factory=list)
    difficulty_distribution: dict = Field(default_factory=dict)
    argumentative_richness: float = Field(0.0, ge=0, le=1)
    case_density: float = Field(0.0, ge=0, le=1)
    recommended_modalities: list[str] = Field(default_factory=list)


# ─────────────────────────────────────────────
# Output completo del extractor
# ─────────────────────────────────────────────

class MateriaPrimaOutput(BaseModel):
    """
    Output completo del pipeline de extracción.
    Se almacena en Supabase una vez que el profesor revisa y aprueba.
    """
    course_id: str
    source_filename: str
    extracted_at: str

    # Las 6 capas
    concepts: list[Concept] = Field(default_factory=list)
    relations: list[ConceptRelation] = Field(default_factory=list)
    clusters: list[ConceptCluster] = Field(default_factory=list)
    repertoires: list[CommonRepertoire] = Field(default_factory=list)
    arguments: list[ArgumentativePosition] = Field(default_factory=list)
    cases: list[EvidenceCase] = Field(default_factory=list)
    meta: Optional[PedagogicalMeta] = None

    # Métricas del pipeline
    pipeline_stats: dict = Field(default_factory=dict)
    low_confidence_count: int = 0
    requires_professor_review: bool = True
