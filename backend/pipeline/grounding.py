"""
pipeline/grounding.py — NUEVO en v2.3.1

Verificación de anclaje textual: comprobar que lo extraído está en el documento.

## El problema

En la corrida medida apareció un concepto llamado "Perceived Cognitive
Consistency Index (PCCI)". El paper nunca dice eso: define PCCI como
*Parasocial Co-Creation Index*. El modelo tomó la sigla, inventó un desarrollo
plausible, y el concepto entró al grafo, generó ítems y se convirtió en
distractor de otros conceptos. Ningún filtro posterior podía detectarlo porque
todo lo demás del pipeline razona sobre lo que el modelo dijo, no sobre el
documento.

## La estrategia

Pedirle al modelo que **cite**. Un concepto real puede señalar el fragmento del
texto donde aparece; uno inventado no. Y la comprobación de que esa cita existe
en el documento es determinista: no hace falta otro LLM para verificarla, ni
hay margen de opinión.

Tres razones por las que esto funciona mejor que pedir "no alucines":

  1. Es verificable sin costo. Comparar cadenas es gratis; volver a preguntarle
     al modelo si dijo la verdad es caro y poco fiable.
  2. Convierte una instrucción blanda en una restricción dura. El modelo no
     puede citar lo que no existe sin que lo pillemos.
  3. Degrada bien. Lo que no verifica no se descarta en silencio: baja su
     confianza y queda marcado, así el profesor ve qué revisar primero.

## La tolerancia

La comparación no es literal. Los modelos normalizan comillas tipográficas,
guiones, espacios y saltos de línea al citar, y a veces recortan por la mitad
de una palabra. Se compara sobre texto normalizado y con similitud de n-gramas,
no con igualdad exacta, porque exigir literalidad produciría falsos negativos
sobre citas que sí son reales.
"""
from __future__ import annotations

import logging
import re
import unicodedata
from difflib import SequenceMatcher

logger = logging.getLogger(__name__)

# Umbral de similitud para dar una cita por encontrada.
UMBRAL_CITA = 0.82
# Longitud mínima de cita útil. Por debajo, cualquier cosa "aparece" en el texto.
MIN_CITA = 25


def normalizar(texto: str) -> str:
    """Forma comparable: sin acentos, sin puntuación tipográfica, en minúsculas."""
    if not texto:
        return ""
    t = unicodedata.normalize("NFKD", str(texto))
    t = "".join(c for c in t if not unicodedata.combining(c))
    # Comillas y guiones que los modelos cambian al citar.
    for a, b in (("\u2018", "'"), ("\u2019", "'"), ("\u201c", '"'), ("\u201d", '"'),
                 ("\u2010", "-"), ("\u2011", "-"), ("\u2012", "-"), ("\u2013", "-"),
                 ("\u2014", "-"), ("\u2212", "-"), ("\u00a0", " ")):
        t = t.replace(a, b)
    t = re.sub(r"[^\w\s]", " ", t.lower())
    return " ".join(t.split())


def _ngramas(texto: str, n: int = 4) -> set[str]:
    palabras = texto.split()
    if len(palabras) < n:
        return {texto} if texto else set()
    return {" ".join(palabras[i:i + n]) for i in range(len(palabras) - n + 1)}


def cita_presente(cita: str, fuente_norm: str, fuente_ngramas: set[str]) -> tuple[bool, float]:
    """¿Esta cita aparece en el documento? Devuelve (encontrada, similitud).

    Primero busca coincidencia directa de subcadena, que es el caso normal.
    Si falla, compara n-gramas: cubre las citas que el modelo recortó, unió con
    puntos suspensivos o alteró levemente al transcribir.
    """
    cita_norm = normalizar(cita)
    if len(cita_norm) < MIN_CITA:
        return False, 0.0

    if cita_norm in fuente_norm:
        return True, 1.0

    grams = _ngramas(cita_norm)
    if not grams:
        return False, 0.0
    solapamiento = len(grams & fuente_ngramas) / len(grams)
    if solapamiento >= UMBRAL_CITA:
        return True, round(solapamiento, 2)

    # Última oportunidad: el modelo pudo citar dos fragmentos unidos. Se parte
    # por puntos suspensivos y se acepta si cada mitad aparece.
    partes = [p.strip() for p in re.split(r"\.{3}|…|\s\[\.\.\.\]\s", cita_norm) if len(p.strip()) >= MIN_CITA]
    if len(partes) > 1 and all(p in fuente_norm for p in partes):
        return True, 0.9

    return False, round(solapamiento, 2)


def _sigla(titulo: str) -> str | None:
    m = re.search(r"\(([A-Z][A-Z0-9\-]{1,9})\)\s*$", (titulo or "").strip())
    return m.group(1) if m else None


def diagnostico_termino(termino: str, fuente_norm: str) -> tuple[bool, str]:
    """(¿está?, diagnóstico). Separa el caso más informativo de todos.

    Cuando la sigla aparece en el documento pero su desarrollo no, estamos ante
    una invención de manual: el modelo tomó "(PCCI)" del texto e inventó
    "Perceived Cognitive Consistency Index" porque suena plausible. Distinguirlo
    de un concepto que simplemente no está importa, porque el mensaje que ve el
    profesor no es el mismo.
    """
    if termino_presente(termino, fuente_norm):
        return True, "presente"
    sigla = _sigla(termino)
    if sigla and normalizar(sigla) in fuente_norm.split():
        return False, "sigla_presente_desarrollo_inventado"
    return False, "ausente"


def termino_presente(termino: str, fuente_norm: str) -> bool:
    """¿Este término aparece literalmente en el documento?

    Se usa para los títulos de concepto. Es más estricto que la cita porque un
    título es corto: se exige que la secuencia completa de palabras aparezca.
    """
    t = normalizar(termino)
    if not t:
        return False
    # Un título con sigla entre paréntesis: basta con que aparezca la base.
    base = re.sub(r"\s*\([^)]*\)\s*$", "", termino).strip()
    if base and base != termino:
        t_base = normalizar(base)
        if t_base and t_base in fuente_norm:
            return True
    return t in fuente_norm


class Verificador:
    """Comprueba contra el texto de origen. Se construye una vez por documento."""

    def __init__(self, texto_fuente: str) -> None:
        self.fuente_norm = normalizar(texto_fuente)
        self.fuente_ngramas = _ngramas(self.fuente_norm)
        self.stats = {
            "conceptos_verificados": 0,
            "conceptos_sin_cita": 0,
            "conceptos_cita_no_encontrada": 0,
            "conceptos_titulo_ausente": 0,
            "conceptos_descartados": 0,
        }
        self.descartados: list[dict] = []

    # ── Conceptos ─────────────────────────────────────────────────────────
    def verificar_conceptos(
        self,
        concepts: list[dict],
        descartar: bool = True,
        min_confianza_sin_verificar: float = 0.35,
    ) -> list[dict]:
        """Marca cada concepto con su nivel de anclaje y descarta lo inventado.

        Tres niveles:
          · `verificado`  — cita encontrada en el documento.
          · `parcial`     — la cita no aparece pero el título sí. Puede ser una
                            cita mal transcrita sobre un concepto real.
          · `sin_anclaje` — ni cita ni título aparecen. Es el caso del PCCI
                            inventado, y es el que se descarta.
        """
        salida: list[dict] = []
        for c in concepts:
            cita = (c.get("evidencia_textual") or "").strip()
            titulo_ok, diagnostico = diagnostico_termino(c.get("title", ""), self.fuente_norm)

            if cita:
                encontrada, sim = cita_presente(cita, self.fuente_norm, self.fuente_ngramas)
            else:
                encontrada, sim = False, 0.0
                self.stats["conceptos_sin_cita"] += 1

            if encontrada:
                nivel = "verificado"
                self.stats["conceptos_verificados"] += 1
            elif titulo_ok:
                nivel = "parcial"
                if cita:
                    self.stats["conceptos_cita_no_encontrada"] += 1
            else:
                nivel = "sin_anclaje"
                self.stats["conceptos_titulo_ausente"] += 1
                if diagnostico == "sigla_presente_desarrollo_inventado":
                    self.stats["siglas_desarrolladas_sin_respaldo"] = (
                        self.stats.get("siglas_desarrolladas_sin_respaldo", 0) + 1
                    )

            c["anclaje_textual"] = nivel
            c["similitud_cita"] = sim

            if nivel == "verificado":
                pass
            elif nivel == "parcial":
                # La confianza no puede superar la del anclaje: el modelo no
                # puede estar más seguro que la evidencia que aporta.
                c["confidence_extraction"] = min(
                    float(c.get("confidence_extraction") or 0.6), 0.6
                )
            else:
                c["confidence_extraction"] = min(
                    float(c.get("confidence_extraction") or 0.6), min_confianza_sin_verificar
                )

            if descartar and nivel == "sin_anclaje":
                self.stats["conceptos_descartados"] += 1
                motivo = (
                    "la sigla aparece en el documento pero su desarrollo no: el "
                    "extractor lo inventó a partir de lo que suena plausible"
                    if diagnostico == "sigla_presente_desarrollo_inventado"
                    else "ni el término ni la cita aparecen en el documento"
                )
                self.descartados.append({
                    "id": c.get("id"),
                    "title": c.get("title"),
                    "motivo": motivo,
                    "diagnostico": diagnostico,
                    "cita_declarada": cita[:160],
                })
                logger.warning("[grounding] descartado por falta de anclaje: %s", c.get("title"))
                continue
            salida.append(c)
        return salida

    # ── Otros objetos con cita ────────────────────────────────────────────
    def verificar_items(
        self,
        items: list[dict],
        campo_cita: str = "evidencia_textual",
        etiqueta: str = "item",
        descartar: bool = False,
    ) -> list[dict]:
        """Igual que arriba, para casos, tesis y marcos.

        Por defecto NO descarta: en estas capas el modelo sintetiza más y una
        cita fallida no prueba invención. Baja la confianza y marca.
        """
        salida = []
        verificados = no_verificados = 0
        for item in items or []:
            cita = (item.get(campo_cita) or "").strip()
            encontrada, sim = (
                cita_presente(cita, self.fuente_norm, self.fuente_ngramas)
                if cita else (False, 0.0)
            )
            item["anclaje_textual"] = "verificado" if encontrada else "sin_verificar"
            item["similitud_cita"] = sim
            if encontrada:
                verificados += 1
            else:
                no_verificados += 1
                item["confidence_extraction"] = min(
                    float(item.get("confidence_extraction") or 0.6), 0.5
                )
                if descartar:
                    continue
            salida.append(item)
        self.stats[f"{etiqueta}_verificados"] = verificados
        self.stats[f"{etiqueta}_sin_verificar"] = no_verificados
        return salida

    # ── Relaciones ────────────────────────────────────────────────────────
    def verificar_relaciones(self, relations: list[dict]) -> list[dict]:
        """Una relación se ancla si su descripción cita el texto.

        No se descartan: una relación puede ser una inferencia legítima sobre
        dos frases separadas. Pero se marca, porque una relación inferida no
        debería pesar igual que una afirmada.
        """
        for r in relations or []:
            cita = (r.get("evidencia_textual") or r.get("description") or "").strip()
            encontrada, sim = (
                cita_presente(cita, self.fuente_norm, self.fuente_ngramas)
                if cita else (False, 0.0)
            )
            r["anclaje_textual"] = "verificado" if encontrada else "inferida"
            if not encontrada:
                r["confidence_extraction"] = min(
                    float(r.get("confidence_extraction") or 0.6), 0.7
                )
        return relations

    def informe(self) -> dict:
        return {
            **self.stats,
            "descartados": self.descartados,
            "tasa_verificacion": round(
                self.stats["conceptos_verificados"]
                / max(1, self.stats["conceptos_verificados"]
                      + self.stats["conceptos_cita_no_encontrada"]
                      + self.stats["conceptos_titulo_ausente"]),
                2,
            ),
        }
