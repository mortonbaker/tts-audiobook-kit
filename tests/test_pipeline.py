"""Every rule here exists because a real book export produced a string that broke narration.
The cases below are paraphrases that trip the same rule. Run: python -m pytest -q
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest  # noqa: E402

import strip_apparatus as sa  # noqa: E402
import verbalize as vb  # noqa: E402

# ---------------------------------------------------------------- stage 1

@pytest.mark.parametrize("src,want", [
    ("one powerful reason for the railroad to prefer Chicago in the 1890 survey.69 But Chicago",
     "one powerful reason for the railroad to prefer Chicago in the 1890 survey. But Chicago"),
    ("Less regulation means less burden” on shipping firms.70", "Less regulation means less burden” on shipping firms."),
    ("that were then being debated in Parliament, and ultimately defeated.72)", "that were then being debated in Parliament, and ultimately defeated.)"),
    ("the 3.5 billion people who occupy the bottom half of the world’s income scale.73 Thanks",
     "the 3.5 billion people who occupy the bottom half of the world’s income scale. Thanks"),
    ("—Massachusetts Attorney General Robert. K. Smith1", "—Massachusetts Attorney General Robert. K. Smith"),
    ("Acme Firm Won $3.8bn Contracts", "Acme Firm Won $3.8bn Contracts"),          # decimal survives
    ("ended in 1980.12 The next year", "ended in 1980. The next year"),
])
def test_inline_note_numbers(src, want):
    assert sa.strip_inline_note_numbers(src) == want


@pytest.mark.parametrize("src,want", [
    ("the canal in 1904 and the bridge in 1937 (below, pp. 18–20, 27–28). It is", "the canal in 1904 and the bridge in 1937. It is"),
    ("the steam revolution before it (see below, pp. 101–08), turns out", "the steam revolution before it, turns out"),
    ("I say below (p. 99) that America", "I say below that America"),
    ("As I warn below on p. 14, the argument", "As I warn below, the argument"),
])
def test_page_refs(src, want):
    assert sa.strip_page_refs(src) == want


def test_acronym_defs():
    assert sa.strip_acronym_defs("recent structural adjustment programs (SAPs) have been") == "recent structural adjustment programs have been"
    assert sa.strip_acronym_defs("Rural Electrification Administration (REA) was") == "Rural Electrification Administration was"


def test_small_caps_opener():
    src = "ON FEBRUARY 3, 2017, THE NEW YORK TIMES REPORTED THE COMPANY’S plans"
    out = sa.unshout_openers(src, sa.DEFAULT_ACRONYMS)
    assert out == "On february 3, 2017, the new york times reported the company’s plans"
    src = "FROM THE OUTSET OF HER YEARS AT NASA, HOPPER’S INFLUENCE was"
    assert sa.unshout_openers(src, sa.DEFAULT_ACRONYMS) == "From the outset of her years at NASA, hopper’s influence was"


def test_heading_case_and_period():
    out = sa.unshout_headings("THE BBC, MARKS AND SPENCER, AND THE LONDON UNDERGROUND", sa.DEFAULT_ACRONYMS, True)
    assert out == "The BBC, Marks And Spencer, And The London Underground."
    out = sa.unshout_headings("WHAT IS MEANT BY THE GILDED AGE?", sa.DEFAULT_ACRONYMS, True)
    assert out == "What Is Meant By The Gilded Age?"


def test_drop_blocks_per_chapter_notes():
    lines = ["body", "NOTES", "1. note", "2. note", "CHAPTER 1", "more body", "NOTES", "3. note"]
    assert sa.drop_blocks(lines, [("NOTES", r"CHAPTER \d+")]) == ["body", "CHAPTER 1", "more body"]


# ---------------------------------------------------------------- stage 2 (pre rules, engine-independent)

@pytest.mark.parametrize("src,want", [
    ("Since 9/11, above all", "Since nine eleven, above all"),
    ("on U.S. Presidents, 1961–1980", "on United States Presidents, 1961 to 1980"),
    # word compounds: a hyphen or slash left a gap in the narration ("Austro... Hungarian")
    ("Austro-Hungarian in 1867–1918, and", "Austro Hungarian in 1867 to 1918, and"),
    ("the Austro/Hungarian empire and/or the Anglo-Saxon court", "the Austro Hungarian empire and or the Anglo Saxon court"),
    ("a well-known B-52 pilot", "a well known B 52 pilot"),
    ("Europe—backed by some", "Europe—backed by some"),     # em dash is a wanted pause: leave it
    ("s/Jane Smith.", "signed, Jane Smith."),
    # dotted acronyms: the chunker split "I.B.M. Research" into two sentences
    ("The History of I.B.M. Research.", "The History of IBM Research."),
    ("Thus while R.C.A. Victor records", "Thus while RCA Victor records"),
    ("owned by G.E.C., and by R.C.A. The next year", "owned by GEC, and by RCA. The next year"),
    ("the B.B.C. in London", "the BBC in London"),
    ("worked for Siemens A.G.", "worked for Siemens AG."),
    ("the Bosch A.G subsidiary", "the Bosch AG subsidiary"),
    ("roles of American I. B. Holdings, General", "roles of American I B Holdings, General"),
    ("largely a C. S. Lewis production", "largely a C S Lewis production"),
    ("alternates T. S. Eliot, a Faber partner", "alternates T S Eliot, a Faber partner"),
    ("It is alleged that H. Smith, president", "It is alleged that H Smith, president"),
    ("delegates was A. Turing of the British", "delegates was A Turing of the British"),
    ("(See Table 2-2.) Margaret", "(See Table 2 2.) Margaret"),
    ("5-10 years; 10–20 percent", "5 to 10 years; 10 to 20 percent"),
    ("Won $3.8bn Contracts", "Won $3.8 billion Contracts"),
    ("worth $4.5m today", "worth $4.5 million today"),
    ("Henry VIII and Louis XIV", "Henry the Eighth and Louis the Fourteenth"),
    ("Star Wars II followed", "Star Wars two followed"),
    ("World War II ended", "World War two ended"),
    ("in the ’80s", "in the 80s"),
    ("No. 5; Vol. 2, pp. 18-20, p. 5. Cf. chapter 3. Ibid.", "Number 5; Volume 2, pages 18 to 20, page 5. Compare chapter 3. ibidem"),
    ("Sen. Jane Smith and Gen. Grant, i.e., the BBC & NASA", "Senator Jane Smith and General Grant, that is, the BBC and NASA"),
    ("Roe v. Wade; Smith vs. Jones", "Roe versus Wade; Smith versus Jones"),
])
def test_pre_rules(src, want):
    assert vb.pre(src) == want


# ---------------------------------------------------------------- stage 2 (simple engine, end to end)

@pytest.mark.parametrize("src,want", [
    ("Acme Firm Won $3.8bn Contracts from Government.", "Acme Firm Won three point eight billion dollars Contracts from Government."),
    ("as much as the 3.5 billion people", "as much as the three point five billion people"),
    ("on U.S. Presidents, 1961–1980", "on United States Presidents, nineteen sixty one to nineteen eighty"),
    ("In the 1960s and the ’80s, 20% of GDP, i.e., $1.2 trillion",
     "In the nineteen sixties and the eighties, twenty percent of GDP, that is, one point two trillion dollars"),
    ("the 21st century; 3rd edition", "the twenty first century; third edition"),
    ("in 1953 the BBC spent $1,000,000 on radio; 10,500 men; 7,000 more.",
     "in nineteen fifty three the BBC spent one million dollars on radio; ten thousand five hundred men; seven thousand more."),
])
def test_simple_engine(src, want):
    pytest.importorskip("num2words")
    assert vb.verbalize(src, "simple") == want


def test_no_digits_survive_simple():
    pytest.importorskip("num2words")
    import re
    src = "On February 3, 2017, 20% of $3.8bn went to 1,200 people in 5-10 years (pp. 18–20); 9/11; 1984–86; No. 7."
    assert not re.search(r"\d", vb.verbalize(src, "simple"))


# ---------------------------------------------------------------- initials
# A narrator stopped dead after the "S" in "Ulysses S. Grant" because the chunker
# split the sentence on that period.

@pytest.mark.parametrize("src,want", [
    ("advisers close to Ulysses S. Grant, looked for", "advisers close to Ulysses S Grant, looked for"),
    ("the Gerard M. Hopkins poems", "the Gerard M Hopkins poems"),
    ("in the Mary W. Shelley novels", "in the Mary W Shelley novels"),
    ("research by J. Robert Oppenheimer, the", "research by J Robert Oppenheimer, the"),
    ("Hunt, Moore, G. Gordon Brown, and the", "Hunt, Moore, G Gordon Brown, and the"),
    ("Chief Engineer J. Howard Smith directed", "Chief Engineer J Howard Smith directed"),
    ("two of the six (William H. Jackson and Frank", "two of the six (William H Jackson and Frank"),
    ("—Massachusetts Attorney General Robert. K. Smith", "—Massachusetts Attorney General Robert. K Smith"),
    ("the work of W. E. B. Du Bois", "the work of W E B Du Bois"),
    ("Admiral Grace B. Hopper, then retired, came", "Admiral Grace B Hopper, then retired, came"),
])
def test_name_initials(src, want):
    assert vb.name_initials(src) == want


@pytest.mark.parametrize("src", [
    "pages just for the letter A. By June 2014 the file",     # real one-letter sentence end
    "backed by his newspaper the L.A. Times, proceeded",      # dotted acronym, no space
    "under the Clean Air Act, Pub. L. one hundred and one",   # initial before a lowercase word
])
def test_name_initials_leaves_sentences_alone(src):
    assert vb.name_initials(src) == src


def test_generational_suffixes():
    assert vb.pre("the Martin Luther King, Jr. memorial") == "the Martin Luther King, Junior memorial"
    assert vb.pre("Smith, Sr., came close") == "Smith, Senior, came close"
    assert vb.pre("born in St. Louis") == "born in Saint Louis"


def test_us_survives_initials_pass():
    assert vb.pre("a U.S. Senate committee") == "a United States Senate committee"


@pytest.mark.parametrize("src,want", [
    ("questioned by the BBC., which had learned", "questioned by the BBC, which had learned"),
    ("John Smith, Sr., Mary Jones", "John Smith, Sr, Mary Jones"),
    ("brought to the ground., by six workers", "brought to the ground, by six workers"),
    ("King, junior.) with a new program", "King, junior) with a new program"),
    ("Emirates (UAE.) city of Dubai", "Emirates (UAE) city of Dubai"),
    ("of the guild.) Faced with a government", "of the guild.) Faced with a government"),   # real stop
])
def test_stray_periods(src, want):
    assert vb.stray_periods(src) == want
