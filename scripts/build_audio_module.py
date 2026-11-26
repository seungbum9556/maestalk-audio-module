"""Create a source-and-weights handoff ZIP using an explicit file allowlist."""
from pathlib import Path
from datetime import datetime, timezone, timedelta
import argparse
import hashlib
import json
import re
import shutil
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    value=hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda:stream.read(1024*1024),b""):
            value.update(block)
    return value.hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir",default="dist")
    parser.add_argument("--suffix",default="")
    args=parser.parse_args()
    if args.suffix and not re.fullmatch(r"[A-Za-z0-9_-]+",args.suffix):
        parser.error("suffix may only contain letters, digits, underscores and hyphens")
    version=re.search(r'^version = "([0-9.]+)"', (ROOT/"pyproject.toml").read_text(),re.M)[1]
    name="maestalk-audio-module-"+version+("_"+args.suffix if args.suffix else "")
    directory=Path(args.output_dir)
    if not directory.is_absolute():directory=ROOT/directory
    directory=directory.resolve();directory.relative_to(ROOT)
    stage=directory/name;archive=directory/(name+".zip")
    if stage.exists() or archive.exists():
        raise FileExistsError("Existing delivery preserved; use a new --suffix")
    files=[ROOT/p for p in ("pyproject.toml","requirements-module-cpu.txt","MODULE_README.md","THIRD_PARTY_NOTICES.md")]
    for folder in ("maestalk_audio","module_tests","examples","docs"):
        files.extend(p for p in (ROOT/folder).rglob("*") if p.is_file() and "__pycache__" not in p.parts
                     and (p.suffix in (".py",".json",".csv",".md",".wav",".mid",".onnx",".pt") or p.name=="LICENSE"))
    files.append(Path(__file__).resolve())
    for path in files:
        if not path.is_file():raise FileNotFoundError(path)
    # Only the explicitly named model assets are expected in the module tree.
    manifest=json.loads((ROOT/"maestalk_audio/assets/models.json").read_text(encoding="utf-8"))
    for item in manifest["models"].values():
        assert digest(ROOT/"maestalk_audio/assets"/item["filename"])==item["sha256"]
    stage.mkdir(parents=True)
    for path in sorted(set(files)):
        relative=path.relative_to(ROOT);target=stage/relative
        target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(path,target)
    (stage/".gitignore").write_text(".venv/\n.cache/\noutputs/\nrecordings/\ndist/\nbuild/\n*.egg-info/\n__pycache__/\n*.pyc\nmaestalk_audio/assets/fcpe_ddsp.pt\n",encoding="utf-8")
    entries={p.relative_to(stage).as_posix():{"size":p.stat().st_size,"sha256":digest(p)}
             for p in sorted(stage.rglob("*")) if p.is_file()}
    (stage/"HANDOFF_MANIFEST.json").write_text(json.dumps({"module_version":version,
        "created_at":datetime.now(timezone(timedelta(hours=9))).isoformat(),
        "contents":"Editable source, selected weights, tests, synthetic example and baseline metrics; no environment or real recordings",
        "files":entries},ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    with zipfile.ZipFile(archive,"w",compression=zipfile.ZIP_DEFLATED,compresslevel=6) as stream:
        for path in sorted(stage.rglob("*")):
            if path.is_file():stream.write(path,Path(name)/path.relative_to(stage))
    with zipfile.ZipFile(archive) as stream:
        assert stream.testzip() is None
    archive.with_suffix(".zip.sha256").write_text(digest(archive)+"  "+archive.name+"\n",encoding="ascii")
    print("Editable source:",stage)
    print("Send this ZIP:",archive)
    print("Archive bytes:",archive.stat().st_size)


if __name__=="__main__":main()
