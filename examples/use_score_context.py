"""Offline MIDI-guided review; preserve raw audio estimates and return proposals separately."""
from pathlib import Path
from maestalk_audio import AudioAnalyzer, AnalysisConfig
from maestalk_audio.score import ScoreReference, compare_with_score
from maestalk_audio.recheck import candidate_review_windows, recheck_file


def main():
    examples = Path(__file__).resolve().parent
    audio = examples / "test_repeat.wav"
    # Optional expanded starts trade higher recall for some extra detections.
    analyzer = AudioAnalyzer(AnalysisConfig(expanded_onsets=True))
    result = analyzer.analyze_file(audio, instrument="synthetic", part_id="part1")
    score = ScoreReference.from_midi(examples / "test_repeat.mid")
    checked = compare_with_score(result, score)
    windows = candidate_review_windows(result, checked)
    rechecked = recheck_file(audio, result, windows)

    # A caller can consume these three independent dictionaries without files.
    payload = {
        "audio": result.to_dict(),
        "score_context": checked.to_dict(),
        "pitch_recheck": rechecked.to_dict(),
    }
    for note in payload["score_context"]["notes"]:
        print(note["expected_note"], note["observed_midi"], note["status"],
              "measured onset:", note["observed_onset_s"])
    print("Pitch proposal frames:", len(payload["pitch_recheck"]["proposals"]))
    print("Original F0 unchanged:", rechecked.summary["audio_estimates_unchanged"])
    # Optional: result.save(...), checked.save(...), rechecked.save(...).


if __name__ == "__main__":
    main()
