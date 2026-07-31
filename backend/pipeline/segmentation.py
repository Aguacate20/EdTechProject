import re
from dataclasses import dataclass
import fitz  # PyMuPDF

@dataclass
class TextSegment:
    text: str
    section_title: str
    pages: list[int]
    char_count: int = 0
    def __post_init__(self):
        self.char_count = len(self.text)

def extract_segments(pdf_bytes: bytes, max_chars_per_segment: int = 4000) -> list[TextSegment]:
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    segments: list[TextSegment] = []
    current_section = "Introducción"
    current_text_parts: list[str] = []
    current_pages: list[int] = []
    current_chars = 0

    for page_num, page in enumerate(doc, start=1):
        blocks = page.get_text("dict")["blocks"]
        for block in blocks:
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                line_text = " ".join(span["text"] for span in line.get("spans", [])).strip()
                if not line_text:
                    continue
                if _is_likely_heading(line) and current_text_parts:
                    _flush_segment(current_text_parts, current_section, current_pages, segments)
                    current_text_parts = []
                    current_pages = []
                    current_chars = 0
                    current_section = line_text
                    continue
                current_text_parts.append(line_text)
                if page_num not in current_pages:
                    current_pages.append(page_num)
                current_chars += len(line_text)
                if current_chars >= max_chars_per_segment:
                    _flush_segment(current_text_parts, current_section, current_pages, segments)
                    current_text_parts = []
                    current_pages = [page_num]
                    current_chars = 0

    if current_text_parts:
        _flush_segment(current_text_parts, current_section, current_pages, segments)
    doc.close()
    return [s for s in segments if s.char_count > 100]

def _is_likely_heading(line: dict) -> bool:
    spans = line.get("spans", [])
    if not spans:
        return False
    text = " ".join(s["text"] for s in spans).strip()
    if len(text) > 120 or text.endswith((".", ",", ";")):
        return False
    avg_size = sum(s.get("size", 0) for s in spans) / len(spans)
    is_bold = any("Bold" in s.get("font", "") for s in spans)
    return is_bold or avg_size > 13

def _flush_segment(parts, section, pages, segments):
    text = re.sub(r"\s+", " ", " ".join(parts)).strip()
    if text:
        segments.append(TextSegment(text=text, section_title=section, pages=list(pages)))