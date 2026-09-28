# tts-audiobook-kit

Turn a book you own into a narrated audiobook with **the TTS engine and voice you like**, then
publish it to [Audiobookshelf](https://www.audiobookshelf.org/) with working chapters.

```
book.epub ─► epub_parts.py ─► verbalize.py ─► narrate.py ─► check.py ─► publish.sh ─► Audiobookshelf
             one text file     numbers, dates,  any engine,    Whisper      mp3 + tags,
             per chapter       initials → speech any voice     catches      chapters that
                                                               garbled audio actually work
```

Most of the work is not the voice. It is getting the **text** into a shape a TTS engine reads
without stumbling, and getting the **player** to show every chapter. This kit is the set of
fixes that took, each one written down with the string that forced it.

## Install

```sh
pip install lxml num2words numpy pytest        # text prep + tests
pip install chatterbox-tts                      # if you use Chatterbox (GPU strongly recommended)
pip install transformers whisper-normalizer     # for check.py
pip install nemo_text_processing                # optional, best number verbalizer (Linux x86_64)
# publish.sh needs ffmpeg; the EPUB step can also run under calibre: calibre-debug -e epub_parts.py -- ...
python -m pytest -q
```

## Quick start

```sh
# 1. See the book's structure, then cut it into parts
python epub_parts.py book.epub --list
python epub_parts.py book.epub stripped \
    --part 00=OEBPS/preface.xhtml --part 01=OEBPS/ch01.xhtml --part 02=OEBPS/ch02.xhtml

# 2. Written form -> spoken form
mkdir -p spoken
for f in stripped/*.txt; do python verbalize.py "$f" "spoken/$(basename "$f")" --engine nemo; done

# 3. Render (resumable; rerun after any text fix and only changed sentences re-render)
python narrate/narrate.py --voice examples/voices/chatterbox.json out spoken/*.txt

# 4. Listen with a machine first: transcribe every chunk and flag garbled ones
python narrate/check.py --voice examples/voices/chatterbox.json out spoken/*.txt --redo

# 5. Publish as parts finish (can run alongside step 3)
cp examples/book.env.example book.env      # edit it
bash publish/publish.sh book.env
```

The EPUB must be one you are allowed to read this way. This kit does not remove DRM.

## Pick your engine and voice

A voice is a small JSON file. Swap the file, and nothing else changes.

**Chatterbox** (zero-shot cloning: give it ~10–20 s of clean speech from the voice you want):

```json
{"engine": "chatterbox", "voice": "narrator.wav",
 "options": {"exaggeration": 0.4, "cfg_weight": 0.5}, "seed": 1234}
```

Lower `exaggeration` reads calmer, which suits nonfiction. A good reference clip is mono, dry
(no music, no room echo), one speaker, in the pace you want the whole book read at.

**Anything with an OpenAI-style `/v1/audio/speech` endpoint**: OpenAI, Kokoro-FastAPI,
chatterbox-tts-api, openedai-speech, LocalAI and others:

```json
{"engine": "openai", "url": "http://localhost:8880/v1/audio/speech",
 "model": "kokoro", "voice": "af_heart", "options": {"speed": 1.0}, "api_key_env": ""}
```

**Any command-line TTS** (chunk text on stdin, `{out}` is the wav it must write), e.g. Piper:

```json
{"engine": "command", "cmd": "piper --model en_US-lessac-high.onnx --output_file {out}"}
```

**Your own engine**: add a class with `synth(self, text) -> (float32_pcm, sample_rate)` to
`narrate/engines.py` and register it in `ENGINES`. Add `reseed(self, n)` if it is stochastic,
so `check.py --redo` can retry a bad chunk with different sampling.

Rendered chunks are cached by their text **and** the voice signature, so trying a second voice
never mixes with the first.

## Why the text needs fixing first

TTS models are trained on transcripts: "nineteen eighty", not "1980". Engines that run locally
mostly do no normalization, and all of them treat punctuation as prosody. Every rule below came
from a real book that broke a real narration.

### Periods that are not sentence ends (the worst one)

Chunkers split on `. ` + capital letter, and the engine reads each chunk as a full sentence:
falling pitch, a stop, then the rest. In the middle of a name it sounds like a corrupt file.

| Written | Heard | Fixed to |
|---|---|---|
| `Ulysses S. Grant` | "Ulysses S." *(stop)* "Grant" | `Ulysses S Grant` |
| `C. S. Lewis`, `W. E. B. Du Bois` | a stop after each initial | `C S Lewis` |
| `I.B.M. Research`, `R.C.A. Victor` | cut into two sentences | `IBM Research` (sentence-final period kept) |
| `King, Jr. memorial` | stop before "memorial" | `King, Junior memorial` |
| `the BBC., which` | stop mid-clause | `the BBC, which` |
| `the letter A. By June` | a real stop | **left alone** |

### Hyphens and slashes inside words

Some engines hear `Austro-Hungarian` as two phrases and leave a gap ("Austro... Hungarian"). In
an A/B with the same seed, the hyphen produced a 0.24 s gap; a space, 0.12 s at most. So
`word-word` and `word/word` become `word word` (`and/or` → "and or"), before the number engine
and again after it. Number ranges become "to" (`1961–1980`), `Table 7-1` stays a label, em dashes
are left as the pause they are meant to be.

### Numbers, dates, money, abbreviations

`verbalize.py --engine nemo` uses NVIDIA's WFST normalizer (best); `--engine simple` uses
num2words and runs anywhere. Pre-rules fix what NeMo alone gets wrong:

| Input | NeMo alone | With the pre-rules |
|---|---|---|
| `9/11`, `24/7` | nine elevenths, twenty four sevenths | nine eleven, twenty-four seven |
| `1961–1980`, `5-10 years` | nineteen sixty one– nineteen eighty | … to … |
| `U.S.` | US (read as "us") | United States |
| `$3.8bn`, `4.5m` | dollar three point eight b n | three point eight billion dollars |
| `Henry VIII`, `World War II` | unchanged | Henry the Eighth, World War two |
| `No. 5`, `Vol. 2`, `pp. 18–20`, `Cf.`, `Ibid.` | unchanged | Number five, Volume two, pages …, Compare, ibidem |
| `Sen.`, `Gen.`, `Dr.`, `St. Louis` | unchanged | Senator, General, Doctor, Saint Louis |

`verbalize.py` prints how many digits survive. Zero is the target.

### Structure, not just strings (`epub_parts.py`)

Working from the EPUB's XHTML instead of a `.txt` export keeps what the export throws away:

- `<table>`s are dropped whole, instead of read aloud cell by cell;
- footnote markers are `<a>` links, dropped exactly, instead of guessing digits glued to punctuation;
- an epigraph citation `(Author, Title, City: Publisher, 1952, p. 420)` becomes `— Author, Title`
  on its own line (narrate.py pauses longer after a line starting with an em dash);
- `CHAPTER THREE` + title become `Chapter Three.` + `Title.`, so the heading is its own sentence;
- bare list markers (`16.`, `d.`) are glued to their item, so the engine never gets a
  two-character chunk (a common source of garbage audio);
- references to the dropped tables, `(See Table 2-1)`, go too.

`--sub 'OLD=NEW'` fixes typos in the source (applied last). `strip_apparatus.py` does the same job
for a plain `.txt` export (front matter, per-chapter endnotes, bibliography, page cross-references,
small-caps openers) when no EPUB is available.

### Audit before you spend GPU hours

```sh
grep -ohE '\b[A-Z]\.\s[A-Z]' spoken/*.txt | sort | uniq -c    # periods that will split a name
grep -ohE '[A-Za-z][-/][A-Za-z]+' spoken/*.txt | sort | uniq -c # compounds left over
grep -ohE '\b[A-Z]{4,}\b' spoken/*.txt | sort | uniq -c       # all-caps words the engine may spell
```

And print every chunk under ~40 characters (use `narrate.chunks`). Real ones are headings;
anything else is a bad split.

## Render, check, fix

`narrate.py` caches each chunk under `out/cache/` by text + voice. Stop it any time and rerun.
Fix a word in `spoken/07.txt`, rerun on the same parts, and only the changed chunks render
before the part wav is reassembled.

`check.py` transcribes each chunk with Whisper and scores word error rate against the source.
Mean WER on a clean part is about 0.01; a chunk over 0.25 is usually garbled audio (a dropped
clause, a loop, mumbling). `--redo` re-renders those with a new seed and rescores.

## Publish to Audiobookshelf

`publish.sh book.env` waits for each part wav, encodes it (mono 64 kbps, loudness-normalized
to −20 LUFS, full ID3 tags with the part title), drops it into the book's folder in your library,
and asks ABS to rescan. It can run on the ABS host while the render runs on another box
(`WAV_DIR=user@render-box:book/out`). Optional ntfy.sh pushes tell you when the first part is
listenable and when the book is done.

**The chapter trap:** ABS builds an item's chapter list once, when it first creates the item.
Publish chapter by chapter and the item is created after part 1; every later part appears under
Audio Tracks while chapter navigation dead-ends. Rescans do not fix it. So `publish.sh` ends with
`abs_tool.py chapters "<Book>"`, which rebuilds one chapter per track from the tracks' own
durations and titles, and exits non-zero unless chapters == tracks. Do not call a book published
until it passes.

## Files

```
epub_parts.py          EPUB -> one clean text file per part (lxml)
strip_apparatus.py     the same from a .txt export, no dependencies
verbalize.py           written -> spoken form (nemo | simple)
narrate/engines.py     chatterbox | openai-compatible | command; add your own
narrate/narrate.py     text parts -> part wavs, text-keyed chunk cache
narrate/check.py       Whisper WER per chunk, --redo
publish/publish.sh     wavs -> mp3 -> Audiobookshelf, as they finish
publish/abs_tool.py    ABS library scan + chapter rebuild
examples/              sample book (before/after), voice configs, book.env
tests/                 text-rule tests: python -m pytest -q
```

## Contributing a rule

Open a PR with the failing input as a test case first. Every rule here exists because a specific
book produced a specific string; a rule without its string is a guess.

## License

MIT.
