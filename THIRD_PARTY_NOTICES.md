# Maestalk audio module: third-party notices

This handoff includes the selected model weights and a subset of their publicly
released inference code. It does not relicense third-party material.

## SwiftF0 0.3.0

- Copyright (c) 2025–2026 Lars Nieradzik; upstream project is
  [lars76/swift-f0](https://github.com/lars76/swift-f0).
- Source: `swift-f0` 0.3.0 release, `swift_f0/core.py` and `model.onnx`.
- License: MIT. The original notice is retained in
  `maestalk_audio/_vendor/swift_f0/LICENSE`.
- Change: an optional explicit `model_path` constructor argument was added so the
  model can be loaded from package assets. The numerical inference code is kept.
- Weight file: `maestalk_audio/assets/swift_f0.onnx`. Its SHA256 is recorded in
  `assets/models.json`.

## FCPE inference code

- Copyright (c) 2023 CN_ChiTu.
- Source: [CNChTu/FCPE](https://github.com/CNChTu/FCPE), commit
  `6a149c1afb1c7e7821b71869dfb31ad50c95b516`.
- License: MIT, retained in `maestalk_audio/_vendor/fcpe/LICENSE`.
- Changes: only the F0 inference subset is bundled. The unused eager MIDI-export
  import is replaced with a function that raises `NotImplementedError`; package
  `__init__` only documents the vendor. No MIDI, training or bundled old FCPE
  weights are included. F0 inference logic is preserved.
- Original source hashes and the applied changes are listed in `assets/models.json`.

## FCPE DDSP-200K weights

- Attribution: ChiTu / CN_ChiTu, FCPE, `DDSP_200k.pt`.
- Source: [ChiTu/FCPE](https://huggingface.co/ChiTu/FCPE), revision
  `aeec888cd3eecd9a350945205a86340ef9293548`.
- License as declared by the model repository: **CC BY-NC-SA 4.0**,
  <https://creativecommons.org/licenses/by-nc-sa/4.0/>.
- File is copied byte-for-byte as `maestalk_audio/assets/fcpe_ddsp.pt`;
  the weights have not been modified. The original filename, source, license and
  SHA256 remain in this notice and `assets/models.json`.
- Sharing this bundle must retain attribution and these license terms. The
  code's MIT license does not replace the weight license's noncommercial terms.

Runtime dependencies (PyTorch, torchaudio, ONNX Runtime, NumPy, SciPy, librosa,
SoundFile, soxr, einops, local-attention and rotary-embedding-torch; optional
matplotlib) are installed separately and retain their own licenses. Environment
and package binaries are not redistributed in this source bundle.

## HarmoF0 verification network

- Copyright (c) 2022 Weiweixing; [WX-Wei/HarmoF0](https://github.com/WX-Wei/HarmoF0),
  commit `3b2223649953f7786b602c8b7d608bce1562da38`.
- The repository declares MIT; its full notice is retained in
  `maestalk_audio/_vendor/harmof0/LICENSE`.
- Included source: `network.py` and `layers.py`. The deprecated `np.int` alias
  is replaced with `int`; the network and weights remain numerically unchanged.
- The provided `mdb-stem-synth.pth` checkpoint is copied byte-for-byte as
  `maestalk_audio/assets/harmof0_mdb.pt`. Its SHA256 and pinned source URL are in
  `assets/models.json`. No local training was performed.
- Our loader uses CPU explicitly, `torch.load(weights_only=True)`, centered
  1024-sample frames and 16-frame batch overlap. The upstream CLI and automatic
  CUDA device selection wrapper are not included.
- This network verifies existing Swift/FCPE candidates; its quantized frequency
  does not replace the final frequency. Model activations are not calibrated
  correctness probabilities.
