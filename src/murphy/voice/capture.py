# capture.py records microphone audio for push-to-talk.
# Runs off the AppKit main thread; returns float32 mono PCM for the STT layer.

from __future__ import annotations

import collections
import queue
import threading
from dataclasses import dataclass
from typing import Protocol

import numpy as np
import sounddevice as sd


@dataclass(frozen=True)
class CaptureResult:
    """PCM samples from one push-to-talk take."""

    samples: np.ndarray  # float32, shape (n,)
    sample_rate: int

    @property
    def duration_seconds(self) -> float:
        if self.sample_rate <= 0:
            return 0.0
        return float(len(self.samples)) / float(self.sample_rate)

    @property
    def is_empty(self) -> bool:
        return len(self.samples) == 0


class AudioCaptureProtocol(Protocol):
    def start(self) -> None: ...

    def stop(self) -> CaptureResult: ...


class AudioCapture:
    """
    Push-to-talk mic capture via sounddevice.

    start() opens the stream and records until stop().
    A short ring buffer keeps the most recent preroll (useful later for wake-word).
    """

    def __init__(
        self,
        sample_rate: int = 16000,
        block_size: int = 1280,
        preroll_seconds: float = 1.0,
    ) -> None:
        self.sample_rate = sample_rate
        self.block_size = block_size
        self.preroll_seconds = preroll_seconds
        self._queue: queue.Queue[np.ndarray] = queue.Queue() # raw handoff queue for audio chunks
        self._stream: sd.InputStream | None = None
        self._running = threading.Event()
        self._drain_thread: threading.Thread | None = None # dedicated thread to move chunks from the queue to chunks and ring buffer
        self._chunks: list[np.ndarray] = [] # full recording for the current PTT
        self._lock = threading.Lock()

        preroll_chunks = max(1, int(preroll_seconds * sample_rate / block_size))
        self._ring: collections.deque[np.ndarray] = collections.deque( # preroll buffer
            maxlen=preroll_chunks
        )

    def start(self) -> None:
        """Open the default input device and begin recording."""

        # Raise an error if the capture is already running
        if self._running.is_set():
            raise RuntimeError("AudioCapture is already running")

        with self._lock:
            # empty the queue and buffers
            self._chunks = [] 
            self._ring.clear() 
            while not self._queue.empty():
                try:
                    self._queue.get_nowait()
                except queue.Empty:
                    break

        self._running.set() # mark recording as started (so we don't start a second thread)
        self._drain_thread = threading.Thread( # start the dedicated thread to move chunks from the queue to chunks and ring buffer
            target=self._drain_loop,
            name="murphy-audio-drain",
            daemon=True,
        )
        self._drain_thread.start() # start the thread

        self._stream = sd.InputStream( # open the mic and start recording
            samplerate=self.sample_rate,
            channels=1,
            dtype="float32",
            blocksize=self.block_size,
            callback=self._on_audio,
        )
        self._stream.start()

    def stop(self) -> CaptureResult:
        """Stop the stream and return the recorded mono float32 samples."""
        self._running.clear()

        stream = self._stream
        self._stream = None
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception:
                pass

        drain = self._drain_thread
        self._drain_thread = None
        if drain is not None:
            drain.join(timeout=2.0)

        # Pick up any frames still sitting in the queue
        self._consume_queue()

        with self._lock:
            if not self._chunks:
                samples = np.zeros(0, dtype=np.float32)
            else:
                samples = np.concatenate(self._chunks).astype(np.float32, copy=False)
            self._chunks = []

        return CaptureResult(samples=samples, sample_rate=self.sample_rate)

    def _on_audio(self, indata, frames, time_info, status) -> None:  # noqa: ANN001
        if not self._running.is_set():
            return
        # sounddevice delivers shape (frames, channels); we asked for mono
        mono = np.ascontiguousarray(indata[:, 0], dtype=np.float32).copy()
        self._queue.put(mono)

    def _drain_loop(self) -> None:
        while self._running.is_set() or not self._queue.empty():
            try:
                chunk = self._queue.get(timeout=0.05)
            except queue.Empty:
                continue
            with self._lock:
                self._ring.append(chunk)
                self._chunks.append(chunk)

    def _consume_queue(self) -> None:
        while True:
            try:
                chunk = self._queue.get_nowait()
            except queue.Empty:
                break
            with self._lock:
                self._ring.append(chunk)
                self._chunks.append(chunk)


class FakeAudioCapture:
    """Test double: no microphone; returns preset samples on stop()."""

    def __init__(
        self,
        samples: np.ndarray | None = None,
        sample_rate: int = 16000,
    ) -> None:
        self.sample_rate = sample_rate
        self._samples = (
            np.zeros(0, dtype=np.float32)
            if samples is None
            else np.asarray(samples, dtype=np.float32).reshape(-1)
        )
        self._running = False

    def start(self) -> None:
        if self._running:
            raise RuntimeError("FakeAudioCapture is already running")
        self._running = True

    def stop(self) -> CaptureResult:
        if not self._running:
            return CaptureResult(
                samples=np.zeros(0, dtype=np.float32),
                sample_rate=self.sample_rate,
            )
        self._running = False
        return CaptureResult(samples=self._samples.copy(), sample_rate=self.sample_rate)
