#!/usr/bin/env python3
"""Catch garbled chunks before a listener does: transcribe each rendered chunk with Whisper and
score it against its source text (word error rate).

usage: check.py --voice VOICE.json OUT_DIR part.txt [...] [--thresh 0.25] [--redo] [--show 5]

--redo re-renders every chunk over the threshold with a fresh seed (engines that support
reseed) and scores it again; then rerun narrate.py to reassemble the part wavs.
Needs: pip install transformers whisper-normalizer (Whisper runs on GPU when there is one).
"""
import argparse
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import narrate as N  # noqa: E402

BRACKETS = re.compile(r"[\[\]()]")


def wer(norm, ref, hyp):
    r, h = norm(BRACKETS.sub(" ", ref)).split(), norm(BRACKETS.sub(" ", hyp)).split()
    if not r:
        return 0.0
    d = list(range(len(h) + 1))
    for i in range(1, len(r) + 1):
        prev, d[0] = d[0], i
        for j in range(1, len(h) + 1):
            cur = d[j]
            d[j] = min(d[j] + 1, d[j - 1] + 1, prev + (r[i - 1] != h[j - 1]))
            prev = cur
    return d[len(h)] / max(1, len(r))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--voice", required=True)
    ap.add_argument("out_dir")
    ap.add_argument("parts", nargs="+")
    ap.add_argument("--thresh", type=float, default=0.25)
    ap.add_argument("--redo", action="store_true")
    ap.add_argument("--show", type=int, default=5)
    ap.add_argument("--asr", default="openai/whisper-small.en")
    a = ap.parse_args()

    import torch
    from transformers import pipeline
    from whisper_normalizer.english import EnglishTextNormalizer
    norm = EnglishTextNormalizer()
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    asr = pipeline("automatic-speech-recognition", model=a.asr, device=dev,
                   torch_dtype=torch.float16 if dev == "cuda" else torch.float32)
    r = N.Renderer(a.voice, a.out_dir)

    def score(c):
        hyp = asr(r.path(c))["text"].strip()
        return wer(norm, c, hyp), hyp

    bad_all = []
    for f in a.parts:
        name = os.path.splitext(os.path.basename(f))[0]
        items = [c for c, _ in N.chunks(open(f, encoding="utf-8").read()) if os.path.exists(r.path(c))]
        rows = sorted(((*score(c), c) for c in items), key=lambda x: -x[0])
        bad = [x for x in rows if x[0] > a.thresh]
        mean = sum(x[0] for x in rows) / max(1, len(rows))
        print(f"[{name}] {len(rows)} chunks, mean WER {mean:.3f}, over {a.thresh}: {len(bad)}", flush=True)
        for e, hyp, c in rows[:a.show]:
            print(f"   WER {e:.2f}\n   SRC {c[:160]}\n   HYP {hyp[:160]}", flush=True)
        bad_all += [(name, c, e) for e, _, c in bad]

    if bad_all and a.redo:
        eng = r.engine
        if hasattr(eng, "reseed"):
            eng.reseed(20260919)
        for name, c, e in bad_all:
            r.render(c, force=True)
            e2, hyp = score(c)
            print(f"redo [{name}] WER {e:.2f} -> {e2:.2f}" + ("" if e2 <= a.thresh else f"  STILL BAD: {hyp[:120]}"), flush=True)
        print("now rerun narrate.py on those parts to reassemble", flush=True)
    sys.exit(1 if bad_all and not a.redo else 0)


if __name__ == "__main__":
    main()
