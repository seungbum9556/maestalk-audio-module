"""Musical changes may have soft attacks; pitch evidence must stay independent of a score."""
import copy
import csv
import json
from pathlib import Path
import tempfile
import unittest
import numpy as np
from maestalk_audio.analysis import AnalysisConfig
from maestalk_audio.boundaries import detect_pitch_boundaries, combine_onsets
from maestalk_audio.result import AnalysisResult


def observed(pitches):
    rows=[]
    for i,midi in enumerate(pitches):
        hz=440*2**((midi-69)/12) if midi is not None else None
        rows.append({"time_s":i*.016,"source_time_s":i*.016,"pitch_hz":hz,
            "swift_hz":hz,"fcpe_hz":hz,"swift_score":.9 if hz else None,
            "fcpe_score":.85 if hz else None,"rms":.1,"chroma":[0.]*12})
    return rows


class PitchBoundaryTests(unittest.TestCase):
    def test_two_models_find_a_soft_change_without_an_energy_attack(self):
        rows=observed([60]*12+[62]*12)
        before=copy.deepcopy(rows);events=detect_pitch_boundaries(rows)
        self.assertEqual(len(events),1)
        self.assertLess(abs(events[0]["time_s"]-.192),.032)
        self.assertFalse(events[0]["rearticulation_evidence"])
        self.assertEqual(before,rows)

    def test_silence_and_same_pitch_do_not_invent_reattacks(self):
        self.assertEqual(detect_pitch_boundaries(observed([None]*30)),[])
        self.assertEqual(detect_pitch_boundaries(observed([60]*30)),[])

    def test_vibrato_and_short_passing_pitch_are_not_new_notes(self):
        rows=observed([60]*36)
        for i,row in enumerate(rows):
            ratio=2**((25*np.sin(i*2*np.pi/12))/1200)
            for key in ("pitch_hz","swift_hz","fcpe_hz"):row[key]*=ratio
        self.assertEqual(detect_pitch_boundaries(rows),[])
        self.assertEqual(detect_pitch_boundaries(observed([60]*12+[64]*2+[60]*12)),[])

    def test_one_model_alone_cannot_supply_consensus(self):
        rows=observed([60]*12+[62]*12)
        for row in rows[12:]:row["fcpe_hz"]=440.
        self.assertEqual(detect_pitch_boundaries(rows),[])

    def test_gain_invariance_and_an_occasional_missing_score_are_finite(self):
        rows=observed([60]*12+[62]*12)
        rows[12]["swift_score"]=None
        first=detect_pitch_boundaries(rows)
        for row in rows:row["rms"]*=.001
        second=detect_pitch_boundaries(rows)
        self.assertEqual(first,second)
        self.assertEqual(len(first),1)
        json.dumps(first,allow_nan=False)

    def test_combination_preserves_original_events_and_export_handles_both_schemas(self):
        original=[{"time_s":.1,"spectral_novelty":2.,"status":"acoustic_candidate"}]
        extra=detect_pitch_boundaries(observed([60]*12+[62]*12))
        combined=combine_onsets(original,extra)
        self.assertIn(original[0],combined)
        self.assertEqual(len(combined),2)
        result=AnalysisResult(observed([60]*12+[62]*12),{"audio_duration_s":.384},
            onsets=combined,acoustic_onsets=original,pitch_boundaries=extra)
        with tempfile.TemporaryDirectory() as directory:
            path=result.save(Path(directory)/"analysis")
            with (path/"onsets.csv").open(encoding="utf-8-sig",newline="") as stream:
                self.assertEqual(len(list(csv.DictReader(stream))),2)
            self.assertTrue((path/"acoustic_onsets.csv").exists())
            self.assertTrue((path/"pitch_boundaries.csv").exists())

    def test_duplicate_event_and_invalid_configuration(self):
        old=[{"time_s":.2}]
        self.assertEqual(combine_onsets(old,[{"time_s":.21}]),old)
        with self.assertRaises(ValueError):AnalysisConfig(expanded_onsets=True,compute_onsets=False)
        with self.assertRaises(ValueError):AnalysisConfig(expanded_onsets="yes")


if __name__=="__main__":unittest.main()
