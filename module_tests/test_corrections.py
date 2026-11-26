"""Waveform counterexamples protect valid pitch estimates from confident wrong alternatives."""
import copy
import unittest
import numpy as np
from maestalk_audio.corrections import repair_pitch
from maestalk_audio.pitch import check_models,valid_hz


def fixture(raw_hz,alternative_hz,duration=1.):
    times=np.arange(0,duration,.016);n=len(times)
    pitch={"hz":np.full(n,raw_hz),"use_fcpe":np.zeros(n,bool),
        "swift_hz":np.full(n,raw_hz),"swift_score":np.full(n,.9),
        "fcpe_hz":np.full(n,alternative_hz),"fcpe_score":np.full(n,.85)}
    return times,pitch


class GuardedPitchTests(unittest.TestCase):
    def test_analysis_keeps_original_pitch_levels_chroma_and_onsets(self):
        from unittest.mock import patch
        from maestalk_audio import AudioAnalyzer,AnalysisConfig
        class Engine:
            def __init__(self,*args,**kwargs):self.settings={'test_double':True}
            def predict(self,wave,sr,query):return fixture(440.,220.,len(wave)/sr)[1]
        class Verifier:
            def __init__(self,*args,**kwargs):self.settings={'provider':'test double'}
            def predict(self,wave,sr,query):return {'hz':np.full(len(query),220.),'score':np.ones(len(query))}
        wave=(.2*np.sin(2*np.pi*220*np.arange(16000)/16000)).astype(np.float32)
        original=wave.copy()
        with patch('maestalk_audio.analysis.PitchPair',Engine),patch('maestalk_audio.corrections.HarmonicVerifier',Verifier):
            fixed=AudioAnalyzer(AnalysisConfig(expanded_onsets=True)).analyze_samples(wave,16000)
            baseline=AudioAnalyzer(AnalysisConfig(expanded_onsets=True,pitch_repairs=False)).analyze_samples(wave,16000)
        self.assertTrue(fixed.summary['pitch_repair']['changes'])
        self.assertTrue(all(r['raw_pitch_hz']==440. for r in fixed.frames))
        for field in ('rms','relative_to_performance_db','volume_change_db','chroma'):
            self.assertEqual([r[field] for r in fixed.frames],[r[field] for r in baseline.frames])
        self.assertEqual(fixed.onsets,baseline.onsets)
        self.assertEqual(fixed.pitch_boundaries,baseline.pitch_boundaries)
        np.testing.assert_array_equal(original,wave)

    def test_a_real_octave_mistake_is_corrected_without_mutating_models(self):
        times,pitch=fixture(440.,220.);original=copy.deepcopy(pitch)
        wave=(.2*np.sin(2*np.pi*220*np.arange(16000)/16000)).astype(np.float32)
        result,changes=repair_pitch(wave,16000,times,pitch)
        self.assertTrue(changes)
        core=(times>.2)&(times<.8)
        self.assertTrue(np.all(result['hz'][core]==220.))
        self.assertTrue(result['use_fcpe'][core].all())
        for key in pitch:np.testing.assert_array_equal(pitch[key],original[key])

    def test_pure_tones_are_not_changed_to_subharmonics_even_with_a_confident_verifier(self):
        for hz in (65.406,130.813,261.626,440.,1046.5,1684.,1975.):
            with self.subTest(hz=hz):
                times,pitch=fixture(hz,hz/2)
                wave=(.2*np.sin(2*np.pi*hz*np.arange(16000)/16000)).astype(np.float32)
                verifier={'hz':np.full(len(times),hz/2),'score':np.full(len(times),.999)}
                result,changes=repair_pitch(wave,16000,times,pitch,verifier=verifier)
                self.assertEqual(changes,[])
                np.testing.assert_array_equal(result['hz'],pitch['hz'])

    def test_large_non_octave_disagreement_cannot_override_a_valid_note(self):
        times,pitch=fixture(493.,98.)
        wave=(.2*np.sin(2*np.pi*493*np.arange(16000)/16000)).astype(np.float32)
        verifier={'hz':np.full(len(times),98.),'score':np.full(len(times),.999)}
        result,changes=repair_pitch(wave,16000,times,pitch,verifier=verifier)
        self.assertEqual(changes,[])

    def test_a_slightly_detuned_correct_estimate_is_not_replaced_by_an_exact_subharmonic(self):
        for actual in (130.813,261.626,440.,1046.5,1684.):
            with self.subTest(actual=actual):
                times,pitch=fixture(actual*2**(40/1200),actual/2)
                t=np.arange(16000)/16000
                wave=(.15*np.sin(2*np.pi*actual*t)+.04*np.sin(4*np.pi*actual*t)).astype(np.float32)
                verifier={'hz':np.full(len(times),actual/2),'score':np.ones(len(times))}
                result,changes=repair_pitch(wave,16000,times,pitch,verifier=verifier)
                self.assertEqual(changes,[])

    def test_a_silent_or_missing_pitch_is_never_filled(self):
        times,pitch=fixture(np.nan,220.)
        verifier={'hz':np.full(len(times),220.),'score':np.ones(len(times))}
        for wave in (np.zeros(16000,np.float32),(.2*np.sin(2*np.pi*220*np.arange(16000)/16000)).astype(np.float32)):
            result,changes=repair_pitch(wave,16000,times,pitch,verifier=verifier)
            self.assertEqual(changes,[])
            self.assertFalse(valid_hz(result['hz']).any())

    def test_high_selected_confidence_and_brief_disagreements_are_preserved(self):
        times,pitch=fixture(440.,220.)
        wave=(.2*np.sin(2*np.pi*220*np.arange(16000)/16000)).astype(np.float32)
        pitch['swift_score'][:]=.99
        self.assertEqual(repair_pitch(wave,16000,times,pitch)[1],[])
        pitch['swift_score'][:]=.9;pitch['fcpe_hz'][:]=440.
        pitch['fcpe_hz'][20]=220.
        self.assertEqual(repair_pitch(wave,16000,times,pitch)[1],[])

    def test_weak_fundamental_and_signal_gain_keep_the_same_repair(self):
        times,pitch=fixture(440.,220.);t=np.arange(16000)/16000
        wave=(.08*np.sin(2*np.pi*220*t)+.3*np.sin(2*np.pi*440*t)+.06*np.sin(2*np.pi*660*t)).astype(np.float32)
        first,changes=repair_pitch(wave,16000,times,pitch)
        second,scaled_changes=repair_pitch(wave*.01,16000,times,pitch)
        self.assertTrue(changes)
        np.testing.assert_array_equal(first['hz'],second['hz'])
        self.assertEqual([r['frame_index'] for r in changes],[r['frame_index'] for r in scaled_changes])

    def test_verifier_asset_is_separately_hash_checked(self):
        self.assertEqual(set(check_models()['models']),{'swift','fcpe_ddsp'})
        all_models=check_models(include_verifier=True)['models']
        self.assertEqual(all_models['harmof0_verifier']['role'],'verification_only')

    def test_invalid_input_does_not_produce_a_repair(self):
        times,pitch=fixture(440.,220.)
        with self.assertRaises(ValueError):repair_pitch(np.zeros((16000,2)),16000,times,pitch)
        with self.assertRaises(ValueError):repair_pitch(np.zeros(16000),True,times,pitch)
        with self.assertRaises(ValueError):repair_pitch(np.zeros(16000),16000,times[::-1],pitch)


if __name__=='__main__':unittest.main()
