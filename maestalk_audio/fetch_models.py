"""Restore omitted FCPE/verifier weights for Git clones; no downloads during analysis."""
from pathlib import Path
import json
import shutil
import subprocess
from urllib.request import urlopen, Request
from .pitch import ASSETS, check_models, digest


def main():
    manifest = json.loads((ASSETS/"models.json").read_text(encoding="utf-8"))
    for name in ("fcpe_ddsp","harmof0_verifier"):
        model=manifest["models"][name]
        target=ASSETS/model["filename"]
        if target.exists():
            if digest(target)!=model["sha256"]:
                raise ValueError(f"Existing model SHA256 mismatch: {target}")
            continue
        print(name,model["license"],model["source"])
        temporary=target.with_suffix(".pt.partial")
        if temporary.exists():
            raise FileExistsError(f"Inspect the existing unfinished download first: {temporary}")
        curl=shutil.which("curl.exe") or shutil.which("curl")
        if curl:
            subprocess.run([curl,"--fail","--location","--retry","2","--connect-timeout","20",
                "--max-time","300","--output",str(temporary),model["download_url"]],check=True)
        else:
            with urlopen(Request(model["download_url"],headers={"User-Agent":"Maestalk-audio-module"}),timeout=60) as response,temporary.open("xb") as stream:
                shutil.copyfileobj(response,stream)
        if digest(temporary)!=model["sha256"]:
            raise ValueError(f"SHA256 mismatch; original models preserved. Inspect {temporary}")
        temporary.replace(target)
    check_models(include_verifier=True)
    print("Model hashes OK")


if __name__ == "__main__":
    main()
