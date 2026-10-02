from __future__ import annotations

import re
from dataclasses import dataclass

from core.work.waybill_ocr import OCRPage


DATE_RE = re.compile(r"(?<!\d)(\d{1,2}[./-]\d{1,2}[./-]\d{4})(?!\d)")
TIME_RE = re.compile(r"(?<!\d)([0-2]?\d[:.]\d{2})(?!\d)")
WAYBILL_HEADER_RE = re.compile(r"путев\w*\s+лист", re.IGNORECASE)
WAYBILL_NUMBER_RE = re.compile(
    r"путев\w*\s+лист\w*\s*(?:№|N|номер)?\s*[:#-]?\s*"
    r"([A-ZА-ЯЁ0-9][A-ZА-ЯЁ0-9./_-]{0,30})",
    re.IGNORECASE,
)
VIN_RE = re.compile(r"\b[A-HJ-NPR-Z0-9]{17}\b", re.IGNORECASE)
PLATE_RE = re.compile(
    r"(?<![A-ZА-ЯЁ0-9])"
    r"([АВЕКМНОРСТУХABEKMHOPCTYX]\s*\d{3}\s*"
    r"[АВЕКМНОРСТУХABEKMHOPCTYX]{2}\s*\d{2,3})"
    r"(?![A-ZА-ЯЁ0-9])",
    re.IGNORECASE,
)
CARD_RE = re.compile(r"(?<!\d)(\d{10,22})(?!\d)")
NUMBER_RE = re.compile(r"-?\d+(?:[.,]\d+)?")


CYR_LAT = str.maketrans({
    "А": "A",
    "В": "B",
    "Е": "E",
    "К": "K",
    "М": "M",
    "Н": "H",
    "О": "O",
    "Р": "P",
    "С": "C",
    "Т": "T",
    "У": "Y",
    "Х": "X",
})


def normalize_plate(value: str) -> str:
    text = re.sub(r"[\s\-_]+", "", str(value or "").upper().replace("Ё", "Е"))
    return text.translate(CYR_LAT)


def normalize_name(value: str) -> str:
    return re.sub(
        r"[^A-ZА-ЯЁ0-9]+",
        " ",
        str(value or "").upper().replace("Ё", "Е"),
    ).strip()


def parse_date(value: str) -> str | None:
    raw = str(value or "").strip()
    match = DATE_RE.search(raw)
    if not match:
        return None
    parts = re.split(r"[./-]", match.group(1))
    try:
        day, month, year = map(int, parts)
        if len(parts[0]) == 4:
            year, month, day = map(int, parts)
        from datetime import date
        return date(year, month, day).isoformat()
    except ValueError:
        return None


def parse_time(value: str) -> str | None:
    match = TIME_RE.search(str(value or ""))
    if not match:
        return None
    raw = match.group(1).replace(".", ":")
    hour, minute = map(int, raw.split(":"))
    if hour > 23 or minute > 59:
        return None
    return f"{hour:02d}:{minute:02d}"


def parse_number(value: str) -> float | None:
    match = NUMBER_RE.search(str(value or "").replace(" ", ""))
    if not match:
        return None
    try:
        return float(match.group(0).replace(",", "."))
    except ValueError:
        return None


def _line_excerpt(text: str, start: int, end: int) -> str:
    line_start = text.rfind("\n", 0, start) + 1
    line_end = text.find("\n", end)
    if line_end < 0:
        line_end = len(text)
    return text[line_start:line_end].strip()[:300]


@dataclass(frozen=True)
class ExtractedField:
    key: str
    value: str
    confidence: float
    page_number: int
    excerpt: str
    char_start: int
    char_end: int

    def as_dict(self) -> dict:
        return {
            "key": self.key,
            "value": self.value,
            "confidence": round(self.confidence, 4),
            "page_number": self.page_number,
            "excerpt": self.excerpt,
            "char_start": self.char_start,
            "char_end": self.char_end,
        }


def _field(
    key: str,
    value: str,
    base_confidence: float,
    page: OCRPage,
    text: str,
    start: int,
    end: int,
) -> ExtractedField:
    return ExtractedField(
        key=key,
        value=str(value).strip(),
        confidence=max(0.0, min(1.0, base_confidence * max(0.2, page.confidence))),
        page_number=page.page_number,
        excerpt=_line_excerpt(text, start, end),
        char_start=start,
        char_end=end,
    )


def _labeled_line(
    page: OCRPage,
    key: str,
    patterns: list[tuple[re.Pattern, float]],
    transform=None,
) -> ExtractedField | None:
    text = page.text
    for pattern, base in patterns:
        match = pattern.search(text)
        if not match:
            continue
        value = match.group(1).strip(" :;-")
        if transform:
            value = transform(value)
        if value in {None, ""}:
            continue
        return _field(
            key,
            str(value),
            base,
            page,
            text,
            match.start(1),
            match.end(1),
        )
    return None


LABEL_LINE_END = r"([^\n\r]{1,90})"
DRIVER_VALUE = r"([А-ЯЁA-Z][А-Яа-яЁёA-Za-z .'-]{2,80})"


PATTERNS = {
    "organization": [
        (re.compile(r"(?im)^\s*(?:организация|предприятие)\s*[:\-]\s*" + LABEL_LINE_END), 0.98),
    ],
    "department": [
        (re.compile(r"(?im)^\s*(?:подразделение|отдел|служба)\s*[:\-]\s*" + LABEL_LINE_END), 0.97),
    ],
    "vehicle_make_model": [
        (re.compile(r"(?im)^\s*(?:марка(?:\s+и\s+модель)?\s+автомобиля|автомобиль)\s*[:\-]\s*" + LABEL_LINE_END), 0.96),
    ],
    "garage_number": [
        (re.compile(r"(?im)^\s*(?:гаражн(?:ый|ого)\s*(?:номер|№)|гаражный\s*№)\s*[:\-]?\s*([A-ZА-ЯЁ0-9./_-]{1,30})"), 0.96),
    ],
    "driver_name": [
        (re.compile(r"(?im)^\s*водител[ья]\s*[:\-]\s*" + DRIVER_VALUE), 0.98),
        (re.compile(r"(?im)^\s*водитель\s+" + DRIVER_VALUE), 0.92),
    ],
    "personnel_number": [
        (re.compile(r"(?im)(?:табельн(?:ый|ого)\s*(?:номер|№)|таб\.\s*№)\s*[:\-]?\s*([A-ZА-ЯЁ0-9./_-]{1,30})"), 0.97),
    ],
    "departure_time": [
        (re.compile(r"(?im)(?:время\s+выезда|выезд(?:\s+из\s+гаража)?)\s*[:\-]?\s*([0-2]?\d[:.]\d{2})"), 0.98),
    ],
    "return_time": [
        (re.compile(r"(?im)(?:время\s+возвращения|возвращение(?:\s+в\s+гараж)?)\s*[:\-]?\s*([0-2]?\d[:.]\d{2})"), 0.98),
    ],
    "odometer_start": [
        (re.compile(r"(?im)(?:одометр|спидометр|показан\w*\s+спидометра)[^\n]{0,40}(?:начал|выезд)[^\d-]{0,20}(-?\d[\d ]*(?:[.,]\d+)?)"), 0.94),
        (re.compile(r"(?im)^\s*(?:пробег|одометр)\s+начало\s*[:\-]\s*(-?\d[\d ]*(?:[.,]\d+)?)"), 0.98),
    ],
    "odometer_end": [
        (re.compile(r"(?im)(?:одометр|спидометр|показан\w*\s+спидометра)[^\n]{0,40}(?:конец|возвращ)[^\d-]{0,20}(-?\d[\d ]*(?:[.,]\d+)?)"), 0.94),
        (re.compile(r"(?im)^\s*(?:пробег|одометр)\s+конец\s*[:\-]\s*(-?\d[\d ]*(?:[.,]\d+)?)"), 0.98),
    ],
    "fuel_open_l": [
        (re.compile(r"(?im)(?:остаток\s+топлива|горючего)[^\n]{0,35}(?:начал|выезд)[^\d-]{0,15}(-?\d+(?:[.,]\d+)?)"), 0.96),
    ],
    "fuel_close_l": [
        (re.compile(r"(?im)(?:остаток\s+топлива|горючего)[^\n]{0,35}(?:конец|возвращ)[^\d-]{0,15}(-?\d+(?:[.,]\d+)?)"), 0.96),
    ],
    "fuel_issued_l": [
        (re.compile(r"(?im)(?:выдано\s+топлива|выдано\s+горючего|получено\s+топлива)\s*[:\-]?\s*(-?\d+(?:[.,]\d+)?)"), 0.96),
    ],
    "refueled_l": [
        (re.compile(r"(?im)(?:заправлено|заправка(?:\s+всего)?)\s*[:\-]?\s*(-?\d+(?:[.,]\d+)?)"), 0.94),
    ],
    "fuel_name": [
        (re.compile(r"(?im)(?:марка\s+топлива|вид\s+топлива|топливо)\s*[:\-]\s*([^\n\r]{1,50})"), 0.94),
    ],
    "route": [
        (re.compile(r"(?im)^\s*(?:маршрут|пункты\s+следования)\s*[:\-]\s*" + LABEL_LINE_END), 0.92),
    ],
    "assignment_text": [
        (re.compile(r"(?im)^\s*(?:задание|задание\s+водителю)\s*[:\-]\s*" + LABEL_LINE_END), 0.92),
    ],
    "note": [
        (re.compile(r"(?im)^\s*(?:примечание|особые\s+отметки)\s*[:\-]\s*" + LABEL_LINE_END), 0.90),
    ],
    "fuel_card_number": [
        (re.compile(r"(?im)(?:топливн\w*\s+карт\w*|карта\s+ГСМ)\s*(?:№|номер)?\s*[:\-]?\s*(\d{10,22})"), 0.99),
    ],
}


NUMERIC_FIELDS = {
    "odometer_start",
    "odometer_end",
    "fuel_open_l",
    "fuel_close_l",
    "fuel_issued_l",
    "refueled_l",
}


def extract_page_fields(page: OCRPage) -> dict[str, ExtractedField]:
    text = page.text
    result: dict[str, ExtractedField] = {}

    number = WAYBILL_NUMBER_RE.search(text)
    if number:
        result["waybill_number"] = _field(
            "waybill_number",
            number.group(1),
            0.99,
            page,
            text,
            number.start(1),
            number.end(1),
        )

    date_matches = list(DATE_RE.finditer(text))
    if date_matches:
        chosen = date_matches[0]
        parsed = parse_date(chosen.group(1))
        if parsed:
            result["trip_date"] = _field(
                "trip_date",
                parsed,
                0.96,
                page,
                text,
                chosen.start(1),
                chosen.end(1),
            )

    plate = None
    labeled_plate = re.search(
        r"(?im)(?:гос(?:ударственн\w*)?\s*(?:номер|№)|рег\.?\s*(?:номер|№))"
        r"\s*[:\-]?\s*"
        r"([АВЕКМНОРСТУХABEKMHOPCTYX]\s*\d{3}\s*"
        r"[АВЕКМНОРСТУХABEKMHOPCTYX]{2}\s*\d{2,3})",
        text,
    )
    if labeled_plate:
        plate = (labeled_plate, 0.99)
    else:
        generic = PLATE_RE.search(text)
        if generic:
            plate = (generic, 0.88)
    if plate:
        match, base = plate
        result["vehicle_plate"] = _field(
            "vehicle_plate",
            normalize_plate(match.group(1)),
            base,
            page,
            text,
            match.start(1),
            match.end(1),
        )

    vin = VIN_RE.search(text)
    if vin:
        result["vehicle_vin"] = _field(
            "vehicle_vin",
            vin.group(0).upper(),
            0.99,
            page,
            text,
            vin.start(),
            vin.end(),
        )

    for key, patterns in PATTERNS.items():
        transform = None
        if key in {"departure_time", "return_time"}:
            transform = parse_time
        elif key in NUMERIC_FIELDS:
            transform = lambda value: (
                str(parse_number(value))
                if parse_number(value) is not None
                else ""
            )
        field = _labeled_line(page, key, patterns, transform=transform)
        if field:
            result[key] = field

    return result


def extract_group_fields(pages: list[OCRPage]) -> dict[str, dict]:
    selected: dict[str, ExtractedField] = {}
    for page in pages:
        for key, field in extract_page_fields(page).items():
            existing = selected.get(key)
            if existing is None or field.confidence > existing.confidence:
                selected[key] = field

    # If a long number was seen near a "карта" label but the strict pattern
    # missed it, use a guarded fallback.
    if "fuel_card_number" not in selected:
        for page in pages:
            for line in page.text.splitlines():
                if "карт" not in line.lower():
                    continue
                match = CARD_RE.search(line)
                if not match:
                    continue
                start = page.text.find(line) + match.start(1)
                selected["fuel_card_number"] = _field(
                    "fuel_card_number",
                    match.group(1),
                    0.84,
                    page,
                    page.text,
                    start,
                    start + len(match.group(1)),
                )
                break

    return {key: field.as_dict() for key, field in selected.items()}


def _page_anchor(page: OCRPage) -> dict:
    fields = extract_page_fields(page)
    text_lower = page.text.lower()
    return {
        "page_number": page.page_number,
        "header": bool(WAYBILL_HEADER_RE.search(page.text)),
        "reverse": any(
            marker in text_lower
            for marker in (
                "оборотная сторона",
                "оборот путевого листа",
                "продолжение путевого листа",
            )
        ),
        "number": fields.get("waybill_number").value if fields.get("waybill_number") else "",
        "date": fields.get("trip_date").value if fields.get("trip_date") else "",
        "plate": fields.get("vehicle_plate").value if fields.get("vehicle_plate") else "",
        "driver": normalize_name(fields.get("driver_name").value) if fields.get("driver_name") else "",
        "ocr_confidence": page.confidence,
    }


def split_waybill_pages(pages: list[OCRPage]) -> list[dict]:
    if not pages:
        return []

    groups: list[dict] = []
    current: dict | None = None

    for page in pages:
        anchor = _page_anchor(page)
        if current is None:
            current = {
                "pages": [page],
                "anchors": [anchor],
                "needs_review": not anchor["header"],
                "split_confidence": 0.92 if anchor["header"] else 0.55,
            }
            continue

        first = current["anchors"][0]
        starts_new = False
        ambiguous = False

        if anchor["header"]:
            if anchor["number"] and first["number"]:
                starts_new = anchor["number"] != first["number"]
            elif anchor["date"] and first["date"] and anchor["date"] != first["date"]:
                starts_new = True
            elif anchor["plate"] and first["plate"] and anchor["plate"] != first["plate"]:
                starts_new = True
            elif anchor["driver"] and first["driver"] and anchor["driver"] != first["driver"]:
                starts_new = True
            elif anchor["number"] or anchor["date"]:
                # Repeated header with same anchors is normally an additional
                # page of the same waybill.
                starts_new = False
            else:
                ambiguous = True
        elif anchor["reverse"]:
            starts_new = False
        else:
            # No document header: treat as continuation, but flag the split
            # unless strong anchors confirm the same document.
            same_plate = bool(anchor["plate"] and anchor["plate"] == first["plate"])
            same_driver = bool(anchor["driver"] and anchor["driver"] == first["driver"])
            same_date = bool(anchor["date"] and anchor["date"] == first["date"])
            ambiguous = not (same_plate or same_driver or same_date)

        if starts_new:
            groups.append(current)
            current = {
                "pages": [page],
                "anchors": [anchor],
                "needs_review": False,
                "split_confidence": 0.94,
            }
        else:
            current["pages"].append(page)
            current["anchors"].append(anchor)
            if ambiguous:
                current["needs_review"] = True
                current["split_confidence"] = min(
                    current["split_confidence"],
                    0.68,
                )

    if current is not None:
        groups.append(current)

    for group in groups:
        group["page_numbers"] = [
            page.page_number for page in group["pages"]
        ]
    return groups


def looks_like_waybill_batch(pages: list[OCRPage]) -> bool:
    if not pages:
        return False
    positive = 0
    for page in pages:
        fields = extract_page_fields(page)
        signals = [
            bool(WAYBILL_HEADER_RE.search(page.text)),
            "vehicle_plate" in fields,
            "driver_name" in fields,
            "odometer_start" in fields or "odometer_end" in fields,
            "departure_time" in fields or "return_time" in fields,
        ]
        if sum(signals) >= 2:
            positive += 1
    return positive >= max(1, len(pages) // 5)
