"""Locate metadata headers and title lines in collected documents.

Stdlib only. Shared by context.py (metadata fields as brief context) and
cases.py (the document body that briefs must not quote excludes the header
and the title line).
"""

import re
from datetime import date, datetime, timedelta, timezone

RFC822_FIELD = re.compile(r"^([A-Z][A-Za-z-]*):[ \t]*(.*)$")
DASH_FIELD = re.compile(r"^\s*[-*]\s+([A-Z][A-Za-z0-9 ()/#-]*?):[ \t]*(.*)$")  # old Rust RFCs: "- RFC PR #:"
GO_FIELD = re.compile(r"^(Authors?(?:\(s\))?|Last updated|Updated|Status|Discussion at|Discussion|Proposal)\s*:?\s*(.*)$", re.I)
TABLE_ROW = re.compile(r"^\s*\|(.+)\|\s*$")


def line_offsets(text):
    """Yield (start_offset, line_without_newline)."""
    pos = 0
    for line in text.splitlines(keepends=True):
        yield pos, line.rstrip("\r\n")
        pos += len(line)


def parse_rfc822(text):
    """PEP-style `Field: value` block at the very top, ended by a blank line."""
    fields, key, end = {}, None, 0
    for start, line in line_offsets(text):
        if not line.strip():
            if fields:
                end = start
                break
            continue
        m = RFC822_FIELD.match(line)
        if m and not line.startswith((" ", "\t")):
            key = m.group(1)
            fields[key] = m.group(2).strip()
        elif key and line.startswith((" ", "\t")):
            fields[key] = (fields[key] + " " + line.strip()).strip()
        else:
            return {}, 0
        end = start + len(line)
    return fields, end


def parse_dash_list(text, max_lines=40):
    """Rust/Cockroach RFC `- Field: value` list before the first heading."""
    fields, end, seen = {}, 0, 0
    for start, line in line_offsets(text):
        seen += 1
        if seen > max_lines or line.startswith("#"):
            break
        m = DASH_FIELD.match(line)
        if m:
            fields[m.group(1).rstrip(" #")] = m.group(2).strip()
            end = start + len(line)
        elif line.strip() and fields:
            break
    return fields, end


def parse_go(text, max_lines=30):
    """Go design doc Author/Last updated/Discussion lines after the title."""
    fields, end, seen = {}, 0, 0
    for start, line in line_offsets(text):
        seen += 1
        if seen > max_lines or (line.startswith("## ")):
            break
        m = GO_FIELD.match(line.strip().strip("_*"))
        if m:
            fields[m.group(1).strip()] = m.group(2).strip()
            end = start + len(line)
    return fields, end


def parse_md_table(text, max_lines=40):
    """rust-goals `| Metadata | |` table directly under the title."""
    fields, end, seen, started = {}, 0, 0, False
    for start, line in line_offsets(text):
        seen += 1
        if seen > max_lines:
            break
        m = TABLE_ROW.match(line)
        if m:
            cells = [c.strip() for c in m.group(1).split("|")]
            started = True
            end = start + len(line)
            if len(cells) >= 2 and cells[0] and not set(cells[0]) <= set(":- ") and cells[0].lower() != "metadata":
                fields[cells[0]] = cells[1]
        elif started:
            break
    return fields, end


PARSERS = {"rfc822": parse_rfc822, "dash_list": parse_dash_list, "go": parse_go, "md_table": parse_md_table}


def parse_header(fmt, text):
    """Return (fields, header_end_offset) for a known header format, else ({}, 0)."""
    if fmt not in PARSERS:
        return {}, 0
    return PARSERS[fmt](text)


def title_span(text, limit=4000):
    """Offsets of the first heading line (markdown ATX/setext, RST title), if near the top."""
    head = text[:limit]
    m = re.search(r"(?m)^#{1,2}[ \t]+\S.*$", head)
    if m:
        return m.start(), m.end()
    m = re.search(r"(?m)^([^\n]{3,200})\n(=+|-+)[ \t]*$", head)
    if m and len(m.group(2)) >= len(m.group(1).strip()) * 0.6:
        return m.start(), m.end()
    return None


def body_text(text, header_format=None):
    """Document text with the metadata header and title line blanked out."""
    _, end = parse_header(header_format, text) if header_format else ({}, 0)
    body = " " * end + text[end:]
    span = title_span(body)
    if span:
        body = body[:span[0]] + " " * (span[1] - span[0]) + body[span[1]:]
    return body


MONTH_NAMES = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def parse_date(value):
    """ISO day (YYYY-MM-DD) from the date forms found in headers and records, else None.

    Accepts ISO dates and timestamps (UTC offsets are applied), 05-Sep-2022,
    2017/09/25 and "September 25, 2017". Returns None for anything vaguer.
    """
    if not value:
        return None
    value = str(value).strip()
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::(\d{2})(?:\.\d+)?)?(Z|([+-])(\d{2}):?(\d{2}))?", value)
    if m:
        # built field by field: fromisoformat before Python 3.11 rejects "+0000" and 2- or 9-digit fractions
        y, mo, d, hh, mm = (int(m.group(i)) for i in range(1, 6))
        try:
            stamp = datetime(y, mo, d, hh, mm, int(m.group(6) or 0))
        except ValueError:
            return None
        if m.group(7):
            sign = -1 if m.group(8) == "-" else 1
            offset = timedelta(hours=int(m.group(9) or 0), minutes=int(m.group(10) or 0)) * sign
            stamp = (stamp - offset).replace(tzinfo=timezone.utc)
        return stamp.date().isoformat()
    m = re.match(r"^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})\b", value)
    if m:
        y, mo, d = map(int, m.groups())
    else:
        m = re.match(r"^(\d{1,2})[- ]([A-Za-z]{3})[A-Za-z]*[- ,]+(\d{4})\b", value) or None
        if m:
            d, mo, y = int(m.group(1)), MONTH_NAMES.get(m.group(2).lower()), int(m.group(3))
        else:
            m = re.match(r"^([A-Za-z]{3})[A-Za-z]*\.?\s+(\d{1,2}),?\s+(\d{4})\b", value)
            if not m:
                return None
            mo, d, y = MONTH_NAMES.get(m.group(1).lower()), int(m.group(2)), int(m.group(3))
    try:
        return date(y, mo, d).isoformat() if mo else None
    except ValueError:
        return None
