"""Optional audio-only rechecking in review windows; expected notes are never inputs."""
from dataclasses import asdict, dataclass
from pathlib import Path
from time import perf_counter
import csv
import hashlib
import json
import math
import numpy as np
from scipy.signal import resample_poly
import soundfile as sf
from .pitch import nearest, valid_hz, digest


@dataclass(frozen=True)
class RecheckConfig:
    sample_rate: int = 16000
    window_samples: int = 2048
    hop_samples: int = 256
    context_s: float = .160
    merge_gap_s: float = .160
    pyin_voiced_min: float = .85
    agreement_cents: float = 35.
    candidate_swift_min: float = .5
    candidate_fcpe_min: float = .4
    keep_swift_score: float = .95
    keep_fcpe_score: float = .95
    minimum_support_s: float = .048

    def __post_init__(self):
        for key,value in asdict(self).items():
            if not math.isfinite(value) or value<=0:raise ValueError("Invalid recheck setting: "+key)
        for key in ("sample_rate","window_samples","hop_samples"):
            if isinstance(getattr(self,key),bool) or not isinstance(getattr(self,key),int):raise ValueError("Recheck sizes must be integers")
        for key in ("pyin_voiced_min","candidate_swift_min","candidate_fcpe_min","keep_swift_score","keep_fcpe_score"):
            if getattr(self,key)>1:raise ValueError("Model score thresholds must be in (0,1]")


def _finite(value):
    return value is not None and np.isfinite(value)


def _windows(windows,duration,config):
    requested=[]
    for row in windows:
        a,b=float(row["start_s"]),float(row["end_s"])
        if not np.isfinite([a,b]).all() or a<0 or b<=a or b>duration+1e-5:
            raise ValueError("Review windows must be finite intervals inside the supplied audio")
        requested.append((a,min(b,duration)))
    expanded=[]
    for a,b in sorted(requested):
        a,b=max(0.,a-config.context_s),min(duration,b+config.context_s)
        if expanded and a<=expanded[-1][1]+config.merge_gap_s:
            expanded[-1]=(expanded[-1][0],max(expanded[-1][1],b))
        else:expanded.append((a,b))
    return requested,expanded


def candidate_review_windows(analysis,score_check=None,*,boundary_s=.080):
    """Include uncertain audio frames and note boundaries, not just whole-note mismatches.

    Correct note medians can hide short edge failures. Those frames must still
    reach the audio verifier. Expected pitch values never leave this selector.
    """
    if not math.isfinite(boundary_s) or boundary_s<=0:raise ValueError("boundary_s must be positive")
    windows=list(score_check.review_windows()) if score_check is not None else []
    duration=float(analysis.summary["audio_duration_s"])
    times=np.array([r["time_s"] for r in analysis.frames],float)
    hop=float(np.median(np.diff(times))) if len(times)>1 else .016
    uncertain=[]
    for i,row in enumerate(analysis.frames):
        state=row.get("pitch_state")
        has_candidate=any(row.get(key) is not None and valid_hz(row[key]) for key in ("swift_hz","fcpe_hz"))
        uncertain.append(has_candidate and (row.get("pitch_hz") is None or state=="model_disagreement"))
    mask=np.asarray(uncertain,bool)
    bounds=np.r_[0,np.flatnonzero(np.diff(mask.astype(int))!=0)+1,len(mask)]
    for a,b in zip(bounds[:-1],bounds[1:]):
        if a<len(mask) and mask[a]:windows.append({"start_s":float(times[a]),"end_s":min(duration,float(times[b-1]+hop)),"reason":"audio_candidate_uncertainty"})
    for event in analysis.onsets or []:
        start=max(0.,event["time_s"]-boundary_s);end=min(duration,event["time_s"]+boundary_s)
        if end>start:windows.append({"start_s":start,"end_s":end,"reason":"acoustic_boundary"})
    return windows


@dataclass
class PitchRecheckResult:
    proposals: list[dict]
    summary: dict

    def to_dict(self):
        return {"schema_version":"pitch-recheck-1.0","summary":self.summary,"proposals":self.proposals}

    def save(self,output_dir):
        output=Path(output_dir).expanduser().resolve()
        if output.exists() and (not output.is_dir() or any(output.iterdir())):
            raise FileExistsError("Choose a new recheck output folder")
        text=json.dumps(self.to_dict(),allow_nan=False,ensure_ascii=False,indent=2)
        output.mkdir(parents=True,exist_ok=True)
        (output/"pitch_recheck.json").write_text(text+"\n",encoding="utf-8")
        keys=list(self.proposals[0]) if self.proposals else ["frame_index","time_s","raw_hz","proposed_hz","status"]
        with (output/"pitch_proposals.csv").open("w",newline="",encoding="utf-8-sig") as stream:
            writer=csv.DictWriter(stream,fieldnames=keys);writer.writeheader();writer.writerows(self.proposals)
        return output


def recheck_samples(samples,sample_rate,analysis,review_windows,*,config=None):
    """Check existing NN candidates using independent pYIN, only inside requested windows.

    No ScoreReference or expected pitch is accepted. Score context may locate a
    window, but cannot choose the returned frequency. Original analysis is intact.
    """
    config=config or RecheckConfig();started=perf_counter()
    wave=np.asarray(samples,np.float32)
    if wave.ndim!=1 or not len(wave) or not np.isfinite(wave).all():raise ValueError("Expected finite mono audio")
    if isinstance(sample_rate,bool) or not isinstance(sample_rate,(int,np.integer)) or sample_rate<=0:
        raise ValueError("Invalid recheck sample rate")
    duration=len(wave)/sample_rate
    if analysis.summary.get("sample_rate",sample_rate)!=sample_rate:
        raise ValueError("Sample rate differs from the supplied analysis")
    if abs(duration-analysis.summary["audio_duration_s"])>1/sample_rate:
        raise ValueError("Audio duration differs from the supplied analysis")
    frames=analysis.frames;times=np.array([f["time_s"] for f in frames],float)
    if not len(times) or not np.isfinite(times).all() or np.any(np.diff(times)<=0):
        raise ValueError("Invalid analysis time grid")
    requested,expanded=_windows(review_windows,duration,config)
    mask=np.zeros(len(times),bool)
    for a,b in requested:mask|=(times>=a)&(times<b)
    verification=np.full(len(times),np.nan);probability=np.full(len(times),np.nan)
    sr=config.sample_rate
    if expanded:
        if sample_rate!=sr:
            divisor=math.gcd(int(sample_rate),sr)
            resampled=resample_poly(wave,sr//divisor,int(sample_rate)//divisor).astype(np.float32)
        else:resampled=wave
        import librosa
        for a,b in expanded:
            start=max(0,int(np.floor(a*sr/config.hop_samples))*config.hop_samples)
            end=min(len(resampled),int(np.ceil(b*sr/config.hop_samples))*config.hop_samples)
            segment=resampled[start:end]
            if len(segment)<config.window_samples or np.max(np.abs(segment))<1e-12:continue
            # Numerical level normalization affects this verifier only, never RMS.
            segment=segment/np.max(np.abs(segment))
            hz,voiced,prob=librosa.pyin(segment,sr=sr,fmin=50.,fmax=2000.,
                frame_length=config.window_samples,hop_length=config.hop_samples,center=True,fill_na=np.nan)
            pt=start/sr+np.arange(len(hz))*config.hop_samples/sr
            inside=mask&(times>=a)&(times<b)
            verification[inside]=nearest(pt,hz,times[inside])
            probability[inside]=nearest(pt,prob,times[inside])
    proposed=[];reasons={"no_pyin_support":0,"raw_already_supported":0,"selected_high_confidence":0,"no_agreeing_neural_candidate":0,"too_short_support":0}
    for i in np.flatnonzero(mask):
        row=frames[i];ph=verification[i];prob=probability[i]
        if not valid_hz(ph) or not _finite(prob) or prob<config.pyin_voiced_min:
            reasons["no_pyin_support"]+=1;continue
        raw=row.get("pitch_hz")
        if raw is not None and valid_hz(raw) and abs(1200*np.log2(raw/ph))<=config.agreement_cents:
            reasons["raw_already_supported"]+=1;continue
        keep=config.keep_swift_score if row.get("pitch_source")=="swift" else config.keep_fcpe_score
        if raw is not None and _finite(row.get("source_score")) and row["source_score"]>=keep:
            reasons["selected_high_confidence"]+=1;continue
        candidates=[]
        for name,min_score in (("swift",config.candidate_swift_min),("fcpe",config.candidate_fcpe_min)):
            hz=row.get(name+"_hz");score=row.get(name+"_score")
            if hz is not None and valid_hz(hz) and _finite(score) and score>=min_score:
                error=abs(1200*np.log2(hz/ph))
                if error<=config.agreement_cents and (raw is None or not valid_hz(raw) or abs(1200*np.log2(hz/raw))>50):
                    candidates.append((name,float(hz),float(score),float(error)))
        if not candidates:
            reasons["no_agreeing_neural_candidate"]+=1;continue
        # Fixed source priority; scores from different models are not compared.
        name,hz,score,error=candidates[0]
        proposed.append({"frame_index":int(i),"time_s":float(times[i]),"raw_hz":float(raw) if raw is not None else None,
            "proposed_hz":hz,"supporting_model":name,"candidate_score":score,"pyin_hz":float(ph),
            "pyin_voiced_probability":float(prob),"agreement_cents":error,"status":"audio_supported_proposal"})
    accepted=[];group=[]
    hop=float(np.median(np.diff(times))) if len(times)>1 else .016
    def flush():
        if group:
            if times[group[-1]["frame_index"]]-times[group[0]["frame_index"]]+hop>=config.minimum_support_s-1e-8:
                accepted.extend(group)
            else:reasons["too_short_support"]+=len(group)
    for row in proposed:
        if group:
            previous=group[-1]
            same_note=round(69+12*np.log2(row["proposed_hz"]/440))==round(69+12*np.log2(previous["proposed_hz"]/440))
            if row["frame_index"]!=previous["frame_index"]+1 or not same_note:
                flush();group=[]
        group.append(row)
    flush()
    return PitchRecheckResult(accepted,{"method":"Independent pYIN verifies an existing neural candidate inside review windows",
        "config":asdict(config),"requested_window_count":len(requested),"requested_frames":int(mask.sum()),
        "processed_segments":[{"start_s":a,"end_s":b} for a,b in expanded],
        "context_audio_s":float(sum(b-a for a,b in expanded)),"proposal_frames":len(accepted),
        "rejections":reasons,"processing_s":perf_counter()-started,"gpu_used":False,
        "expected_pitch_used":False,"audio_estimates_unchanged":True,"automatic_replacement":False,
        "waveform_sha256":hashlib.sha256(wave.tobytes()).hexdigest(),
        "scope":"Experimental proposals; evaluate additions/losses before applying; not confidence probabilities"})


def recheck_file(path,analysis,review_windows,*,config=None):
    """Read the identical analyzed file/segment; reject accidental file mismatches."""
    path=Path(path).expanduser().resolve();source=analysis.summary.get("source",{})
    if not source.get("sha256") or digest(path)!=source["sha256"]:
        raise ValueError("Recheck file must match the analysis source hash; use recheck_samples for arrays")
    info=sf.info(path)
    if info.channels!=1:raise ValueError("Expected a separated mono recording")
    start=round(analysis.summary.get("source_start_s",0.)*info.samplerate)
    stop=start+round(analysis.summary["audio_duration_s"]*info.samplerate)
    samples,sr=sf.read(path,start=start,stop=stop,dtype="float32")
    return recheck_samples(samples,sr,analysis,review_windows,config=config)
