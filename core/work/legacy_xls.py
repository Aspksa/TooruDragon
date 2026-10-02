from __future__ import annotations

import struct
from dataclasses import dataclass


class LegacyXlsError(ValueError):
    pass


FREESECT = 0xFFFFFFFF
ENDOFCHAIN = 0xFFFFFFFE
FATSECT = 0xFFFFFFFD
DIFSECT = 0xFFFFFFFC


def _u16(data: bytes, offset: int) -> int:
    return struct.unpack_from("<H", data, offset)[0]


def _u32(data: bytes, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def _u64(data: bytes, offset: int) -> int:
    return struct.unpack_from("<Q", data, offset)[0]


def _decode_rk(raw: int) -> float:
    if raw & 0x02:
        signed = struct.unpack("<i", struct.pack("<I", raw))[0]
        value = float(signed >> 2)
    else:
        bits = (raw & 0xFFFFFFFC) << 32
        value = struct.unpack("<d", struct.pack("<Q", bits))[0]
    if raw & 0x01:
        value /= 100.0
    return float(value)


@dataclass(frozen=True)
class XlsSheet:
    name: str
    cells: dict[tuple[int, int], object]

    def rows(self) -> list[list[object | None]]:
        if not self.cells:
            return []
        max_row = max(row for row, _ in self.cells)
        max_col = max(col for _, col in self.cells)
        result = []
        for row in range(max_row + 1):
            result.append([
                self.cells.get((row, col))
                for col in range(max_col + 1)
            ])
        return result

    def text(self) -> str:
        lines = []
        for row in self.rows():
            values = [
                "" if value is None else str(value)
                for value in row
            ]
            if any(value.strip() for value in values):
                lines.append("\t".join(values).rstrip())
        return "\n".join(lines)


class LegacyXlsWorkbook:
    """Small dependency-free reader for classic OLE/BIFF .xls files.

    The reader is intentionally narrow. It supports the BIFF5/7 cell records used by
    the fuel-card statements supplied to TooruDragon: LABEL, NUMBER, RK and MULRK.
    It never executes macros or formulas; formula records are treated only as cached
    numeric results.
    """

    def __init__(self, raw: bytes):
        self.raw = bytes(raw)
        if self.raw[:8] != b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
            raise LegacyXlsError("file is not an OLE Compound Document")

        self.sector_size = 1 << _u16(self.raw, 30)
        self.mini_sector_size = 1 << _u16(self.raw, 32)
        self.first_directory_sector = _u32(self.raw, 48)
        self.mini_cutoff = _u32(self.raw, 56)
        self.first_minifat_sector = _u32(self.raw, 60)
        self.num_minifat_sectors = _u32(self.raw, 64)
        self.first_difat_sector = _u32(self.raw, 68)
        self.num_difat_sectors = _u32(self.raw, 72)

        if self.sector_size not in {512, 4096}:
            raise LegacyXlsError("unsupported OLE sector size")
        if self.mini_sector_size != 64:
            raise LegacyXlsError("unsupported OLE mini-sector size")

        self.fat = self._read_fat()
        self.directory = self._read_directory()
        self.root_entry = next(
            (entry for entry in self.directory if entry["type"] == 5),
            None,
        )
        if self.root_entry is None:
            raise LegacyXlsError("OLE root directory entry is missing")

    def _sector(self, sector_id: int) -> bytes:
        if sector_id < 0:
            raise LegacyXlsError("negative OLE sector id")
        offset = (sector_id + 1) * self.sector_size
        end = offset + self.sector_size
        if end > len(self.raw):
            raise LegacyXlsError("OLE sector points outside the file")
        return self.raw[offset:end]

    def _chain(
        self,
        start: int,
        table: list[int],
        *,
        maximum: int = 100_000,
    ) -> list[int]:
        if start in {FREESECT, ENDOFCHAIN}:
            return []
        result = []
        seen = set()
        current = start
        while current not in {FREESECT, ENDOFCHAIN}:
            if current in seen:
                raise LegacyXlsError("OLE sector chain loop detected")
            if current < 0 or current >= len(table):
                raise LegacyXlsError("OLE sector chain is out of range")
            seen.add(current)
            result.append(current)
            if len(result) > maximum:
                raise LegacyXlsError("OLE sector chain is too long")
            current = table[current]
        return result

    def _read_fat(self) -> list[int]:
        difat = [
            _u32(self.raw, 76 + index * 4)
            for index in range(109)
        ]
        fat_sector_ids = [
            value
            for value in difat
            if value not in {FREESECT, ENDOFCHAIN}
        ]

        current = self.first_difat_sector
        for _ in range(self.num_difat_sectors):
            if current in {FREESECT, ENDOFCHAIN}:
                break
            sector = self._sector(current)
            values = struct.unpack(
                "<" + "I" * (self.sector_size // 4),
                sector,
            )
            fat_sector_ids.extend(
                value
                for value in values[:-1]
                if value not in {FREESECT, ENDOFCHAIN}
            )
            current = values[-1]

        fat = []
        for sector_id in fat_sector_ids:
            if sector_id in {FATSECT, DIFSECT}:
                continue
            sector = self._sector(sector_id)
            fat.extend(struct.unpack(
                "<" + "I" * (self.sector_size // 4),
                sector,
            ))
        if not fat:
            raise LegacyXlsError("OLE FAT is empty")
        return fat

    def _read_directory(self) -> list[dict]:
        chain = self._chain(self.first_directory_sector, self.fat)
        stream = b"".join(self._sector(sector_id) for sector_id in chain)
        result = []
        for offset in range(0, len(stream), 128):
            entry = stream[offset:offset + 128]
            if len(entry) < 128:
                break
            name_length = _u16(entry, 64)
            if name_length >= 2:
                name = entry[:name_length - 2].decode("utf-16le", "ignore")
            else:
                name = ""
            result.append({
                "name": name,
                "type": entry[66],
                "start_sector": _u32(entry, 116),
                "size": _u64(entry, 120),
            })
        return result

    def _mini_fat(self) -> list[int]:
        if self.num_minifat_sectors <= 0:
            return []
        chain = self._chain(self.first_minifat_sector, self.fat)
        raw = b"".join(
            self._sector(sector_id)
            for sector_id in chain[:self.num_minifat_sectors]
        )
        if not raw:
            return []
        return list(struct.unpack(
            "<" + "I" * (len(raw) // 4),
            raw[:len(raw) - (len(raw) % 4)],
        ))

    def _stream(self, entry: dict) -> bytes:
        size = int(entry["size"])
        start = int(entry["start_sector"])
        if size <= 0:
            return b""

        if size < self.mini_cutoff:
            mini_fat = self._mini_fat()
            if not mini_fat:
                raise LegacyXlsError("OLE mini FAT is missing")
            root_chain = self._chain(
                int(self.root_entry["start_sector"]),
                self.fat,
            )
            mini_stream = b"".join(
                self._sector(sector_id)
                for sector_id in root_chain
            )
            result = bytearray()
            for mini_id in self._chain(start, mini_fat):
                offset = mini_id * self.mini_sector_size
                result.extend(
                    mini_stream[offset:offset + self.mini_sector_size]
                )
            return bytes(result[:size])

        chain = self._chain(start, self.fat)
        return b"".join(
            self._sector(sector_id)
            for sector_id in chain
        )[:size]

    def workbook_stream(self) -> bytes:
        entry = next(
            (
                item for item in self.directory
                if item["type"] == 2
                and item["name"] in {"Workbook", "Book"}
            ),
            None,
        )
        if entry is None:
            raise LegacyXlsError("Workbook/Book stream is missing")
        return self._stream(entry)

    @staticmethod
    def _records(stream: bytes, start: int = 0):
        position = start
        while position + 4 <= len(stream):
            record_id, length = struct.unpack_from("<HH", stream, position)
            payload_start = position + 4
            payload_end = payload_start + length
            if payload_end > len(stream):
                raise LegacyXlsError("truncated BIFF record")
            yield position, record_id, stream[payload_start:payload_end]
            position = payload_end

    @staticmethod
    def _codec(stream: bytes) -> str:
        for _, record_id, payload in LegacyXlsWorkbook._records(stream):
            if record_id == 0x0042 and len(payload) >= 2:
                codepage = _u16(payload, 0)
                if codepage == 1200:
                    return "utf-16le"
                try:
                    "test".encode(f"cp{codepage}")
                    return f"cp{codepage}"
                except LookupError:
                    pass
            if record_id == 0x000A:
                break
        return "cp1251"

    @staticmethod
    def _sheet_entries(stream: bytes, codec: str) -> list[tuple[int, str]]:
        result = []
        for _, record_id, payload in LegacyXlsWorkbook._records(stream):
            if record_id == 0x0085 and len(payload) >= 7:
                bof_offset = _u32(payload, 0)
                name_length = payload[6]
                raw_name = payload[7:7 + name_length]
                name = raw_name.decode(codec, "replace")
                result.append((bof_offset, name or "Sheet"))
            if record_id == 0x000A:
                break
        return result

    @staticmethod
    def _biff_version(stream: bytes) -> int:
        for _, record_id, payload in LegacyXlsWorkbook._records(stream):
            if record_id == 0x0809 and len(payload) >= 2:
                return _u16(payload, 0)
        raise LegacyXlsError("BIFF BOF record is missing")

    @staticmethod
    def _parse_sheet(
        stream: bytes,
        start: int,
        codec: str,
        *,
        biff_version: int,
    ) -> dict[tuple[int, int], object]:
        if biff_version not in {0x0500, 0x0600}:
            raise LegacyXlsError(
                f"unsupported BIFF version 0x{biff_version:04x}"
            )

        cells: dict[tuple[int, int], object] = {}
        for _, record_id, payload in LegacyXlsWorkbook._records(stream, start):
            if record_id == 0x000A:
                break

            if record_id == 0x0204 and len(payload) >= 8:
                row, col, _xf, length = struct.unpack_from(
                    "<HHHH",
                    payload,
                    0,
                )
                raw_value = payload[8:8 + length]
                if biff_version == 0x0600:
                    # BIFF8 normally uses LABELSST. Direct LABEL values are rare;
                    # decode a simple direct Unicode label if one is present.
                    value = raw_value.decode("utf-16le", "replace")
                else:
                    value = raw_value.decode(codec, "replace")
                cells[(row, col)] = value
                continue

            if record_id == 0x00FD:
                raise LegacyXlsError(
                    "BIFF8 shared-string .xls is not supported by the built-in "
                    "reader yet"
                )

            if record_id == 0x0203 and len(payload) >= 14:
                row, col, _xf = struct.unpack_from("<HHH", payload, 0)
                cells[(row, col)] = struct.unpack_from("<d", payload, 6)[0]
                continue

            if record_id == 0x027E and len(payload) >= 10:
                row, col, _xf, raw_rk = struct.unpack_from(
                    "<HHHI",
                    payload,
                    0,
                )
                cells[(row, col)] = _decode_rk(raw_rk)
                continue

            if record_id == 0x00BD and len(payload) >= 12:
                row, first_col = struct.unpack_from("<HH", payload, 0)
                last_col = _u16(payload, len(payload) - 2)
                offset = 4
                col = first_col
                while offset + 6 <= len(payload) - 2 and col <= last_col:
                    _xf, raw_rk = struct.unpack_from("<HI", payload, offset)
                    cells[(row, col)] = _decode_rk(raw_rk)
                    offset += 6
                    col += 1
                continue

            if record_id == 0x0002 and len(payload) >= 9:
                row, col, _xf = struct.unpack_from("<HHH", payload, 0)
                cells[(row, col)] = float(_u16(payload, 7))
                continue

            if record_id == 0x0006 and len(payload) >= 14:
                row, col, _xf = struct.unpack_from("<HHH", payload, 0)
                result = payload[6:14]
                # Do not evaluate formulas. Preserve only numeric cached values.
                if result[6:8] != b"\xff\xff":
                    cells[(row, col)] = struct.unpack("<d", result)[0]

        return cells

    def sheets(self) -> list[XlsSheet]:
        stream = self.workbook_stream()
        biff_version = self._biff_version(stream)
        codec = self._codec(stream)
        entries = self._sheet_entries(stream, codec)
        if not entries:
            # Fallback for single-sheet legacy exports without BOUNDSHEET.
            entries = [(0, "Sheet1")]

        result = []
        for offset, name in entries:
            cells = self._parse_sheet(
                stream,
                offset,
                codec,
                biff_version=biff_version,
            )
            result.append(XlsSheet(name=name, cells=cells))
        return result

    def first_sheet(self) -> XlsSheet:
        sheets = self.sheets()
        if not sheets:
            raise LegacyXlsError("workbook has no worksheets")
        return sheets[0]

    def text(self) -> str:
        chunks = []
        for sheet in self.sheets():
            text = sheet.text()
            if text:
                chunks.append(f"[{sheet.name}]\n{text}")
        return "\n\n".join(chunks)
