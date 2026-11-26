"""Example integration; no UI, server, score matching or LLM dependency."""
from pathlib import Path
from maestalk_audio import AudioAnalyzer


def main():
    analyzer = AudioAnalyzer()  # Reuse this object for subsequent recordings.
    sample = Path(__file__).resolve().parent/"test_scale.wav"
    result = analyzer.analyze_file(sample, instrument="synthetic", part_id="part1")
    # The next module can read the plain Python dictionary directly.
    payload = result.to_dict()
    first_note = next(frame for frame in payload["frames"] if frame["note"] is not None)
    print("First detected note:", first_note["note"], first_note["pitch_hz"], "Hz")
    print("Relative level:", first_note["relative_to_performance_db"], "dB")
    print("Onset support:", payload["summary"]["capabilities"]["onsets"])
    # No file output is required to use the analyzer as a module.
    print("Frames:", len(payload["frames"]))


if __name__ == "__main__":
    main()
