"""Observed pitch changes supplement soft acoustic attacks; score notes are never inputs."""
import numpy as np
from .pitch import valid_hz

SETTINGS = {"minimum_stable_s": .048, "minimum_pitch_change_cents": 75.,
    "maximum_gap_s": .128, "two_model_agreement_cents": 50.,
    "minimum_swift_score": .5, "minimum_fcpe_score": .4,
    "minimum_consensus_frames": 2, "new_to_previous_rms_min": .25,
    "duplicate_radius_s": .064}


def detect_pitch_boundaries(frames):
    """Estimate stable pitch transitions, not proof of a new bow/pluck attack."""
    if len(frames) < 3:
        return []
    times = np.array([r["time_s"] for r in frames], float)
    if not np.isfinite(times).all() or np.any(np.diff(times) <= 0):
        raise ValueError("Boundary frames must have increasing finite times")
    hop = float(np.median(np.diff(times)))
    def values(key):
        return np.array([r.get(key) if r.get(key) is not None else np.nan for r in frames], float)
    raw, swift, fcpe = [values(k) for k in ("pitch_hz", "swift_hz", "fcpe_hz")]
    ss, fs = [np.nan_to_num(values(key), nan=0.) for key in ("swift_score", "fcpe_score")]
    mid = np.full(len(raw), np.nan)
    valid = valid_hz(raw)
    mid[valid] = 69 + 12 * np.log2(raw[valid] / 440)
    labels = np.full(len(raw), -1)
    labels[valid] = np.rint(mid[valid]).astype(int)
    agree = valid_hz(swift) & valid_hz(fcpe)
    cents = np.full(len(raw), np.inf)
    cents[agree] = abs(1200 * np.log2(swift[agree] / fcpe[agree]))
    consensus = (cents <= SETTINGS["two_model_agreement_cents"]) & (ss >= SETTINGS["minimum_swift_score"]) & (fs >= SETTINGS["minimum_fcpe_score"])
    bounds = np.r_[0, np.flatnonzero(np.diff(labels) != 0) + 1, len(raw)]
    runs = []
    for a, b in zip(bounds[:-1], bounds[1:]):
        if labels[a] >= 0 and (b - a) * hop >= SETTINGS["minimum_stable_s"] - 1e-8:
            runs.append((a, b, float(np.median(mid[a:b]))))
    result = []
    for previous, current in zip(runs[:-1], runs[1:]):
        a, b, old = previous
        c, end, new = current
        if abs(new - old) < SETTINGS["minimum_pitch_change_cents"] / 100 or times[c] - (times[b - 1] + hop) > SETTINGS["maximum_gap_s"]:
            continue
        if consensus[max(a, b - 3):b].sum() < SETTINGS["minimum_consensus_frames"] or consensus[c:min(end, c + 3)].sum() < SETTINGS["minimum_consensus_frames"]:
            continue
        old_rms = np.median([r["rms"] for r in frames[max(a, b - 3):b]])
        new_rms = np.median([r["rms"] for r in frames[c:min(end, c + 3)]])
        if not np.isfinite([old_rms, new_rms]).all() or new_rms < old_rms * SETTINGS["new_to_previous_rms_min"]:
            continue
        midpoint = (old + new) / 2
        sign = 1 if new > old else -1
        crossings = []
        for i in range(max(a, b - 4), min(end, c + 4) - 1):
            if not np.isfinite(mid[i:i + 2]).all():
                continue
            left, right = sign * (mid[i:i + 2] - midpoint)
            if left <= 0 < right:
                crossings.append(float(times[i] - left / (right - left) * (times[i + 1] - times[i])))
        if not crossings:
            continue
        approximate = (times[b - 1] + hop + times[c]) / 2
        onset = min(crossings, key=lambda t: abs(t - approximate))
        result.append({"time_s": onset, "peak_time_s": onset,
            "strength": float(min(np.median(ss[c:min(end, c + 3)]), np.median(fs[c:min(end, c + 3)]))),
            "sources": "stable_pitch_transition_two_models", "time_uncertainty_s": .032,
            "status": "pitch_boundary_candidate", "previous_midi_median": old,
            "next_midi_median": new, "rearticulation_evidence": False})
    return result


def combine_onsets(acoustic, pitch_boundaries):
    """Keep every original event; add candidates beyond the duplicate radius."""
    merged = list(acoustic)
    for event in pitch_boundaries:
        if not merged or min(abs(event["time_s"] - r["time_s"]) for r in merged) > SETTINGS["duplicate_radius_s"]:
            merged.append(event)
    return sorted(merged, key=lambda r: r["time_s"])
