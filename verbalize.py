#!/usr/bin/env python3
"""Stage 2: turn written forms into spoken forms.

    $3.8bn            -> three point eight billion dollars
    1961–1980         -> nineteen sixty one to nineteen eighty
    9/11              -> nine eleven          (NeMo alone says "nine elevenths")
    U.S.              -> United States        (NeMo alone says "US" -> engines read "us")
    Henry VIII        -> Henry the Eighth
    No. 5 / Vol. 2    -> Number five / Volume two
    cf. / ibid. / pp. -> compare / ibidem / pages
    Ulysses S. Grant  -> Ulysses S Grant       (the period ends a TTS sentence mid-name)
    King, Jr.         -> King, Junior

Two engines:
  --engine nemo       NVIDIA nemo_text_processing (WFST, best quality; Linux x86_64 only)
  --engine simple     num2words-based fallback that runs anywhere (years, money,
                      percents, ordinals, decimals, plain integers)

Order matters: PRE rules fix what the engine gets wrong, the engine does the
bulk, POST rules tidy the engine's spacing. See README.md for the verified
trap list this encodes.

usage: verbalize.py IN.txt OUT.txt [--engine nemo|simple]
"""
import argparse
import io
import re
import sys

ROMAN = {"II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6, "VII": 7, "VIII": 8, "IX": 9, "X": 10,
         "XI": 11, "XII": 12, "XIII": 13, "XIV": 14, "XV": 15, "XVI": 16, "XVII": 17, "XVIII": 18,
         "XIX": 19, "XX": 20}
# names that take "the Eighth" rather than "eight"
REGNAL = ("Henry|Louis|George|Edward|Charles|James|William|Elizabeth|Richard|Philip|Napoleon|"
          "Nicholas|Alexander|Frederick|Ivan|Peter|Catherine|Pope|Pius|Leo|Benedict|Paul|John|"
          "Gregory|Urban|Innocent|Clement|Ptolemy|Ramses|Rameses|Constantine|Justinian|Otto|"
          "Wilhelm|Kaiser|Mehmed|Selim|Abdul|Umberto|Victor Emmanuel|Christian|Gustav|Carl|Olaf|"
          "Haakon|Ferdinand|Alfonso|Juan Carlos|Leopold|Albert|Baudouin|Rainier|Mohammed|Hassan")


def _ordinal_words(n):
    from num2words import num2words
    return num2words(n, to="ordinal")


def _cardinal_words(n):
    from num2words import num2words
    return num2words(n)


PRE_RULES = [
    # things every engine we tested gets wrong
    (r"\b9/11\b", "nine eleven"),
    (r"\b24/7\b", "twenty-four seven"),
    (r"\b50/50\b", "fifty-fifty"),
    (r"\bU\.S\.A\.?(?=\W)", "United States of America"),
    (r"\bU\.S\.(?=\W)", "United States"),
    (r"\bU\.K\.(?=\W)", "United Kingdom"),
    (r"\bU\.N\.(?=\W)", "United Nations"),
    (r"\bD\.C\.(?=\W)", "D C"),
    # table/figure numbers are not ranges: "Table 7-1" -> "Table 7 1"
    (r"\b(Tables?|Figures?|Charts?|Exhibits?) (\d+)[–\-](\d+)", r"\1 \2 \3"),
    # numeric ranges: 1961–1980, 5-10 years, 10–20 percent -> "to"
    (r"(?<=\d)\s*[–\-]\s*(?=\d)", " to "),
    (r"\bs/(?=[A-Z])", "signed, "),          # letter signature "s/Jane Smith" (before the slash rule)
    # word compounds: Austro-Hungarian, Anglo-Saxon, and/or, B-52 -> a space. Chatterbox reads a
    # hyphen or slash as a boundary and sometimes leaves a gap there ("Austro... Hungarian"). A/B on the
    # same sentence and seed: 0.24 s gap with the hyphen, 0.12 s max with a space.
    (r"(?<=[A-Za-z])[\-/](?=[A-Za-z\d])", " "),
    # money/quantity suffixes NeMo does not know
    (r"(?<=\d)\s?bn\b", " billion"),
    (r"(?<=\d)\s?mn\b", " million"),
    (r"(\$\d[\d,]*(?:\.\d+)?)\s?m\b", r"\1 million"),   # $4.5m
    (r"(?<=\d)\s?tn\b", " trillion"),
    (r"(?<=\d)\s?k\b", " thousand"),
    # decade with curly apostrophe: ’80s -> 80s  (NeMo trips on the quote)
    (r"[’'](?=\d0s\b)", ""),
    # scholarly abbreviations left alone by NeMo
    (r"\bNo\.\s?(?=\d)", "Number "),
    (r"\bNos\.\s?(?=\d)", "Numbers "),
    (r"\bVol\.\s?", "Volume "),
    (r"\bVols\.\s?", "Volumes "),
    (r"\bpp\.\s?(?=\d)", "pages "),
    (r"\bp\.\s?(?=\d)", "page "),
    (r"\bCf\.\s", "Compare "),
    (r"\bcf\.\s", "compare "),
    (r"\bIbid\.", "ibidem"),
    (r"\bibid\.", "ibidem"),
    (r"\bOp\. cit\.", "the work cited"),
    (r"\bop\. cit\.", "the work cited"),
    (r"\be\.g\.,?\s", "for example, "),
    (r"\bi\.e\.,?\s", "that is, "),
    (r"\bviz\.\s", "namely "),
    (r"\bet al\.", "and others"),
    (r"\bca\.\s?(?=\d)", "circa "),
    (r"\bc\.\s?(?=\d{3,4}\b)", "circa "),
    (r"\bSen\.\s(?=[A-Z])", "Senator "),
    (r"\bRep\.\s(?=[A-Z])", "Representative "),
    (r"\bGen\.\s(?=[A-Z])", "General "),
    (r"\bGov\.\s(?=[A-Z])", "Governor "),
    (r"\bLt\.\s(?=[A-Z])", "Lieutenant "),
    (r"\bCol\.\s(?=[A-Z])", "Colonel "),
    (r"\bAdm\.\s(?=[A-Z])", "Admiral "),
    (r"\bCapt\.\s(?=[A-Z])", "Captain "),
    (r"\bSgt\.\s(?=[A-Z])", "Sergeant "),
    (r"\bDr\.\s(?=[A-Z])", "Doctor "),
    (r"\bMr\.\s(?=[A-Z])", "Mister "),
    (r"\bMrs\.\s(?=[A-Z])", "Missus "),
    (r"\bMs\.\s(?=[A-Z])", "Miz "),
    (r"\bProf\.\s(?=[A-Z])", "Professor "),
    (r"\bPres\.\s(?=[A-Z])", "President "),
    (r"\bvs\.\s", "versus "),
    (r"\bv\.\s(?=[A-Z])", "versus "),   # case names: Roe v. Wade
    (r"\bCo\.(?=\W)", "Company"),
    (r"\bInc\.(?=\W)", "Incorporated"),
    (r"\bCorp\.(?=\W)", "Corporation"),
    (r"\bLtd\.(?=\W)", "Limited"),
    (r"\bDept\.(?=\W)", "Department"),
    (r"\bJr\.(?=\W)", "Junior"),      # the period splits "King, Jr. assassination"
    (r"\bSr\.(?=\W)", "Senior"),
    (r"\bSt\.\s(?=[A-Z])", "Saint "),
    (r"\bMt\.\s(?=[A-Z])", "Mount "),
    (r"\bFt\.\s(?=[A-Z])", "Fort "),
    # symbols
    (r"\s*&\s*", " and "),
    (r"¶\s?", "paragraph "),
    (r"§\s?", "section "),
    (r"…", "..."),
    (r"[“”]", '"'),
    (r"[‘’]", "'"),
]


# ---------------------------------------------------------------- initials
# "Ulysses S. Grant" is the single worst trap in narration: every chunker and
# every TTS engine reads that period as a full stop, so the voice drops pitch
# and pauses in the middle of the man's name. Dropping the period is safe --
# a bare capital is still read as the letter -- but a one-letter SENTENCE end
# does exist ("...just for the letter A. By June 2014..."), so guard on the
# word that follows: an initial is followed by a name, not a sentence opener.
SENTENCE_STARTERS = frozenset("""
A An And As At After Against Along Although Among Another Any Are At Because Before Besides
Between Both But By Despite During Each Either Even Every Few For From Further Hence Her Here
His How However If In Indeed Instead It Its Later Many Meanwhile Moreover Most My Neither
Nevertheless Next No Nonetheless Nor Not Now Of On Once One Only Other Our Over Perhaps Rather
Several She Since So Some Still Such Than That The Their Then There These They This Those Though
Thus To Toward Towards Two Three Under Unless Until Upon Us We What When Where Whether Which
While Who Whom Whose Why With Within Without Yet You Your
""".split())

_NAME = r"[A-Z][A-Za-z'’-]*[a-z]"          # Grant, Edgar, McCloy, O'Brien, Du
_INITIAL_CHAIN = re.compile(r"\b([A-Z])\.(?=\s+[A-Z]\.)")                            # W. E. B.
_INITIAL_LEAD = re.compile(r"\b([A-Z])\.\s+(?=(" + _NAME + r")\s+" + _NAME + r")")   # J. Robert Oppenheimer
_INITIAL_PAIR = re.compile(r"\b([A-Z]) ([A-Z])\.\s+(?=(" + _NAME + r"))")              # C S. Lewis (after CHAIN)
_INITIAL_ONE = re.compile(r"(?<=\s)([A-Z])\.\s+(?=(" + _NAME + r")\b)")               # H. Smith, president
_INITIAL_MID = re.compile(r"\b([A-Z][a-z]+\.?)\s+([A-Z])\.\s+(?=(" + _NAME + r"))")  # Ulysses S. Grant


def name_initials(text):
    """Strip the period from personal-name initials so no reader stops mid-name."""
    def lead(m):
        return m.group(1) + " " if m.group(2) not in SENTENCE_STARTERS else m.group(0)

    def mid(m):
        return "%s %s " % (m.group(1), m.group(2)) if m.group(3) not in SENTENCE_STARTERS else m.group(0)

    for _ in range(4):                      # chains resolve one initial per pass
        before = text
        text = _INITIAL_CHAIN.sub(r"\1", text)
        text = _INITIAL_LEAD.sub(lead, text)
        text = _INITIAL_MID.sub(mid, text)
        text = _INITIAL_PAIR.sub(mid, text)
        text = _INITIAL_ONE.sub(lead, text)
        if text == before:
            break
    return text


def roman_numerals(text):
    def fix(m):
        name, rn = m.group(1), m.group(2)
        n = ROMAN[rn]
        if re.fullmatch(REGNAL, name):
            return f"{name} the {_ordinal_words(n).capitalize()}"
        return f"{name} {_cardinal_words(n)}"
    return re.sub(r"\b([A-Z][a-z]+(?: [A-Z][a-z]+)?) (" + "|".join(ROMAN) + r")\b(?=[\s,.;:)!?\"']|$)", fix, text)


_DOTTED = re.compile(r"\b((?:[A-Z]\.){2,}|(?:[A-Z]\.)+[A-Z]\b(?!\.))")       # I.G.  A.G


def dotted_acronyms(text):
    """I.B.M. Research -> IBM Research. The chunker splits on a period + space + capital, so every
    dotted acronym before a name cut the sentence in two. Solid letters read the same
    (Whisper transcripts of test renders) and ~1 s/sentence faster than "I G". Keep one
    period where the acronym really ends a sentence: "worked for R.C.A. The next" -> "RCA. The next"."""
    def fix(m):
        solid = m.group(1).replace(".", "")
        if not m.group(1).endswith("."):
            return solid                                    # "Bosch A.G subsidiary": never a sentence end
        rest = m.string[m.end():]
        nxt = re.match(r"\s+(\S+)", rest)
        if rest.strip() == "" or rest.startswith("\n"):
            ends = True                                     # end of paragraph
        elif nxt is None:
            ends = False                                    # glued punctuation: "G.E.C., and"
        else:
            ends = re.sub(r"\W", "", nxt.group(1)) in SENTENCE_STARTERS
        return solid + ("." if ends else "")
    return _DOTTED.sub(fix, text)


def pre(text):
    text = roman_numerals(text)
    for pat, rep in PRE_RULES:
        text = re.sub(pat, rep, text)
    text = dotted_acronyms(text)    # after PRE_RULES: U.S./U.K./U.N. are already spelled out
    return name_initials(text)


def stray_periods(text):
    """A full stop that cannot be one: before a comma, or closing a parenthesis
    that the sentence continues past. Both make a narrator stop dead mid-clause."""
    text = re.sub(r"(?<=[A-Za-z])\.(?=,)", "", text)        # "the FBI., which had learned"
    text = re.sub(r"\.\)(?=\s*[a-z])", ")", text)           # "King, junior.) with a new"
    return text


COMPOUND = re.compile(r"(?<=[A-Za-z])[\-/](?=[A-Za-z\d])")


def post(text):
    text = COMPOUND.sub(" ", text)          # again after the engine: NeMo writes "twenty five-percent"; "RCA-Victor"
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return stray_periods(text)


# ---------------------------------------------------------------- engines
def engine_nemo(text):
    from nemo_text_processing.text_normalization.normalize import Normalizer
    n = Normalizer(input_case="cased", lang="en")
    out = []
    for para in text.split("\n"):
        out.append(n.normalize(para, verbose=False) if para.strip() else para)
    return "\n".join(out)


def _decade(w):
    return w[:-1] + "ies" if w.endswith("y") else w + "s"


def engine_simple(text):
    from num2words import num2words as _n2w

    def num2words(n, **kw):
        return _n2w(n, **kw).replace(",", "")
    scale = {"thousand": "thousand", "million": "million", "billion": "billion", "trillion": "trillion"}

    def money(m):
        amt, unit = m.group(1).replace(",", ""), (m.group(2) or "").lower()
        n = float(amt) if "." in amt else int(amt)
        words = num2words(n)
        if unit in scale:
            return f"{words} {unit} dollars"
        if n == 1:
            return "one dollar"
        return f"{words} dollars"
    text = re.sub(r"\$([\d,]+(?:\.\d+)?)(?:\s?(thousand|million|billion|trillion))?\b", money, text)
    text = re.sub(r"\b(\d+(?:\.\d+)?)\s?%", lambda m: num2words(float(m.group(1)) if "." in m.group(1) else int(m.group(1))) + " percent", text)
    text = re.sub(r"\b(\d+)(st|nd|rd|th)\b", lambda m: num2words(int(m.group(1)), to="ordinal"), text)
    text = re.sub(r"\b(1[0-9]|20)(\d0)s\b", lambda m: _decade(num2words(int(m.group(1) + m.group(2)), to="year")), text)   # 1960s
    text = re.sub(r"\b(\d0)s\b", lambda m: _decade(num2words(int(m.group(1)))), text)  # 80s
    text = re.sub(r"\b(1[0-9]\d\d|20\d\d)\b", lambda m: num2words(int(m.group(1)), to="year"), text)
    text = re.sub(r"\b(\d{1,3}(?:,\d{3})+)\b", lambda m: num2words(int(m.group(1).replace(",", ""))), text)
    text = re.sub(r"\b(\d+)\.(\d+)\b", lambda m: num2words(int(m.group(1))) + " point " + " ".join(num2words(int(d)) for d in m.group(2)), text)
    text = re.sub(r"\b\d+\b", lambda m: num2words(int(m.group(0))), text)
    return text


ENGINES = {"nemo": engine_nemo, "simple": engine_simple}


def verbalize(text, engine="simple"):
    return post(ENGINES[engine](pre(text)))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("src")
    ap.add_argument("dst")
    ap.add_argument("--engine", choices=ENGINES, default="simple")
    a = ap.parse_args()
    text = io.open(a.src, encoding="utf-8").read()
    try:
        out = verbalize(text, a.engine)
    except ImportError as e:
        sys.exit(f"engine {a.engine!r} needs a package that is not installed: {e}")
    io.open(a.dst, "w", encoding="utf-8").write(out)
    left = re.findall(r"\d+", out)
    print(f"{a.dst}: {len(out.split())} words; digits remaining: {len(left)}" + (f" e.g. {left[:8]}" if left else ""))


if __name__ == "__main__":
    main()
