"""TTS engines behind one interface: synth(text) -> (float32 mono pcm, sample_rate).

A voice config is a small JSON file naming the engine and its options:

    {"engine": "chatterbox", "voice": "voices/narrator.wav",
     "options": {"exaggeration": 0.4, "cfg_weight": 0.5}, "seed": 1234}

    {"engine": "openai", "url": "http://localhost:8880/v1/audio/speech",
     "model": "kokoro", "voice": "af_heart", "options": {"speed": 1.0}}

    {"engine": "command", "cmd": "piper --model en_US-lessac-high.onnx --output_file {out}"}

Adding an engine: write a class with `synth(self, text) -> (pcm, sr)` (and optionally
`reseed(self, n)`), then register it in ENGINES. Nothing else in the pipeline changes.
"""
import io
import json
import os
import subprocess
import tempfile
import urllib.request
import wave

import numpy as np


def read_wav_bytes(data):
    with wave.open(io.BytesIO(data), "rb") as w:
        sr, ch, width = w.getframerate(), w.getnchannels(), w.getsampwidth()
        raw = w.readframes(w.getnframes())
    if width != 2:
        raise ValueError(f"expected 16-bit wav, got {8 * width}-bit")
    pcm = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32767
    if ch > 1:
        pcm = pcm.reshape(-1, ch).mean(axis=1)
    return pcm, sr


class Chatterbox:
    """Resemble AI Chatterbox, zero-shot voice cloning from a ~10 s reference wav.
    pip install chatterbox-tts"""

    def __init__(self, voice=None, options=None, seed=1234, device=None):
        import torch
        from chatterbox.tts import ChatterboxTTS
        self.torch = torch
        if device is None:
            device = "cuda" if torch.cuda.is_available() else "mps" if torch.backends.mps.is_available() else "cpu"
        self.model = ChatterboxTTS.from_pretrained(device=device)
        self.voice = voice
        self.options = {"exaggeration": 0.5, "cfg_weight": 0.5, **(options or {})}
        self.reseed(seed)

    def reseed(self, n):
        self.torch.manual_seed(n)

    def synth(self, text):
        with self.torch.inference_mode():
            wav = self.model.generate(text, audio_prompt_path=self.voice, **self.options)
        return wav.squeeze().cpu().numpy().astype(np.float32), self.model.sr


class OpenAISpeech:
    """Any server speaking OpenAI's POST /v1/audio/speech: OpenAI itself, Kokoro-FastAPI,
    chatterbox-tts-api, openedai-speech, LocalAI, ... The API key comes from the env var
    named by `api_key_env` (default OPENAI_API_KEY); local servers usually need none."""

    def __init__(self, url="https://api.openai.com/v1/audio/speech", model="tts-1", voice="alloy",
                 options=None, api_key_env="OPENAI_API_KEY", seed=None):
        self.url, self.model, self.voice = url, model, voice
        self.options = options or {}
        self.key = os.environ.get(api_key_env or "", "")

    def synth(self, text):
        body = {"model": self.model, "input": text, "voice": self.voice, "response_format": "wav", **self.options}
        req = urllib.request.Request(self.url, data=json.dumps(body).encode(), method="POST",
                                     headers={"Content-Type": "application/json",
                                              **({"Authorization": "Bearer " + self.key} if self.key else {})})
        with urllib.request.urlopen(req, timeout=300) as r:
            return read_wav_bytes(r.read())


class Command:
    """Any CLI. The chunk text goes to stdin; {out} in `cmd` is replaced by a temp .wav path
    the command must write. Example (Piper):
        {"engine": "command", "cmd": "piper --model en_US-lessac-high.onnx --output_file {out}"}"""

    def __init__(self, cmd, seed=None, **_):
        self.cmd = cmd

    def synth(self, text):
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "chunk.wav")
            subprocess.run(self.cmd.format(out=out), shell=True, input=text.encode(), check=True)
            with open(out, "rb") as f:
                return read_wav_bytes(f.read())


ENGINES = {"chatterbox": Chatterbox, "openai": OpenAISpeech, "command": Command}


def load_config(path):
    with open(path, encoding="utf-8") as f:
        cfg = json.load(f)
    base = os.path.dirname(os.path.abspath(path))
    v = cfg.get("voice")
    if cfg.get("engine") == "chatterbox" and v and not os.path.isabs(v):
        cfg["voice"] = os.path.join(base, v)            # reference wav relative to the config file
    return cfg


def signature(cfg):
    """What makes a rendered chunk reusable: same engine, same voice, same options."""
    keep = {k: cfg.get(k) for k in ("engine", "voice", "model", "url", "cmd", "options")}
    if keep.get("voice") and os.path.exists(str(keep["voice"])):
        keep["voice"] = os.path.basename(keep["voice"]) + ":" + str(os.path.getsize(keep["voice"]))
    return json.dumps(keep, sort_keys=True)


def make(cfg):
    kw = {k: v for k, v in cfg.items() if k != "engine"}
    return ENGINES[cfg["engine"]](**kw)
