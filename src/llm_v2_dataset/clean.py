"""Reproducible extraction of a single historical text from retained bytes."""

import codecs
import re
import unicodedata
from dataclasses import dataclass
from html.parser import HTMLParser

CLEANING_VERSION = "6"
_START = re.compile(r"(?im)^[ \t]*\*{3}[ \t]*START OF (?:THIS|THE) PROJECT GUTENBERG (?:EBOOK|ETEXT)\b[^\n]*$")
_END = re.compile(r"(?im)^[ \t]*\*{3}[ \t]*END OF (?:THIS|THE) PROJECT GUTENBERG (?:EBOOK|ETEXT)\b[^\n]*$")
_TRANSCRIBER = re.compile(r"(?im)^\s*\[?transcriber(?:['’]s|s['’]?)?\s+notes?\s*[:.\]]?\s*$")
_MODERN_NOTE = re.compile(
    r"(?i)typograph|proofread|this (?:e-?book|electronic)|transcription|silently correct|"
    r"corrected silently|obvious (?:errors|mistakes)|changed to|minor typos|end of transcriber['’]s notes|underscores|small capitals"
)
_CREDIT = re.compile(r"(?i)^(?:(?:text |e-?text |ebook )?(?:produced|prepared|transcribed|proofread) by|credits?:\s*(?:produced|prepared|transcribed|the online distributed))\b")
_LEGACY_END = re.compile(r"(?im)^[ \t]*end of (?:this |the )?project gutenberg(?:['’]s|\b[^\n]{0,24}\be-?(?:book|text)\b)")
_DIGITAL_CREDIT = re.compile(
    r"(?i)^(?:note:\s*project gutenberg also has an? (?:html|illustrated) version|"
    r"images of the original pages are available through|this e-?(?:text|book) was (?:proofread|prepared) by)\b"
)
_BYLINE = re.compile(
    r"(?im)^[ \t_]*(?:with\s+)?(?:an?\s+|the\s+)?(?:preface|introduction|foreword|afterword|annotations?|"
    r"notes|translation|translated(?:\s+from\s+the\s+\w+)?|edited|revised|adapted|abridged)"
    r"\s+by\s+(?P<who>[^\n]{1,110})"
)


class CleanError(ValueError):
    """The source needs a different decoder or an explicit boundary review."""


@dataclass(frozen=True)
class Cleaned:
    text: str
    before_chars: int
    notes: str


class BodyHTML(HTMLParser):
    """Keep text inside body, discarding explicit navigation and script subtrees."""

    ignored = {"nav", "script", "style", "template", "noscript"}
    blocks = {"p", "div", "section", "article", "li", "blockquote", "pre",
              "h1", "h2", "h3", "h4", "h5", "h6", "tr", "caption", "figcaption"}
    void = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link",
            "meta", "param", "source", "track", "wbr"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.in_body = False
        self.hidden = []
        self.pre = False

    def handle_starttag(self, tag, attrs):
        if tag == "body":
            self.in_body = True
        if not self.in_body:
            return
        attrs = dict(attrs)
        hide = (tag in self.ignored or "hidden" in attrs or attrs.get("aria-hidden") == "true")
        if hide or self.hidden:
            if tag not in self.void:
                self.hidden.append(tag)
            return
        if tag in self.blocks:
            self.parts.append("\n\n")
        elif tag in {"hr", "br"}:
            self.parts.append("\n")
        elif tag in {"td", "th"}:
            self.parts.append("\t")
        if tag == "pre":
            self.pre = True

    def handle_endtag(self, tag):
        if self.hidden:
            if self.hidden[-1] == tag:
                self.hidden.pop()
            return
        if self.in_body and tag in self.blocks:
            self.parts.append("\n\n")
        if tag == "pre":
            self.pre = False
        if tag == "body":
            self.in_body = False

    def handle_data(self, data):
        if self.in_body and not self.hidden:
            self.parts.append(data if self.pre else re.sub(r"[ \t\r\n]+", " ", data))


def _gutenberg_body(text, notes):
    starts, ends = list(_START.finditer(text)), list(_END.finditer(text))
    if len(starts) != 1 or len(ends) != 1 or starts[0].end() >= ends[0].start():
        raise CleanError("missing, reversed or multiple Gutenberg START/END boundaries")
    body_start = starts[0].end()
    if not starts[0][0].rstrip().endswith("***"):
        continuation = re.match(r"\n(?:[^\n*]{1,180}\n){0,2}[^\n*]{1,180}\*\*\*[ \t]*(?=\n|$)", text[body_start:])
        if continuation:
            body_start += continuation.end()
    body = text[body_start:ends[0].start()].strip()
    notes.append("Gutenberg START/END markers")
    imprint = re.search(r"(?m)^The Millennium Fulcrum Edition \d+(?:\.\d+)*[ \t]*$", body[:1800])
    if imprint:
        body = body[:imprint.start()] + body[imprint.end():]
        notes.append("digital edition imprint")
    # Some transcriptions place a short digital source note after the title.
    preparer = re.search(r"(?im)^[ \t]*preparer['’]s note[ \t]*\n\s*This text was prepared from\b[^\n]*(?:\n[^\n]+)*?(?=\n[ \t]*\n)", body[:1600])
    if preparer and len(preparer[0]) < 500:
        body = body[:preparer.start()] + body[preparer.end():]
        notes.append("digitizer's imprint note")
    legacy = list(_LEGACY_END.finditer(body))
    if legacy:
        if len(legacy) != 1 or len(body) - legacy[0].start() > 2500:
            raise CleanError("ambiguous legacy Gutenberg end marker")
        body = body[:legacy[0].start()].rstrip()
        notes.append("legacy end credit inside wrapper")
    # Production credits at the beginning are usually a distinct paragraph.
    # Do not delete an unbounded block or anything between chapters.
    for _ in range(4):
        lead = re.match(r"(.{1,1800}?)\n[ \t]*\n+", body, re.S)
        from_edition = lead and re.match(r"(?is)^transcribed from (?:the|an?)\s+.{1,230}?\bedition by\b", lead[1].strip())
        if lead and (_CREDIT.search(lead[1].strip()) or _DIGITAL_CREDIT.search(lead[1].strip()) or from_edition):
            body = body[lead.end():].lstrip()
            notes.append("initial production credit")
        else:
            break
    # Bracketed margin notes have explicit bounds. Multiline endnotes require
    # a standalone final heading and wording characteristic of digital editing.
    bracket = re.compile(r"(?is)\[(?:illustration:\s*)?transcriber(?:['’]s|s['’]?)?\s+notes?\s*:[^\[\]]{1,3000}\]")
    body, count = bracket.subn("", body)
    if count:
        notes.append(f"{count} bracketed transcription note(s)")
    box_pattern = r"(?ims)^[ \t]*(?P<edge>\+?-{5,}\+?)\n(?P<body>(?:[ \t]*\|[^\n]*\|[ \t]*\n)+)[ \t]*(?P=edge)[ \t]*$"
    for box in reversed(list(re.finditer(box_pattern, body))):
        if "transcriber" in box["body"].lower() and len(box[0]) < 7000:
            body = body[:box.start()] + body[box.end():]
            notes.append("boxed transcription note")
    body = body.strip()
    preparer = re.search(r"(?im)^[ \t]*preparer['’]s note[.:]?[ \t]*\n\s*This E-?(?:text|book) was prepared from [^\n]+(?:\n[^\n]+){0,4}", body[:2000])
    if preparer:
        body = body[:preparer.start()] + body[preparer.end():]
        notes.append("delimited electronic edition note")
    body, omitted = re.subn(r"(?im)^[ \t]*\(Not included in this e-?(?:text|book)\)[ \t]*$", "", body)
    if omitted:
        notes.append("standalone omitted-illustration notices")
    footnote = r"(?im)^[ \t]*\*transcriber['’]s note[.:][^\n]*(?:\n[ \t]+[^\n]+){0,4}(?=\n\s*\n)"
    body, footnotes = re.subn(footnote, "", body)
    if footnotes:
        notes.append("explicitly marked digital footnotes")
    if re.match(r"(?i)^transcriber(?:['’]s|s['’]?)?\s+notes?\b", body):
        # Leading digital notes can span several paragraphs. Use a printed
        # ornament or a large break before the historical title as the boundary.
        limit = body[:2500]
        boundary = re.search(r"(?m)^[ \t]*(?:\*[ \t]*){3,}$|\n{4,}(?=[ \t]*[A-Z][A-Z][A-Z ])", limit)
        if boundary and _MODERN_NOTE.search(limit[:boundary.start()]):
            if "glossary" not in limit[:boundary.start()].lower():
                body = body[boundary.end():].lstrip()
                notes.append("delimited opening transcription note")
    corrections = re.search(r"(?im)^[ \t]*corrections made to (?:the )?printed text[.:]?[ \t]*$", body)
    if corrections and len(body) - corrections.start() < 6000 and re.search(r"(?i)corrected from", body[corrections.end():]):
        body = body[:corrections.start()]
        notes.append("final digital correction list")
    for heading in reversed(list(_TRANSCRIBER.finditer(body))):
        suffix = body[heading.end():]
        if heading.start() > len(body) * 0.7 and len(suffix) < 15000 and _MODERN_NOTE.search(suffix):
            body = body[:heading.start()]
            notes.append("final transcription notes")
            break
    # A remaining explicit heading signals a boundary we cannot place safely.
    if _TRANSCRIBER.search(body) or re.search(r"(?im)^\s*\[?transcriber['’]s?\s+notes?\s*:", body):
        raise CleanError("unresolved transcription note boundaries")
    if _CREDIT.match(body):
        raise CleanError("unresolved Gutenberg production credit")
    if re.search(r"(?i)project gutenberg|distributed proofreading|@pglaf\.org|\b(?:e-?book|etext)\b|transcriber(?:['’]s|s['’]?)? notes?\b|https?://", body):
        raise CleanError("unresolved digital edition note or link")
    return body


def _check_frontmatter(row, text):
    front = text[:8500]
    # Author-date strings in catalogue order still identify the credited writer.
    # Only allow another named translator if the eligibility gate has dated
    # their contribution; an unknown editorial credit needs item-level review.
    names = [row.get("authors", ""), row.get("pg_author_name", "")]
    if row.get("translation_year") and row.get("translation_evidence_url"):
        names.append(row.get("translator", ""))
    recognized = [set(re.findall(r"[^\W\d_]+", s.casefold())) for s in names if s]
    # The body of a credited foreword can follow a long table of contents.
    for credit in re.finditer(r"(?m)^[ \t]*(?i:foreword|critical introduction|afterword)[.: \t]*\n\s*"
                              r"_(?P<who>[A-Z][a-zA-Z.’'-]+(?: [A-Z][a-zA-Z.’'-]+){1,4})_[ \t]*$", text):
        if not any(set(credit["who"].casefold().split()) <= name for name in recognized):
            raise CleanError("separately credited editorial text: " + credit["who"])
    for credit in _BYLINE.finditer(front):
        words = set(re.findall(r"[^\W\d_]+", credit["who"].casefold()))
        if words == {"the", "author"} or (words and any(words <= name for name in recognized)):
            continue
        raise CleanError("unverified textual contributor in front matter: " + " ".join(credit[0].split())[:120])
    latest = int(row.get("scope_end_year") or 1945)
    for marker in re.finditer(r"(?im)^.{0,30}(?:©|\b(?:copyright(?:ed)?|(?:revised|new|this) edition|first published)\b)[^\n]{0,130}(?:\n[ \t]*(?:19|20)\d{2})?", front):
        if any(int(y) > latest for y in re.findall(r"\b(?:19|20)\d{2}\b", marker[0])):
            raise CleanError("post-scope print date in front matter: " + " ".join(marker[0].split())[:140])


def extract(row, raw_bytes):
    """Return canonical text, decoded input length and extraction decisions."""
    encoding = row.get("encoding") or "utf-8"
    if raw_bytes.startswith(codecs.BOM_UTF8):
        encoding = "utf-8-sig"
    is_pg = (row.get("source") or "").lower() in {"pg", "project gutenberg", "gutenberg"}
    if is_pg and not raw_bytes.startswith(codecs.BOM_UTF8):
        wrapper = raw_bytes[:4000].split(b"***START")[0].split(b"*** START")[0]
        declared = re.search(rb"(?im)^Character set encoding:\s*(ISO-8859-1|UTF-8|US-ASCII|ASCII|Windows-1252)\b", wrapper)
        if declared:
            encoding = declared[1].decode("ascii")
    mismatch = is_pg and encoding.casefold() in {"us-ascii", "ascii"} and not raw_bytes.isascii()
    if mismatch:
        encoding = "utf-8"
    try:
        decoded = raw_bytes.decode(encoding)
    except (UnicodeError, LookupError) as exc:
        raise CleanError(f"cannot decode source as {encoding}") from exc
    text = decoded.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n").replace("\f", "\n\n")
    notes = [f"{encoding}, NFC and LF"]
    if mismatch:
        notes.append("declared ASCII disagrees with bytes; strict UTF-8 verified")
    if "html" in (row.get("media_type") or "").lower():
        parser = BodyHTML()
        parser.feed(text)
        parser.close()
        text = "".join(parser.parts)
        if not text.strip():
            raise CleanError("no readable HTML body")
        notes.append("HTML body, block and explicit line breaks")
    first_line, after_line = row.get("extraction_start"), row.get("extraction_end")
    begin, end = row.get("body_start", ""), row.get("body_end", "")
    if first_line or after_line:
        if not first_line or not after_line:
            raise CleanError("both reviewed line boundaries are required")
        lines = text.split("\n")
        try:
            first = next(i for i, line in enumerate(lines) if line.strip() == first_line)
            after = next(i for i in range(first + 1, len(lines)) if lines[i].strip() == after_line)
        except StopIteration as exc:
            raise CleanError("reviewed line boundary missing or out of order") from exc
        text = "\n".join(lines[first:after])
        notes.append("reviewed full-line boundaries (start included, end excluded)")
        if row.get("source") == "Project Gutenberg Australia":
            text = re.sub(r"(?im)^\s*\(Not included in this eBook\)\s*$", "\n", text)
    elif begin or end:
        if not (begin and end and text.count(begin) == 1 and text.count(end) == 1):
            raise CleanError("both reviewed boundary markers must be unique")
        left, right = text.index(begin) + len(begin), text.index(end)
        if left >= right:
            raise CleanError("reviewed body boundaries out of order")
        text = text[left:right]
        notes.append("explicit reviewed boundary markers (excluded)")
    elif is_pg:
        text = _gutenberg_body(text, notes)
    elif row.get("extraction_basis") == "reviewed_body" and row.get("source_record_url"):
        notes.append("reviewed standalone historical body")
    else:
        raise CleanError("source needs reviewed body boundaries")
    text = unicodedata.normalize("NFC", text).strip()
    _check_frontmatter(row, text)
    if not text or "\ufffd" in text or re.search(r"[\x00-\x08\x0b\x0e-\x1f\x7f-\x9f]", text):
        raise CleanError("empty extraction, replacement character or unexpected control character")
    return Cleaned(text, len(decoded), "; ".join(notes))
