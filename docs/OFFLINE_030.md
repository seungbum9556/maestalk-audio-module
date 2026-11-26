# 녹음 후 오디오 분석·악보 보조 모듈 0.3.0

이 문서는0.3.0 당시 기록이다. 현재0.4.0의 선택 시작점 확장·스키마1.2·새 어려운 구간 검증은 [HARD_PASSAGES_040.md](HARD_PASSAGES_040.md)를 따른다. 기본 음높이·RMS·Chroma·악보·pYIN 재검토 기능은 유지한다.

2026-11-26. 기존 SwiftF0 + FCPE DDSP-200K·RMS·Chroma·파일/배열 API를 유지하면서 시작점 후보, 악보 시간 정렬, 반복음 구분, 음높이 재검토를 연결했다. 새로운 신경망 학습은 하지 않았다. 바이올린·첼로는 같은 모델과 설정을 쓴다.

## 사용 흐름

1. 분리된 단일 악기 모노 녹음을 분석해 실제 Hz/음 이름·옥타브·RMS/상대dB·Chroma·시작점 후보를 얻는다. 악보 없이도 실행된다.
2. 선택한 파트의 MIDI 또는 음표JSON이 있으면, 실제 음열과 악보의 순서·박자·음 길이를 정렬한다. 입력 악보는 기대하는 곡 정보이며 연주 정답 주석이 아니다.
3. 틀린 음 의심, 미관측 음표, 추가 음향 구간, 정렬 불확실성, 같은 음의 재시작 불확실성을 따로 표시한다.
4. 선택적으로 오디오의 불확실 프레임·음 시작 부근·악보 불일치 구간을 pYIN으로 다시 분석한다. pYIN과 일치하는 **기존 Swift/FCPE 후보**만 별도 제안한다. pYIN에 예상 악보 음높이는 넣지 않는다.

원본 `pitch_hz`는 유지한다. 일치하지 않는 이유는 연주 실수·음높이 인식 오류·악보 정렬 오류 중 하나일 수 있으므로 자동으로 연주 실수를 확정하지 않는다. 이 버전은 녹음 후 분석용이다.

## 이 PC에서 바로 실행

프로젝트 폴더의 PowerShell에서 아래 명령을 입력한다. 이 PC에는 기존 CPU 패키지를 재사용한 `.cache/module_check_env` 환경이 준비되어 있다.

```powershell
.\.cache\module_check_env\Scripts\python.exe -m maestalk_audio examples/test_repeat.wav --score examples/test_repeat.mid --recheck --plot
.\.cache\module_check_env\Scripts\python.exe examples/use_score_context.py
.\.cache\module_check_env\Scripts\python.exe -m unittest discover -s module_tests -v
```

첫 명령은 `outputs/실행시각_test_repeat/`에 결과를 저장한다. 예제는 0.2·0.5·0.8·1.1초에 C4·C4·C4·D4가 시작된다. MIDI의120BPM을 실제 녹음 속도로 가정하지 않는다. 검산한 실행에서 시작점 후보는 0.176·0.496·0.800·1.096초였고, 네 음 모두 `consistent_with_score`였다. 재검토 후보3프레임은 두 번째 C4 시작 부근에서 빠진 C4 후보였다. 합성 예제 한 조건의 결과다.

|생성 파일|확인할 내용|
|---|---|
|`analysis.json`, `summary.json`|원본 오디오 분석, 설정·모델 해시·실제 처리 시간, 기능 상태|
|`frames.csv`|16ms마다 Hz·음 이름·옥타브·점수·RMS·상대dB·변화량|
|`chroma.csv`|C~B의12차원 특징. 옥타브 구분용이 아님|
|`onsets.csv`|실제 소리에서 찾은 시작점 후보, 시각·검출 근거·강도|
|`analysis.png`|파형과 시작점, F0, 상대RMS, Chroma 네 패널|
|`score/score_check.json`, `score/score_notes.csv`|악보별 예상음/실제 관측음·대응 구간·재검토 상태|
|`recheck/pitch_recheck.json`, `recheck/pitch_proposals.csv`|선택적인 음높이 재검토 후보·근거·제외 사유 집계|

`--score`를 생략하면 `score/`가 없고, `--recheck`를 생략하면 `recheck/`가 없다. 빈 후보CSV는 오류가 아니다. 기존 결과 폴더에는 덮어쓰지 않으므로 `--output`을 지정할 때는 새 이름을 쓴다.

전체6초 음계와 고의 오음 예제도 유지했다.

```powershell
.\.cache\module_check_env\Scripts\python.exe -m maestalk_audio examples/test_scale.wav --score examples/test_scale_score.json --plot
.\.cache\module_check_env\Scripts\python.exe -m maestalk_audio examples/test_wrong_note.wav --score examples/test_scale_score.json --recheck --plot
```

두 번째 예제의 실제 세 번째 음은 F#4이고 악보는 E4다. 악보에 맞추려고 실제 F#4를 E4로 덮지 않아야 한다.

## 팀원 설치와 공동 개발

전달할 파일은 `dist/maestalk-audio-module-0.3.0.zip`이다. 전체 압축을 풀고 그 폴더를 VS Code로 연다. Python3.10 설치 후 [MODULE_README.md](../MODULE_README.md)의 CPU requirements → 편집 가능 설치 순서로 진행한다. 이 PC 전용 `.cache` 환경은 ZIP에 넣지 않는다. Linux/Astrago는 경로를 `.venv/bin/python`으로 바꾸되 실제 Linux 실행은 아직 검증하지 않았다.

패키지·가중치가 설치된 뒤에는 분석에 계정·네트워크·GPU가 필요 없다. ZIP에는 필요한 두 모델 가중치·소스·합성 예제·테스트·지표가 있다. 개인 녹음, 실제 악기 데이터 전체, 과거 실험과 가상환경은 없다. 원격 Git 생성·업로드는 하지 않았다. FCPE DDSP-200K 가중치의 CC BY-NC-SA4.0 조건과 출처를 유지한다. 상세 내역은 [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md)에 있다.

## 자기 녹음과 악보 넣기

```powershell
python -m maestalk_audio recordings/cello.wav --instrument cello --part-id cello1 --score scores/piece.mid --score-track 1 --score-channel 0 --score-prefix --start 0 --duration 30 --output outputs/cello_score_run1 --recheck --plot
```

이 예시의 경로는 직접 준비한 파일로 바꾼다. MIDI 트랙·채널은0부터 센다. 여러 파트가 있는 MIDI는 해당 악기의 트랙·채널을 골라야 한다. 악기 이름은 기록용이며 모델을 바꾸지 않는다. 스테레오/혼합 합주는 분리 모노 파일로 준비한다.

|악보 대조 범위|CLI|Python `partial_score`|
|---|---|---|
|전체 연주|옵션 생략|`False`|
|곡 처음부터 녹음했으나 끝까지 연주하지 않음|`--score-prefix`|`"prefix"`|
|악보 중 어느 위치인지 모르는 연속 발췌|`--partial-score`|`True`|

두 부분 범위 옵션은 동시에 쓰지 않는다. 곡 처음임을 알고 있으면 prefix를 써야 같은 음열이 반복되는 다른 위치로 잘못 붙는 것을 줄일 수 있다. 임의 반복·되돌아가기·곡 중간 점프·화음은 아직 지원하지 않는다. 큰 악보와 긴 녹음은 DP 크기 제한100만 셀에 걸릴 수 있으며, 해당 파트와 연속 구간을 먼저 나눠서 검증한다.

음표JSON 형식은 다음과 같다. `start_beat`와 `duration_beats`는 **4분음표 기준 박 단위**이며 연주 초 단위가 아니다. 6/8 MIDI에서도 ticks/beat의 기본 단위는4분음표다. MusicXML/PDF/HWP 악보를 바로 읽는 기능은 없다. MIDI나 아래 음표 목록으로 변환해 받는다.

```json
{"notes": [
  {"midi": 60, "start_beat": 0.0, "duration_beats": 1.0, "note_id": "n1"},
  {"midi": 62, "start_beat": 1.0, "duration_beats": 0.5, "note_id": "n2"}
]}
```

## Python에서 호출

```python
from maestalk_audio import AudioAnalyzer
from maestalk_audio.score import ScoreReference, compare_with_score
from maestalk_audio.recheck import candidate_review_windows, recheck_file

analyzer = AudioAnalyzer()  # 파일을 바꿔도 재사용
audio_path = "examples/test_repeat.wav"
audio = analyzer.analyze_file(audio_path, instrument="cello", part_id="cello1")
score = ScoreReference.from_midi("examples/test_repeat.mid")
checked = compare_with_score(audio, score)  # 전체 예제이므로 기본값
proposals = recheck_file(audio_path, audio, candidate_review_windows(audio, checked))

# 세 결과를 구분해서 사용한다. audio.frames를 후보로 덮어쓰지 않는다.
audio_payload = audio.to_dict()
score_payload = checked.to_dict()
recheck_payload = proposals.to_dict()
```

배열 분석 뒤에는 `recheck_samples(samples, sample_rate, audio, windows)`를 쓴다. 파일 재검토는 분석 원본과 SHA256이 같은지 확인하며 분석한 구간만 다시 읽는다. 모든 시각은 분석 구간 기준이고, 원본 파일 시각은 `source_start_s`를 더한다. 파형 배열은1차원 float32, [-1,1], 유한한 값이며 PCM int16 수치를 그대로 넣지 않는다.

## 반환값과 판단 범위

오디오 스키마는 **1.1**이다. 기존 frame 필드는 유지했고 `onsets`를 실제 후보 목록으로 채웠다. 검출했지만 후보가 없으면 `[]`, 시작점 기능을 껐으면 `null`이다. 시작점의 `time_s`는 음향 특징에서 거슬러 추정한 시각이고 `peak_time_s`와 구분한다. `rearticulation_evidence`는 같은 음 재시작을 나눌 때 쓰며 단순한 음량 상승만으로 유지음을 나누지 않는다.

악보 결과 스키마는 `score-check-1.0`이며 필드를 추가했다. `consistent_with_score`는 해당 대응 구간의 유효 F0 중80% 이상이 예상음±50cent라는 뜻이다. 누락된 F0를 포함하는 전체 정확도 지표가 아니고, 대응이 잘못됐을 수도 있다. 나머지 주요 상태는 `pitch_mismatch_review`, `not_observed_review`, `repeat_boundary_unresolved`, `alignment_ambiguous`, `alignment_uncertain`, `outside_analyzed_score_span`이다. 추가·짧은 불안정 구간은 별도 목록에 남긴다.

`expected_aligned_start_s/end_s`는 실제 연주 근거로 맞춘 악보 위치다. `timing_residual_s`는 자기 자신의 시작점을 제외한 이웃 기준점으로 예상한 시각과의 차이다. 자기 시각에 맞춘 뒤 차이가0이라고 보고하지 않는다. `timing_review`는 재확인 표시이며 지휘·메트로놈 기준의 리듬 실수 확정이 아니다. `rhythm_deviation_evaluated`는 `False`다.

재검토 결과는 `pitch-recheck-1.0`이다. `proposals`는 프레임별 대안이고 원본 변경은 없다. `source_score`, 후보 `strength`, pYIN의 유성 확률 중 어느 것도 **음높이가 맞을 확률**로 해석하지 않는다. 오디오만으로 근거가 부족하면 빈 후보를 반환한다.

## 기본 설정과 수식

|항목|설정|
|---|---|
|기본 F0|SwiftF0 0.3.0 + FCPE DDSP-200K, CPU, 공통50–2000Hz; FCPE 상한1975.5Hz|
|선택|Swift 자체점수≥0.9 유지. FCPE 자체점수≥0.8이고 Swift가 없거나<0.9이면 FCPE. 서로 다른 점수를 같은 확률로 비교하지 않음|
|출력 격자|16ms. 원래 모델 추정을 최근접 시각에 대응; Hz 평균·무음 보간 없음|
|RMS|원본 파형의100ms 중앙 창, 약96ms 전 대비 변화, ±1dB로 up/down/steady|
|곡 상대음량|전체 녹음의 선택된 에너지 구간 평균제곱 크기를 기준으로 `20 log10(RMS/reference_RMS)`|
|Chroma|librosa STFT4096, 약16ms hop.12차원, 옥타브 정보 없음|
|시작점|16kHz, STFT1024/64ms, hop128/8ms, RMS512/32ms, mel64. 양의 스펙트럼 변화+에너지+실제 F0 전환|
|시작점 기준|중앙값+3MAD, 최소간격64ms, 최대backtrack80ms, attack3dB, 재시작 dip2dB, F0변화75cent·안정48ms|
|악보 정렬|최소F0구간48ms, 짧은 gap32ms, 삽입/삭제0.9·치환1.0, 시간0.15·길이0.10·Chroma0.05의 제한된 보조 비용|
|시간 대응|신뢰 가능한 일치 구간3개 이상. 가능하면 독립적인 음향 시작점을 기준점으로 사용|
|음높이 재검토|16kHz, pYIN2048/128ms·hop256/16ms, 문맥±160ms, 유성 확률≥0.85, 후보 일치±35cent, 연속48ms 이상|
|후보 제한|Swift≥0.5 / FCPE≥0.4. 이미 채택한 모델 자체점수≥0.95이면 변경 후보로 삼지 않음|

정확한 모델·설정·프레임 길이·버전·처리 시간은 각 실행 `summary.json`에도 저장된다. `f = 440 × 2^((MIDI−69)/12)`, cent 차이는 `1200 log2(f_est/f_ref)`로 계산한다. 원본 신호 RMS를 모델용 정규화로 바꾸지 않는다. onset/pYIN 특징의 별도 정규화는 RMS에 영향을 주지 않는다.

## 실제로 검증한 결과

합성17조건과 실제11조건(8개 원본 녹음과3개 변형 조건)을 CPU로 분석했다. 기존에 사용한 녹음이므로 새 곡·연주자에 대한 독립 검증은 아니다. 데이터가 사전학습에 포함됐는지도 확인하지 못했다. 모델·onset·시간 정렬 소스는 실험 전에 동결했고, 재검토 범위 확장은 후속 소스/프로토콜로 별도 보존했다. [28조건 지표](offline_030_checks.csv), [검증 요약](SOURCE_VERIFICATION.json)을 본다.

- 같은 음 재시작 합성 조건: 시작점4개, 누락0·추가0, 매칭된 시작점 평균 절대오차7ms, 미해결 반복음2→0. 재시작 없는 유지음은 미해결 상태를 보존했다.
- 음표 위치를 정확히 찾은 수: 같은 시작 범위 정보를 준 대조군 대비 Jupiter 바이올린33→40/42개, Schubert 첼로44→47/53개. **F0 정확도 향상이 아니라 악보 위치 대응의 개선**이다.
- MusicNet2298은 정확히 위치를 찾은 음표가128→131/175개로 늘었지만, 평가된 대응 구간 중 위치 일치율은83.12→80.86%로 낮아졌다. 개선만 보고하지 않는다.
- 재검토 후보를 평가상 적용하면 실제11조건 합계 정답11프레임 추가(Jupiter 바이올린8, Schubert 원본3), 기존 정답 손실0, 무음 오검출 증가0이었다. 11프레임은 음표11개가 아니다. 기본 F0에는 적용하지 않는다.
- 재검토 범위를 넓혀도 Maria와 두 MusicNet 첼로의 정답 추가는0이었다. 유성 기준0.85→0.5 실험은 작은 Schubert에서 정답3개와 무음 오검출4개가 함께 늘어 **미채택**했다.
- 실제 Maria에 적용한 알려진 크기 변화(0.5·2·0.25배)는 잡음을 추가하지 않은 조건에서 RMS dB 오차0.01dB 미만이었다. 전환±100ms 제외. 고정 잡음을 넣으면 작은 연주음의 변화가 가려진다. 실제 SPL/악기 간 연주 강도·AGC 해결을 검증한 결과가 아니다.

아래 F0는 **동일16ms 격자**의 정답 유성 프레임 중±50cent 이내 비율이다. 추정 누락도 분모에 남겼다. 원본 F0와 재검토 후보 적용 결과를 구분한다.

|원본 녹음|정답 종류|기본 F0|후보를 평가상 적용|
|---|---|---:|---:|
|Maria 첼로 처음30초|URMP 연속F0|91.80%|91.80%|
|Jupiter 바이올린 처음30초|URMP 연속F0|98.11%|98.63%|
|Schubert 첼로0–53.125초|TRIOS 명목MIDI|96.61%|96.74%|
|MusicNet2217 처음30초|명목MIDI|60.65%|60.65%|
|MusicNet2298 처음30초|명목MIDI|62.57%|62.57%|

이전 `BASELINE.md`는 모델 원출력→64ms로 평가한 선정 당시 기록이다. 이번 수치는 모듈16ms 출력을 평가하므로 시각 대응/경계 반올림이 달라 예전92.86% 등과 직접 비교하지 않는다. 실제 원본11조건의16ms F0는 동결된 선정 모델과 일치함을 확인했다. 연속F0와 명목MIDI는 정답의 성격이 다르므로 합쳐 하나의 정확도로 발표하지 않는다.

시작점은±50ms 안에서 한 검출을 한 정답에만 매칭했다. 오차는 매칭된 것만의 평균이고 누락·추가를 반드시 함께 본다.

|녹음|정답 시작점|누락|추가|매칭된 평균 절대오차|
|---|---:|---:|---:|---:|
|Jupiter 바이올린|43|6|6|17.9ms|
|Maria 첼로|91|41|39|27.3ms|
|Jupiter 첼로|22|15|15|24.7ms|
|Schubert 첼로|53|15|22|19.0ms|
|MusicNet2217 첼로|175|105|20|26.4ms|
|MusicNet2298 첼로|176|86|31|23.4ms|

**첼로 시작점과 빠른 음 전환의 인식 품질은 아직 충분하지 않다.** 후보 출력과 악보 대조가 구현됐다는 것을 오류 해결 완료로 설명하지 않는다. 모든 음을 맞추도록 악보로 덮어쓰는 방식은 실제 연주 실수를 숨기므로 사용하지 않는다.

## 데이터 출처와 검증 구분

URMP의 분리 악기 녹음·연속F0/음표 주석, TRIOS 분리 녹음·연주 정렬MIDI는 [이전 출처 안내](BASELINE.md)를 따른다. URMP 악보 입력은 음 순서만의 대체 목록이며 시간 정렬 가중치를 껐다. 그 주석의 실제 시작 시각을 악보 입력으로 누설하지 않았다. TRIOS MIDI는 이미 연주 시각에 맞춰진 자료이므로 시간 정렬 검사는 조건부 동작 확인이다.

MusicNet은 [공식 Zenodo 배포](https://zenodo.org/records/5120004)의 `musicnet_midis.tar.gz`에서 원래 악보 `Bach/2217_cs3-1pre.mid`, `Bach/2298_cs4-6gig.mid`를 받았다. 트랙1/채널0을 사용했고 녹음 처음30초에 prefix 정렬을 했다. MIDI ticks는4분음표 기준이며,2298 CSV 정답의8분음표 박 표기는 평가 시에만0.5를 곱해 음표ID를 대조했다. 실측 시각으로 맞춘 임의 시간 보정은 하지 않았다. 다운로드 주소·압축/선택파일 SHA256은 이 프로젝트의 `data/score_references/source.json`에 있다. 실제 녹음·공식 MIDI는 전달ZIP에 넣지 않았다. 포함된 예제 MIDI는 직접 만든 합성 예제다.

이 버전의44개 모듈 테스트와 기존174개 테스트가 통과했다. ZIP을 다른 폴더에 풀어 재설치하는 검산 결과는 검증 요약 파일을 따른다. 현재 PC의 기존 CPU 의존성을 재사용한 Windows/Python3.10 검사이며 깨끗한 PC에서 인터넷으로 새로 설치하거나 Linux에서 실행한 검사로 표현하지 않는다. 파일 처리 시간은 실제 마이크→화면 지연이 아니다.

남은 우선 작업은 빠른 첼로의 실제 F0·주석 경계를 검수한 뒤, 지금까지 쓰지 않은 녹음에서 고정된 모듈을 검증하는 것이다. 지휘 기준의 리듬 평가에는 별도 기준 시계가 필요하며, 마이크·스트리밍·UI·LLM·3입력 동시 처리는 이번 범위 밖이다.
