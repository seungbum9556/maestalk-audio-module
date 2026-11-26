# Maestalk 오디오 분석 모듈

Maestalk의 녹음 후 오디오 분석 파트를 함께 개발하는 저장소입니다. 현재 버전은 **0.4.1**, 기준 환경은 **Python 3.10 / Windows / CPU**입니다.

분리된 단일 악기 모노 녹음을 입력받아 시각별 주파수·음 이름/옥타브·음량 변화·Chroma·상태와 시작점 후보를 반환합니다. 바이올린과 첼로는 같은 모델·설정을 사용합니다.

|기능|현재 구성|
|---|---|
|음높이|사전학습 SwiftF0 0.3.0 + FCPE DDSP-200K|
|오음 교정|기존 후보와 파형 반복성 비교. 필요한 구간에 HarmoF0 검증을 추가하며 교정 전 값도 보존|
|음량|원본 RMS·dBFS·곡 내 기준 대비 상대 dB·증가/감소|
|Chroma|librosa 기반 12개 음급 특징. 옥타브 구분은 음높이 출력 사용|
|시작점|음향 변화 후보. `--expanded-onsets`로 안정된 음 변화 후보 추가 가능|
|악보 보조|선택 MIDI/음표 JSON 정렬. 실제 오디오 추정을 악보 음으로 덮어쓰지 않음|

현재는 단음 중심 녹음 후 분석입니다. 빠른 첼로·작은 음 누락·시작점 추가 검출·주석상 무음의 음 출력이 남아 있습니다. 마이크 스트리밍, 혼합음 분리, 화음 전사와 3입력 동시 처리는 아직 검증하지 않았습니다.

## 처음 내려받고 실행하기

Git과 Python 3.10이 설치된 Windows PowerShell에서 실행합니다.

```powershell
git clone https://github.com/seungbum9556/maestalk-audio-module.git
cd maestalk-audio-module
py -3.10 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements-module-cpu.txt
.\.venv\Scripts\python.exe -m pip install -e ".[plot,score]"
.\.venv\Scripts\python.exe -m maestalk_audio.fetch_models
.\.venv\Scripts\python.exe -m maestalk_audio --check-models
.\.venv\Scripts\python.exe -m maestalk_audio examples/test_scale.wav --plot
```

Git 없이 받으려면 저장소의 **Code → Download ZIP**을 누르고 압축을 풉니다. `pyproject.toml`이 있는 폴더를 열어 `py -3.10 -m venv .venv`부터 실행합니다. 파일을 수정하고 다시 공유하려면 Git clone을 권합니다.

의존성 설치와 최초 FCPE 가중치 복구에는 인터넷이 필요합니다. 작은 SwiftF0·HarmoF0 가중치는 저장소에 포함합니다. FCPE 약 43MB는 고정 출처에서 받고 SHA256을 검증합니다. 분석 중에는 모델을 자동 다운로드하지 않습니다. 가중치를 받은 뒤에는 계정·네트워크·GPU 없이 분석합니다.

VS Code 인터프리터는 이 폴더의 `.venv\Scripts\python.exe`를 선택합니다. `pip install -e` 설치이므로 `.py`를 수정하면 다음 실행에 반영됩니다. Linux는 경로를 `.venv/bin/python`으로 바꾸지만, 현재 실행 검산은 Windows에서 했습니다.

## 실행 결과 확인

위 합성 예제는 6초이며 1·2·3·4·5초에 C4·D4·E4·F4·G4가 시작합니다. `outputs/실행시각_test_scale/` 아래에 결과가 생성됩니다.

|파일|내용|
|---|---|
|`analysis.json`, `summary.json`|전체 결과, 설정, 가중치 해시, CPU 처리 시간|
|`frames.csv`|시각별 음높이·음 이름/옥타브·원래 추정·교정 근거·RMS·상대 dB|
|`pitch_corrections.csv`|교정 전후 후보와 파형 근거. 변경이 없으면 헤더만 저장|
|`chroma.csv`|12음급 특징|
|`onsets.csv`|시작점 후보. 확장 옵션은 원래/추가 후보 CSV도 저장|
|`analysis.png`|파형·음높이·RMS·Chroma 그래프|

자신의 분리 모노 녹음은 다음과 같이 넣습니다. `recordings/`와 `outputs/`는 Git에서 제외합니다.

```powershell
.\.venv\Scripts\python.exe -m maestalk_audio recordings/cello.wav --instrument cello --plot
.\.venv\Scripts\python.exe -m maestalk_audio examples/test_repeat.wav --score examples/test_repeat.mid --expanded-onsets --recheck --plot
```

교정 전 기준과 비교하려면 `--no-pitch-repairs`를 붙입니다. 확장 시작점은 누락을 줄이면서 추가 검출을 늘릴 수 있어 기본으로 켜지 않습니다. 상대 음량은 녹음된 신호 기준이며 실제 음압이나 악기 간 연주 강도가 아닙니다.

## 다른 모듈에서 호출

```python
from maestalk_audio import AudioAnalyzer

analyzer = AudioAnalyzer()  # 여러 파일을 같은 객체로 순서대로 분석
result = analyzer.analyze_file("examples/test_scale.wav", instrument="synthetic")
payload = result.to_dict()  # schema_version == "1.3"
print(payload["frames"][100])
```

NumPy 배열 입력, MIDI 트랙 선택, 반환 필드와 추가 예제는 [MODULE_README.md](MODULE_README.md)에 있습니다.

## 함께 수정할 때

|수정할 내용|파일|
|---|---|
|공개 API·설정·RMS·Chroma|`maestalk_audio/analysis.py`|
|음높이 모델 추론·결합|`maestalk_audio/pitch.py`|
|오음 교정·검증|`maestalk_audio/corrections.py`|
|시작점·음 변화 후보|`maestalk_audio/onsets.py`, `boundaries.py`|
|악보 정렬·시간 대응|`maestalk_audio/score.py`, `timing.py`|
|선택 pYIN 재검토|`maestalk_audio/recheck.py`|
|JSON·CSV·그래프|`maestalk_audio/result.py`|
|예제·회귀 검사|`examples/`, `module_tests/`|

수정 전에 최신 `main`에서 각자 작업 브랜치를 만듭니다. 원격 변경을 받기 전에는 작업 내용을 커밋하거나 별도로 보관합니다.

```powershell
git switch main
git pull --ff-only
git switch -c feature/my-change
# VS Code에서 수정한 뒤 검사
.\.venv\Scripts\python.exe -m unittest discover -s module_tests -v
git status
git add maestalk_audio module_tests
git diff --staged
git commit -m "Improve audio analysis"
git push -u origin feature/my-change
```

그다음 GitHub에서 해당 브랜치의 Pull Request를 만들어 변경 내용과 실제 검증 결과를 함께 확인합니다. 예제나 문서를 수정했다면 해당 파일도 명시해 `git add`합니다. 저장소에 올리려는 팀원은 소유자가 **Settings → Collaborators**에서 초대해야 합니다.

평가에서는 음높이 ±50cent, 누락·오음·옥타브 오류·주석상 무음 출력, 시작점 ±50ms의 일대일 대응·누락·추가를 함께 기록합니다. 프레임 정확도와 음표 전체 정확도는 다릅니다. 반환 필드를 바꾸면 문서와 계약 테스트도 함께 수정합니다.

## 현재 측정과 한계

0.4.1 교정은 합성 17조건·실제 47조건에서 정답 14프레임 추가, 기존 정답 손실 0, 누락·무음 출력 변화 0이었습니다. 같은 녹음의 크기·잡음 변형도 조건에 포함하며, 마지막 별도 6조건에는 교정도 손실도 없었습니다. 음높이 프레임 간격은 16ms입니다.

|구간|현재 음높이 일치율|정답 종류|
|---|---:|---|
|Jupiter 바이올린 0–30초|98.18%|연속 F0|
|Maria 첼로 0–30초|91.80%|연속 F0|
|MusicNet 2217 첼로|60.65%|명목 MIDI|
|MusicNet 2298 첼로|62.57%|명목 MIDI|

정답 유성 프레임 중 ±50cent 이내 비율이며 누락을 분모에 포함합니다. 무음 오검출은 이 정확도에 직접 반영되지 않습니다. 연속 F0와 명목 MIDI를 합친 성공률로 해석하지 않습니다. 한 곡·연주자의 결과로 악기 전체 성능을 일반화하지 않습니다. CPU 파일 처리 시간은 실제 마이크/화면 지연이 아닙니다.

전체 조건의 누락·오음·옥타브·무음 출력과 교정 전후 수치는 [64조건 CSV](docs/pitch_error_fixes_041.csv), 검산은 [검증 기록](docs/ERROR_FIX_VERIFICATION.json), 이전 시작점 측정은 [시작점 안내](docs/HARD_PASSAGES_040.md)에 있습니다. 실제 평가 녹음·주석과 과거 실험 전체는 이 저장소에 넣지 않았습니다.

## 모델 출처·사용 조건

SwiftF0와 HarmoF0의 출처·MIT 고지를 유지했습니다. **FCPE 추론 소스는 MIT, DDSP-200K 가중치는 CC BY-NC-SA 4.0**입니다. 사용 전 각 가중치 조건을 확인합니다. 고정 버전·URL·SHA256은 [models.json](maestalk_audio/assets/models.json), 원저작권과 수정 내역은 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)에 있습니다.
