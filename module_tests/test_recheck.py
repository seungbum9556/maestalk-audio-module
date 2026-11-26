"""The verifier must follow audio evidence, never replace a real wrong note with score."""
import copy
import unittest
import numpy as np
from maestalk_audio.result import AnalysisResult
from maestalk_audio.recheck import recheck_samples,candidate_review_windows


def example(raw=220.,alternative=440.,score=.92):
    sr=16000;t=np.arange(sr)/sr;wave=(.1*np.sin(2*np.pi*440*t)).astype(np.float32)
    rows=[{"time_s":float(x),"pitch_hz":raw,"pitch_source":"swift","source_score":score,
           "swift_hz":raw,"swift_score":score,"fcpe_hz":alternative,"fcpe_score":.9} for x in np.arange(0,1.,.016)]
    return wave,sr,AnalysisResult(rows,{"audio_duration_s":1.,"sample_rate":sr})


class PitchRecheckTests(unittest.TestCase):
    def test_uncertain_note_edge_is_reviewed_even_when_note_median_matches(self):
        wave,sr,audio=example(raw=None)
        for row in audio.frames:
            row["pitch_state"]="unvoiced";row["swift_hz"]=None
        windows=candidate_review_windows(audio)
        self.assertTrue(windows)
        self.assertEqual(windows[0]["reason"],"audio_candidate_uncertainty")
        self.assertTrue(all("expected_midi" not in w for w in windows))

    def test_audio_supported_candidate_is_proposed_without_mutating_original(self):
        wave,sr,audio=example();before=copy.deepcopy(audio.to_dict())
        checked=recheck_samples(wave,sr,audio,[{"start_s":.2,"end_s":.6}])
        self.assertTrue(checked.proposals)
        self.assertTrue(all(abs(p["proposed_hz"]-440)<1e-8 for p in checked.proposals))
        self.assertTrue(all(.2<=p["time_s"]<.6 for p in checked.proposals))
        self.assertEqual(audio.to_dict(),before)
        self.assertFalse(checked.summary["expected_pitch_used"])

    def test_real_wrong_note_is_preserved_when_audio_supports_it(self):
        wave,sr,audio=example(raw=440.,alternative=220.)
        checked=recheck_samples(wave,sr,audio,[{"start_s":.2,"end_s":.8,"expected_midi":57}])
        self.assertEqual(checked.proposals,[])

    def test_confident_selected_output_is_not_automatically_replaced(self):
        wave,sr,audio=example(score=.99)
        checked=recheck_samples(wave,sr,audio,[{"start_s":.2,"end_s":.8}])
        self.assertEqual(checked.proposals,[])
        self.assertGreater(checked.summary["rejections"]["selected_high_confidence"],0)

    def test_silence_does_not_become_a_note(self):
        wave,sr,audio=example(raw=None,alternative=440.)
        checked=recheck_samples(wave*0,sr,audio,[{"start_s":0.,"end_s":1.}])
        self.assertEqual(checked.proposals,[])

    def test_wrong_duration_and_outside_windows_rejected(self):
        wave,sr,audio=example()
        with self.assertRaises(ValueError):recheck_samples(wave[:8000],sr,audio,[])
        with self.assertRaises(ValueError):recheck_samples(wave,sr,audio,[{"start_s":-.1,"end_s":.5}])


if __name__=="__main__":unittest.main()
