# Maestalk 오디오 분석 모듈 0.4.1 — 실행·공동 개발 안내

녹음한 **단일 악기 모노 오디오 → 음높이·음 이름/옥타브·상대 음량·Chroma**를 반환하는 Python 모듈이다. 팀원이 소스를 수정하며 함께 개발할 수 있는 전달본이다. Python 3.10, CPU를 기준으로 제공한다.

0.4.1은 **기존 음높이 후보 중 파형 근거가 더 강한 후보를 고르는 보수적인 오음 교정**을 기본 적용한다. SwiftF0 + FCPE는 유지하며, 일부 불일치 구간에는 HarmoF0를 검증용으로만 사용한다. HarmoF0의 주파수를 그대로 출력하거나 악보 음으로 바꾸지 않는다. 교정 전 음높이는 별도 필드에 남긴다. 64조건에서 정답 14프레임 추가, 기존 정답 손실 0, 누락·무음 오검출 변화 0이었다. **14개 음표를 고쳤다는 뜻은 아니다.** 빠른 첼로의 큰 오류는 남아 있다. [조건별 결과](docs/pitch_error_fixes_041.csv), [실제 검산 기록](docs/ERROR_FIX_VERIFICATION.json)을 따른다.

0.4.0의 선택 시작점 확장 `--expanded-onsets`와 0.3.0의 악보 시간 정렬·반복음·pYIN 재검토는 유지한다. [시작점 옵션의 이전 측정](docs/HARD_PASSAGES_040.md), [악보·재검토 안내](docs/OFFLINE_030.md)는 해당 버전의 기록이다. 이번 교정은 시작점·RMS·Chroma를 바꾸지 않는다. 과거 ZIP은 보존한다.

## 현재 제공 범위

|기능|구현/상태|
|---|---|
|음높이|사전학습 SwiftF0 0.3.0 + FCPE DDSP-200K, 바이올린·첼로 동일 설정. 교정은 기존 후보·파형 반복성과 선택 HarmoF0 검증에 근거|
|음량|원본 신호 RMS·dBFS, 곡 내 에너지 구간 평균 대비 상대dB, 약96ms 전 대비 변화|
|Chroma|librosa STFT 기반12차원, 옥타브 정보 없음|
|상태/점수|추정 음높이 없음·모델 간 불일치 표시, 각 모델 자체 점수|
|악보 보조|선택 기능. MIDI/음표JSON의 음 순서·박자·음 길이와 실제 오디오 구간 정렬, 불일치·미관측·추가·불확실 구간 표시|
|시작점|음향 변화 후보. 선택 `--expanded-onsets`는 두 모델의 안정된 음 변화 후보를 추가. 누락 감소와 추가 오검출 증가를 함께 평가|
|음높이 재검토|선택 `--recheck`. 독립 pYIN이 지지하는 기존 신경망 후보를 제안. 악보 음으로 치환하지 않으며 원본 F0는 유지|
|입력|녹음 파일 또는 NumPy 모노 배열. 스트리밍/마이크/혼합음 분리/악기 자동 분류/화음 전사/3입력 동시 처리는 미구현|

현재의 실행 가능한 개발 버전이며 성능 완성본은 아니다. 빠른 첼로 등 오류가 남아 있다. 입력은 파트별로 분리된 단음 중심, 공통 음역50–2000Hz이며 FCPE 자체 상한은1975.5Hz다. `instrument`는 기록용 메타데이터다. 악기명으로 다른 모델을 고르거나 정답을 제한하지 않는다.

## 1. 전달받은 팀원: Windows 설치

저장소를 clone하거나 ZIP을 모두 풀고 `pyproject.toml`과 이 문서가 있는 폴더를 VS Code로 연다. **Python 3.10**이 설치되어 있어야 한다. PowerShell에서 다음을 순서대로 실행한다. 가상환경 활성화 명령은 필요 없다.

```powershell
py -3.10 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements-module-cpu.txt
.\.venv\Scripts\python.exe -m pip install -e ".[plot,score]"
.\.venv\Scripts\python.exe -m maestalk_audio.fetch_models
.\.venv\Scripts\python.exe -m maestalk_audio --check-models
```

앞의 설치에는 패키지 다운로드용 인터넷이 필요하다. Git 저장소에는 작은 SwiftF0와 HarmoF0 가중치가 있고 FCPE는 `fetch_models` 명령으로 복구한다. 기존 모듈 전달 ZIP에는 세 가중치가 모두 들어 있다. 복구 명령은 기존 파일도 SHA256을 검사하며, 필요한 가중치가 준비된 뒤 분석 중에는 다운로드·계정·GPU가 필요 없다. 추가 Python 의존성은 없다. CPU requirements를 먼저 설치해 CUDA 패키지 설치를 피한다. VS Code 인터프리터도 이 폴더의 `.venv\Scripts\python.exe`로 선택한다.

첫 분석에는 라이브러리 초기화·Numba 컴파일이 추가될 수 있어 다음 실행보다 오래 걸릴 수 있다. 일반 사용 환경과 별개로 파일시스템이 제한된 실행기에서는 쓰기 가능한 `NUMBA_CACHE_DIR`·`MPLCONFIGDIR`를 지정해야 한다.

Linux에서는 `python3.10 -m venv .venv`로 만들고 위의 Python 경로를 `.venv/bin/python`으로 바꾼다. 실제 검산은 Windows/Python3.10에서 했으며 Linux 실행은 아직 검증하지 않았다.

## 2. 바로 실행하기

```powershell
.\.venv\Scripts\python.exe -m maestalk_audio examples/test_scale.wav --instrument synthetic --plot
.\.venv\Scripts\python.exe examples/use_audio_module.py
.\.venv\Scripts\python.exe -m unittest discover -s module_tests -v
```

첫 명령은 `outputs/실행시각_test_scale/`에 다음 파일을 만든다. 기존 폴더에는 덮어쓰지 않는다.

- `analysis.json`: 다른 Python/서버 모듈에 전달할 전체 결과. 표준 JSON이며 NaN/Infinity 없이 미확인 값은`null`이다.
- `frames.csv`: 시각별 음높이·음 이름/옥타브·점수·RMS·상대dB.
- `pitch_corrections.csv`: 교정한 시각·원래 값·선택한 값·선택 모델·파형 근거. 교정이 없으면 헤더만 저장.
- `chroma.csv`: C~B 순서12개 특징.
- `onsets.csv`: 시작점 후보 시각·근거·강도. 후보가 없으면 헤더만 저장.
- `acoustic_onsets.csv`, `pitch_boundaries.csv`: `--expanded-onsets`일 때 기존 검출과 음 변화 후보를 구분해 저장.
- `summary.json`: 실제 분석 구간·설정·가중치 해시·처리 시간·기능 상태·한계.
- `analysis.png`: `--plot`일 때 파형·음높이·상대RMS·Chroma.

예제는1·2·3·4·5초에 C4/D4/E4/F4/G4가 시작되는6초 합성음이다. 음 시작/끝 부근의 불안정 구간도 함께 볼 수 있다. 파형 위 주황색 선이 시작점 후보이며 실제 악기에서는 누락·추가 검출을 따로 확인해야 한다.

교정은 기본으로 켜져 있다. 이전 음높이 결과와 비교하려면 같은 명령에 `--no-pitch-repairs`를 붙인다. Python에서는 `AudioAnalyzer(AnalysisConfig(pitch_repairs=False))`를 쓴다. 교정이 의심스러운 프레임에만 HarmoF0 CPU 추론을 추가하므로 처리 시간이 늘 수 있다. `summary.json`의 `pitch_repair`·`timing.pitch_repair_processing_s`에 적용 기준·변경 목록·처리 시간을 기록한다. 이 시간은 마이크부터 화면까지의 지연이 아니다.

악보·반복음·음높이 재검토까지 한 번에 확인하는 예제는 다음과 같다. C4·C4·C4·D4를 연주하며 MIDI의 기준 템포와 실제 오디오 속도는 다르다.

```powershell
.\.venv\Scripts\python.exe -m maestalk_audio examples/test_repeat.wav --score examples/test_repeat.mid --recheck --plot
.\.venv\Scripts\python.exe -m maestalk_audio examples/test_repeat.wav --score examples/test_repeat.mid --expanded-onsets --plot
.\.venv\Scripts\python.exe examples/use_score_context.py
```

추가로 `score/score_check.json`, `score/score_notes.csv`, `recheck/pitch_recheck.json`, `recheck/pitch_proposals.csv`가 생성된다. 같은 음의 재시작은 실제 음향 근거가 있을 때만 구분한다. 재검토 후보는 자동 적용되지 않는다.

자신의 녹음은 다음처럼 넣는다. 상대 경로는 **명령을 실행하는 폴더 기준**이다. 스테레오는 임의로 섞지 않고 오류로 돌려준다. 최대3개의 분리 파트라면 각 파일을 같은 객체로 순서대로 분석할 수 있지만 동시3입력 성능은 아직 평가하지 않았다.

```powershell
.\.venv\Scripts\python.exe -m maestalk_audio "recordings/cello.wav" --instrument cello --part-id cello1 --start 0 --duration 30 --output outputs/cello_first30 --plot
```

## 3. 다른 코드에서 호출하는 방법

```python
from maestalk_audio import AudioAnalyzer

analyzer = AudioAnalyzer()  # 최초 분석 때 모델 로드; 다음 파일에도 재사용
result = analyzer.analyze_file(
    "recordings/cello.wav",
    instrument="cello",
    part_id="cello1",
    start_s=0.0,
    duration_s=30.0,  # 생략하면 파일 끝까지
)

payload = result.to_dict()  # 파일 저장 없이 다른 모듈이 직접 받음
print(payload["schema_version"])  # "1.3"
for frame in payload["frames"]:
    if frame["pitch_hz"] is not None:
        print(frame["time_s"], frame["note"], frame["relative_to_performance_db"])

result.save("outputs/cello_run1", plot=True)  # 저장은 선택
```

이미 받은 배열을 넣을 수도 있다. **8–192kHz 정수 샘플링 주파수·최소0.1초·1차원·유한한[-1,1] 신호**를 받는다. PCM int16 정수를 그대로 넣지 말고 float32로 읽는다. 오디오나 모델을 강제 정규화해 원래 RMS를 바꾸지 않는다.

```python
import soundfile as sf
samples, sample_rate = sf.read("recordings/violin.wav", dtype="float32")
result = analyzer.analyze_samples(samples, sample_rate, instrument="violin", part_id="violin1")
json_text = result.to_json()  # 표준 JSON 문자열
```

같은 분석기 객체의 동시 호출은 내부에서 순서대로 처리한다. 객체를 파일마다 새로 만들면 모델 로드 비용이 반복된다. PyTorch 스레드 수는 기본8이며 프로세스 전체 설정이다. 다른 PyTorch 기능과 함께 쓸 때 기존 스레드 수를 유지하려면 `AnalysisConfig(torch_threads=None)`을 전달한다. GPU 가시성 환경변수는 바꾸지 않는다. 실제 모델/텐서는 CPU에 둔다.

## 4. 반환값 계약 — schema_version 1.3

최상위 키는 `schema_version`, `summary`, `frames`, `onsets`, `acoustic_onsets`, `pitch_boundaries`다. `frames`는 기본16ms 격자다. `onsets`는 선택한 모드의 후보이고 `acoustic_onsets`는 기존 검출 결과다. `pitch_boundaries`는 확장 기능을 끄면null, 켜면 추가 음 변화 후보 목록이다. 자세한 차이와 CSV는 새 안내를 따른다.

|frame 필드|뜻|
|---|---|
|`time_s`|분석 구간의 시작을0초로 둔 시각|
|`source_time_s`|원본 파일의 실제 시작 시각을 더한 시각|
|`part_id`, `instrument`|호출자가 지정한 파트/악기 정보|
|`pitch_hz`, `note`, `midi`|추정 주파수, C4 같은 이름, MIDI 번호. 추정값 없음은 모두`null`|
|`raw_pitch_hz`, `raw_pitch_source`|이번 교정 전 Swift/FCPE 결합값과 선택 모델. 교정을 꺼도 보존|
|`pitch_repair_reason`|교정 근거. 바꾸지 않은 프레임은`null`. 모델 자체 점수는 교정의 정답 확률이 아님|
|`pitch_state`|`voiced` / `unvoiced` / `model_disagreement`|
|`pitch_source`|`swift` / `fcpe_ddsp` / `none`|
|`source_score`|선택 모델의 자체 점수. 정답 확률·전체 정확도가 아님|
|`swift_hz`, `swift_score`, `fcpe_hz`, `fcpe_score`|결합 이전 두 모델의 값. 추정값이 없으면`null`|
|`rms`, `rms_dbfs`|정규화 전 원본 신호의100ms 창 RMS와dBFS. 로그 바닥은−200dBFS|
|`relative_to_performance_db`|전체 녹음 내 선택된 에너지 구간의 평균제곱 크기를0dB로 둔 상대값. 무음처럼 기준을 만들 수 없으면`null`|
|`volume_change_db`, `volume_direction`|약96ms 전 대비 변화와`up`/`down`/`steady`/`unknown`. ±1dB 기준, 비교할 과거가 없으면`null`/`unknown`|
|`chroma`|C,C#,D,D#,E,F,F#,G,G#,A,A#,B 순서12개 값. 옥타브 구분에 쓰지 않음|

`unvoiced`는 음높이를 채택하지 않았다는 상태다. 조용한 실제 음과 잡음을 완벽히 구분했다는 보장은 없다. `model_disagreement`는 두 모델이50cent보다 다르다는 뜻이며 틀린 모델을 확정한 상태는 아니다. `onsets: []`는 검출을 수행했지만 후보가 없다는 뜻이다. `AnalysisConfig(compute_onsets=False)`로 끄거나 과거 결과를 불러온 경우의 `onsets: null`과 구분한다. 후보 `strength`와 모델 점수는 정답 확률이 아니다.

곡 기준 상대음량은 전체 입력 게인의 일정한 배율 변화에 영향을 덜 받지만, 마이크 거리 변화·AGC·일정 잡음의 영향을 해결한 값은 아니다. 실제 음압/SPL·악기 간 동일한 연주 강도로 해석하지 않는다. Chroma의 프레임별 정규화도 잡음을 음악으로 바꾸는 기능이 아니다.

## 5. 팀원이 수정할 위치와 개발 절차

|파일|담당 역할|
|---|---|
|`maestalk_audio/analysis.py`|공개 API, 설정, 원본 RMS/상대음량/Chroma, 입력 검증|
|`maestalk_audio/pitch.py`|두 모델 CPU 추론·결합·시각 정렬·가중치 검증|
|`maestalk_audio/corrections.py`|기존 후보의 오음 교정, 64/128ms 파형 반복성 검사, 필요 시 HarmoF0 CPU 검증|
|`maestalk_audio/result.py`|반환 계약, JSON/CSV/PNG 출력|
|`maestalk_audio/onsets.py`|악보와 독립적인 음향 시작점·재시작 후보|
|`maestalk_audio/boundaries.py`|두 모델이 지지하는 안정된 음 변화와 기존 후보 결합. 선택 옵션|
|`maestalk_audio/score.py`|선택 악보 입력, 순서·시간 정렬과 재확인표. 실제F0 보존|
|`maestalk_audio/timing.py`|실제 음향 근거로 반복음 구분, 박자→연주 시각 대응, 이웃 기준 시간차|
|`maestalk_audio/recheck.py`|음 시작·끝·불확실 구간 선택, pYIN으로 기존 신경망 후보 재검토|
|`maestalk_audio/__main__.py`|파일 분석용 CLI|
|`maestalk_audio/assets/models.json`|고정 모델 출처·버전·SHA256·사용 조건|
|`maestalk_audio/_vendor/`|필요한 외부 추론 코드와 원저작권. 일반 기능 수정은 위 파일에서 진행|
|`module_tests/`|입력/출력 계약·상대음량·실제 모델 합성음/무음 검사|
|`examples/use_audio_module.py`, `examples/use_score_context.py`|기본 분석·악보 보조 API 호출 예제|
|`docs/BASELINE.md`, `docs/baseline_metrics.csv`|선정 당시 실제 성능·한계. 개선 후에도 이전 수치를 보존|

`pip install -e .`로 설치했으므로 소스를 수정하면 재설치 없이 다음 실행에 반영된다. 각자 브랜치에서 담당 파일을 수정하고, 위 테스트와 같은 녹음 비교를 통과한 뒤 합친다. API 필드를 변경할 때는 이 표·예제·계약 테스트를 함께 수정한다. 의미나 필드를 깨는 변경은 `schema_version`을 올린다.

모델·설정 변경에는 정답 음높이±50cent, 누락/오음/옥타브/무음 오검출, 시작점은 별도 누락/추가/시각 오차를 기록한다. 한 곡으로 임계값을 맞추면 그 곡은 개발 자료가 되므로 새 자료에서 다시 검증한다. 기존 측정값을 새 코드의 성능으로 복사하지 않는다.

공동 개발 저장소는 `https://github.com/seungbum9556/maestalk-audio-module`이다. 가상환경/개인 녹음/실행 결과는 커밋하지 않는다. 기존 전달 ZIP에는 가중치가 있지만 Git에서는 큰 FCPE 가중치를 제외한다. 새로 clone한 사람은 모델 복구 명령을1회 실행한다. 브랜치와 Pull Request 작업 순서는 [README.md](README.md)를 따른다.

```powershell
.\.venv\Scripts\python.exe -m maestalk_audio.fetch_models
.\.venv\Scripts\python.exe -m maestalk_audio --check-models
```

## 6. 성능과 사용 조건

현재 0.4.1은 합성 17조건과 실제 47조건, 총 64조건을 검사했다. 같은 녹음의 크기·잡음 변형도 별도 조건이므로 64개의 서로 다른 곡은 아니다. ±50cent 기준 정답 14프레임 추가, 기존 정답 손실 0, 원래 누락·무음 오검출 변화 0이었다. 마지막에 별도로 확인한 6조건은 새 교정도 손실도 없었다. 모듈 61개와 기존 174개, 총 235테스트가 통과했다. 신경망을 새로 학습하거나 악기별 설정을 나누지 않았다.

교정에는 원래·대체 후보의 안정성, 모델 점수, 64/128ms 두 파형 창의 반복성 차이를 요구한다. 순수음에 잘못된 절반 주파수 후보를 준 경우와 원래 추정이 ±40cent 벗어난 경우를 반례로 검사했다. 누락을 채우는 실험은 추가 무음 오검출 2프레임, 시작 시각을 당기는 실험은 기존에 맞던 시작점 6개 손실이 생겨 제외했다. **원래 누락과 시작점 오검출이 해결된 버전은 아니다.** 빠른 MusicNet 첼로의 16ms 명목 MIDI 일치율은 60.65%·62.57%로 유지됐다. 아래는 이전 버전과 모델 선정 당시 기록이다.

이전 0.4.0은 합성17·기존 실제11·후반의 빠른 실제 구간12조건을 확인했다. 새 기능은 시작점 후보 복원이며 음높이 추정은 변경하지 않았다. 실제23조건 중21조건에서 시작점F1이 개선됐고1조건은 같고1조건은 조금 악화됐다. 모듈51+기존174=225테스트가 통과했다. [당시 지표·파일/구간·실험과 반례](docs/HARD_PASSAGES_040.md)를 따른다.

이전 0.3.0은 합성17조건과 실제11조건에서 검증했다. 기본 분석 F0는 이전 선정 모델과 같고, 별도 재검토 후보를 평가상 적용한 경우 실제11조건 합계 정답11프레임 추가·기존 정답 손실0·무음 오검출 증가0이었다. Maria·빠른 MusicNet 첼로의 음높이 개선은 없었다. 음표 위치를 더 잘 찾은 결과를 음높이 정확도 향상으로 바꿔 말하지 않는다. [당시16ms 지표·시작점 누락/추가·검증 범위](docs/OFFLINE_030.md), [28조건 CSV](docs/offline_030_checks.csv)를 본다. 모듈44개 테스트가 통과했다.

아래 표는 **이전 모델 선정 당시의64ms 평가 기록**이다. 현재16ms 지표와 직접 빼서 개선량으로 사용하지 않는다.

9개 실제 녹음×원본/−12dB/SNR10의27조건으로 선정했다. 기존 CREPE+Swift와 같은 파형·같은 채점 시각의 결과는 아래와 같다. 평가 시각은64ms 격자로 모듈 출력16ms와 구분한다. 자세한27조건은`docs/baseline_metrics.csv`에 있다.

|녹음|정답 종류|기존 → 선정|
|---|---|---|
|Maria 첼로|연속F0|90.26 → 92.86%|
|Schubert 첼로|정렬MIDI|93.17 → 97.02%|
|MusicNet2217 첼로, 빠른 전환|정렬MIDI|57.52 → 61.66%|
|MusicNet2298 첼로, 빠른 전환|정렬MIDI|57.74 → 60.51%|
|Jupiter 바이올린|연속F0|98.45 → 98.19%|

정답 유성 프레임 중±50cent 이내 비율이며 누락도 분모에 포함한다. 명목MIDI와 연속F0를 같은 정확도로 합치지 않는다. 공통20조건에서 정답+222/기존정답 손실75프레임이 있었고, 작은 Schubert C3의 완전 누락은 정답을 얻었다. 빠른 첼로는 아직 개선이 필요하다. 기존 자료 재검증이므로 새로운 곡·연주자에서의 성능 보장은 아니다. 포장은 정확도 개선 작업과 구분한다.

FCPE 추론 코드와 SwiftF0는MIT이다. **FCPE DDSP-200K 가중치는CC BY-NC-SA4.0**이며 모델의 출처·조건을 유지해야 한다. HarmoF0 검증 소스·체크포인트는 원저장소의 MIT 고지와 출처를 함께 보존했다. 자세한 출처와 원본/수정 사항은`THIRD_PARTY_NOTICES.md`, 원저작권 전문은각 vendor의`LICENSE`에 있다. 기본 두 가중치와 검증 가중치를 포함하며 개인 녹음·공개 실제 악기 데이터 전체·과거 실험·기존 Python 환경은 전달본에 포함하지 않는다.
