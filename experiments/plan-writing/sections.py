"""Detect section headings in collected document text.

Stdlib only. `headings(doc, text, raw)` returns Heading tuples whose `start`
is the offset of the first character of the heading line in `text`. The
method depends on how collect.py produced the text:

- markdown: ATX (`#`) and setext headings outside fenced code;
- rst: reStructuredText adornment (underline, optional overline), levels in
  order of first appearance; also used for plain-text docs from git sources;
- numbered: IETF RFC plain text and pdftotext output, using numbered headings
  (`3.2.`, `Appendix B.1`) that must continue a plausible numbering sequence,
  rejecting table-of-contents lines, plus known unnumbered RFC headings;
- html: headings recovered from the retained raw HTML by replaying
  collect.page_text (needs bs4) with markers around each heading;
- html-search: fallback when the replay is unavailable or does not reproduce
  the text: heading texts searched for in the flattened text. It can land on
  an earlier inline occurrence of the same words, so catalogs are built with
  the replay (cases.py refuses to build without it).
"""

import re
from collections import namedtuple
from html.parser import HTMLParser

Heading = namedtuple("Heading", "start end level title")
RFC_FILE = re.compile(r"(^|/)rfc\d+\.txt$")

FENCE = re.compile(r"^\s{0,3}(```|~~~)")
ATX = re.compile(r"^\s{0,3}(#{1,6})[ \t]+(.+?)[ \t#]*$")
SETEXT = re.compile(r"^\s{0,3}(=+|-+)[ \t]*$")
ADORN = re.compile(r"^([=\-`:'\"~^_*+#<>.])\1{2,}[ \t]*$")
NUMBERED = re.compile(r"^(?P<indent>[ \t]{0,8})(?P<num>(?:\d{1,2})(?:\.\d{1,2}){0,4})\.?[ \t]+(?P<title>[A-Z][^\n]{1,90})$")
APPENDIX = re.compile(r"^(?P<indent>[ \t]{0,8})(?:Appendix|APPENDIX)[ \t]+(?P<num>[A-Z](?:\.\d{1,2}){0,4})\.?(?:[ \t]*[:.\-]?[ \t]+(?P<title>\S[^\n]{0,90}))?$")
COLUMN_GAP = re.compile(r"(?<=\S)[ \t]{3,}(?=\S)")
TOC_LINE = re.compile(r"(\.\s?){4,}|\s\d{1,4}\s*$|_{4,}")
RFC_UNNUMBERED = {
    "abstract", "status of this memo", "copyright notice", "table of contents", "introduction", "references",
    "normative references", "informative references", "acknowledgements", "acknowledgments", "author's address",
    "authors' addresses", "authors addresses", "contributors", "security considerations", "iana considerations",
    "full copyright statement", "intellectual property", "index",
}


def _lines(text):
    pos = 0
    for line in text.splitlines(keepends=True):
        yield pos, line.rstrip("\r\n")
        pos += len(line)


def markdown_headings(text):
    out, fenced, prev = [], False, None
    for start, line in _lines(text):
        if FENCE.match(line):
            fenced = not fenced
            prev = None
            continue
        if fenced:
            continue
        m = ATX.match(line)
        if m:
            out.append(Heading(start, start + len(line), len(m.group(1)), m.group(2).strip()))
            prev = None
            continue
        m = SETEXT.match(line)
        if m and prev and prev[1].strip() and not prev[1].startswith((" " * 4, "\t", "-", "*", "|", ">")) and not ATX.match(prev[1]):
            level = 1 if m.group(1)[0] == "=" else 2
            if len(m.group(1)) >= 2 or level == 1:
                out.append(Heading(prev[0], start + len(line), level, prev[1].strip()))
                prev = None
                continue
        prev = (start, line)
    return out


def rst_headings(text):
    lines = list(_lines(text))
    styles, out, i = [], [], 0
    while i < len(lines):
        start, line = lines[i]
        over = ADORN.match(line)
        # overline + title + underline
        if over and i + 2 < len(lines):
            title, under = lines[i + 1][1], lines[i + 2][1]
            if title.strip() and not ADORN.match(title) and under.strip() == line.strip() and len(line.strip()) >= len(title.strip()):
                style = (line.strip()[0], True)
                styles.append(style) if style not in styles else None
                out.append(Heading(start, lines[i + 2][0] + len(under), styles.index(style) + 1, title.strip()))
                i += 3
                continue
        # title + underline
        if i + 1 < len(lines) and line.strip() and not line[0].isspace() and not ADORN.match(line):
            under = lines[i + 1][1]
            m = ADORN.match(under)
            prev_blank = i == 0 or not lines[i - 1][1].strip() or ADORN.match(lines[i - 1][1])
            if m and prev_blank and len(under.rstrip()) >= len(line.rstrip()) and len(line) <= 120:
                style = (under.strip()[0], False)
                styles.append(style) if style not in styles else None
                out.append(Heading(start, lines[i + 1][0] + len(under), styles.index(style) + 1, line.strip()))
                i += 2
                continue
        i += 1
    return out


def _key(num):
    parts = num.split(".")
    head = parts[0]
    first = (1000 + ord(head) - ord("A")) if head.isalpha() else int(head)
    return (first,) + tuple(int(p) for p in parts[1:])


def _follows(prev, cur):
    """True when `cur` is a plausible next section number after `prev`."""
    if prev is None:
        return len(cur) == 1 or (len(cur) == 2 and cur[1] == 1)
    if cur == prev + (1,):
        return True
    if len(cur) == 2 and cur[1] == 1 and 1 <= cur[0] - prev[0] <= 2:
        return True  # first subsection of a chapter whose own heading was not detected
    for k in range(len(prev)):
        if cur[:-1] == prev[:k] and len(cur) == k + 1 and 1 <= cur[k] - prev[k] <= (2 if k == 0 else 1):
            return True
    return len(cur) == 1 and cur[0] == 1000 and prev[0] < 1000


def numbered_headings(text, unnumbered=True, max_indent=8):
    """Numbered headings forming the longest plausible numbering sequence."""
    cands, extra = [], []
    for start, full in _lines(text):
        head = re.match(r"^(\s*(?:Appendix\s+|APPENDIX\s+)?\S+\s+)(.*)$", full)
        line = head.group(1) + COLUMN_GAP.split(head.group(2), 1)[0] if head else full
        if not line.strip() or len(line) > 100 or TOC_LINE.search(line):
            continue
        m = NUMBERED.match(line) or APPENDIX.match(line)
        if m and len(m.group("indent").expandtabs()) <= max_indent:
            title = (m.group("title") or "").strip()
            if title.endswith((",", ";")) or len(title.split()) > 14:
                continue
            cands.append((_key(m.group("num")), Heading(start, start + len(full), 0, line.strip())))
            continue
        if unnumbered and not line[0].isspace() and line.strip().lower().rstrip(":") in RFC_UNNUMBERED:
            extra.append(Heading(start, start + len(full), 1, line.strip()))
    # longest chain under _follows (O(n^2) over candidates, bounded window)
    best, back = [0] * len(cands), [-1] * len(cands)
    for i, (key, _) in enumerate(cands):
        best[i] = 1 if _follows(None, key) else 0
        for j in range(max(0, i - 400), i):
            if best[j] and best[j] + 1 > best[i] and _follows(cands[j][0], key):
                best[i], back[i] = best[j] + 1, j
    chain = []
    if cands and max(best):
        i = max(range(len(cands)), key=lambda k: (best[k], -k))
        while i >= 0:
            chain.append(cands[i])
            i = back[i]
    out = [h._replace(level=len(key)) for key, h in reversed(chain)]
    return out + extra


class _HeadingParser(HTMLParser):
    """Collect heading texts (h1-h6) in document order, joined like get_text('\\n', strip=True)."""

    SKIP = {"script", "style", "nav", "header", "footer", "noscript"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.found, self.stack, self.skip, self.parts = [], [], 0, None

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip += 1
        if re.fullmatch(r"h[1-6]", tag) and not self.skip:
            self.stack.append(int(tag[1]))
            self.parts = []

    def handle_endtag(self, tag):
        if tag in self.SKIP and self.skip:
            self.skip -= 1
        if re.fullmatch(r"h[1-6]", tag) and self.stack and self.parts is not None:
            level = self.stack.pop()
            text = "\n".join(p for p in self.parts if p)
            if text:
                self.found.append((level, text))
            self.parts = None

    def handle_data(self, data):
        if self.parts is not None and not self.skip:
            self.parts.append(data.strip())


MARK, MARK_END = "\ue000", "\ue001"
MARKERS = re.compile(MARK + r"H(\d)" + MARK + r"\s*|\n?" + MARK_END)


def _page_text():
    """collect.page_text, or None when bs4 (which collect.py needs) is missing."""
    try:
        from collect import page_text
    except ImportError:
        return None
    return page_text


def html_replay_available():
    return _page_text() is not None


def html_headings(text, raw):
    """(method, headings): exact offsets by replaying collect.page_text with markers around each heading."""
    page_text = _page_text()
    if page_text is None:
        return "html-search", html_headings_by_search(text, raw.decode("utf-8", "replace"))
    marked = re.sub(rb"(<h([1-6])\b[^>]*>)", lambda m: m.group(1) + (MARK + "H" + m.group(2).decode() + MARK).encode(), raw, flags=re.I)
    marked = re.sub(rb"(</h[1-6]\s*>)", lambda m: MARK_END.encode() + m.group(1), marked, flags=re.I)
    replay = page_text(marked)[1]
    pieces, length, last, open_heads, out = [], 0, 0, [], []
    for m in MARKERS.finditer(replay):
        pieces.append(replay[last:m.start()])
        length += m.start() - last
        last = m.end()
        if m.group(1):
            open_heads.append((length, int(m.group(1))))
        elif open_heads:
            out.append((*open_heads.pop(), length))
    pieces.append(replay[last:])
    cleaned = "".join(pieces)
    if cleaned != text:
        return "html-search", html_headings_by_search(text, raw.decode("utf-8", "replace"))
    return "html", [Heading(a, b, lvl, " ".join(text[a:b].split())) for a, lvl, b in sorted(out)
                    if text[a:b].strip() and (a == 0 or text[a - 1] == "\n")]


def html_headings_by_search(text, raw_html):
    parser = _HeadingParser()
    parser.feed(raw_html)
    out, pos = [], 0
    for level, htext in parser.found:
        needle = "\n" + htext + "\n"
        if text.startswith(htext + "\n", pos) and pos == 0:
            idx = 0
        else:
            idx = text.find(needle, pos)
            if idx < 0:
                continue
            idx += 1
        out.append(Heading(idx, idx + len(htext), level, htext.replace("\n", " ")))
        pos = idx + len(htext)
    return out


def method_for(doc, raw_head):
    """Choose a detection method from the record and the start of its raw file."""
    if raw_head.startswith(b"%PDF"):
        return "numbered"
    ident = doc["identity"].lower()
    if RFC_FILE.search(ident):
        return "numbered"
    if ident.endswith((".md", ".markdown")):
        return "markdown"
    if ident.endswith(".rst"):
        return "rst"
    if ident.endswith(".txt") and doc.get("revision"):
        return "rst"
    return "html"


def headings(doc, text, raw):
    """Detected headings for a corpus record; `raw` is the retained raw bytes."""
    method = method_for(doc, raw[:8])
    if method == "markdown":
        found = markdown_headings(text)
    elif method == "rst":
        found = rst_headings(text)
    elif method == "numbered":
        rfc = bool(RFC_FILE.search(doc["identity"].lower()))
        # RFC headings start in column 0; indented numbered lines are TOC entries or lists.
        found = numbered_headings(text, unnumbered=rfc, max_indent=0 if rfc else 8)
    else:
        method, found = html_headings(text, raw)
    return method, sorted(found, key=lambda h: h.start)


def section_end(found, index, text_length):
    """End offset of section `index`: the next heading at the same or a shallower level."""
    level = found[index].level
    for h in found[index + 1:]:
        if h.level <= level:
            return h.start
    return text_length


def is_boundary(found, offset):
    return any(h.start == offset for h in found)
