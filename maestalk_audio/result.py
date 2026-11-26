"""Versioned result object and JSON/CSV/optional PNG export."""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import csv
import json

SCHEMA_VERSION = "1.3"
CHROMA_NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")


def write_csv(path, rows):
    with Path(path).open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


@dataclass
class AnalysisResult:
    frames: list[dict]
    summary: dict
    _waveform: Any = field(default=None, repr=False)
    onsets: list[dict] | None = None
    acoustic_onsets: list[dict] | None = None
    pitch_boundaries: list[dict] | None = None

    def to_dict(self):
        """JSON-compatible dictionary: unavailable values are None, never NaN."""
        return {"schema_version": SCHEMA_VERSION, "summary": self.summary,
                "frames": self.frames, "onsets": self.onsets,
                "acoustic_onsets":self.acoustic_onsets,"pitch_boundaries":self.pitch_boundaries}

    def to_json(self, *, indent=2):
        return json.dumps(self.to_dict(), ensure_ascii=False, allow_nan=False, indent=indent)

    def save(self, output_dir, *, plot=False):
        """Write to a new/empty folder; preserve existing results on repeated runs."""
        if not self.frames:
            raise ValueError("No frames to export")
        output = Path(output_dir).expanduser().resolve()
        if output.exists() and (not output.is_dir() or any(output.iterdir())):
            raise FileExistsError(f"Choose a new output folder; existing results preserved: {output}")
        # Check strict serialization and optional dependency before creating files.
        payload = self.to_json()
        if plot:
            import matplotlib  # noqa: F401
        output.mkdir(parents=True, exist_ok=True)
        (output/"analysis.json").write_text(payload+"\n", encoding="utf-8")
        (output/"summary.json").write_text(json.dumps({"schema_version": SCHEMA_VERSION, **self.summary},
            ensure_ascii=False, allow_nan=False, indent=2)+"\n", encoding="utf-8")
        write_csv(output/"frames.csv", [{k:v for k,v in row.items() if k != "chroma"} for row in self.frames])
        changes=self.summary.get("pitch_repair",{}).get("changes")
        if changes is not None:
            with (output/"pitch_corrections.csv").open("w",newline="",encoding="utf-8-sig") as stream:
                keys=list(changes[0]) if changes else ["frame_index","time_s","original_hz","corrected_hz","candidate_source","reason"]
                writer=csv.DictWriter(stream,fieldnames=keys);writer.writeheader();writer.writerows(changes)
        write_csv(output/"chroma.csv", [{"time_s": row["time_s"], "source_time_s": row["source_time_s"],
            **dict(zip(CHROMA_NAMES, row["chroma"]))} for row in self.frames])
        if self.onsets is not None:
            with (output/"onsets.csv").open("w",newline="",encoding="utf-8-sig") as stream:
                keys=list(dict.fromkeys(k for row in self.onsets for k in row)) if self.onsets else ["time_s","peak_time_s","strength","status"]
                writer=csv.DictWriter(stream,fieldnames=keys);writer.writeheader();writer.writerows(self.onsets)
        if self.pitch_boundaries is not None:
            for name,rows in (("acoustic_onsets.csv",self.acoustic_onsets or []),("pitch_boundaries.csv",self.pitch_boundaries)):
                with (output/name).open("w",newline="",encoding="utf-8-sig") as stream:
                    keys=list(dict.fromkeys(k for row in rows for k in row)) if rows else ["time_s","sources","status"]
                    writer=csv.DictWriter(stream,fieldnames=keys);writer.writeheader();writer.writerows(rows)
        if plot:
            self._plot(output/"analysis.png")
        return output

    def _plot(self, path):
        import numpy as np
        from matplotlib.figure import Figure
        from matplotlib.backends.backend_agg import FigureCanvasAgg
        figure = Figure(figsize=(12, 9))
        FigureCanvasAgg(figure)
        axes = figure.subplots(4, 1, sharex=True)
        times = np.array([r["time_s"] for r in self.frames])
        if self._waveform is not None:
            axes[0].plot(*self._waveform, linewidth=.4)
            axes[0].set_ylabel("Raw waveform")
        else:
            axes[0].plot(times, [r["rms"] for r in self.frames])
            axes[0].set_ylabel("Raw RMS")
        hz = np.array([r["pitch_hz"] if r["pitch_hz"] is not None else np.nan for r in self.frames])
        axes[1].plot(times, hz, ".", markersize=2)
        if np.isfinite(hz).any():
            axes[1].set_yscale("log")
        axes[1].set_ylabel("F0 (Hz)")
        event_types=set()
        for event in self.onsets or []:
            added=event.get("status")=="pitch_boundary_candidate"
            label="Added pitch boundary" if added else "Acoustic onset candidate"
            axes[0].axvline(event["time_s"],color="teal" if added else "darkorange",alpha=.55,linewidth=.6,
                linestyle="--" if added else "-",label=label if label not in event_types else None)
            event_types.add(label)
        if event_types:axes[0].legend(loc="upper right",fontsize="small")
        axes[2].plot(times, [r["relative_to_performance_db"] for r in self.frames])
        axes[2].axhline(0, color="black", linestyle="--", linewidth=.6)
        axes[2].set_ylabel("Relative RMS (dB)")
        matrix = np.array([r["chroma"] for r in self.frames], dtype=float).T
        axes[3].imshow(matrix, origin="lower", aspect="auto",
                       extent=[0, self.summary["audio_duration_s"], -.5, 11.5])
        axes[3].set_yticks(range(12), CHROMA_NAMES)
        axes[3].set_ylabel("Chroma")
        axes[3].set_xlabel("Segment time (s)")
        figure.suptitle("Maestalk offline audio module "+self.summary.get("module_version", "unknown"))
        figure.tight_layout()
        figure.savefig(path, dpi=140)
