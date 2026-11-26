"""Offline acoustic onset candidates, independent of any reference score."""
from dataclasses import asdict, dataclass
import math
import numpy as np
from scipy.ndimage import maximum_filter1d, median_filter
from scipy.signal import find_peaks, resample_poly


@dataclass(frozen=True)
class OnsetConfig:
    sample_rate: int = 16000
    window_samples: int = 1024
    hop_samples: int = 128
    rms_window_samples: int = 512
    mel_bins: int = 64
    minimum_separation_s: float = .064
    maximum_backtrack_s: float = .080
    flux_mad_multiplier: float = 3.
    minimum_flux_prominence: float = .25
    attack_threshold_db: float = 3.
    minimum_energy_change_db: float = 1.5
    rearticulation_dip_db: float = 2.
    pitch_change_cents: float = 75.
    pitch_stability_s: float = .048
    pitch_flux_search_s: float = .080

    def __post_init__(self):
        for name,value in asdict(self).items():
            if not math.isfinite(value) or value<=0:
                raise ValueError("Onset setting must be positive and finite: "+name)
        for name in ("sample_rate","window_samples","hop_samples","rms_window_samples","mel_bins"):
            if isinstance(getattr(self,name),bool) or not isinstance(getattr(self,name),int):
                raise ValueError("Onset size/rate must be an integer: "+name)
        if self.sample_rate<8000 or self.window_samples<128 or self.hop_samples>self.window_samples:
            raise ValueError("Invalid onset frame configuration")


def detect_onsets(samples, sample_rate, *, pitch_times=None, pitch_hz=None, config=None):
    """Return measured candidates and reproducible settings, never expected score starts.

    Time estimates use signal backtracking, not an annotation-fitted time shift.
    Energy/flux-supported rearticulations are distinguished from pitch changes.
    """
    config=config or OnsetConfig()
    wave=np.asarray(samples,np.float32)
    if wave.ndim!=1 or not len(wave) or not np.isfinite(wave).all():
        raise ValueError("Expected nonempty finite mono audio for onset analysis")
    if isinstance(sample_rate,bool) or not isinstance(sample_rate,(int,np.integer)) or sample_rate<=0:
        raise ValueError("Invalid onset input sample rate")
    settings={"method":"Log-mel spectral novelty + energy attack + optional observed pitch transitions",
        "config":asdict(config),"uses_score":False,"score_is_probability":False,
        "resolution_s":config.hop_samples/config.sample_rate,
        "time_definition":"Segment-relative; backtracked from acoustic feature peaks",
        "timing_scope":"Offline estimate, not microphone/UI latency"}
    peak=float(np.max(np.abs(wave)))
    if peak<1e-12:
        return [],{**settings,"status":"digital_silence"}
    sr=config.sample_rate
    if sample_rate!=sr:
        divisor=math.gcd(int(sample_rate),sr)
        wave=resample_poly(wave,sr//divisor,int(sample_rate)//divisor).astype(np.float32)
    # Feature normalization is confined to onset detection; raw RMS is untouched.
    wave=wave/float(np.max(np.abs(wave)))
    import librosa
    hop=config.hop_samples; dt=hop/sr
    spectrum=abs(librosa.stft(wave,n_fft=config.window_samples,hop_length=hop,
                              win_length=config.window_samples,center=True,pad_mode="constant"))**2
    mel=librosa.feature.melspectrogram(S=spectrum,sr=sr,n_mels=config.mel_bins,fmin=40.,fmax=min(6000.,sr/2))
    logmel=10*np.log10(np.maximum(mel/max(float(mel.max()),1e-20),1e-8))
    previous=maximum_filter1d(logmel,size=3,axis=0,mode="nearest")
    flux=np.r_[0.,np.maximum(0.,logmel[:,1:]-previous[:,:-1]).mean(axis=0)]
    rms=librosa.feature.rms(y=wave,frame_length=config.rms_window_samples,hop_length=hop,
                            center=True,pad_mode="constant")[0]
    size=min(len(flux),len(rms));flux=flux[:size];rms=rms[:size]
    energy=20*np.log10(np.maximum(rms,max(float(rms.max())*1e-6,1e-12)))
    energy=median_filter(energy,size=3,mode="nearest")
    lag=max(1,round(.016/dt))
    rise=np.maximum(0.,energy-np.r_[np.repeat(energy[0],lag),energy[:-lag]])
    floor,top=np.percentile(energy,[10,95])
    active_floor=max(top-40.,floor+8.) if top-floor>=18. else top-40.
    median=float(np.median(flux));mad=float(1.4826*np.median(abs(flux-median)))
    threshold=median+max(config.minimum_flux_prominence,config.flux_mad_multiplier*mad)
    prominence=max(config.minimum_flux_prominence,2*mad)
    peaks,properties=find_peaks(flux,height=threshold,prominence=prominence,
                                distance=max(1,round(.032/dt)))
    by_peak={int(p):{"prominence":float(v),"sources":set()} for p,v in zip(peaks,properties["prominences"])}
    back=max(1,round(config.maximum_backtrack_s/dt))
    def dip_evidence(p):
        lo=max(0,p-round(.016/dt));hi=min(size,p+round(.048/dt)+1)
        valley=lo+int(np.argmin(energy[lo:hi]))
        side=max(1,round(.032/dt))
        if valley-side<0 or valley+side>=size:return valley,0.
        dip=float(min(energy[valley-side],energy[valley+side])-energy[valley])
        return valley,max(0.,dip)
    for p,item in by_peak.items():
        left=max(0,p-back);right=min(size,p+max(3,round(config.window_samples/sr/2/dt)+1))
        gain=float(np.max(energy[p:right])-np.min(energy[left:p+1]))
        if gain>=config.minimum_energy_change_db:
            item["sources"].add("spectral_energy_attack")
        _,dip=dip_evidence(p)
        if dip>=config.rearticulation_dip_db:
            item["sources"].add("energy_dip_recovery")
    attack_peaks,_=find_peaks(rise,height=config.attack_threshold_db,prominence=1.,
                              distance=max(1,round(.032/dt)))
    for p in attack_peaks:
        nearest=min(by_peak,key=lambda v:abs(v-p)) if by_peak else None
        if nearest is not None and abs(nearest-p)*dt<=.040:
            by_peak[nearest]["sources"].add("energy_attack")
        elif energy[p]>=active_floor:
            by_peak[int(p)]={"prominence":float(flux[p]),"sources":{"energy_attack"}}
    if pitch_times is not None and pitch_hz is not None:
        pt=np.asarray(pitch_times,float);ph=np.asarray(pitch_hz,float)
        if len(pt)!=len(ph) or (len(pt)>1 and np.any(np.diff(pt)<=0)):
            raise ValueError("Invalid observed pitch timestamps")
        window=config.pitch_stability_s
        for i in range(1,len(pt)):
            left=int(np.searchsorted(pt,pt[i]-window))
            right=int(np.searchsorted(pt,pt[i]+window))
            before=ph[left:i]
            after=ph[i:right]
            before=before[np.isfinite(before)&(before>0)];after=after[np.isfinite(after)&(after>0)]
            if len(before)<2 or len(after)<2:continue
            a,b=np.median(before),np.median(after)
            if abs(1200*np.log2(b/a))<config.pitch_change_cents:continue
            options=[p for p in by_peak if abs(p*dt-pt[i])<=config.pitch_flux_search_s and flux[p]>=threshold]
            if options:
                p=min(options,key=lambda v:abs(v*dt-pt[i]))
                by_peak[p]["sources"].add("observed_pitch_change")
    events=[];duration=len(samples)/sample_rate
    for p,item in sorted(by_peak.items()):
        right=min(size,p+max(3,round(config.window_samples/sr/2/dt)+1))
        if not item["sources"] or p*dt<.016 or p*dt>=duration-.008 or np.max(energy[p:right])<active_floor:
            continue
        left=max(0,p-back)
        valley=float(np.min(energy[left:p+1]));post=float(np.max(energy[p:right]))
        change=post-valley
        dip_frame,dip=dip_evidence(p)
        from_quiet=change>=6. and valley<=top-30.
        rearticulation=from_quiet or dip>=config.rearticulation_dip_db
        if dip>=config.rearticulation_dip_db and change<6.:
            onset=dip_frame
        elif change>=6.:
            local_min=left+int(np.argmin(energy[left:p+1]))
            crossings=np.flatnonzero(energy[local_min:p+1]>=post-12.)
            onset=int(local_min+crossings[0]) if len(crossings) else p
        else:
            start=max(left,p-round(.048/dt));floor_flux=float(np.median(flux[left:max(left+1,start)]))
            crossings=np.flatnonzero(flux[start:p+1]>=floor_flux+.2*(flux[p]-floor_flux))
            onset=int(start+crossings[0]) if len(crossings) else p
        confidence=float(min(1.,max(0.,(flux[p]-median)/(threshold+prominence+1e-8))*.5+min(change/12.,1.)*.5))
        event={"time_s":float(onset*dt),"peak_time_s":float(p*dt),"strength":confidence,
               "spectral_novelty":float(flux[p]),"energy_change_db":float(change),
               "energy_dip_db":float(dip),
               "rearticulation_evidence":bool(rearticulation),"sources":"+".join(sorted(item["sources"])),
               "time_uncertainty_s":config.window_samples/sr/2,"status":"acoustic_candidate"}
        events.append(event)
    # Suppress duplicate candidates by peak strength, independently of score tempo.
    accepted=[]
    for event in sorted(events,key=lambda e:e["strength"],reverse=True):
        if all(abs(event["time_s"]-other["time_s"])>=config.minimum_separation_s for other in accepted):
            accepted.append(event)
    accepted.sort(key=lambda e:e["time_s"])
    return accepted,{**settings,"status":"computed_candidates","flux_threshold":threshold,
        "flux_median":median,"flux_mad":mad,"active_floor_db_relative":float(active_floor),
        "candidate_count":len(accepted)}
