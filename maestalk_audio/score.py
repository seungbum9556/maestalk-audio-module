"""Optional score context: align pitch runs and expose discrepancies for review.

Sequence alignment uses acoustic starts, score beats and note lengths when
available. It never replaces observed F0 with the expected MIDI pitch.
"""
from collections import defaultdict, deque
from dataclasses import asdict, dataclass, field
from pathlib import Path
import csv
import json
import math
import numpy as np
from .pitch import digest, valid_hz
from .result import AnalysisResult
from .timing import split_at_onsets, make_time_map, temporal_penalties

NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")


def note_name(midi):
    return NAMES[midi % 12]+str(midi//12-1)


@dataclass(frozen=True)
class ScoreNote:
    midi: int
    start_beat: float
    duration_beats: float
    note_id: str = ""

    def __post_init__(self):
        if isinstance(self.midi, bool) or not isinstance(self.midi, int) or not 0 <= self.midi <= 127:
            raise ValueError("MIDI note must be an integer in [0, 127]")
        if not math.isfinite(self.start_beat) or self.start_beat < 0:
            raise ValueError("start_beat must be nonnegative and finite")
        if not math.isfinite(self.duration_beats) or self.duration_beats <= 0:
            raise ValueError("duration_beats must be positive and finite")


@dataclass(frozen=True)
class ScoreReference:
    notes: tuple[ScoreNote, ...]
    source: dict = field(default_factory=dict)

    def __post_init__(self):
        if not self.notes or any(not isinstance(n, ScoreNote) for n in self.notes):
            raise ValueError("A score needs ScoreNote entries")
        if any(b.start_beat <= a.start_beat for a,b in zip(self.notes, self.notes[1:])):
            raise ValueError("Provide one ordered monophonic score part; simultaneous/chord notes are unsupported")
        ids = [n.note_id for n in self.notes if n.note_id]
        if len(set(ids)) != len(ids):
            raise ValueError("Score note IDs must be unique")

    @classmethod
    def from_notes(cls, notes, *, source=None):
        """Accept dictionaries with midi/start_beat/duration_beats and optional note_id."""
        return cls(tuple(ScoreNote(**n) if isinstance(n,dict) else n for n in notes), source or {})

    @classmethod
    def from_json(cls, path):
        path=Path(path)
        payload=json.loads(path.read_text(encoding="utf-8"))
        notes=payload["notes"] if isinstance(payload,dict) else payload
        return cls.from_notes(notes,source={"format":"note_list", "filename":path.name, "sha256":digest(path)})

    @classmethod
    def from_midi(cls, path, *, track_index=None, channel=None):
        """Read score ticks as beats; never use MIDI seconds as performance timestamps."""
        import mido
        path=Path(path)
        midi=mido.MidiFile(path)
        if midi.type==2:
            raise ValueError("Asynchronous MIDI type 2 is unsupported")
        if channel is not None and (isinstance(channel,bool) or not isinstance(channel,int) or not 0<=channel<=15):
            raise ValueError("channel must be an integer from 0 to 15")
        candidates=[i for i,t in enumerate(midi.tracks) if any(
            msg.type=="note_on" and msg.velocity>0 and (channel is None or msg.channel==channel) for msg in t)]
        if track_index is None:
            if len(candidates)!=1:
                raise ValueError("Select track_index explicitly for a MIDI file with multiple or no note tracks")
            track_index=candidates[0]
        if isinstance(track_index,bool) or not isinstance(track_index,int) or not 0<=track_index<len(midi.tracks):
            raise ValueError("Invalid MIDI track_index")
        track=midi.tracks[track_index]
        channels={msg.channel for msg in track if msg.type=="note_on" and msg.velocity>0 and
                  (channel is None or msg.channel==channel)}
        if len(channels)!=1:
            raise ValueError("Select one melodic channel explicitly")
        selected_channel=next(iter(channels))
        if selected_channel==9:
            raise ValueError("Percussion MIDI is outside the monophonic pitch scope")
        active=defaultdict(deque); notes=[]; tick=0
        for msg in track:
            tick+=msg.time
            if getattr(msg,"channel",None)!=selected_channel:
                continue
            if msg.type=="pitchwheel" and msg.pitch:
                raise ValueError("Nonzero score pitch bend needs an explicit tuning policy")
            if msg.type=="note_on" and msg.velocity>0:
                active[msg.note].append(tick)
            elif msg.type=="note_off" or (msg.type=="note_on" and msg.velocity==0):
                if not active[msg.note]:
                    raise ValueError("MIDI note-off without note-on")
                start=active[msg.note].popleft()
                notes.append(ScoreNote(int(msg.note),start/midi.ticks_per_beat,
                                       (tick-start)/midi.ticks_per_beat))
        if any(active.values()):
            raise ValueError("Unclosed MIDI notes; offsets will not be guessed")
        notes.sort(key=lambda n:(n.start_beat,n.midi))
        notes=[ScoreNote(n.midi,n.start_beat,n.duration_beats,f"note_{i}") for i,n in enumerate(notes)]
        signatures=[]
        for part in midi.tracks:
            tick=0
            for msg in part:
                tick+=msg.time
                if msg.type=="time_signature":
                    value={"beat":tick/midi.ticks_per_beat,"numerator":msg.numerator,"denominator":msg.denominator}
                    if value not in signatures:signatures.append(value)
        return cls(tuple(notes),{"format":"MIDI", "filename":path.name, "sha256":digest(path),
            "track_index":track_index, "channel":selected_channel, "ticks_per_beat":midi.ticks_per_beat,
            "beat_unit":"quarter_note","time_signatures":sorted(signatures,key=lambda v:v["beat"]),
            "tempo_used_as_performance_clock":False})


@dataclass(frozen=True)
class ScoreCheckConfig:
    minimum_run_s: float = .048
    bridge_gap_s: float = .032
    substitution_cost: float = 1.
    insertion_deletion_cost: float = .9
    ambiguity_margin: float = .15
    minimum_match_fraction: float = .5
    max_alignment_cells: int = 1_000_000
    use_timing: bool = True
    onset_split_strength: float = .35
    timing_minimum_anchors: int = 3
    time_weight: float = .15
    duration_weight: float = .10
    chroma_weight: float = .05

    def __post_init__(self):
        for key,value in asdict(self).items():
            if not math.isfinite(value) or value<0:
                raise ValueError(f"Invalid score check setting: {key}")
        if self.minimum_run_s<=0 or self.substitution_cost<=0 or self.insertion_deletion_cost<=0:
            raise ValueError("Run length and alignment costs must be positive")
        if not 0<=self.minimum_match_fraction<=1 or self.max_alignment_cells<1:
            raise ValueError("Invalid alignment acceptance setting")
        if not isinstance(self.use_timing,bool) or not isinstance(self.timing_minimum_anchors,int) or self.timing_minimum_anchors<3:
            raise ValueError("Invalid temporal alignment setting")


def pitch_runs(result, config):
    """Group stable F0 labels for sequence alignment; these are NOT detected notes/onsets."""
    frames=result.frames
    if not frames:
        raise ValueError("No audio analysis frames")
    times=np.array([r["time_s"] for r in frames],float)
    if not np.isfinite(times).all() or np.any(np.diff(times)<=0):
        raise ValueError("Audio timestamps must be finite and strictly increasing")
    hop=float(result.summary.get("config",{}).get("hop_s",np.median(np.diff(times)) if len(times)>1 else .016))
    if not math.isfinite(hop) or hop<=0:
        raise ValueError("Invalid audio frame hop")
    labels=[]
    for row in frames:
        hz=row.get("pitch_hz")
        labels.append(round(69+12*np.log2(hz/440)) if hz is not None and valid_hz(hz) else -1)
    labels=np.array(labels,int)
    bounds=np.r_[0,np.flatnonzero(np.diff(labels)!=0)+1,len(labels)]
    stable,short=[],[]
    duration=float(result.summary.get("audio_duration_s",times[-1]+hop))
    for begin,end in zip(bounds[:-1],bounds[1:]):
        if labels[begin]<0:
            continue
        run={"midi":int(labels[begin]),"start_s":float(times[begin]),
             "end_s":float(min(duration,times[end-1]+hop)),"indices":list(range(int(begin),int(end)))}
        if len(run["indices"])*hop+1e-8<config.minimum_run_s:
            short.append(run)
        elif stable and stable[-1]["midi"]==run["midi"] and run["start_s"]-stable[-1]["end_s"]<=config.bridge_gap_s+1e-8:
            stable[-1]["end_s"]=run["end_s"]
            stable[-1]["indices"].extend(run["indices"])
        else:
            stable.append(run)
    for run in stable:
        vectors=[frames[i].get("chroma") for i in run["indices"]]
        vectors=[v for v in vectors if v is not None and len(v)==12 and all(x is not None and np.isfinite(x) for x in v)]
        run["chroma"]=np.mean(vectors,axis=0) if vectors else None
    if result.onsets:
        stable=split_at_onsets(stable,frames,result.onsets,config.minimum_run_s,config.onset_split_strength)
    return stable,short


def align_runs(runs, score, config, partial, time_map=None):
    n,m=len(runs),len(score.notes)
    if (n+1)*(m+1)>config.max_alignment_cells:
        raise ValueError("Score alignment is too large; analyze a shorter score part/segment")
    gap=config.insertion_deletion_cost
    substitution=np.array([[0. if r["midi"]==s.midi else config.substitution_cost for s in score.notes] for r in runs],float).reshape(n,m)
    for i,run in enumerate(runs):
        chroma=run.get("chroma")
        if chroma is not None and np.max(chroma)>0:
            substitution[i]+=config.chroma_weight*(1.-np.asarray([chroma[s.midi%12] for s in score.notes])/np.max(chroma))
    if time_map is not None:
        substitution+=temporal_penalties(runs,score,time_map,config.time_weight,config.duration_weight)
    forward=np.zeros((n+1,m+1)); backward=np.zeros_like(forward)
    forward[:,0]=np.arange(n+1)*gap
    free_prefix=partial is True
    forward[0,:]=0. if free_prefix else np.arange(m+1)*gap
    for i in range(1,n+1):
        for j in range(1,m+1):
            forward[i,j]=min(forward[i-1,j-1]+substitution[i-1,j-1],forward[i-1,j]+gap,forward[i,j-1]+gap)
    backward[:,m]=np.arange(n,-1,-1)*gap
    backward[n,:]=0. if partial else np.arange(m,-1,-1)*gap
    for i in range(n-1,-1,-1):
        for j in range(m-1,-1,-1):
            backward[i,j]=min(backward[i+1,j+1]+substitution[i,j],backward[i+1,j]+gap,backward[i,j+1]+gap)
    i=n; j=int(np.argmin(forward[n])) if partial else m
    end=j; cost=float(forward[i,j]); pairs=[];extra=[];missing=[]
    while i>0 or (j>0 and not free_prefix):
        if i>0 and j>0 and abs(forward[i,j]-forward[i-1,j-1]-substitution[i-1,j-1])<1e-7:
            pairs.append((i-1,j-1));i-=1;j-=1
        elif i>0 and abs(forward[i,j]-forward[i-1,j]-gap)<1e-7:
            extra.append(i-1);i-=1
        else:
            missing.append(j-1);j-=1
    start=j if free_prefix else 0
    ambiguous=set()
    for ri,si in pairs:
        alternatives=forward[ri,:m]+substitution[ri,:]+backward[ri+1,1:]
        alternatives[si]=np.inf
        if np.min(alternatives)<=cost+config.ambiguity_margin+1e-7:
            ambiguous.add(si)
    return sorted(pairs),sorted(extra),sorted(missing),ambiguous,start,end,cost


@dataclass
class ScoreCheckResult:
    notes: list[dict]
    extra_runs: list[dict]
    short_unstable_runs: list[dict]
    summary: dict

    def to_dict(self):
        return {"schema_version":"score-check-1.0","summary":self.summary,"notes":self.notes,
                "extra_runs":self.extra_runs,"short_unstable_runs":self.short_unstable_runs}

    def review_windows(self):
        """Audio-only coordinates for optional rechecking; no expected pitches."""
        windows=[]
        duration=float(self.summary.get("audio_duration_s",float("inf")))
        for row in self.notes:
            if row["status"] in ("consistent_with_score","outside_analyzed_score_span"):continue
            start=row["observed_start_s"] if row["observed_start_s"] is not None else row.get("expected_aligned_start_s")
            end=row["observed_end_s"] if row["observed_end_s"] is not None else row.get("expected_aligned_end_s")
            if start is not None and end is not None and min(duration,end)>max(0.,start):
                windows.append({"start_s":max(0.,start),"end_s":min(duration,end),"reason":row["status"]})
        for row in self.extra_runs+self.short_unstable_runs:
            if row["end_s"]>row["start_s"]:
                windows.append({"start_s":max(0.,row["start_s"]),"end_s":min(duration,row["end_s"]),"reason":row["reason"]})
        return windows

    def save(self, output_dir):
        output=Path(output_dir).expanduser().resolve()
        if output.exists() and (not output.is_dir() or any(output.iterdir())):
            raise FileExistsError(f"Choose a new output directory: {output}")
        payload=json.dumps(self.to_dict(),ensure_ascii=False,allow_nan=False,indent=2)
        output.mkdir(parents=True,exist_ok=True)
        (output/"score_check.json").write_text(payload+"\n",encoding="utf-8")
        with (output/"score_notes.csv").open("w",newline="",encoding="utf-8-sig") as stream:
            writer=csv.DictWriter(stream,fieldnames=list(self.notes[0]))
            writer.writeheader();writer.writerows(self.notes)
        return output


def compare_with_score(result, score, *, partial_score=False, config=None):
    """Return expected/observed evidence without changing any audio analysis frame.

    Audio anchors estimate a score-beat/time map and soft timing/length costs.
    Acoustic rearticulation evidence may split repeated pitches. Unresolved
    repetitions are explicitly retained; arbitrary score jumps are unsupported.
    """
    if not isinstance(result,AnalysisResult) or not isinstance(score,ScoreReference):
        raise TypeError("Expected an AnalysisResult and ScoreReference")
    if not (isinstance(partial_score,bool) or partial_score=="prefix"):
        raise ValueError("partial_score must be False, True or 'prefix'")
    config=config or ScoreCheckConfig()
    runs,short=pitch_runs(result,config)
    pairs,extra,missing,ambiguous,start,end,cost=align_runs(runs,score,config,partial_score)
    time_map=make_time_map(runs,score,pairs,ambiguous,config.timing_minimum_anchors) if config.use_timing else None
    if time_map is not None:
        pairs,extra,missing,ambiguous,start,end,cost=align_runs(runs,score,config,partial_score,time_map)
        updated=make_time_map(runs,score,pairs,ambiguous,config.timing_minimum_anchors)
        if updated is not None:time_map=updated
    match_count=sum(runs[ri]["midi"]==score.notes[si].midi for ri,si in pairs)
    match_fraction=match_count/max(1,len(pairs)+len(extra)+len(missing))
    reliable=bool(runs) and match_fraction>=config.minimum_match_fraction
    mapping={si:ri for ri,si in pairs}
    notes=[]
    for si,note in enumerate(score.notes):
        ri=mapping.get(si);run=runs[ri] if ri is not None else None
        row={"score_index":si,"score_note_id":note.note_id or f"note_{si}","expected_midi":note.midi,
             "expected_note":note_name(note.midi),"start_beat":note.start_beat,"duration_beats":note.duration_beats,
             "next_expected_midi":score.notes[si+1].midi if si+1<len(score.notes) else None,
             "run_index":ri,"observed_midi":None,"observed_pitch_hz_median":None,
             "observed_start_s":None,"observed_end_s":None,"cents_error_median":None,
             "within_50cent_fraction":None,"relative_level_db_median":None,
             "expected_aligned_start_s":float(time_map.predict(note.start_beat)) if time_map else None,
             "expected_aligned_end_s":float(time_map.predict(note.start_beat+note.duration_beats)) if time_map else None,
             "observed_onset_s":None,"onset_evidence":None,"timing_residual_s":None,
             "timing_anchor_note_indices":None,"timing_review":False,
             "status":"not_observed_review","needs_review":True}
        repeated=(si>0 and score.notes[si-1].midi==note.midi) or (si+1<len(score.notes) and score.notes[si+1].midi==note.midi)
        if partial_score and reliable and not start<=si<end:
            row.update(status="outside_analyzed_score_span",needs_review=False)
        elif run is not None:
            hz=np.array([result.frames[i]["pitch_hz"] for i in run["indices"]],float)
            cents=1200*np.log2(hz/(440*2**((note.midi-69)/12)))
            levels=[result.frames[i].get("relative_to_performance_db") for i in run["indices"]]
            levels=[v for v in levels if v is not None and np.isfinite(v)]
            within=float(np.mean(abs(cents)<=50))
            status="consistent_with_score" if within>=.8 else "pitch_mismatch_review"
            if not reliable:status="alignment_uncertain"
            elif repeated:
                group=[si]
                k=si-1
                while k>=0 and score.notes[k].midi==note.midi:group.append(k);k-=1
                k=si+1
                while k<len(score.notes) and score.notes[k].midi==note.midi:group.append(k);k+=1
                events=[runs[mapping[k]].get("boundary_event") for k in group if k in mapping]
                resolved=len(events)==len(group) and all(e is not None for e in events) and len({round(e["time_s"],6) for e in events})==len(group)
                if not resolved:status="repeat_boundary_unresolved"
            elif si in ambiguous:status="alignment_ambiguous"
            if reliable and si in ambiguous and status!="repeat_boundary_unresolved":status="alignment_ambiguous"
            row.update(observed_midi=run["midi"],observed_pitch_hz_median=float(np.median(hz)),
                observed_start_s=run["start_s"],observed_end_s=run["end_s"],cents_error_median=float(np.median(cents)),
                within_50cent_fraction=within,relative_level_db_median=float(np.median(levels)) if levels else None,
                status=status,needs_review=status!="consistent_with_score")
            event=run.get("boundary_event")
            if event:
                row.update(observed_onset_s=float(event["time_s"]),onset_evidence=event.get("sources","acoustic_candidate"))
                prediction=time_map.leave_one_out(si,note.start_beat) if time_map and reliable and si not in ambiguous else None
                if prediction:
                    expected,ids=prediction;residual=float(event["time_s"]-expected)
                    threshold=max(.080,.2*time_map.rate(note.start_beat))
                    row.update(timing_residual_s=residual,timing_anchor_note_indices=ids,timing_review=abs(residual)>threshold)
                    if row["timing_review"]:row["needs_review"]=True
        elif repeated and runs:
            row["status"]="repeat_boundary_unresolved"
        elif not reliable and runs:
            row["status"]="alignment_uncertain"
        notes.append(row)
    def public_run(run, reason):
        hz=[result.frames[i]["pitch_hz"] for i in run["indices"]]
        return {"midi":run["midi"],"note":note_name(run["midi"]),"start_s":run["start_s"],
                "end_s":run["end_s"],"pitch_hz_median":float(np.median(hz)),"reason":reason}
    return ScoreCheckResult(notes,[public_run(runs[i],"unmatched_audio_run_review") for i in extra],
        [public_run(r,"short_unstable_pitch_run") for r in short],
        {"method":"Pitch/Chroma sequence alignment with acoustic onset anchors and soft beat/length timing; experimental",
         "score_source":score.source,"config":asdict(config),"partial_score":partial_score,
         "alignment_cost":cost,"exact_run_match_fraction":match_fraction,
         "alignment_status":"accepted_for_review" if reliable else "insufficient_audio" if not runs else "uncertain",
         "score_notes":len(score.notes),"observed_stable_runs":len(runs),
         "review_note_count":sum(r["needs_review"] for r in notes),"extra_run_count":len(extra),
         "short_unstable_run_count":len(short),"audio_estimates_unchanged":True,
         "pitch_replacement_performed":False,"audio_onset_detection_performed":result.onsets is not None,
         "timing_map":time_map.to_dict() if time_map else None,
         "relative_timing_evaluated":any(r["timing_residual_s"] is not None for r in notes),
         "rhythm_deviation_evaluated":False,"alignment_uses_midi_seconds":False,
         "source_start_s":result.summary.get("source_start_s",0.),
         "audio_duration_s":result.summary.get("audio_duration_s",result.frames[-1]["time_s"]+.016),
         "score_span_mode":"prefix" if partial_score=="prefix" else "subsequence" if partial_score else "full",
         "time_definition":"Segment-relative; add source_start_s for original recording times",
         "scope":"Review evidence; discrepancies may be performance errors, recognition errors or alignment errors",
         "limitations":["Timing is fitted from performance anchors, not a supplied conductor/metronome clock",
             "Same-pitch reattacks require independent acoustic evidence; otherwise remain unresolved",
             "Arbitrary repeats/jumps and polyphony are unsupported",
             "No independent calibrated probability for alignment correctness",
             "A matching score note does not prove the acoustic estimate is correct"]})
