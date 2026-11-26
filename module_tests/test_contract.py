"""Public contract and input safeguards; no ground-truth-informed inference."""
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import json
import unittest
import numpy as np
import soundfile as sf
from maestalk_audio import AudioAnalyzer, AnalysisConfig
from maestalk_audio.analysis import centered_rms, volume_reference
from maestalk_audio.pitch import nearest, select_pair


class SilentEngine:
    def __init__(self, config, model_dir=None):
        self.settings = {"test_double": True}

    def predict(self, audio, sr, query):
        blank = np.full(len(query), np.nan)
        return {"hz": blank, "use_fcpe": np.zeros(len(query), bool), "swift_hz": blank,
                "swift_score": blank, "fcpe_hz": blank, "fcpe_score": blank}


class ContractTests(unittest.TestCase):
    def test_invalid_audio_rejected_before_loading_models(self):
        analyzer = AudioAnalyzer()
        bad = [([], 16000), (np.zeros((16000, 2)), 16000), ([np.nan]*16000, 16000),
               ([np.inf]*16000, 16000), (np.zeros(10), 16000), (np.ones(16000)*3, 16000),
               (np.zeros(16000), 0), (np.zeros(16000), 16000.5), (np.zeros(16000), True)]
        for wave, sr in bad:
            with self.subTest(sr=sr), self.assertRaises(ValueError):
                analyzer.analyze_samples(wave, sr)
        self.assertIsNone(analyzer._pitch)

    def test_invalid_config_rejected(self):
        for values in ({"fcpe_min": 2}, {"swift_keep": float("nan")}, {"hop_s": 0},
                       {"rms_window_s": -1}, {"swift_threads": True}, {"torch_threads": 0}):
            with self.subTest(values=values), self.assertRaises(ValueError):
                AnalysisConfig(**values)

    def test_stereo_and_invalid_interval_rejected(self):
        with TemporaryDirectory() as temp:
            path = Path(temp)/"stereo.wav"
            sf.write(path, np.zeros((16000, 2)), 16000)
            with self.assertRaises(ValueError):
                AudioAnalyzer().analyze_file(path)
            mono = Path(temp)/"mono.wav"
            sf.write(mono, np.zeros(16000), 16000)
            for values in ({"start_s": 2}, {"start_s": -.1}, {"duration_s": 0}, {"duration_s": float("inf")}):
                with self.subTest(values=values), self.assertRaises(ValueError):
                    AudioAnalyzer().analyze_file(mono, **values)

    def test_relative_volume_is_invariant_to_input_gain(self):
        sr=16000; t=np.arange(sr)/sr
        wave=.1*np.sin(2*np.pi*250*t); wave[:4000]=0
        a,_=volume_reference(wave,sr); b,_=volume_reference(wave*.25,sr)
        self.assertAlmostEqual(b/a,.25)
        np.testing.assert_allclose(20*np.log10(centered_rms(wave,sr,[.4,.7])/a),
            20*np.log10(centered_rms(wave*.25,sr,[.4,.7])/b),atol=1e-10)

    def test_doubled_amplitude_is_six_db(self):
        sr=16000; t=np.arange(sr)/sr
        wave=np.sin(2*np.pi*250*t)*np.where(t<.5,.1,.2)
        a,b=centered_rms(wave,sr,[.25,.75])
        self.assertAlmostEqual(20*np.log10(b/a),6.020599913,places=7)

    def test_threshold_selection_retains_confident_swift(self):
        hz,chosen=select_pair(np.array([220.,220.,np.nan]),np.array([.95,.6,.1]),
            np.array([440.,440.,130.]),np.array([.99,.9,.85]))
        np.testing.assert_array_equal(hz,[220.,440.,130.])
        np.testing.assert_array_equal(chosen,[False,True,True])

    def test_native_frame_mapping_does_not_fill_unvoiced_gaps(self):
        result=nearest([0.,.01,.02],[220.,np.nan,440.],[.005,.01,.015,.05])
        self.assertEqual(result[0],220.)
        self.assertTrue(np.isnan(result[1]))
        self.assertTrue(np.isnan(result[-1]))

    @patch("maestalk_audio.analysis.PitchPair",SilentEngine)
    def test_strict_json_preserves_unavailable_and_unimplemented_states(self):
        analyzer=AudioAnalyzer()
        result=analyzer.analyze_samples(np.zeros(16000),16000)
        data=json.loads(result.to_json(),parse_constant=lambda value: self.fail(value))
        self.assertEqual(data["schema_version"],"1.3")
        self.assertEqual(data["onsets"],[])
        self.assertEqual(data["summary"]["capabilities"]["onsets"],"implemented_candidates")
        for frame in data["frames"]:
            self.assertIsNone(frame["pitch_hz"])
            self.assertIsNone(frame["source_score"])
            self.assertIsNone(frame["relative_to_performance_db"])
            self.assertEqual(len(frame["chroma"]),12)

    @patch("maestalk_audio.analysis.PitchPair",SilentEngine)
    def test_segment_timestamps_and_export_preserve_existing_output(self):
        with TemporaryDirectory() as temp:
            path=Path(temp)/"mono.wav"
            sf.write(path,np.zeros(16000),16000)
            result=AudioAnalyzer().analyze_file(path,start_s=.25,duration_s=.5,part_id="cello1",instrument="cello")
            self.assertEqual(result.frames[0]["time_s"],0.)
            self.assertEqual(result.frames[0]["source_time_s"],.25)
            self.assertEqual(result.summary["source"]["end_s"],.75)
            folder=result.save(Path(temp)/"out")
            for name in ("analysis.json","frames.csv","chroma.csv","summary.json"):
                self.assertTrue((folder/name).is_file())
            old=(folder/"analysis.json").read_bytes()
            with self.assertRaises(FileExistsError):
                result.save(folder)
            self.assertEqual((folder/"analysis.json").read_bytes(),old)


if __name__=="__main__":
    unittest.main()
