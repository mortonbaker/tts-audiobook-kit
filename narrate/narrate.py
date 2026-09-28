#!/usr/bin/env python3
"""Spoken-form text -> one WAV per part, with any engine in engines.py.

usage: narrate.py --voice VOICE.json OUT_DIR part.txt [part.txt ...]

Every chunk is cached as OUT_DIR/cache/<hash>.wav, keyed by the chunk's TEXT plus the
voice signature (engine, voice, options). So:
  - a crashed or stopped run resumes where it left off;
  - editing a word re-renders only the chunks whose text changed, then reassembles;
  - switching voice or engine re-renders everything (different signature).
Paragraph gaps are longer than sentence gaps; a line starting with an em dash (an
epigraph attribution) gets the longest pause.
"""
import argparse
import hashlib
import os
import re
import sys
import time
import wave

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import engines as E  # noqa: E402

MAX_CHARS = 240          # Chatterbox drifts past ~300 chars; stay under
SENT_GAP = 0.30          # seconds between chunks inside a paragraph
PARA_GAP = 0.75          # seconds between paragraphs
EPIGRAPH_GAP = 1.5       # after an epigraph attribution line (starts with an em dash)


def chunks(text):
    """Yield (chunk_text, ends_paragraph)."""
    for para in re.split(r"\n\s*\n", text.strip()):
        para = " ".join(para.split())
        if not para:
            continue
        sents = re.split(r"(?<=[.!?…])\s+(?=[\"'(A-Z—])", para)
        buf, out = "", []
        for s in sents:
            if buf and len(buf) + 1 + len(s) > MAX_CHARS:
                out.append(buf)
                buf = s
            else:
                buf = (buf + " " + s).strip()
        if buf:
            out.append(buf)
        final = []                        # one sentence longer than MAX_CHARS: split on clause punctuation
        for c in out:
            while len(c) > MAX_CHARS * 1.5:
                cut = max(c.rfind(", ", 0, MAX_CHARS), c.rfind("; ", 0, MAX_CHARS), c.rfind(": ", 0, MAX_CHARS))
                if cut < 40:
                    break
                final.append(c[:cut + 1])
                c = c[cut + 2:]
            final.append(c)
        for i, c in enumerate(final):
            yield c, i == len(final) - 1


def gap(chunk, para_end):
    return EPIGRAPH_GAP if chunk.startswith("—") else PARA_GAP if para_end else SENT_GAP


def key(sig, text):
    return hashlib.md5((sig + "\n" + text).encode("utf-8")).hexdigest()


def write_wav(path, pcm, sr):
    tmp = path + ".tmp"
    with wave.open(tmp, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((np.clip(pcm, -1, 1) * 32767).astype(np.int16).tobytes())
    os.replace(tmp, path)                 # never leave a half-written wav for a watcher to grab


def read_wav(path):
    with wave.open(path, "rb") as w:
        return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32767, w.getframerate()


class Renderer:
    def __init__(self, voice_cfg, out_dir):
        self.cfg = E.load_config(voice_cfg)
        self.sig = E.signature(self.cfg)
        self.cache = os.path.join(out_dir, "cache")
        os.makedirs(self.cache, exist_ok=True)
        self._engine = None

    @property
    def engine(self):
        if self._engine is None:          # load the model only if something needs rendering
            self._engine = E.make(self.cfg)
        return self._engine

    def path(self, text):
        return os.path.join(self.cache, key(self.sig, text) + ".wav")

    def render(self, text, force=False):
        p = self.path(text)
        if force or not os.path.exists(p):
            pcm, sr = self.engine.synth(text)
            write_wav(p, pcm, sr)
        return p


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--voice", required=True, help="voice config JSON (see engines.py)")
    ap.add_argument("out_dir")
    ap.add_argument("parts", nargs="+")
    a = ap.parse_args()
    r = Renderer(a.voice, a.out_dir)
    for f in a.parts:
        name = os.path.splitext(os.path.basename(f))[0]
        items = list(chunks(open(f, encoding="utf-8").read()))
        todo = [c for c, _ in items if not os.path.exists(r.path(c))]
        print(f"[{name}] {len(items)} chunks, {len(todo)} to render, {sum(len(c) for c, _ in items)} chars", flush=True)
        t0, done = time.time(), 0
        for c in todo:
            r.render(c)
            done += 1
            if done % 20 == 0 or done == len(todo):
                print(f"[{name}] {done}/{len(todo)} {time.time() - t0:.0f}s", flush=True)
        pcm, sr = [], None
        for c, para_end in items:
            x, sr = read_wav(r.path(c))
            pcm += [x, np.zeros(int(sr * gap(c, para_end)), dtype=np.float32)]
        out = os.path.join(a.out_dir, name + ".wav")
        write_wav(out, np.concatenate(pcm), sr)
        print(f"[{name}] -> {out} {sum(len(x) for x in pcm) / sr / 60:.1f} min", flush=True)


if __name__ == "__main__":
    main()
