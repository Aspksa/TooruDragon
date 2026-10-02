from __future__ import annotations

import io
import json
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path


class OCRUnavailableError(RuntimeError):
    pass


@dataclass
class OCRPage:
    page_number: int
    text: str
    confidence: float
    engine: str
    blocks: list[dict] = field(default_factory=list)
    tables: list[dict] = field(default_factory=list)
    image_path: str = ""


def _clean_text(value: str) -> str:
    return "\n".join(
        line.rstrip()
        for line in str(value or "").replace("\r\n", "\n").split("\n")
    ).strip()


def _tesseract_page(image_path: Path) -> OCRPage:
    command = [
        shutil.which("tesseract") or "tesseract",
        str(image_path),
        "stdout",
        "-l",
        "rus+eng",
        "tsv",
    ]
    proc = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        check=False,
    )
    if proc.returncode != 0:
        raise OCRUnavailableError(
            "Tesseract OCR failed: " + (proc.stderr.strip() or f"exit {proc.returncode}")
        )

    rows = []
    lines: dict[tuple[int, int, int], list[str]] = {}
    confidences = []
    for index, line in enumerate(proc.stdout.splitlines()):
        if index == 0 or not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) < 12:
            continue
        try:
            level = int(parts[0])
            block_num = int(parts[2])
            par_num = int(parts[3])
            line_num = int(parts[4])
            left = int(parts[6])
            top = int(parts[7])
            width = int(parts[8])
            height = int(parts[9])
            confidence = float(parts[10])
        except ValueError:
            continue
        word = parts[11].strip()
        if level != 5 or not word:
            continue
        if confidence >= 0:
            confidences.append(confidence / 100.0)
        rows.append({
            "text": word,
            "left": left,
            "top": top,
            "width": width,
            "height": height,
            "confidence": round(max(0.0, confidence) / 100.0, 4),
        })
        lines.setdefault((block_num, par_num, line_num), []).append(word)

    text = "\n".join(
        " ".join(words)
        for _, words in sorted(lines.items())
        if words
    ).strip()
    if not text:
        raise OCRUnavailableError("Tesseract returned no text")
    confidence = (
        sum(confidences) / len(confidences)
        if confidences
        else 0.65
    )
    return OCRPage(
        page_number=1,
        text=text,
        confidence=round(confidence, 4),
        engine="tesseract",
        blocks=rows,
        image_path=str(image_path),
    )


class OCRService:
    """Single-pass page extraction/OCR with deterministic local backends.

    No LLM or Ollama is used. Text PDFs are read directly. Scans use
    pdftoppm+tesseract when available or Windows.Media.Ocr on Windows.
    """

    def extract_pages(self, filename: str, raw: bytes) -> list[OCRPage]:
        suffix = Path(filename).suffix.lower()
        if suffix == ".pdf":
            direct = self._pdf_text_pages(raw)
            if direct and all(len(page.text.strip()) >= 20 for page in direct):
                return direct

            raster = self._pdf_tesseract(raw)
            if raster:
                return raster

            windows = self._windows_ocr(filename, raw)
            if windows:
                return windows

            if direct:
                # Keep any text that was available; low-confidence blank pages
                # remain explicit review items instead of being silently dropped.
                return direct
            raise OCRUnavailableError(
                "Scanned PDF requires OCR. Install Tesseract + pdftoppm or use "
                "Windows OCR; no OCR backend is available."
            )

        if suffix in {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff"}:
            if shutil.which("tesseract"):
                with tempfile.TemporaryDirectory(prefix="tooru-ocr-") as tmp:
                    path = Path(tmp) / ("input" + suffix)
                    path.write_bytes(raw)
                    page = _tesseract_page(path)
                    page.page_number = 1
                    page.image_path = ""
                    return [page]
            windows = self._windows_ocr(filename, raw)
            if windows:
                return windows
            raise OCRUnavailableError(
                "Image OCR requires Tesseract or Windows OCR."
            )

        raise ValueError("waybill batch supports PDF/JPG/PNG/TIFF images")

    @staticmethod
    def _pdf_text_pages(raw: bytes) -> list[OCRPage]:
        try:
            from pypdf import PdfReader
        except ImportError:
            return []
        try:
            reader = PdfReader(io.BytesIO(raw))
        except Exception:
            return []

        result = []
        for index, page in enumerate(reader.pages, start=1):
            text = _clean_text(page.extract_text() or "")
            confidence = 0.99 if text else 0.0
            result.append(OCRPage(
                page_number=index,
                text=text,
                confidence=confidence,
                engine="pypdf_text",
                blocks=(
                    [{"text": text, "page": index, "confidence": confidence}]
                    if text
                    else []
                ),
            ))
        return result

    @staticmethod
    def _pdf_tesseract(raw: bytes) -> list[OCRPage]:
        pdftoppm = shutil.which("pdftoppm")
        tesseract = shutil.which("tesseract")
        if not pdftoppm or not tesseract:
            return []

        with tempfile.TemporaryDirectory(prefix="tooru-pdf-ocr-") as tmp:
            root = Path(tmp)
            pdf_path = root / "batch.pdf"
            pdf_path.write_bytes(raw)
            prefix = root / "page"
            proc = subprocess.run(
                [pdftoppm, "-jpeg", "-r", "220", str(pdf_path), str(prefix)],
                capture_output=True,
                text=True,
                timeout=300,
                check=False,
            )
            if proc.returncode != 0:
                return []
            images = sorted(
                root.glob("page-*.jpg"),
                key=lambda path: int(re.search(r"(\d+)$", path.stem).group(1)),
            )
            result = []
            for index, image_path in enumerate(images, start=1):
                page = _tesseract_page(image_path)
                page.page_number = index
                # Temporary image is only an OCR working file. The immutable
                # original PDF remains the evidentiary source.
                page.image_path = ""
                result.append(page)
            return result

    @staticmethod
    def _windows_ocr(filename: str, raw: bytes) -> list[OCRPage]:
        if os.name != "nt":
            return []
        powershell = shutil.which("powershell.exe") or shutil.which("powershell")
        if not powershell:
            return []
        script = Path(__file__).resolve().parents[2] / "scripts" / "windows_ocr.ps1"
        if not script.exists():
            return []

        with tempfile.TemporaryDirectory(prefix="tooru-win-ocr-") as tmp:
            source = Path(tmp) / Path(filename).name
            source.write_bytes(raw)
            proc = subprocess.run(
                [
                    powershell,
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(script),
                    "-InputPath",
                    str(source),
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=300,
                check=False,
            )
            if proc.returncode != 0:
                return []
            try:
                payload = json.loads(proc.stdout)
            except json.JSONDecodeError:
                return []

        pages = []
        for item in payload.get("pages", []):
            pages.append(OCRPage(
                page_number=int(item.get("page_number") or len(pages) + 1),
                text=_clean_text(item.get("text") or ""),
                confidence=float(item.get("confidence") or 0.78),
                engine=str(item.get("engine") or "windows_ocr"),
                blocks=item.get("blocks") if isinstance(item.get("blocks"), list) else [],
                tables=item.get("tables") if isinstance(item.get("tables"), list) else [],
            ))
        return pages


class StaticOCRService(OCRService):
    """Deterministic injected page source used by integration tests."""

    def __init__(self, pages: list[OCRPage]):
        self.pages = pages

    def extract_pages(self, filename: str, raw: bytes) -> list[OCRPage]:
        return [
            OCRPage(
                page_number=page.page_number,
                text=page.text,
                confidence=page.confidence,
                engine=page.engine,
                blocks=list(page.blocks),
                tables=list(page.tables),
                image_path=page.image_path,
            )
            for page in self.pages
        ]
