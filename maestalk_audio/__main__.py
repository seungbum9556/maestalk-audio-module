"""Command line interface: python -m maestalk_audio recording.wav --plot."""
from argparse import ArgumentParser
from datetime import datetime
from pathlib import Path
import sys
from . import AudioAnalyzer, AnalysisConfig, __version__
from .pitch import check_models


def main():
    parser = ArgumentParser(description="Maestalk CPU offline instrument analysis")
    parser.add_argument("audio", nargs="?")
    parser.add_argument("--output", "-o")
    parser.add_argument("--instrument", default="unspecified")
    parser.add_argument("--part-id", default="part1")
    parser.add_argument("--start", type=float, default=0.)
    parser.add_argument("--duration", type=float)
    parser.add_argument("--model-dir")
    parser.add_argument("--plot", action="store_true")
    parser.add_argument("--expanded-onsets", action="store_true",
        help="Add stable pitch-change boundaries for soft/fast passages; extra detections may increase")
    parser.add_argument("--no-pitch-repairs",action="store_true",help="Reproduce the unrefined SwiftF0+FCPE baseline")
    parser.add_argument("--check-models", action="store_true")
    parser.add_argument("--score", help="Optional monophonic MIDI or note-list JSON")
    parser.add_argument("--score-track", type=int)
    parser.add_argument("--score-channel", type=int)
    parser.add_argument("--partial-score", action="store_true", help="Audio contains only a contiguous excerpt of the score")
    parser.add_argument("--score-prefix", action="store_true", help="Recording starts at the beginning of the score and may end early")
    parser.add_argument("--recheck", action="store_true", help="Optional pYIN verification of neural pitch candidates in review windows")
    parser.add_argument("--version", action="version", version=__version__)
    args = parser.parse_args()
    try:
        if args.check_models:
            manifest = check_models(args.model_dir,include_verifier=not args.no_pitch_repairs)
            for name, item in manifest["models"].items():
                print(name, "SHA256 OK", item["sha256"])
            return 0
        if args.audio is None:
            parser.error("Provide a mono audio file, or use --check-models")
        score = None
        if args.score:
            from .score import ScoreReference
            if Path(args.score).suffix.lower() in (".mid", ".midi"):
                score = ScoreReference.from_midi(args.score, track_index=args.score_track, channel=args.score_channel)
            elif Path(args.score).suffix.lower() == ".json":
                score = ScoreReference.from_json(args.score)
            else:
                raise ValueError("--score expects a monophonic MIDI or note-list JSON file")
        elif args.score_track is not None or args.score_channel is not None or args.partial_score or args.score_prefix or args.recheck:
            raise ValueError("Score options require --score")
        if args.partial_score and args.score_prefix:raise ValueError("Choose --partial-score or --score-prefix")
        analyzer = AudioAnalyzer(AnalysisConfig(expanded_onsets=args.expanded_onsets,pitch_repairs=not args.no_pitch_repairs),model_dir=args.model_dir)
        result = analyzer.analyze_file(args.audio, instrument=args.instrument,
            part_id=args.part_id, start_s=args.start, duration_s=args.duration)
        output = Path(args.output) if args.output else Path("outputs")/(datetime.now().strftime("%Y%m%d_%H%M%S_%f")+"_"+Path(args.audio).stem)
        checked = None
        if score is not None:
            from .score import compare_with_score
            checked = compare_with_score(result, score, partial_score="prefix" if args.score_prefix else args.partial_score)
        rechecked = None
        if args.recheck:
            from .recheck import recheck_file,candidate_review_windows
            rechecked = recheck_file(args.audio,result,candidate_review_windows(result,checked))
        saved = result.save(output, plot=args.plot)
        if checked is not None:
            checked.save(saved/"score")
            print("Score context:", checked.summary["alignment_status"],
                  "review notes:", checked.summary["review_note_count"])
        if rechecked is not None:
            rechecked.save(saved/"recheck")
            print("Audio-supported pitch proposals:",len(rechecked.proposals),"(original F0 preserved)")
        print("Saved:", saved)
    except (ValueError, OSError, ImportError, RuntimeError) as error:
        parser.exit(2, f"Analysis failed: {error}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
