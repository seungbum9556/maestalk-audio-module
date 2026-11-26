# 악보·MIDI를 보조 입력으로 쓰는 초기 기능 (0.2.0)

이 문서는0.2.0 당시 기록이다. 현재0.3.0의 시작점·박자/길이 정렬·음높이 재검토와 실행법은 [OFFLINE_030.md](OFFLINE_030.md)를 따른다. 아래의 미구현 항목은 당시 범위를 뜻한다.

사용자가 제공하는 것은 곡의 음표와 박자 정보다. 곡 정보를 이용해 연주 위치와 예상음을 추정하고, 독립적인 오디오 추정과 다른 부분을 재확인 대상으로 남긴다. 현재 구현은 **음 순서 정렬의 기초 버전**이며 음높이 모델의 정답률 향상을 달성했다고 주장하지 않는다.

악보와 연주를 함께 분석하는 접근은 [score-informed transcription 연구](https://webspace.eecs.qmul.ac.uk/s.e.dixon/pub/2012/Benetos-Klapuri-Dixon-EUSIPCO2012.pdf)에서 사용한다. [연주 오류·반복/건너뛰기를 고려한 악보 추적](https://arxiv.org/abs/1512.07748), [RUMAA의 악보 정렬·전사·오류 검출](https://arxiv.org/abs/2507.12175)도 관련 접근이다. 우리 구현은 이 논문들을 재현한 모델이 아니며, 논문의 피아노/클라리넷 성능을 우리 현악기 성능으로 옮기지 않는다.

## 구현한 흐름

1. 기존 SwiftF0+FCPE로 실제 오디오를 분석한다. `pitch_hz`·점수·RMS·Chroma를 보존한다.
2. MIDI의 파트/채널을 선택하고 음표·시작박·길이를 읽는다. MIDI의 초 단위를 실제 연주 시계로 사용하지 않는다.
3. 기존F0를 반음 단위의 안정된 음높이 구간(pitch run)으로 묶고, 삽입/삭제를 허용한 동적계획으로 악보의 음 순서와 정렬한다.
4. 예상음·실제 추정음·차이·관측하지 못한 음표·추가 구간·불확실한 정렬을 별도 결과로 저장한다. 실제 관측 구간의 상대 음량도 보존한다.

악보 음으로 원래F0를 덮어쓰지 않는다. 악보 정보만으로 소리를 만들어내거나 무음 후보를 채택하지 않는다. 이 단계는 모델 후보를 다시 고르는 기능도 아직 수행하지 않는다.

## CLI

원래 오디오 분석 명령에 `--score`만 추가할 수 있다. 현재PC의 준비된 환경 예시다. 전달받은 팀원은 자신의`.venv` Python 경로를 사용한다. MIDI를 읽으려면 `pip install -e ".[plot,score]"` 또는 갱신된CPU requirements를 설치한다.

```powershell
.\.cache\module_check_env\Scripts\python.exe -m maestalk_audio examples/test_scale.wav --score examples/test_scale_score.json --output outputs/score_example_run1 --plot
```

일반 오디오 결과와 함께 `outputs/score_example_run1/score/score_check.json`, `score_notes.csv`가 생긴다. 같은 폴더에 덮어쓰지 않는다.

전달본에 포함된 `examples/test_wrong_note.wav`는C4/D4/**F#4**/F4/G4를 연주한 합성음이다. 같은 악보JSON으로 실행하면 세 번째 예상E4와 실제 추정F#4의 차이를 확인할 수 있다.

```powershell
python -m maestalk_audio examples/test_wrong_note.wav --score examples/test_scale_score.json --output outputs/wrong_note_review1
```

```powershell
python -m maestalk_audio cello.wav --score piece.mid --score-track 1 --score-channel 0 --output outputs/cello_score_run1
```

트랙은0부터 센다. 악보의 여러 파트가 들어 있으면 명시적으로 하나를 선택한다. 녹음이 곡의 연속된 일부 구간뿐이면 `--partial-score`를 사용한다. 이 옵션은 앞뒤 나머지 악보를 모두 누락으로 표시하지 않게 한다. 중간 반복·다른 위치로의 점프를 해결하는 옵션은 아니다.

## Python API

```python
from maestalk_audio import AudioAnalyzer
from maestalk_audio.score import ScoreReference, compare_with_score

audio = AudioAnalyzer().analyze_file("cello.wav", instrument="cello")
score = ScoreReference.from_midi("piece.mid", track_index=1, channel=0)
checked = compare_with_score(audio, score)

payload = audio.to_dict()       # 실제 음높이·RMS·Chroma, 기존 schema 1.0 유지
context = checked.to_dict()     # 별도 score-check-1.0 결과
checked.save("outputs/score_review1")
```

다른 파트에서 이미 음표 목록을 받으면 MIDI 파일 변환 없이 사용할 수 있다.

```python
score = ScoreReference.from_notes([
    {"note_id": "bar1_note1", "midi": 60, "start_beat": 0.0, "duration_beats": 1.0},
    {"note_id": "bar1_note2", "midi": 62, "start_beat": 1.0, "duration_beats": 0.5},
])
```

## 결과를 읽는 방법

|상태|뜻|
|---|---|
|`consistent_with_score`|이번 정렬에서 안정된 관측 구간의80% 이상이 예상음±50cent. 곡 전체/음표 정답률은 아님|
|`pitch_mismatch_review`|정렬된 관측음이 예상음과 달라 추가 확인 필요|
|`not_observed_review`|해당 악보 음표에 대응하는 안정 구간을 찾지 못함. 실제 연주 누락과 인식 누락을 확정 분리하지 못함|
|`alignment_ambiguous`|다른 악보 위치도 비슷한 비용으로 설명되어 위치가 불확실함|
|`alignment_uncertain`|관측 음열과 악보의 일치가 부족해 위치를 신뢰하기 어려움|
|`repeat_boundary_unresolved`|같은 음의 재시작을F0만으로 나누기 어려움|
|`outside_analyzed_score_span`|일부 구간 모드에서 이번 정렬 범위 밖인 음표|

`extra_runs`와`short_unstable_runs`도 함께 확인한다. 짧아 불안정한 후보를 조용히 없애지 않고 따로 남긴다. `exact_run_match_fraction`은 정렬 내부 지표이며 기존의64ms 프레임 음높이 정확도와 다르다. `observed_start_s/end_s`는 음높이 구간 경계로, 실제 악기 음 시작점을 검출한 시각이 아니다.

관측 구간 시각은 분석한 오디오 구간의 시작을0초로 둔다. 원본 파일 시각은 함께 저장한 오디오 결과의 `summary.source_start_s`를 더해서 얻는다. 부분 녹음의 재확인표는 원본 `analysis.json`과 함께 전달한다.

## 실제로 확인한 것과 남은 것

고정 설정으로8개 합성 조건(정상/다른 음/빠진 음/추가 음/옥타브 실수/템포 변화/같은 음 반복/빠른 저음)과 기존 실제3녹음의 분석 캐시를 사용했다. 고의 오음·누락·추가 각각을 재확인 대상으로 표시했고 기존 오디오 결과를 바꾸지 않았다. 같은 음 반복은 해결됐다고 표시하지 않았다.

고의로E4 대신F#4를 낸 합성 조건에서 실제 연주음 기준 원래F0 정확도는96.8%였다. 정렬된 구간을 악보 음으로 강제로 덮는 잘못된 대조군은77.6%가 됐다. 이 수치는 한 합성 조건의 사례이며 실제 악기 일반 성능이 아니다. 그래서 악보와의 일치율을 음성 인식 정확도로 홍보하지 않는다.

실제 Schubert MIDI와 작은 첼로의 정렬표도 만들었다. MusicNet 두 녹음은 제공된 음표 주석의 **음 순서만 악보 대용**으로 사용한 탐색이다. 새 독립 악보/연주 검증이 아니며 빠른 첼로의 기존 약60% 프레임 일치율은 그대로다. 재확인 표시가 실제 연주 실수로 검증된 것도 아니다.

전달본에도 요약 `docs/score_context_checks.csv`·`score_context_verification.json`과 합성 오음 예제/테스트를 포함한다. 전체 소스/설정/조건을 고정한 결과는 원래 개발 프로젝트의 `outputs/score_guidance_20261126/`의 `protocol.json`, `comparison.csv`, `verification.json`, `wrong_note_preservation.png`, 각 조건의`score/`에 있다. 구현은`maestalk_audio/score.py`, 회귀 테스트는`module_tests/test_score.py`다. 원래 프로젝트의`experiments/score_guidance_check.py`는 기존 실제 분석 캐시도 필요하므로 전달본에는 포함하지 않는다. 기존 결과가 있으면 보존을 위해 중단한다.

다음 개선은 **박자·음 길이를 반영한 시간 정렬과 시작점 근거를 추가해 같은 음 반복/빠른 전환의 위치를 더 안정적으로 찾는 것**, 그리고 불일치 구간의 다른 음높이 후보를 오디오 근거로 재검사하는 것이다. 악보에 맞추기 위해 실제로 다르게 연주한 음을 삭제하면 안 된다. 리듬·템포 오차 평가와 자동F0 보정은 아직 수행하지 않는다.
