"""Score context must preserve actual mistakes, uncertainty and raw estimates."""
from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory
import copy
import json
import unittest
import numpy as np
from maestalk_audio.result import AnalysisResult
from maestalk_audio.score import ScoreNote, ScoreReference, compare_with_score


def reference(pitches):
    return ScoreReference(tuple(ScoreNote(p,i,1.,f"n{i}") for i,p in enumerate(pitches)))


def performance(pitches, lengths=None):
    lengths=lengths or [12]*len(pitches)
    rows=[]
    for midi,length in zip(pitches,lengths):
        for _ in range(length):
            rows.append({"time_s":len(rows)*.016,"pitch_hz":440*2**((midi-69)/12) if midi is not None else None,
                         "relative_to_performance_db":-3.})
    return AnalysisResult(rows,{"audio_duration_s":len(rows)*.016,"config":{"hop_s":.016}})


class ScoreContextTests(unittest.TestCase):
    def test_correct_sequence_with_different_tempo_and_initial_silence(self):
        audio=performance([None,60,62,64,65,67],[25,10,30,8,17,20])
        checked=compare_with_score(audio,reference([60,62,64,65,67]))
        self.assertTrue(all(n["status"]=="consistent_with_score" for n in checked.notes))
        self.assertAlmostEqual(checked.notes[0]["observed_start_s"],.4)
        self.assertFalse(checked.summary["alignment_uses_midi_seconds"])
        self.assertFalse(checked.summary["rhythm_deviation_evaluated"])

    def test_wrong_note_is_reported_and_never_corrected_to_score(self):
        audio=performance([60,62,66,65,67]);before=copy.deepcopy(audio.to_dict())
        checked=compare_with_score(audio,reference([60,62,64,65,67]))
        self.assertEqual(checked.notes[2]["status"],"pitch_mismatch_review")
        self.assertEqual(checked.notes[2]["expected_midi"],64)
        self.assertEqual(checked.notes[2]["observed_midi"],66)
        self.assertEqual(audio.to_dict(),before)
        self.assertFalse(checked.summary["pitch_replacement_performed"])

    def test_missing_note_remains_unobserved_instead_of_synthesized(self):
        checked=compare_with_score(performance([60,62,65,67]),reference([60,62,64,65,67]))
        self.assertEqual(checked.notes[2]["status"],"not_observed_review")
        self.assertIsNone(checked.notes[2]["observed_midi"])

    def test_extra_note_is_retained_separately(self):
        checked=compare_with_score(performance([60,62,69,64,65,67]),reference([60,62,64,65,67]))
        self.assertEqual(len(checked.extra_runs),1)
        self.assertEqual(checked.extra_runs[0]["midi"],69)

    def test_repeated_same_pitch_is_not_claimed_as_detected_reattack(self):
        checked=compare_with_score(performance([60,62],[30,12]),reference([60,60,62]))
        self.assertTrue(all(n["status"]=="repeat_boundary_unresolved" for n in checked.notes[:2]))
        self.assertFalse(checked.summary["audio_onset_detection_performed"])

    def test_partial_recording_does_not_mark_unplayed_remainder_missing(self):
        checked=compare_with_score(performance([64,65,67]),reference([60,62,64,65,67,69]),partial_score=True)
        self.assertEqual(checked.notes[0]["status"],"outside_analyzed_score_span")
        self.assertEqual(checked.notes[-1]["status"],"outside_analyzed_score_span")
        self.assertTrue(all(n["status"]=="consistent_with_score" for n in checked.notes[2:5]))

    def test_identical_score_phrases_are_ambiguous(self):
        checked=compare_with_score(performance([60,62,64]),reference([60,62,64,60,62,64]),partial_score=True)
        mapped=[n for n in checked.notes if n["run_index"] is not None]
        self.assertTrue(mapped)
        self.assertTrue(all(n["status"]=="alignment_ambiguous" for n in mapped))

    def test_wrong_piece_does_not_create_confident_performance_accusations(self):
        checked=compare_with_score(performance([72,74,77]),reference([60,62,64]))
        self.assertEqual(checked.summary["alignment_status"],"uncertain")
        self.assertTrue(all(n["status"]=="alignment_uncertain" for n in checked.notes))

    def test_silence_stays_unobserved_even_in_partial_mode(self):
        checked=compare_with_score(performance([None]),reference([60,62,64]),partial_score=True)
        self.assertEqual(checked.summary["alignment_status"],"insufficient_audio")
        self.assertTrue(all(n["status"]=="not_observed_review" for n in checked.notes))

    def test_short_candidates_are_kept_as_uncertain_evidence(self):
        checked=compare_with_score(performance([60,66,62],[12,1,12]),reference([60,62]))
        self.assertEqual(checked.short_unstable_runs[0]["midi"],66)
        self.assertEqual(checked.short_unstable_runs[0]["reason"],"short_unstable_pitch_run")

    def test_json_has_no_nonstandard_numbers(self):
        checked=compare_with_score(performance([None]),reference([60]))
        text=json.dumps(checked.to_dict(),allow_nan=False)
        self.assertIsNone(json.loads(text)["notes"][0]["observed_pitch_hz_median"])

    def test_chord_score_rejected(self):
        with self.assertRaises(ValueError):
            ScoreReference((ScoreNote(60,0.,1.),ScoreNote(64,0.,1.)))

    def test_midi_tempo_changes_do_not_become_performance_clock(self):
        import mido
        with TemporaryDirectory() as temp:
            parsed=[]
            for tempo in (250000,1500000):
                midi=mido.MidiFile();track=mido.MidiTrack();midi.tracks.append(track)
                track.append(mido.MetaMessage("set_tempo",tempo=tempo))
                for pitch in (60,62,64):
                    track.append(mido.Message("note_on",note=pitch,velocity=80,time=0))
                    track.append(mido.Message("note_off",note=pitch,time=480))
                path=Path(temp)/f"tempo{tempo}.mid";midi.save(path)
                parsed.append(ScoreReference.from_midi(path))
            self.assertEqual([asdict(n) for n in parsed[0].notes],[asdict(n) for n in parsed[1].notes])

    def test_multitrack_score_requires_explicit_part(self):
        import mido
        with TemporaryDirectory() as temp:
            midi=mido.MidiFile(type=1)
            for pitch in (60,48):
                track=mido.MidiTrack();midi.tracks.append(track)
                track.append(mido.Message("note_on",note=pitch,velocity=80))
                track.append(mido.Message("note_off",note=pitch,time=480))
            path=Path(temp)/"parts.mid";midi.save(path)
            with self.assertRaises(ValueError):
                ScoreReference.from_midi(path)
            self.assertEqual(ScoreReference.from_midi(path,track_index=1).notes[0].midi,48)

    def test_midi_beats_remain_quarters_in_six_eight(self):
        import mido
        with TemporaryDirectory() as temp:
            midi=mido.MidiFile();track=mido.MidiTrack();midi.tracks.append(track)
            track.append(mido.MetaMessage("time_signature",numerator=6,denominator=8))
            track.append(mido.Message("note_on",note=48,velocity=80,time=480))
            track.append(mido.Message("note_off",note=48,time=480))
            path=Path(temp)/"six_eight.mid";midi.save(path)
            score=ScoreReference.from_midi(path)
            self.assertEqual(score.notes[0].start_beat,1.)
            self.assertEqual(score.source["beat_unit"],"quarter_note")
            self.assertEqual(score.source["time_signatures"][0]["denominator"],8)


if __name__=="__main__":unittest.main()
