#!/usr/bin/env python3
"""Stage 1 (EPUB route): one clean text file per audiobook part, straight from the EPUB's XHTML.

Working from the XHTML instead of an `ebook-convert` .txt keeps the structure the text export
throws away: tables are elements (drop them whole instead of reading a price list cell by cell),
footnote markers are links (drop them instead of regex-guessing digits glued to punctuation),
and the parts are spine files (no TOC-skipping heuristics).

    epub_parts.py book.epub OUTDIR --part 00=OEBPS/c4G.xhtml --part 01=OEBPS/c51.xhtml ...
                  [--sub 'Tbe Works=The Works'] [--acronyms FILE]

Run with `--list` first to see the spine: file, word count, tables, links, opening words.

Per part:
  - <table> dropped, with any caption paragraph that is ALL CAPS directly above it
  - <a> whose text is a bare number (a footnote marker) dropped, its trailing text kept
  - an epigraph citation "(Author, Title, City: Publisher, 1952, p. 420)" becomes its own
    paragraph "— Author, Title" (narrate.py gives lines starting with an em dash a longer pause)
  - "CHAPTER THREE" + "The Second Title" -> "Chapter Three." + "The Second Title."
  - spaced scholarly ellipses ". . ." -> "..."
  - then strip_apparatus: page refs, acronym defs, ALL-CAPS headings/openers, heading periods
Needs lxml (calibre-debug -e has it; or pip install lxml).
"""
import argparse
import io
import os
import re
import sys
import zipfile

from lxml import etree, html

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import strip_apparatus as sa  # noqa: E402

OPF_NS = {"o": "http://www.idpf.org/2007/opf", "c": "urn:oasis:names:tc:opendocument:xmlns:container"}
BLOCKS = "//p[not(ancestor::li)] | //li | //h1 | //h2 | //h3 | //h4 | //h5 | //h6"
PLACES = (r"New York|London|Boston|Chicago|Washington|Los Angeles|Philadelphia|Cambridge|Oxford|"
          r"Berlin|Paris|Princeton|New Haven|Garden City|Indianapolis|Stanford|Belmont|San Francisco|"
          r"Toronto|Edinburgh|Munich|Frankfurt|Leipzig|Vienna|Zurich|Geneva|Baltimore|Hamburg")


def spine(z):
    root = etree.fromstring(z.read("META-INF/container.xml"))
    opf_path = root.find(".//c:rootfile", OPF_NS).get("full-path")
    opf = etree.fromstring(z.read(opf_path))
    base = os.path.dirname(opf_path)
    man = {i.get("id"): i.get("href") for i in opf.findall(".//o:manifest/o:item", OPF_NS)}
    return [os.path.normpath(os.path.join(base, man[r.get("idref")])).replace("\\", "/")
            for r in opf.findall(".//o:spine/o:itemref", OPF_NS)]


def squash(s):
    return " ".join(s.split())


def is_shout(s):
    letters = re.sub(r"[^A-Za-z]", "", s)
    return len(letters) >= 4 and letters.isupper()


def cite(s):
    """(Jane Author, A Title: The Subtitle, 1929-1941, New York: Macmillan, 1952, p. 420)
    -> — Jane Author, A Title: The Subtitle"""
    s = s.strip().strip("()").strip()
    cut = re.search(r",\s*(?:\d{4}\b|(?:" + PLACES + r")\b)", s)
    if cut:
        s = s[:cut.start()]
    return "— " + s.rstrip(" ,;:")


def part_text(xhtml, subs):
    t = html.fromstring(xhtml)
    for br in t.xpath("//br"):                                # "PART ONE<br/>THE EARLY YEARS"
        br.tail = " " + (br.tail or "")
    for tb in t.xpath("//table"):
        prev = tb.getprevious()
        if prev is not None and prev.tag == "p" and is_shout(prev.text_content()):
            prev.drop_tree()                                  # "LIST OF FACTORIES BY REGION"
        nxt = tb.getnext()
        if nxt is not None and nxt.tag == "p" and squash(nxt.text_content()).startswith("Source:"):
            nxt.drop_tree()                                   # "Source: Annual Report, p. 943"
        tb.drop_tree()
    for a in t.xpath("//a"):
        if re.fullmatch(r"\s*\d{1,3}\s*", a.text_content()):
            a.drop_tree()                                     # footnote marker; drop_tree keeps .tail
    paras = []
    for b in t.xpath(BLOCKS):
        epigraph = None
        for sp in b.xpath(".//span"):
            st = squash(sp.text_content())
            if st.startswith("(") and st.endswith(")") and len(st) > 25 and len(paras) < 6:
                epigraph = cite(st)
                sp.drop_tree()
        s = squash(b.text_content())
        if s:
            paras.append(s)
        if epigraph:
            paras.append(epigraph)
    merged = []
    for s in paras:                                           # "16." / "d." alone -> glue onto its item
        if merged and re.fullmatch(r"\(?(\d{1,2}|[A-Za-z]|[ivxIVX]{1,4})[.)]", merged[-1]):
            s = merged.pop() + " " + s
        merged.append(s)
    text = "\n\n".join(merged)
    # the tables and charts are gone, so are pointers to them: "(See Chart 2-1 and Table 2-1)"
    text = re.sub(r"\s*\((?:[Ss]ee )(?:[Cc]harts?|[Tt]ables?|[Ff]igures?)\b[^)]*\)\.?", "", text)
    text = re.sub(r"(?:\s?\.){3,4}(?=\s|$)", lambda m: "..." if m.group(0).count(".") == 3 else "....", text)
    text = re.sub(r"\s+\.\.\.", "...", text)
    return text


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("epub")
    ap.add_argument("outdir", nargs="?")
    ap.add_argument("--list", action="store_true", help="print the spine and exit")
    ap.add_argument("--part", action="append", default=[], metavar="NN=HREF[+HREF...]",
                    help="output NN.txt from these spine files, in order; repeatable")
    ap.add_argument("--sub", action="append", default=[], metavar="OLD=NEW", help="literal fix-up; repeatable")
    ap.add_argument("--acronyms", metavar="FILE", help="extra tokens to keep upper-case, one per line")
    a = ap.parse_args()

    z = zipfile.ZipFile(a.epub)
    files = spine(z)
    if a.list or not a.part:
        for f in files:
            t = html.fromstring(z.read(f))
            txt = squash(t.text_content())
            print(f"{f:28} words={len(txt.split()):6} tables={len(t.xpath('//table')):2} "
                  f"links={len(t.xpath('//a[@href]')):3} | {txt[:60]}")
        return

    acronyms = set(sa.DEFAULT_ACRONYMS)
    if a.acronyms:
        acronyms |= {l.strip() for l in io.open(a.acronyms, encoding="utf-8") if l.strip()}
    subs = [s.split("=", 1) for s in a.sub]
    os.makedirs(a.outdir, exist_ok=True)
    for spec in a.part:
        nn, hrefs = spec.split("=", 1)
        text = "\n\n".join(part_text(z.read(h), subs) for h in hrefs.split("+"))
        text = sa.strip_page_refs(text)
        text = sa.strip_acronym_defs(text)
        text = sa.unshout_headings(text, acronyms, True)
        text = sa.unshout_openers(text, acronyms)
        text = sa.punctuate_short_lines(text + "\n\n").strip()
        # hearing transcripts: "Mr. LEE. Yes, sir." -- the engine spells or shouts the caps name
        text = re.sub(r"\b(Mr\.|Mrs\.|Dr\.|Miss|Senator|Chairman|Colonel|General) ([A-Z]{2,})\b(?!\.[A-Z])",
                      lambda m: m.group(1) + " " + m.group(2).capitalize(), text)
        for old, new in subs:                                 # last, so they see the final casing
            text = text.replace(old, new)
        out = os.path.join(a.outdir, nn + ".txt")
        io.open(out, "w", encoding="utf-8", newline="\n").write(text + "\n")
        print(f"{out}: {len(text.split())} words | {text[:70]!r}")


if __name__ == "__main__":
    main()
