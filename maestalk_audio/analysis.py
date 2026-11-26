"""Public file/array API and features computed from the original signal."""
from dataclasses import asdict, dataclass, field
from pathlib import Path
from threading import RLock
from time import perf_counter
import math
import numpy as np
import soundfile as sf
from .pitch import PitchPair, digest, nearest, valid_hz
from .result import AnalysisResult
from .onsets import OnsetConfig, detect_onsets
from .boundaries import SETTINGS as BOUNDARY_SETTINGS, detect_pitch_boundaries, combine_onsets
from .corrections import PitchRepair

NOTE_NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")


@dataclass(frozen=True)
class AnalysisConfig:
    """Baseline thresholds are calibrated together; changes need fresh evaluation."""
    swift_keep: float = .9
    fcpe_min: float = .8
    hop_s: float = .016
    rms_window_s: float = .1
    volume_change_s: float = .1
    volume_change_threshold_db: float = 1.
    chroma_window_samples: int = 4096
    swift_threads: int = 2
    torch_threads: int | None = 8
    compute_onsets: bool = True
    onset: OnsetConfig = field(default_factory=OnsetConfig)
    expanded_onsets: bool = False
    pitch_repairs: bool = True

    def __post_init__(self):
        if not isinstance(self.compute_onsets,bool) or not isinstance(self.onset,OnsetConfig) or not isinstance(self.expanded_onsets,bool):
            raise ValueError("Invalid onset configuration")
        if self.expanded_onsets and not self.compute_onsets:
            raise ValueError("expanded_onsets requires compute_onsets=True")
        if not isinstance(self.pitch_repairs,bool):
            raise ValueError("pitch_repairs must be a boolean")
        for name in ("swift_keep", "fcpe_min"):
            value = getattr(self, name)
            if not math.isfinite(value) or not 0 <= value <= 1:
                raise ValueError(f"{name} must be in [0, 1]")
        for name in ("hop_s", "rms_window_s", "volume_change_s", "volume_change_threshold_db"):
            value = getattr(self, name)
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be positive and finite")
        for name in ("chroma_window_samples", "swift_threads", "torch_threads"):
            value = getattr(self, name)
            if name == "torch_threads" and value is None:
                continue
            if isinstance(value, bool) or not isinstance(value, int) or value < (32 if name == "chroma_window_samples" else 1):
                raise ValueError(f"Invalid {name}")


def centered_rms(wave, sr, times, window_s=.1):
    centers = np.rint(np.asarray(times)*sr).astype(int)
    half = max(1, round(window_s*sr/2))
    left, right = np.maximum(0, centers-half), np.minimum(len(wave), centers+half)
    energy = np.r_[0., np.cumsum(np.asarray(wave, np.float64)**2)]
    return np.sqrt(np.maximum(0., energy[right]-energy[left])/np.maximum(1, right-left))


def volume_reference(wave, sr):
    """Whole-recording energy reference, independent of pitch detection correctness."""
    hop = max(1, round(.016*sr))
    first = np.arange(0, len(wave), hop)
    end = np.minimum(first+hop, len(wave))
    energy = np.r_[0., np.cumsum(np.asarray(wave, np.float64)**2)]
    powers = np.maximum(0., energy[end]-energy[first])/(end-first)
    if not np.any(powers > 1e-20):
        return None, {"status": "silent", "active_fraction": 0.}
    db = 10*np.log10(np.maximum(powers, 1e-20))
    floor, upper = np.percentile(db, [10, 95])
    threshold = max(upper-35., floor+6.) if upper-floor >= 12. else upper-35.
    active = (db > threshold) & (powers > 1e-20)
    if not active.any():
        return None, {"status": "no_energy_reference", "active_fraction": 0.}
    rms = float(np.sqrt(np.sum((energy[end]-energy[first])[active])/np.sum((end-first)[active])))
    return rms, {"status": "energy_reference_only", "threshold_dbfs": float(threshold),
        "active_fraction": float(np.sum((end-first)[active])/len(wave)),
        "reference_dbfs": float(20*np.log10(rms)), "calibrated_spl": False}


def optional_number(value):
    return float(value) if np.isfinite(value) else None


class AudioAnalyzer:
    """Reusable offline analyzer. Model loading is lazy; calls are serialized.

    Input paths follow the caller's working directory. A frame time is relative
    to the analyzed segment; source_time_s includes its actual file start.
    """
    def __init__(self, config=None, model_dir=None):
        self.config = config if config is not None else AnalysisConfig()
        if not isinstance(self.config, AnalysisConfig):
            raise TypeError("config must be an AnalysisConfig")
        self.model_dir = model_dir
        self._pitch = None
        self._repair = None
        self._lock = RLock()

    def analyze_file(self, path, *, instrument="unspecified", part_id="part1", start_s=0., duration_s=None):
        """Read one mono recording; stereo is rejected instead of silently mixed."""
        path = Path(path).expanduser().resolve()
        if not math.isfinite(start_s) or start_s < 0:
            raise ValueError("start_s must be nonnegative and finite")
        if duration_s is not None and (not math.isfinite(duration_s) or duration_s <= 0):
            raise ValueError("duration_s must be positive and finite")
        info = sf.info(path)
        if info.channels != 1:
            raise ValueError("Expected one separated mono instrument recording; received multiple channels")
        start = round(start_s*info.samplerate)
        if start >= info.frames:
            raise ValueError("start_s is outside the recording")
        stop = min(info.frames, start+round(duration_s*info.samplerate)) if duration_s is not None else info.frames
        wave, sr = sf.read(path, start=start, stop=stop, dtype="float32")
        result = self.analyze_samples(wave, sr, instrument=instrument, part_id=part_id,
                                      source_start_s=start/sr)
        result.summary["source"] = {"filename": path.name, "sha256": digest(path),
            "start_s": start/sr, "end_s": stop/sr, "original_duration_s": info.duration,
            "original_channels": info.channels, "original_subtype": info.subtype}
        return result

    def analyze_samples(self, samples, sample_rate, *, instrument="unspecified", part_id="part1", source_start_s=0.):
        """Analyze >=0.1s of normalized mono samples at an integer 8–192kHz rate."""
        if isinstance(sample_rate, (bool, np.bool_)) or not isinstance(sample_rate, (int, np.integer)) or not 8000 <= sample_rate <= 192000:
            raise ValueError("sample_rate must be an integer from 8000 to 192000 Hz")
        if not math.isfinite(source_start_s) or source_start_s < 0:
            raise ValueError("source_start_s must be nonnegative and finite")
        if not isinstance(part_id, str) or not isinstance(instrument, str):
            raise TypeError("part_id and instrument must be strings")
        wave = np.asarray(samples, dtype=np.float32)
        if wave.ndim != 1 or not len(wave) or not np.isfinite(wave).all():
            raise ValueError("Expected nonempty finite mono samples")
        sr = int(sample_rate)
        if len(wave)/sr < .1:
            raise ValueError("Offline analysis needs at least 0.1 seconds of audio")
        if np.max(np.abs(wave)) > 1.000001:
            raise ValueError("Expected normalized samples in [-1, 1]; read with soundfile dtype='float32'")
        with self._lock:
            return self._analyze(wave, sr, instrument, part_id, float(source_start_s))

    def _analyze(self, wave, sr, instrument, part_id, source_start_s):
        total_start = perf_counter()
        if self._pitch is None:
            self._pitch = PitchPair(self.config, self.model_dir)
        setup_s = perf_counter()-total_start
        started = perf_counter()
        c = self.config
        times = np.arange(0, len(wave)/sr, c.hop_s)
        pitch_start = perf_counter()
        p = self._pitch.predict(wave, sr, times)
        pitch_s = perf_counter()-pitch_start
        onset_start = perf_counter()
        onsets,onset_settings=detect_onsets(wave,sr,pitch_times=times,pitch_hz=p["hz"],config=c.onset) if c.compute_onsets else (None,{"status":"disabled"})
        onset_s=perf_counter()-onset_start
        raw_pitch = p["hz"].copy()
        raw_fcpe = p["use_fcpe"].copy()
        repair_changes = []
        repair_settings = {"enabled":False,"changed_frames":0,"changes":[],"processing_s":0.}
        if c.pitch_repairs:
            if self._repair is None:
                self._repair = PitchRepair(self.model_dir)
            p,repair_changes,repair_settings = self._repair.predict(wave,sr,times,p)
        repaired_by_index = {row["frame_index"]:row for row in repair_changes}
        reference, reference_meta = volume_reference(wave, sr)
        rms = centered_rms(wave, sr, times, c.rms_window_s)
        db = 20*np.log10(np.maximum(rms, 1e-10))
        relative = db-20*np.log10(reference) if reference else np.full(len(times), np.nan)
        previous = max(1, round(c.volume_change_s/c.hop_s))
        delta = np.r_[np.full(min(previous, len(times)), np.nan), db[previous:]-db[:-previous]]
        import librosa
        hop = max(1, round(sr*c.hop_s))
        chroma = librosa.feature.chroma_stft(y=wave, sr=sr, n_fft=c.chroma_window_samples,
                                            hop_length=hop, tuning=0., norm=np.inf)
        chroma_times = np.arange(chroma.shape[1])*hop/sr
        values = np.column_stack([nearest(chroma_times, row, times) for row in chroma])
        frames = []
        for i, t in enumerate(times):
            hz = p["hz"][i]
            midi = round(69+12*np.log2(hz/440)) if valid_hz(hz) else None
            both = valid_hz(p["swift_hz"][i]) and valid_hz(p["fcpe_hz"][i])
            disagree = bool(both and abs(1200*np.log2(p["swift_hz"][i]/p["fcpe_hz"][i])) > 50)
            source = ("fcpe_ddsp" if p["use_fcpe"][i] else "swift") if midi is not None else "none"
            selected_score = p["fcpe_score"][i] if p["use_fcpe"][i] else p["swift_score"][i]
            frames.append({"time_s": float(t), "source_time_s": source_start_s+float(t),
                "part_id": part_id, "instrument": instrument,
                "pitch_hz": optional_number(hz), "note": NOTE_NAMES[midi%12]+str(midi//12-1) if midi is not None else None,
                "midi": midi, "pitch_source": source,
                "raw_pitch_hz":optional_number(raw_pitch[i]),
                "raw_pitch_source":("fcpe_ddsp" if raw_fcpe[i] else "swift") if valid_hz(raw_pitch[i]) else "none",
                "pitch_repair_reason":repaired_by_index[i]["reason"] if i in repaired_by_index else None,
                "source_score": optional_number(selected_score) if midi is not None else None,
                "pitch_state": "unvoiced" if midi is None else "model_disagreement" if disagree else "voiced",
                "swift_hz": optional_number(p["swift_hz"][i]), "swift_score": optional_number(p["swift_score"][i]),
                "fcpe_hz": optional_number(p["fcpe_hz"][i]), "fcpe_score": optional_number(p["fcpe_score"][i]),
                "rms": float(rms[i]), "rms_dbfs": float(db[i]),
                "relative_to_performance_db": optional_number(relative[i]), "volume_change_db": optional_number(delta[i]),
                "volume_direction": "unknown" if not np.isfinite(delta[i]) else "up" if delta[i] >= c.volume_change_threshold_db else "down" if delta[i] <= -c.volume_change_threshold_db else "steady",
                "chroma": [optional_number(v) for v in values[i]]})
        acoustic_onsets = onsets
        boundary_start = perf_counter()
        boundary_frames = [{**row,"pitch_hz":row["raw_pitch_hz"]} for row in frames] if c.expanded_onsets else frames
        pitch_boundaries = detect_pitch_boundaries(boundary_frames) if c.expanded_onsets else None
        if c.expanded_onsets:
            onsets = combine_onsets(acoustic_onsets, pitch_boundaries)
        boundary_s = perf_counter()-boundary_start
        onset_settings = {**onset_settings, "expanded_onsets": c.expanded_onsets,
            "pitch_boundary_settings": dict(BOUNDARY_SETTINGS) if c.expanded_onsets else None,
            "acoustic_candidate_count": len(acoustic_onsets) if acoustic_onsets is not None else None,
            "pitch_boundary_candidate_count": len(pitch_boundaries) if pitch_boundaries is not None else None,
            "combined_candidate_count": len(onsets) if onsets is not None else None,
            "original_onsets_removed": 0,
            "expanded_scope": "Stable observed pitch changes supplement soft attacks; extra detections can increase"}
        summary = {"module_version": "0.4.1", "mode": "offline", "gpu_used": False,
            "audio_duration_s": len(wave)/sr, "sample_rate": sr, "source_start_s": source_start_s,
            "source": {"type": "samples"}, "frame_count": len(frames), "config": asdict(c),
            "models": self._pitch.settings, "volume_reference": reference_meta,
            "volume_change_comparison_s": previous*c.hop_s,
            "chroma": {"names": list(NOTE_NAMES), "method": "librosa chroma_stft",
                "window_samples": c.chroma_window_samples, "hop_samples": hop, "normalization": "per-frame maximum", "octave_information": False},
            "capabilities": {"pitch": "implemented_monophonic", "volume": "implemented_signal_relative",
                "chroma": "implemented", "onsets": "implemented_candidates" if c.compute_onsets else "disabled", "streaming": "not_implemented"},
            "onset_detection":onset_settings,
            "pitch_repair":repair_settings,
            "input_status": {"digital_silence": bool(np.max(np.abs(wave)) == 0),
                "peak": float(np.max(np.abs(wave))), "samples_abs_ge_1": int((np.abs(wave) >= 1).sum())},
            "timing": {"model_setup_s": setup_s, "pitch_processing_s": pitch_s,"onset_processing_s":onset_s,
                "pitch_boundary_processing_s": boundary_s,
                "pitch_repair_processing_s":repair_settings["processing_s"],
                "analysis_processing_s": perf_counter()-started, "total_s": perf_counter()-total_start,
                "scope": "CPU file analysis, excluding file I/O/export; no microphone or UI latency"},
            "limitations": ["Fast MusicNet cello passages remain near 60% nominal-note agreement in the existing evaluation",
                "Onset events are acoustic candidates with measured misses/extras, not guaranteed true starts", "One separated monophonic part per call; no source separation or chord transcription",
                "Model scores are not calibrated correctness probabilities", "RMS is recorded signal level, not SPL or calibrated performance intensity",
                "Energy reference does not solve stationary noise or AGC", "Pitch range 50–2000Hz; FCPE model upper limit 1975.5Hz"]}
        step = max(1, len(wave)//100000)
        waveform = (np.arange(0, len(wave), step)/sr, wave[::step].copy())
        return AnalysisResult(frames=frames, summary=summary, _waveform=waveform,onsets=onsets,
            acoustic_onsets=acoustic_onsets,pitch_boundaries=pitch_boundaries)
