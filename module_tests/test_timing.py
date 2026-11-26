"""Acoustic boundaries and beat timing must not be invented from score expectations."""
import unittest
import numpy as np
from maestalk_audio.onsets import detect_onsets
from maestalk_audio.result import AnalysisResult
from maestalk_audio.score import ScoreNote,ScoreReference,compare_with_score


def make_signal(pitches, durations, *, lead=.2, gap=0.):
    sr=16000;pieces=[np.zeros(round(lead*sr))];cursor=lead;intervals=[]
    for pitch,duration in zip(pitches,durations):
        count=round(duration*sr);t=np.arange(count)/sr;tone=.2*np.sin(2*np.pi*(440*2**((pitch-69)/12))*t)
        fade=160;tone[:fade]*=np.linspace(0,1,fade);tone[-fade:]*=np.linspace(1,0,fade)
        pieces.extend([tone,np.zeros(round(gap*sr))]);intervals.append((cursor,cursor+duration,pitch));cursor+=duration+gap
    pieces.append(np.zeros(3200));return np.concatenate(pieces).astype(np.float32),sr,intervals


def analysis_from_intervals(intervals,duration,events=None):
    rows=[]
    for t in np.arange(0,duration,.016):
        pitch=next((p for a,b,p in intervals if a<=t<b),None)
        rows.append({"time_s":float(t),"pitch_hz":440*2**((pitch-69)/12) if pitch is not None else None,
                     "relative_to_performance_db":-2.})
    return AnalysisResult(rows,{"audio_duration_s":duration,"config":{"hop_s":.016}},onsets=events)


class AcousticTimingTests(unittest.TestCase):
    def test_known_attacks_within_fifty_ms_and_gain_invariant(self):
        wave,sr,truth=make_signal([60,62,64],[.3,.3,.3],gap=.1)
        first,_=detect_onsets(wave,sr);second,_=detect_onsets(wave*.25,sr)
        self.assertEqual(len(first),3)
        for event,(start,_,_) in zip(first,truth):self.assertLessEqual(abs(event["time_s"]-start),.05)
        self.assertEqual([e["time_s"] for e in first],[e["time_s"] for e in second])

    def test_silence_has_no_onsets(self):
        events,info=detect_onsets(np.zeros(16000),16000)
        self.assertEqual(events,[]);self.assertEqual(info["status"],"digital_silence")

    def test_same_pitch_reattacks_need_audio_evidence(self):
        wave,sr,truth=make_signal([60,60,60,62],[.3,.3,.3,.3])
        events,_=detect_onsets(wave,sr)
        audio=analysis_from_intervals(truth,len(wave)/sr,events)
        score=ScoreReference(tuple(ScoreNote(p,i,.9) for i,p in enumerate([60,60,60,62])))
        checked=compare_with_score(audio,score)
        self.assertEqual([n["observed_midi"] for n in checked.notes],[60,60,60,62])
        self.assertFalse(any(n["status"]=="repeat_boundary_unresolved" for n in checked.notes))
        self.assertTrue(all(n["observed_onset_s"] is not None for n in checked.notes))

    def test_held_tone_is_not_split_just_because_score_repeats(self):
        wave,sr,truth=make_signal([60,62],[.9,.3])
        events,_=detect_onsets(wave,sr)
        audio=analysis_from_intervals(truth,len(wave)/sr,events)
        checked=compare_with_score(audio,ScoreReference(tuple(ScoreNote(p,i,.9) for i,p in enumerate([60,60,60,62]))))
        self.assertEqual(sum(n["observed_midi"]==60 for n in checked.notes),1)
        self.assertTrue(any(n["status"] in ("repeat_boundary_unresolved","alignment_uncertain") for n in checked.notes))

    def test_loudness_step_alone_does_not_split_a_held_note(self):
        sr=16000;t=np.arange(sr*2)/sr
        wave=(np.sin(2*np.pi*261.625565*t)*np.where(t<1.,.08,.24)).astype(np.float32)
        events,_=detect_onsets(wave,sr)
        audio=analysis_from_intervals([(0.,2.,60)],2.,events)
        checked=compare_with_score(audio,ScoreReference((ScoreNote(60,0.,4.),)))
        self.assertEqual(checked.summary["observed_stable_runs"],1)

    def test_local_timing_residual_does_not_fit_its_own_anchor(self):
        intervals=[(1.,1.3,60),(1.5,1.8,62),(2.2,2.4,64),(2.5,2.8,65)]
        events=[{"time_s":a,"strength":1.,"sources":"measured_test_attack","rearticulation_evidence":True} for a,b,p in intervals]
        audio=analysis_from_intervals(intervals,3.,events)
        score=ScoreReference(tuple(ScoreNote(p,i,.8) for i,p in enumerate([60,62,64,65])))
        checked=compare_with_score(audio,score)
        row=checked.notes[2]
        self.assertAlmostEqual(row["timing_residual_s"],.2,places=6)
        self.assertNotIn(2,row["timing_anchor_note_indices"])
        self.assertTrue(row["timing_review"])

    def test_prefix_mode_retains_start_position_in_repeated_phrase(self):
        intervals=[(.2,.4,60),(.5,.7,62),(.8,1.,64)]
        audio=analysis_from_intervals(intervals,1.2)
        score=ScoreReference(tuple(ScoreNote(p,i,.8) for i,p in enumerate([60,62,64,60,62,64])))
        checked=compare_with_score(audio,score,partial_score="prefix")
        self.assertEqual([n["score_index"] for n in checked.notes if n["run_index"] is not None],[0,1,2])
        self.assertTrue(all(n["status"]=="outside_analyzed_score_span" for n in checked.notes[3:]))


if __name__=="__main__":unittest.main()
