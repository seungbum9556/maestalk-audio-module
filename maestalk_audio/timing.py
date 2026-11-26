"""Monotonic score-beat/performance-time mapping from observed audio anchors."""
from dataclasses import dataclass
import numpy as np


def nearest_onset(events, time_s, search_s=.1, *, before_only=False):
    eligible=[e for e in events if abs(e["time_s"]-time_s)<=search_s and
              e.get("strength",0.)>=.35 and (not before_only or e["time_s"]<=time_s+.024)]
    return min(eligible,key=lambda e:abs(e["time_s"]-time_s)) if eligible else None


def split_at_onsets(runs, frames, events, minimum_run_s, minimum_strength):
    """Split same-pitch spans only at independently measured rearticulation events."""
    result=[]
    hop=float(np.median(np.diff([r["time_s"] for r in frames]))) if len(frames)>1 else .016
    for run in runs:
        indices=np.array(run["indices"],int)
        cuts=[]
        for event in events:
            if not event.get("rearticulation_evidence") or event.get("strength",0.)<minimum_strength:
                continue
            split=int(np.searchsorted([frames[i]["time_s"] for i in indices],event["time_s"]))
            if split*hop>=minimum_run_s-1e-8 and (len(indices)-split)*hop>=minimum_run_s-1e-8:
                cuts.append((split,event))
        previous=0;start_event=None
        for cut,event in sorted(cuts,key=lambda c:c[0]):
            if (cut-previous)*hop<minimum_run_s-1e-8:continue
            chunk=indices[previous:cut]
            result.append({**run,"indices":chunk.tolist(),"start_s":float(frames[chunk[0]]["time_s"]),
                "end_s":float(frames[chunk[-1]]["time_s"]+hop),"split_by_acoustic_onset":start_event is not None,
                "boundary_event":start_event})
            previous=cut;start_event=event
        chunk=indices[previous:]
        result.append({**run,"indices":chunk.tolist(),"start_s":float(frames[chunk[0]]["time_s"]),
            "end_s":float(min(run["end_s"],frames[chunk[-1]]["time_s"]+hop)),
            "split_by_acoustic_onset":start_event is not None,"boundary_event":start_event})
    for run in result:
        if run.get("boundary_event") is None:
            run["boundary_event"]=nearest_onset(events,run["start_s"],before_only=True)
    return result


@dataclass
class BeatTimeMap:
    beats: np.ndarray
    seconds: np.ndarray
    note_indices: np.ndarray
    mode: str
    rejected_note_indices: list

    def predict(self, beats):
        values=np.asarray(beats,float)
        slopes=np.diff(self.seconds)/np.diff(self.beats)
        first=float(np.median(slopes[:3]));last=float(np.median(slopes[-3:]))
        output=np.interp(values,self.beats,self.seconds)
        output=np.where(values<self.beats[0],self.seconds[0]+(values-self.beats[0])*first,output)
        output=np.where(values>self.beats[-1],self.seconds[-1]+(values-self.beats[-1])*last,output)
        return float(output) if output.ndim==0 else output

    def rate(self, beat):
        return max(.001,float(self.predict(beat+.25)-self.predict(beat-.25))/.5)

    def leave_one_out(self, note_index, beat):
        """Never report zero residual merely because this note fitted its own clock."""
        if self.mode!="acoustic_onset_anchors":return None
        keep=self.note_indices!=note_index
        b=self.beats[keep];t=self.seconds[keep];ids=self.note_indices[keep]
        before=np.flatnonzero(b<beat);after=np.flatnonzero(b>beat)
        if not len(before) or not len(after):return None
        lo,hi=int(before[-1]),int(after[0])
        if b[hi]-b[lo]>8.:return None
        expected=float(t[lo]+(beat-b[lo])*(t[hi]-t[lo])/(b[hi]-b[lo]))
        return expected,[int(ids[lo]),int(ids[hi])]

    def to_dict(self):
        return {"mode":self.mode,"beats":self.beats.tolist(),"seconds":self.seconds.tolist(),
            "note_indices":self.note_indices.tolist(),"rejected_note_indices":self.rejected_note_indices,
            "seconds_per_beat":(np.diff(self.seconds)/np.diff(self.beats)).tolist(),
            "source":"Observed audio matched to score beats; MIDI seconds not used",
            "timing_residual_reference":"Leave-one-out neighboring anchors, not a conductor/metronome clock"}


def make_time_map(runs, score, pairs, ambiguous, minimum_anchors=3):
    correct=[(ri,si) for ri,si in pairs if si not in ambiguous and runs[ri]["midi"]==score.notes[si].midi]
    onsets=[]
    for ri,si in correct:
        event=runs[ri].get("boundary_event")
        if event is not None:
            onsets.append((score.notes[si].start_beat,float(event["time_s"]),si,
                           abs(event["time_s"]-runs[ri]["start_s"])))
    # One acoustic event cannot anchor two different score notes.
    unique={}
    for anchor in onsets:
        key=round(anchor[1],6)
        if key not in unique or anchor[3]<unique[key][3]:unique[key]=anchor
    anchors=sorted(unique.values())
    mode="acoustic_onset_anchors"
    if len(anchors)<minimum_anchors:
        mode="pitch_center_fallback"
        anchors=sorted((score.notes[si].start_beat+score.notes[si].duration_beats/2,
                        (runs[ri]["start_s"]+runs[ri]["end_s"])/2,si,0.) for ri,si in correct)
    if len(anchors)<minimum_anchors:return None
    filtered=[];rejected=[]
    for anchor in anchors:
        if filtered and (anchor[0]<=filtered[-1][0] or anchor[1]<=filtered[-1][1]):
            rejected.append(int(anchor[2]));continue
        filtered.append(anchor)
    if len(filtered)<minimum_anchors:return None
    # Reject isolated timing outliers before applying a piecewise tempo map.
    beats=np.array([a[0] for a in filtered]);times=np.array([a[1] for a in filtered])
    rate=float(np.median(np.diff(times)/np.diff(beats)))
    if len(filtered)>=5:
        keep=np.ones(len(filtered),bool)
        for i in range(1,len(filtered)-1):
            estimate=times[i-1]+(beats[i]-beats[i-1])*(times[i+1]-times[i-1])/(beats[i+1]-beats[i-1])
            if abs(times[i]-estimate)>max(.20,.5*rate):
                keep[i]=False;rejected.append(int(filtered[i][2]))
        filtered=[a for a,k in zip(filtered,keep) if k]
    if len(filtered)<minimum_anchors:return None
    return BeatTimeMap(np.array([a[0] for a in filtered]),np.array([a[1] for a in filtered]),
                       np.array([a[2] for a in filtered],int),mode,rejected)


def temporal_penalties(runs, score, time_map, time_weight, duration_weight):
    penalty=np.zeros((len(runs),len(score.notes)))
    for j,note in enumerate(score.notes):
        expected_start=time_map.predict(note.start_beat)
        expected_end=time_map.predict(note.start_beat+note.duration_beats)
        expected_length=max(.032,expected_end-expected_start)
        sigma=max(.080,.5*expected_length)
        for i,run in enumerate(runs):
            event=run.get("boundary_event")
            observed=event["time_s"] if event else (run["start_s"]+run["end_s"])/2
            expected=expected_start if event else (expected_start+expected_end)/2
            actual_length=max(.016,run["end_s"]-run["start_s"])
            penalty[i,j]=time_weight*min(2.,abs(observed-expected)/sigma)+duration_weight*min(2.,abs(np.log(actual_length/expected_length)))
    return penalty
