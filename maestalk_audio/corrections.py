"""Guarded selection of existing pitch candidates; preserve voicing and original estimates."""
import json
import math
from pathlib import Path
from time import perf_counter
import numpy as np
from scipy.signal import resample_poly
from .pitch import ASSETS, digest, valid_hz, nearest

SETTINGS = {
    "sample_rate": 16000, "windows_samples": [1024, 2048],
    "keep_selected_score": .95, "candidate_swift_min": .5, "candidate_fcpe_min": .4,
    "stable_radius_frames": 2, "stable_range_cents": 50.,
    "octave_tolerance_cents": 50., "maximum_octaves": 2,
    "minimum_periodicity": .6, "pair_minimum_periodicity_gain": .03,
    "verifier_minimum_score": .8, "verifier_agreement_cents": 35.,
    "maximum_small_change_cents": 300., "verifier_minimum_periodicity_gain": .01,
    "original_pitch_search_cents": 50., "original_pitch_search_step_cents": 5.,
    "gap_recovery_enabled": False,
}


def _distance(a, b):
    result = np.full(len(a), np.inf)
    mask = valid_hz(a) & valid_hz(b)
    result[mask] = abs(1200 * np.log2(a[mask] / b[mask]))
    return result


def _stable(hz):
    radius = SETTINGS["stable_radius_frames"]
    result = np.zeros(len(hz), bool)
    for i in range(radius, len(hz) - radius):
        span = hz[i-radius:i+radius+1]
        if valid_hz(span).all() and 1200*np.log2(span.max()/span.min()) <= SETTINGS["stable_range_cents"]:
            result[i] = True
    return result


def periodicity_at(audio, sr, times, hz, indices, window, *, search_cents=0.):
    """Normalized autocorrelation at candidate periods, only for affected frames."""
    result = np.zeros(len(times), float)
    for i in indices:
        if not np.isfinite(hz[i]) or not 0<hz[i]<sr/2:
            continue
        center = round(times[i]*sr)
        left = center-window//2
        segment = np.zeros(window, np.float32)
        a, b = max(0, left), min(len(audio), left+window)
        if b > a:
            segment[a-left:b-left] = audio[a:b]
        segment = (segment-segment.mean()).astype(float)
        offsets=np.arange(-search_cents,search_cents+1e-9,SETTINGS["original_pitch_search_step_cents"]) if search_cents else np.array([0.])
        lag=np.clip(sr/(hz[i]*2.**(offsets/1200.)),1,window-1)
        # Fractional-lag autocorrelation avoids favoring a subharmonic merely
        # because twice its period happens to land nearer an integer sample.
        size = 2*window
        spectrum = abs(np.fft.rfft(segment,n=size))**2
        phase = lag[:,None]*(2*np.pi*np.fft.rfftfreq(size))[None,:]
        correlation = (spectrum[0] + 2*np.cos(phase[:,1:-1]).dot(spectrum[1:-1])
            + spectrum[-1]*np.cos(phase[:,-1]))/size
        energy = np.r_[0.,np.cumsum(segment**2)]
        grid = np.arange(window+1)
        denominator = np.interp(window-lag,grid,energy) + energy[-1]-np.interp(lag,grid,energy)
        result[i] = np.max(np.clip(2*correlation/np.maximum(denominator,1e-20),-1.,1.))
    return result


def _candidates(pitch, verifier=None):
    raw = np.asarray(pitch["hz"], float)
    native = {key: np.asarray(pitch[key], float) for key in ("swift_hz", "swift_score", "fcpe_hz", "fcpe_score")}
    chosen = np.asarray(pitch["use_fcpe"], bool)
    score = np.where(chosen, native["fcpe_score"], native["swift_score"])
    score = np.nan_to_num(score, nan=0.)
    stable_raw = _stable(raw)
    candidate = np.full(len(raw), np.nan)
    candidate_fcpe = np.zeros(len(raw), bool)
    pair_support = np.zeros(len(raw), bool)
    harmonic_support = np.zeros(len(raw), bool)
    suspicious = np.zeros(len(raw), bool)
    for model, minimum in (("swift", SETTINGS["candidate_swift_min"]), ("fcpe", SETTINGS["candidate_fcpe_min"])):
        hz, own_score = native[model+"_hz"], native[model+"_score"]
        change = _distance(raw, hz)
        multiples = np.rint(np.where(np.isfinite(change), change, 0)/1200)
        octave = (multiples >= 1) & (multiples <= SETTINGS["maximum_octaves"]) & (abs(change-1200*multiples) <= SETTINGS["octave_tolerance_cents"])
        eligible = valid_hz(raw) & valid_hz(hz) & (score < SETTINGS["keep_selected_score"]) & np.isfinite(own_score) & (own_score >= minimum) & stable_raw & (change > 50)
        pair = eligible & octave & _stable(hz)
        candidate[pair] = hz[pair]
        candidate_fcpe[pair] = model == "fcpe"
        pair_support |= pair
        suspicious |= eligible & (octave | (change <= SETTINGS["maximum_small_change_cents"]))
        if verifier is not None:
            vh, vs = verifier["hz"], verifier["score"]
            support = eligible & (octave | (change <= SETTINGS["maximum_small_change_cents"])) & _stable(vh)
            support &= (vs >= SETTINGS["verifier_minimum_score"]) & (_distance(raw, vh) > SETTINGS["verifier_agreement_cents"]) & (_distance(hz, vh) <= SETTINGS["verifier_agreement_cents"])
            # There is only one alternative to the selected two-model frequency.
            # Conflicting evidence is kept out rather than averaged.
            support &= ~valid_hz(candidate) | (_distance(candidate, hz) < 1e-5)
            candidate[support] = hz[support]
            candidate_fcpe[support] = model == "fcpe"
            harmonic_support |= support
    return candidate, candidate_fcpe, pair_support, harmonic_support, suspicious


def repair_pitch(samples, sample_rate, times, pitch, *, verifier=None):
    """Return supported candidate swaps and provenance, without creating/removing voicing.

    Original model arrays stay intact. Verifier frequencies only check candidates;
    they never become the output frequency. No expected score pitch is accepted.
    """
    wave, times = np.asarray(samples, np.float32), np.asarray(times, float)
    if wave.ndim != 1 or not len(wave) or not np.isfinite(wave).all():
        raise ValueError("Expected finite mono samples")
    if isinstance(sample_rate, bool) or not isinstance(sample_rate, (int, np.integer)) or sample_rate <= 0:
        raise ValueError("Invalid repair sample rate")
    raw = np.asarray(pitch["hz"], float)
    if len(times) != len(raw) or len(times) < 2 or not np.isfinite(times).all() or np.any(np.diff(times) <= 0):
        raise ValueError("Expected one pitch per increasing time")
    candidate, use_fcpe, pair, harmonic, _ = _candidates(pitch, verifier)
    indices = np.flatnonzero(valid_hz(candidate))
    evidence = {}
    if len(indices):
        target = SETTINGS["sample_rate"]
        divisor = math.gcd(int(sample_rate), target)
        audio = wave if sample_rate == target else resample_poly(wave, target//divisor, int(sample_rate)//divisor).astype(np.float32)
        for size in SETTINGS["windows_samples"]:
            before = periodicity_at(audio, target, times, raw, indices, size,search_cents=SETTINGS["original_pitch_search_cents"])
            after = periodicity_at(audio, target, times, candidate, indices, size)
            evidence[size] = (before, after)
            pair &= (after >= SETTINGS["minimum_periodicity"]) & (after-before >= SETTINGS["pair_minimum_periodicity_gain"])
            harmonic &= (after >= SETTINGS["minimum_periodicity"]) & (after-before >= SETTINGS["verifier_minimum_periodicity_gain"])
    accepted = pair | harmonic
    hz = raw.copy()
    hz[accepted] = candidate[accepted]
    chosen = np.asarray(pitch["use_fcpe"], bool).copy()
    chosen[accepted] = use_fcpe[accepted]
    changes = []
    for i in np.flatnonzero(accepted):
        row = {"frame_index": int(i), "time_s": float(times[i]), "original_hz": float(raw[i]),
            "corrected_hz": float(hz[i]), "candidate_source": "fcpe_ddsp" if chosen[i] else "swift",
            "reason": "waveform_verified_octave" if pair[i] else "harmof0_and_waveform_verified_candidate"}
        for size in SETTINGS["windows_samples"]:
            before, after = evidence[size]
            row["periodicity_"+str(size)] = float(after[i])
            row["periodicity_gain_"+str(size)] = float(after[i]-before[i])
        changes.append(row)
    assert np.array_equal(valid_hz(raw), valid_hz(hz))
    return {**pitch, "hz": hz, "use_fcpe": chosen}, changes


class HarmonicVerifier:
    """Pinned HarmoF0 network on CPU; explicit centered frames and batch context."""
    def __init__(self, model_dir=None):
        import torch
        from ._vendor.harmof0.network import HarmoF0
        folder = ASSETS if model_dir is None else Path(model_dir)
        manifest = json.loads((ASSETS/"models.json").read_text(encoding="utf-8"))["models"]["harmof0_verifier"]
        path = folder/manifest["filename"]
        if not path.is_file():
            raise FileNotFoundError("Missing HarmoF0 verifier; run python -m maestalk_audio.fetch_models")
        if digest(path) != manifest["sha256"]:
            raise ValueError("HarmoF0 verifier SHA256 mismatch")
        self.torch = torch
        self.net = HarmoF0().to("cpu").eval()
        self.net.load_state_dict(torch.load(path, map_location="cpu", weights_only=True))
        if not all(p.device.type == "cpu" for p in self.net.parameters()):
            raise RuntimeError("Verifier must remain on CPU")
        self.settings = {**manifest, "provider": "PyTorch CPU", "frame_samples": 1024,
            "sample_rate": 16000, "hop_samples": 160, "batch_frames": 512, "batch_context_frames": 16,
            "centering": "Explicit 512-sample padding; no fitted timestamp shift"}

    def predict(self, wave, sr, query):
        import librosa
        divisor = math.gcd(sr, 16000)
        audio = wave if sr == 16000 else resample_poly(wave, 16000//divisor, sr//divisor).astype(np.float32)
        framing = librosa.util.frame(np.pad(audio, (512, 512)), frame_length=1024, hop_length=160).T
        activations = []
        for start in range(0, len(framing), 512):
            end = min(len(framing), start+512)
            a, b = max(0, start-16), min(len(framing), end+16)
            tensor = self.torch.from_numpy(framing[a:b].copy())[None]
            with self.torch.inference_mode():
                output, _ = self.net(tensor)
            activations.append(output[0, start-a:end-a].cpu().numpy())
        values = np.concatenate(activations)
        hz = 27.5*2.**(values.argmax(axis=1)/48.)
        score = values.max(axis=1)
        native_times = np.arange(len(hz))*.01
        return {"hz": nearest(native_times, hz, query), "score": nearest(native_times, score, query)}


class PitchRepair:
    """Reusable verifier; skip its neural pass when no supported alternative exists."""
    def __init__(self, model_dir=None):
        self.model_dir = model_dir
        self.verifier = None

    def predict(self, wave, sr, times, pitch):
        started = perf_counter()
        suspicious = _candidates(pitch)[-1]
        verified = None
        if suspicious.any():
            if self.verifier is None:
                self.verifier = HarmonicVerifier(self.model_dir)
            verified = self.verifier.predict(wave, sr, times)
        result, changes = repair_pitch(wave, sr, times, pitch, verifier=verified)
        metadata = {"enabled": True, "settings": dict(SETTINGS), "uses_expected_score": False,
            "original_voicing_preserved": True, "verifier_used": verified is not None,
            "verifier": self.verifier.settings if verified is not None else None,
            "changed_frames": len(changes), "changes": changes, "processing_s": perf_counter()-started,
            "scope": "Conservative candidate swaps; unvoiced frames remain unvoiced; scores are not correctness probabilities"}
        return result, changes, metadata
