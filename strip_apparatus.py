#!/usr/bin/env python3
"""Stage 1: strip the scholarly apparatus out of a plain-text book export.

Input is the .txt that calibre / Epubor / `ebook-convert book.epub book.txt`
produces from an EPUB. Output is body text only: no front matter, no endnotes,
no bibliography, no inline note numbers, no page cross-references.

Everything here is a heuristic. Run it, diff the result against the source,
and add a rule when the book fights back. See README.md for the rationale.

usage: strip_apparatus.py IN.txt OUT.txt [options]
"""
import argparse
import io
import re
import sys

# Tokens that stay upper-case when we de-shout headings and chapter openers.
DEFAULT_ACRONYMS = {
    "I", "A", "U.S.", "U.K.", "U.N.", "USA", "UK", "UN", "EU", "CIA", "FBI", "NSA",
    "NSC", "DOD", "DOJ", "FEMA", "TV", "DNA", "CEO", "GDP", "PBS", "BBC",
    "CNN", "NBC", "ABC", "CBS", "AI", "IT", "OK", "PhD", "MD", "JFK", "LBJ", "FDR",
    "WTC", "NATO", "NAFTA", "OPEC", "IMF", "WHO", "UNESCO", "NASA", "IBM", "AT&T",
    "OSS", "KGB", "GRU", "MI5", "MI6", "LSD", "UC", "II", "III", "IV",
}


def _tok_core(w):
    return re.sub(r"[^\w.&]", "", w)


def find_line(lines, pattern, start=0):
    rx = re.compile(pattern)
    for i in range(start, len(lines)):
        if rx.fullmatch(lines[i].strip()):
            return i
    return None


def cut_body(lines, body_start, body_end, skip_toc_marker):
    """Keep lines from the body_start heading up to (not including) body_end.

    A table of contents usually lists the same headings we search for, so we
    first jump past the TOC's last entry (skip_toc_marker) and only then look
    for the real headings.
    """
    origin = 0
    if skip_toc_marker:
        m = find_line(lines, skip_toc_marker)
        if m is not None:
            origin = m + 1
    s = find_line(lines, body_start, origin) if body_start else 0
    if s is None:
        sys.exit(f"body-start heading not found: {body_start!r}")
    e = find_line(lines, body_end, s + 1) if body_end else len(lines)
    if e is None:
        sys.exit(f"body-end heading not found: {body_end!r}")
    return lines[s:e]


def drop_blocks(lines, blocks):
    """blocks: list of (start_pattern, end_pattern). Removes [start, end) for
    every occurrence. end_pattern=None removes to the end of the text.
    Used for per-chapter NOTES sections and trailing bibliographies."""
    for start_pat, end_pat in blocks:
        out, i = [], 0
        srx = re.compile(start_pat)
        erx = re.compile(end_pat) if end_pat else None
        while i < len(lines):
            if srx.fullmatch(lines[i].strip()):
                j = i + 1
                if erx is None:
                    break
                while j < len(lines) and not erx.fullmatch(lines[j].strip()):
                    j += 1
                i = j
                continue
            out.append(lines[i])
            i += 1
        lines = out
    return lines


def strip_inline_note_numbers(text):
    # superscript note numbers land glued to the preceding punctuation:
    #   election.69   reform.”70   defeated.72)   scale,73   Smith1 (epigraph)
    text = re.sub(r"(?<=[^\d\s][.,;:!?”’)\]])\d{1,3}(?=[\s,)]|$)", "", text)
    # sentence ends on a digit (a year): 1980.12 The next   -- only when the
    # note number is followed by a capital or end of line, so 3.5 billion survives
    text = re.sub(r"(?<=\d[.!?”])\d{1,3}(?=\s+[A-Z“(]|\s*$)", "", text)
    # epigraph attribution lines: —Senator Jane Smith1
    text = re.sub(r"^(—.*[a-z)])\d{1,2}$", lambda m: m.group(1), text, flags=re.M)
    return text


def strip_page_refs(text):
    # (below, pp. 18–20, 27–28)  (see below, pp. 101–08)  (p. 99)  (pp. 14–15. etc.)
    text = re.sub(r"\s*\((?:see |cf\. )?(?:below|above)?,?\s*pp?\.\s*[\d–\-, ]+\.?(?: etc\.)?\)", "", text)
    # "As I warn below on p. 14, the argument ..."
    text = re.sub(r"\s+on pp?\. [\d–\-, ]+,", ",", text)
    return text


def strip_acronym_defs(text):
    # "structural adjustment programs (SAPs) have" -> the parenthetical is print-only
    return re.sub(r"\s\((?:[A-Z][A-Za-z&]{1,7}s?)\)(?=[\s,.;:])", "", text)


def unshout_openers(text, acronyms):
    """Chapter openers are typeset in small caps and export as
    'ON FEBRUARY 3, 2017, THE NEW YORK TIMES REPORTED THE COMPANY'S plans'.
    TTS engines spell or shout runs of capitals. Lower the leading run."""
    def fix(m):
        words = m.group(0).split(" ")
        out = []
        for k, w in enumerate(words):
            if _tok_core(w) in acronyms:
                out.append(w)
            elif k == 0:
                out.append(w[0] + w[1:].lower())
            else:
                out.append(w.lower())
        return " ".join(out)
    return re.sub(r"^(?:[^\sa-z]+)(?: [^\sa-z]+){2,}(?= )", fix, text, flags=re.M)


def unshout_headings(text, acronyms, punctuate):
    """ALL-CAPS heading lines -> Title Case, optionally with a terminal period
    so chunkers and TTS treat the heading as its own sentence."""
    def fix(m):
        words = m.group(0).split(" ")
        t = " ".join(w if _tok_core(w) in acronyms else w.capitalize() for w in words)
        if punctuate and not re.search(r"[.!?:]$", t):
            t += "."
        return t
    return re.sub(r"^(?=.*[A-Z])[A-Z0-9 ,:'’“”\"()&.—–/?!-]{4,}$", fix, text, flags=re.M)


def punctuate_short_lines(text):
    """Any short line (title-case heading, 'Chapter 3') without terminal
    punctuation gets a period so it isn't run into the next paragraph."""
    def fix(m):
        line = m.group(0)
        if len(line.split()) <= 12 and not re.search(r"[.!?:;,—–-]$", line):
            return line + "."
        return line
    return re.sub(r"^(?!\s)[^\n]{2,90}$(?=\n\s*\n)", fix, text, flags=re.M)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("src")
    ap.add_argument("dst")
    ap.add_argument("--body-start", default=r"Introduction|Prologue|Preface|Chapter 1|CHAPTER 1|1",
                    help="regex fully matching the first body heading line")
    ap.add_argument("--body-end", default=r"Notes|NOTES|Endnotes|Bibliography|Selected Bibliography|Index|Acknowledgments",
                    help="regex fully matching the first back-matter heading line")
    ap.add_argument("--skip-toc", default=r"About the Author|Index|Notes",
                    help="regex for the LAST table-of-contents entry; heading search starts after it")
    ap.add_argument("--drop", action="append", nargs=2, metavar=("START_RE", "END_RE"), default=[],
                    help="drop lines from a heading matching START_RE up to (not incl.) END_RE; repeatable. "
                         "e.g. --drop NOTES 'CHAPTER \\d+' for per-chapter notes. END_RE='' drops to EOF")
    ap.add_argument("--citations", metavar="FILE",
                    help="file of regexes, one per line; each is stripped from line ends "
                         "(marginal citations glued onto verse or sidebars)")
    ap.add_argument("--acronyms", metavar="FILE", help="extra tokens to keep upper-case, one per line")
    ap.add_argument("--keep-acronym-defs", action="store_true", help="keep '(SAPs)'-style parentheticals")
    ap.add_argument("--no-punctuate-headings", action="store_true")
    ap.add_argument("--header", default="", help="text to prepend (title / author line)")
    a = ap.parse_args()

    acronyms = set(DEFAULT_ACRONYMS)
    if a.acronyms:
        acronyms |= {l.strip() for l in io.open(a.acronyms, encoding="utf-8") if l.strip()}

    lines = io.open(a.src, encoding="utf-8").read().split("\n")
    lines = cut_body(lines, a.body_start, a.body_end, a.skip_toc)
    lines = drop_blocks(lines, [(s, e or None) for s, e in a.drop])

    if a.citations:
        pats = [l.rstrip("\n") for l in io.open(a.citations, encoding="utf-8") if l.strip() and not l.startswith("#")]
        crx = re.compile(r"\s+(?:" + "|".join(pats) + r")\s*$")
        lines = [crx.sub("", l) for l in lines]

    text = "\n".join(lines)
    text = strip_inline_note_numbers(text)
    text = strip_page_refs(text)
    if not a.keep_acronym_defs:
        text = strip_acronym_defs(text)
    text = unshout_headings(text, acronyms, not a.no_punctuate_headings)   # before openers: a heading is all caps, an opener is not
    text = unshout_openers(text, acronyms)
    if not a.no_punctuate_headings:
        text = punctuate_short_lines(text)
    text = re.sub(r"[ \t]+$", "", text, flags=re.M)
    text = re.sub(r"\n{3,}", "\n\n", text)

    io.open(a.dst, "w", encoding="utf-8").write((a.header + "\n\n" if a.header else "") + text.strip() + "\n")
    print(f"{a.dst}: {len(text.split())} words")


if __name__ == "__main__":
    main()
