# 어려운 곡을 위한0.4.0 확장 시작점 옵션

이 문서는 **0.4.0 당시의 측정 기록**이다. 현재 0.4.1은 기존 후보와 파형 검증을 이용한 제한적인 F0 교정을 기본 적용한다. 아래 HarmoF0 미채택은 당시의 보호 장치 없는 보완 방식에 대한 결과이며, 현재는 조건부 검증용으로 사용한다. [현재 사용법·성능·제외한 보정](../MODULE_README.md)을 따른다. 0.4.0의 선택 시작점 기능은 유지한다.

기존 음높이 모델 **SwiftF0 + FCPE DDSP-200K**와 RMS·상대dB·Chroma를 유지하고, 부드럽고 빠른 음 변화에서 놓친 시작 후보를 보충하는 `--expanded-onsets`를 추가했다. 바이올린·첼로는 같은 모델·설정이다. GPU는 사용하지 않는다.

**음높이 인식 오류를 모두 해결한 버전은 아니다.** 새 음높이 보완 모델 HarmoF0도 시험했지만 기존 정답 손실이 남아 채택하지 않았다. 이번에 반영한 것은 시작점 후보 복원이다. 추가 오검출이 늘 수 있어 옵션을 켜서 선택한다. 옵션을 생략하면 기존0.3.0의 시작점 방식이다.

## 이 PC에서 실행

프로젝트 폴더의 PowerShell에서 다음을 입력한다. 새 폴더에 결과를 저장하므로 이전 결과를 덮어쓰지 않는다.

```powershell
.\.cache\module_check_env\Scripts\python.exe -m maestalk_audio examples/test_repeat.wav --score examples/test_repeat.mid --expanded-onsets --recheck --plot
```

이 프로젝트에 준비된 실제 빠른 첼로30초와 원래 악보 MIDI를 쓰는 명령은 다음과 같다. 실제 녹음은 전달ZIP에 넣지 않는다.

```powershell
.\.cache\module_check_env\Scripts\python.exe -m maestalk_audio outputs/score_timing_20261126/cases/musicnet2217_cello_original/input.wav --score data/score_references/2217_cs3-1pre.mid --score-track 1 --score-channel 0 --score-prefix --expanded-onsets --plot
```

자신의 파일은 위 오디오·MIDI 경로로 바꾼다. MIDI 트랙·채널은0부터 센다. 분리 모노 단음 입력이며 혼합 합주·화음·악기 자동 분류는 지원하지 않는다. 전체곡은 `--score-prefix`를 빼고, 악보 중간의 연속 발췌 위치를 모르면 `--partial-score`를 쓴다. 두 범위 옵션은 동시에 쓰지 않는다. 기본 설치와 입력 형식은 [MODULE_README.md](../MODULE_README.md), 기존 악보/재검토 기능은 [OFFLINE_030.md](OFFLINE_030.md)를 따른다.

## 생성 파일과 코드 역할

|파일|뜻|
|---|---|
|`analysis.json`, `summary.json`|전체 결과·설정·가중치 해시·시각 기준·처리 시간|
|`frames.csv`, `chroma.csv`|기존 F0·음 이름/옥타브·모델 점수·RMS·상대dB·Chroma|
|`onsets.csv`|선택한 모드의 시작 후보. 옵션을 켜면 기존 후보+추가 후보|
|`acoustic_onsets.csv`|옵션을 켰을 때 보존한 기존 검출 후보|
|`pitch_boundaries.csv`|옵션을 켰을 때 음높이 전환으로 찾은 전체 후보. 중복 제외 전 목록|
|`analysis.png`|파형/F0/RMS/Chroma. 주황 실선=기존 후보, 청록 점선=실제로 추가된 음 변화 후보|
|`score/`|악보를 넣었을 때 예상음과 실제 관측 구간·검토 상태|
|`recheck/`|`--recheck` 선택 시 기존 pYIN 검증 후보. 자동 F0 치환 없음|

`maestalk_audio/boundaries.py`가 두 모델이 함께 지지하는 안정된 음 변화를 찾는다. `analysis.py`가 옵션을 연결하고 `result.py`가 원래 후보·추가 후보를 구분해 저장한다. `onsets.py`의 기존 음향 검출기는 유지했다. 새 가중치·패키지 설치는 필요 없다.

## Python API·스키마

```python
from maestalk_audio import AudioAnalyzer, AnalysisConfig

analyzer = AudioAnalyzer(AnalysisConfig(expanded_onsets=True))
result = analyzer.analyze_file("examples/test_repeat.wav", instrument="cello")
payload = result.to_dict()
print(payload["schema_version"])  # "1.2"
print(payload["acoustic_onsets"])  # 보존한 기존 검출 후보
print(payload["pitch_boundaries"]) # 관측 음높이 전환 후보
print(payload["onsets"])          # 실제 선택한 결합 후보
```

오디오 스키마는 **1.2**다. 기존 frame 필드와 `onsets`는 유지하고 `acoustic_onsets`, `pitch_boundaries`를 추가했다. `expanded_onsets=False`에서는 후자가 `null`이다. 검출했지만 후보가 없으면 `[]`다. `compute_onsets=False`와 확장 옵션을 동시에 지정하면 오류다.

추가 후보의 `status`는 `pitch_boundary_candidate`, `sources`는 `stable_pitch_transition_two_models`다. 실제 음높이가 바뀌는 경계이며 새로운 활/뜯기 동작을 증명하지 않는다. `rearticulation_evidence=False`이므로 같은 음 재시작을 악보만 보고 나누지 않는다. `strength`는 정답 확률이 아니다.

설정: 안정 구간48ms, 최소75cent 음 변화, gap≤128ms, Swift 점수≥0.5·FCPE 점수≥0.4와50cent 이내 합의2프레임 이상, 새 구간RMS가 직전의0.25배 이상, 기존 후보64ms 이내 중복 제외. 실제 F0 변화의 중간을 통과한 시각을 사용하며 정답 시각으로 맞춘 상수 보정은 없다. 전체 설정은 실행 `summary.json`에 남는다.

기존 후보를 지우지 않으므로 시작점 누락은 이번40조건에서 증가하지 않았다. 다만 추가 후보가 거짓이면 정밀도는 낮아질 수 있다. 확장 후보를 악보 시간 정렬에도 사용하므로 대응 위치가 바뀔 수 있다. MusicNet2217에서는 정확히 위치를 찾은 음표가123→122/174개로1개 줄었다. `onsets` 개선을 악보 정렬·음높이의 일괄 개선으로 해석하지 않는다.

## 실제 검증 결과

기존 합성17+실제11조건에, 실제 녹음의 빠른 후반4구간×원본/−12dB/SNR10의12조건을 더해40조건에서 확인했다. 총23조건이 실제 녹음 기반이며 변형 조건이 포함된다. 같은 곡/연주자일 수 있고 새 연주자로 독립 검증한 결과는 아니다.

추가한 구간은 Rondeau 바이올린70–100초, K515 바이올린110–140초, Spring 첼로30–60초, Maria 첼로40–70초다. 각각30초에127·104·115·119개 완전한 음표가 있고 음표 길이 중앙값은174·153.5·141·209ms다. 예측 점수를 보기 전에 주석의 음표 밀도로 골랐다.

**시작점 평가는±50ms에서 일대일 매칭**한다. 전체40조건 합계 누락963→729개, 추가585→624개였다. F1은21조건 개선·1조건 악화·18조건 동일이었다. 이 집계는 하나의 악기 일반 정확도가 아니다.

|구간|시작점 F1 기존→확장|누락 기존→확장|추가 기존→확장|
|---|---:|---:|---:|
|Maria 첼로 처음30초|0.556→0.617|41→33|39→39|
|Maria 첼로 처음30초−12dB|0.557→0.604|42→36|36→36|
|MusicNet2217 첼로 처음30초|0.528→0.630|105→77|20→38|
|MusicNet2298 첼로 처음30초|0.606→0.691|86→63|31→38|
|Rondeau 바이올린70–100초|0.789→0.858|30→15|22→22|
|K515 바이올린110–140초|0.680→0.757|37→25|25→25|
|Spring 첼로30–60초|0.640→0.658|45→42|35→35|

Spring 첼로SNR10 조건은 누락이 같고 추가가1개 늘어 F1이0.766→0.763으로 소폭 악화됐다. 같은 구간−12dB는 변화가 없었다. 성공한 조건만 남기지 않았다. 새로운30초 발췌의 onset 평가는 잘린 경계 영향을 줄이기 위해 양끝80ms를 제외했다.

**기본 F0는 이번 옵션으로 변하지 않는다.** 다음은 새 구간 원본의 기존 모델 성능이며, 정답 유성 프레임 중±50cent·누락 포함·16ms 기준이다.

|URMP 연속F0 정답 구간|기본 F0 일치율|
|---|---:|
|Rondeau 바이올린70–100초|97.50%|
|K515 바이올린110–140초|95.14%|
|Spring 첼로30–60초|92.89%|
|Maria 첼로40–70초|90.24%|

MusicNet의 명목MIDI 일치율60.65/62.57%와 위 연속F0를 같은 정확도로 합치지 않는다. MusicNet의 F0 개선은 달성하지 못했다. 작은 소리에서 K515는90.68%, Maria 후반은87.33%로 낮아지는 문제도 남는다. 같은 모델이 두 악기에 실행된다는 사실과 모든 곡에서 충분한 성능이라는 주장은 다르다.

시험한 다른 방법은 입력 증폭,64ms pYIN, 다중 창YIN 합의, 느린 재생 추론, HarmoF0, FCPE 출력 디코더 변경이다. 각각 이득·손실·오검출을 기록했고 개선이 확인되지 않은 방식은 기본값에 넣지 않았다. HarmoF0 안정 구간 결합은40조건에서 정답+17/기존 정답 손실3이 있어 미채택했다. 단순한 신뢰도 기준 완화나 모델 추가만으로 해결됐다고 설명하지 않는다.

## 지표·출처·검증 범위

[시작점40조건 CSV](hard_passage_onsets.csv), [음높이 실험40조건 CSV](hard_passage_pitch.csv), [검증 요약](HARD_PASSAGE_VERIFICATION.json)을 본다. **음높이 CSV의 `after_`는 미채택 HarmoF0 실험 결과이며 배포 모듈의 출력이 아니다. 배포 F0는 `before_`와 같다.** 오음·옥타브·누락·무음 오검출·경계32ms·중앙50ms·낮은 음 통계를 구분했다.

원본·정답 파일과 구간·SHA256·잡음 시드는 프로젝트 `outputs/hard_passages_20261126/selected_confirmation/protocol.json`에 있다. [URMP 공식](https://labsites.rochester.edu/air/projects/urmp/), [MusicNet 공식](https://zenodo.org/records/5120004)의 분리 오디오·제공 주석을 사용했다. 마이크·거리·입력 게인·AGC는 제공 자료에서 미확인이다. −12dB는 진폭 약1/4, SNR10은 원래 구간의 전체 신호 전력 대비 추가한 고정 잡음 전력이다. 실제 소음 환경 전체를 대표하지 않는다.

모듈51+기존174=225개 테스트, 실제 CLI·MIDI·CSV·그래프 출력,40조건 동결 검출과 실제 모듈의 후보 시각 일치, 실제 MusicNet의 F0/RMS/Chroma 불변과 원본70파일 보존을 확인했다. Windows/Python3.10·기존 CPU 의존성 재사용 환경이다. Linux·깨끗한PC 온라인 설치·마이크 지연은 미검증이다. 새 ZIP의 다른 폴더 재설치 검산은 전달본 옆 `.zip.verification.json`에 기록한다.

전달본은 `dist/maestalk-audio-module-0.4.0.zip`이다. 기존0.1/0.2/0.3 전달본은 보존했다. 음높이 오류·작은 음 누락·추가 시작점 오류가 남아 있으며, 이 버전을 완성된 현악기 인식기로 일반화하지 않는다.
