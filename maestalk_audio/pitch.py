"""Selected SwiftF0 + FCPE pair. Reference annotations never enter this module."""
from pathlib import Path
import hashlib
import json
import math
from threading import Lock
import numpy as np
from scipy.signal import resample_poly

ASSETS = Path(__file__).resolve().parent / "assets"
FMIN, FMAX = 50.0, 2000.0


def digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def valid_hz(hz):
    hz = np.asarray(hz)
    return np.isfinite(hz) & (hz >= FMIN) & (hz <= FMAX)


def nearest(times, values, query):
    """Nearest native frame, at most half a hop away; never bridge unvoiced gaps."""
    times, values, query = [np.asarray(v) for v in (times, values, query)]
    if not len(times) or len(times) != len(values) or np.any(np.diff(times) <= 0):
        raise ValueError("Expected estimates with strictly increasing timestamps")
    right = np.clip(np.searchsorted(times, query), 0, len(times) - 1)
    left = np.maximum(0, right - 1)
    index = np.where(abs(query - times[left]) <= abs(query - times[right]), left, right)
    result = values[index].astype(float)
    tolerance = np.median(np.diff(times)) / 2 + 1e-7 if len(times) > 1 else 1e-7
    result[abs(query - times[index]) > tolerance] = np.nan
    return result


def select_pair(swift, swift_score, fcpe, fcpe_score, minimum=.8, keep=.9):
    selected = np.asarray(swift).copy()
    use_fcpe = valid_hz(fcpe) & (fcpe_score >= minimum) & (~valid_hz(swift) | (swift_score < keep))
    selected[use_fcpe] = fcpe[use_fcpe]
    return selected, use_fcpe


def check_models(model_dir=None, *, include_verifier=False):
    """Check bundled model identity without importing PyTorch or using the network."""
    folder = Path(model_dir) if model_dir is not None else ASSETS
    manifest = json.loads((ASSETS / "models.json").read_text(encoding="utf-8"))
    manifest = {**manifest,"models":{name:item for name,item in manifest["models"].items()
        if include_verifier or item.get("role")!="verification_only"}}
    for name, item in manifest["models"].items():
        path = folder / item["filename"]
        if not path.is_file():
            raise FileNotFoundError(f"Missing {name} weights: {path}. See MODULE_README.md / fetch_models.")
        if digest(path) != item["sha256"]:
            raise ValueError(f"{name} model SHA256 mismatch: {path}")
    return manifest


class PitchPair:
    """CPU inference; one object can be reused for sequential recordings."""
    def __init__(self, config, model_dir=None):
        import torch
        from ._vendor.swift_f0.core import SwiftF0
        from ._vendor.fcpe.models_infer import InferCFNaiveMelPE
        from ._vendor.fcpe.tools import DotDict

        folder = Path(model_dir) if model_dir is not None else ASSETS
        manifest = check_models(folder)
        if config.torch_threads is not None:
            torch.set_num_threads(config.torch_threads)
        self.torch, self.config, self.lock = torch, config, Lock()
        self.swift = SwiftF0(threads=config.swift_threads, spin=False,
                             model_path=str(folder / manifest["models"]["swift"]["filename"]))
        if self.swift.session.get_providers() != ["CPUExecutionProvider"]:
            raise RuntimeError("SwiftF0 must use CPUExecutionProvider")
        checkpoint = torch.load(folder / manifest["models"]["fcpe_ddsp"]["filename"],
                                map_location="cpu", weights_only=True)
        self.fcpe = InferCFNaiveMelPE(DotDict(checkpoint["config_dict"]), checkpoint["model"]).to("cpu")
        self.fcpe.eval()
        if not all(p.device.type == "cpu" for p in self.fcpe.parameters()):
            raise RuntimeError("FCPE parameters must remain on CPU")
        self.settings = {
            "models": manifest["models"], "frequency_range_hz": [FMIN, FMAX],
            "swift": {"version": "0.3.0", "provider": "CPUExecutionProvider",
                "threads": config.swift_threads, "voiced_threshold": .5, "sample_rate": 16000,
                "hop_samples": 256, "keep_threshold": config.swift_keep},
            "fcpe": {"provider": "PyTorch CPU", "torch_version": torch.__version__,
                "threads": torch.get_num_threads(), "threshold": .006,
                "selection_threshold": config.fcpe_min, "tta": False, "interpolate_unvoiced": False,
                "sample_rate": self.fcpe.get_model_sr(), "hop_samples": self.fcpe.get_hop_size(),
                "first_frame_center_s": .5*self.fcpe.get_hop_size()/self.fcpe.get_model_sr(),
                "architecture": self.fcpe.args_dict["model"], "mel": self.fcpe.args_dict["mel"]},
            "alignment": "Nearest native frame within half a hop, no unvoiced interpolation",
        }

    def predict(self, audio, sr, query):
        # Capturing FCPE raw activations temporarily replaces its forward callback.
        # Serialize access to this model instance and always restore the callback.
        with self.lock:
            return self._predict(audio, sr, query)

    def _predict(self, audio, sr, query):
        torch = self.torch
        a = self.swift.detect(audio, sr, fmin=FMIN, fmax=FMAX)
        swift_hz = np.where(a.confidence >= .5, a.pitch_hz, np.nan)
        swift_hz = np.where(valid_hz(swift_hz), swift_hz, np.nan)
        target = self.fcpe.get_model_sr()
        divisor = math.gcd(sr, target)
        audio16 = audio if sr == target else resample_poly(audio, target//divisor, sr//divisor).astype(np.float32)
        wave = torch.from_numpy(np.ascontiguousarray(audio16))[None, :, None]
        activation = []
        original = self.fcpe.model.forward

        def forward(*args, **kwargs):
            output = original(*args, **kwargs)
            activation.append(output.detach().cpu().numpy())
            return output

        self.fcpe.model.forward = forward
        try:
            with torch.inference_mode():
                output = self.fcpe.infer(wave, target, threshold=.006, f0_min=FMIN,
                    f0_max=None, interp_uv=False, test_time_augmentation=False)
        finally:
            self.fcpe.model.forward = original
        raw = output.detach().cpu().numpy().reshape(-1)
        score = np.asarray(activation[0][0]).max(axis=-1)
        fcpe_hz = np.where(valid_hz(raw), raw, np.nan)
        fcpe_times = (np.arange(len(raw))+.5)*self.fcpe.get_hop_size()/target
        inside = fcpe_times < len(audio)/sr
        sh = nearest(a.timestamps, swift_hz, query)
        ss = nearest(a.timestamps, a.confidence, query)
        fh = nearest(fcpe_times[inside], fcpe_hz[inside], query)
        fs = nearest(fcpe_times[inside], score[inside], query)
        hz, chosen = select_pair(sh, ss, fh, fs, self.config.fcpe_min, self.config.swift_keep)
        return {"hz": hz, "use_fcpe": chosen, "swift_hz": sh, "swift_score": ss,
                "fcpe_hz": fh, "fcpe_score": fs}
