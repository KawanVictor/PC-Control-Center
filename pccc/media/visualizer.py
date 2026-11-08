"""Visualizador de áudio: espectro do som que está tocando no PC.

Captura por *loopback* WASAPI (o mesmo recurso que gravadores de tela usam para pegar o som
do sistema), ou seja, lê uma cópia do que vai para a saída padrão — nada é gravado em disco
e o microfone não é usado. Roda numa thread própria somente enquanto algum visualizador
estiver na tela (widget ou página), e para sozinho alguns segundos depois.
"""
from __future__ import annotations

import threading
import time
import warnings

import numpy as np

from ..core.com import ensure_com
from ..core.logger import get_logger

log = get_logger("visualizer")

RATE = 48000
BLOCK = 1024                 # ~21 ms por leitura
FFT = 2048
BANDS = 48
FMIN, FMAX = 40.0, 16000.0
IDLE_STOP_S = 5.0


class AudioVisualizer:
    _instance: "AudioVisualizer | None" = None

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._bands = np.zeros(BANDS)
        self._peaks = np.zeros(BANDS)
        self._level = 0.0
        self._last_use = 0.0
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self.error = ""
        self.device = ""
        edges = np.geomspace(FMIN, FMAX, BANDS + 1)
        freqs = np.fft.rfftfreq(FFT, 1 / RATE)
        self._bins = [(int(np.searchsorted(freqs, lo)), max(int(np.searchsorted(freqs, hi)),
                                                             int(np.searchsorted(freqs, lo)) + 1))
                      for lo, hi in zip(edges[:-1], edges[1:], strict=True)]
        self._window = np.hanning(FFT).astype(np.float32)
        # graves têm muito mais energia: compensação leve para o desenho ficar equilibrado
        self._tilt = np.linspace(0.0, 9.0, BANDS)

    @classmethod
    def instance(cls) -> "AudioVisualizer":
        if cls._instance is None:
            cls._instance = AudioVisualizer()
        return cls._instance

    # ------------------------------------------------------------------ uso
    def snapshot(self) -> tuple[list[float], list[float], float]:
        """(bandas 0–1, picos 0–1, nível geral 0–1). Mantém a captura ligada enquanto chamado."""
        self._last_use = time.monotonic()
        if self._thread is None or not self._thread.is_alive():
            self._start()
        with self._lock:
            return self._bands.tolist(), self._peaks.tolist(), self._level

    def _start(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="pccc-visualizer", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        t = self._thread
        if t is not None and t.is_alive():
            t.join(timeout=2)

    # --------------------------------------------------------------- captura
    def _run(self) -> None:
        warnings.simplefilter("ignore")      # soundcard avisa sobre descontinuidades (normal)
        # O soundcard inicia o COM ao ser importado e trata "COM já iniciado" (S_FALSE) como
        # erro — por isso ele é importado ANTES do ensure_com, nesta thread de trabalho.
        try:
            import soundcard as sc
        except Exception as e:     # noqa: BLE001
            self.error = f"Captura de áudio indisponível: {e}"
            log.warning(self.error)
            return
        ensure_com()
        buf = np.zeros(FFT, dtype=np.float32)
        while not self._stop.is_set():
            if time.monotonic() - self._last_use > IDLE_STOP_S:
                break
            try:
                spk = sc.default_speaker()
                self.device = spk.name
                mic = sc.get_microphone(id=str(spk.name), include_loopback=True)
                self.error = ""
                with mic.recorder(samplerate=RATE, blocksize=BLOCK) as rec:
                    check = time.monotonic()
                    while not self._stop.is_set():
                        data = rec.record(numframes=BLOCK)
                        mono = data.mean(axis=1) if data.ndim == 2 else data
                        buf = np.roll(buf, -len(mono))
                        buf[-len(mono):] = mono[-FFT:]
                        self._analyze(buf)
                        now = time.monotonic()
                        if now - self._last_use > IDLE_STOP_S:
                            break
                        if now - check > 2.0:          # saída padrão mudou? recomeça nela
                            check = now
                            if sc.default_speaker().name != self.device:
                                break
            except Exception as e:     # noqa: BLE001 — sem saída de áudio, dispositivo removido...
                self.error = str(e) or type(e).__name__
                log.debug("Visualizador: %s", e)
                with self._lock:
                    self._bands[:] = 0
                    self._level = 0.0
                self._stop.wait(2.0)
        with self._lock:
            self._bands[:] = 0
            self._peaks[:] = 0
            self._level = 0.0

    def _analyze(self, buf: np.ndarray) -> None:
        spec = np.abs(np.fft.rfft(buf * self._window)) / (FFT / 4)
        mags = np.array([spec[a:b].max() for a, b in self._bins])
        db = 20 * np.log10(mags + 1e-9) + self._tilt
        target = np.clip((db + 60) / 60, 0, 1)            # -60 dB → 0, 0 dB → 1
        rms = float(np.sqrt(np.mean(buf[-BLOCK:] ** 2)))
        with self._lock:
            # sobe rápido, desce suave (como um VU)
            up = target > self._bands
            self._bands = np.where(up, self._bands * 0.35 + target * 0.65, self._bands * 0.82 + target * 0.18)
            self._peaks = np.maximum(self._peaks - 0.012, self._bands)
            self._level = min(1.0, rms * 4)


def is_running() -> bool:
    v = AudioVisualizer._instance
    return bool(v and v._thread and v._thread.is_alive())
