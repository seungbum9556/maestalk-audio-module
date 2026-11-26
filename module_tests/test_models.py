"""Actual CPU model smoke tests shipped with the handoff source."""
from pathlib import Path
import unittest
import numpy as np
from maestalk_audio import AudioAnalyzer
from maestalk_audio.pitch import check_models

SAMPLE=Path(__file__).resolve().parents[1]/"examples/test_scale.wav"


class SelectedModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.analyzer=AudioAnalyzer()
        cls.result=cls.analyzer.analyze_file(SAMPLE,instrument="synthetic")

    def test_bundled_model_hashes(self):
        self.assertEqual(set(check_models()["models"]),{"swift","fcpe_ddsp"})

    def test_known_scale_core_notes(self):
        for start,midi in enumerate((60,62,64,65,67),1):
            rows=[r for r in self.result.frames if start+.1<=r["time_s"]<=start+.6]
            self.assertTrue(rows)
            self.assertTrue(all(r["midi"]==midi for r in rows),(start,rows))

    def test_models_are_cpu_and_scores_are_not_presented_as_accuracy(self):
        models=self.result.summary["models"]
        self.assertEqual(models["swift"]["provider"],"CPUExecutionProvider")
        self.assertEqual(models["fcpe"]["provider"],"PyTorch CPU")
        self.assertFalse(self.result.summary["gpu_used"])
        self.assertTrue(any("not calibrated correctness" in value for value in self.result.summary["limitations"]))

    def test_real_silence_serializes_without_inventing_pitch(self):
        result=self.analyzer.analyze_samples(np.zeros(16000),16000)
        self.assertTrue(result.summary["input_status"]["digital_silence"])
        self.assertTrue(all(r["pitch_hz"] is None for r in result.frames))
        self.assertTrue(all(r["relative_to_performance_db"] is None for r in result.frames))
        result.to_json()

    def test_instrument_name_does_not_change_pitch_selection(self):
        other=self.analyzer.analyze_file(SAMPLE,instrument="cello",part_id="other")
        self.assertEqual([r["pitch_hz"] for r in other.frames],[r["pitch_hz"] for r in self.result.frames])
        self.assertEqual(other.frames[0]["instrument"],"cello")

    def test_score_context_keeps_an_actual_synthesized_wrong_note(self):
        from maestalk_audio.score import ScoreReference, compare_with_score
        sample=SAMPLE.with_name("test_wrong_note.wav")
        raw=self.analyzer.analyze_file(sample,instrument="synthetic")
        before=raw.to_json()
        checked=compare_with_score(raw,ScoreReference.from_json(SAMPLE.with_name("test_scale_score.json")))
        self.assertEqual(checked.notes[2]["expected_midi"],64)
        self.assertEqual(checked.notes[2]["observed_midi"],66)
        self.assertEqual(checked.notes[2]["status"],"pitch_mismatch_review")
        self.assertTrue(any(r["note"]=="F#4" for r in raw.frames))
        self.assertEqual(raw.to_json(),before)

    def test_actual_repeated_note_fixture_uses_acoustic_reattacks(self):
        from maestalk_audio.score import ScoreReference,compare_with_score
        raw=self.analyzer.analyze_file(SAMPLE.with_name("test_repeat.wav"))
        checked=compare_with_score(raw,ScoreReference.from_midi(SAMPLE.with_name("test_repeat.mid")))
        self.assertEqual([n["observed_midi"] for n in checked.notes],[60,60,60,62])
        self.assertFalse(any(n["status"]=="repeat_boundary_unresolved" for n in checked.notes))


if __name__=="__main__":
    unittest.main()
