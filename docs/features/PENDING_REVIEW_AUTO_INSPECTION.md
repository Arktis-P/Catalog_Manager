# Pending Review Auto Inspection

## 목적

이미 1회 생성이 끝난 V2 캐릭터 중 `review_status=pending`인 항목만 자동 검사하여 사람이 다시 볼 절대 수를 줄인다.

이 기능은 완료된 리뷰를 다시 검사하지 않는다. 이후 새로 생성하거나 재생성하는 V2 이미지에는 동일한 검사 로직이 기존 V2 quality/identity 파이프라인을 통해 자동 적용된다.

## 카운트 기준

V2 화면의 일반 진행 통계와 Pending 자동 검사 통계는 대상 범위가 다르다.

- 일반 V2 `대기`: `GlobalCharacter` 전체 중 review가 없거나 `review_status=pending`인 캐릭터 수. 이미지가 아직 없는 캐릭터도 포함한다.
- Pending 자동 검사 `자동 검사 가능(이미지 있음)`: 위 pending 캐릭터 중 `GlobalCharacterImage`가 최소 1장 존재하는 캐릭터 수.
- `이미지 없음`: 일반 V2 pending 수에서 자동 검사 가능한 수를 뺀 값이다. 아직 검사할 실제 이미지가 없으므로 자동 검사 대상이 아니다.
- `자동 검사 남음`: 이미지가 있으면서 현재 quality/identity checker 버전으로 아직 검사되지 않은 캐릭터 수다.

따라서 일반 V2의 pending 수와 Pending 자동 검사 대상 수가 다른 것은 정상이다. 이 수치는 이미지 장수가 아니라 캐릭터 수를 기준으로 한다.

## 자원 절약 원칙

- 로컬 비전 모델을 추가하지 않는다.
- 이미 사용 중인 Hugging Face WD 태거의 1회 예측 결과를 semantic 검사에도 재사용한다.
- **일반적인 pending 이미지는 Danbooru를 추가 조회하지 않는다.** 이미 DB에 저장된 gender/non-human 신호와 WD 결과만으로 먼저 판정한다.
- 생성 결과에서 수영복/속옷 신호가 강하게 나온 경우처럼 기본 복장 비교가 실제로 필요한 항목에 대해서만 `{character_tag} solo` 메타데이터를 최대 60개 포스트까지 1회 조회한다.
- Danbooru 참조 이미지는 다운로드하거나 저장하지 않는다. 포스트의 태그 메타데이터만 사용한다.
- 필요해서 만든 reference profile도 작은 JSON 통계만 캐시하며, 자동 완료된 캐릭터에서는 즉시 제거한다.
- 자동 재생성은 기본 최대 2회로 제한한다.
- 재생성 후 이전 reject 이미지는 cover/provisional이 아닌 경우 삭제하여 저장공간 증가를 제한한다.
- UI는 10개 단위 배치로 순차 처리한다. 같은 배치에서 진행이 멈추면 무한 재시도하지 않고 자동 중단한다.
- 일반 V2 생성/재생성 작업이 진행 중일 때는 Pending 자동 검사를 시작하지 않아 NAIA/SQLite 작업이 서로 경쟁하지 않게 한다.
- 작업 목록 진행률도 10개 배치가 끝날 때만 갱신해 불필요한 요청/렌더링을 늘리지 않는다.
- 검사 중 실제 재생성이 발생할 때만 V2 서버 작업 목록을 1초 간격으로 갱신해 해당 캐릭터 재생성 작업을 발견한다. 평상시에는 추가 polling을 하지 않는다.

## 검사 흐름

```text
pending + 기존 이미지 1장
  -> 기존 quality 검사
  -> 기존 HF WD identity 검사 1회
     -> 동일 WD 결과로 semantic 검사
        -> 기존 DB gender/non-human 신호 우선 사용
        -> 수영복/속옷 신호가 강할 때만 compact Danbooru outfit profile 조회/비교
  -> pass/warning: pending 유지
  -> reject: 기존 V2 재생성 파이프라인으로 최대 2회 재생성
       -> 캐릭터별 "검사 재생성" 작업을 전역 작업 목록에 별도 표시
       -> 생성될 때마다 quality -> identity -> semantic 재검사
  -> 성공: 최신 1장 유지 + 이전 reject 파일 정리
  -> 제한까지 실패: rating 0 자동 후보
```

## Semantic reject

보수적으로 명확한 실패만 자동 재생성한다.

- `multiple_views`, `character_sheet`, `reference_sheet`, `collage` 등 이미지 속 이미지/시트형 출력
- 카드, 포스터, 화면, 인쇄 의상 신호가 여러 개 겹치거나 다중 인물 신호와 같이 검출되는 경우
- reference profile에서 수영복/속옷 비중이 매우 낮은데 생성 이미지에서 해당 복장이 높은 confidence로 검출되는 경우
- 기존 gender가 여성인데 생성 결과가 강하게 남성/비인간으로 판정되는 경우

단일 `print_shirt` 같은 약한 신호 하나만으로는 자동 reject하지 않는다.

## Reference profile

Reference profile은 모든 캐릭터에 미리 만드는 데이터가 아니다. **생성 이미지 자체가 수영복/속옷으로 보여 기본 복장 비교가 필요한 pending 캐릭터에서만 지연 생성한다.**

영구 저장하는 것은 이미지가 아니라 다음 통계뿐이다.

- sample count
- `1girl` 비율
- `1boy` 비율
- non-human 비율
- swimwear 비율
- underwear 비율
- 상위 outfit tag 최대 6개

reference sample이 12개 미만이면 outfit/gender 자동 판단에는 사용하지 않는다.

## 자동 rating 정책

- `-1`: 기존 non-human 데이터와 생성 결과가 충분히 일치하거나, 필요한 경우 reference가 안정적으로 비인간일 때 후보
- `1`: 원본 gender가 남성이고 생성 결과도 높은 confidence로 남성일 때 후보
- `3`: 두 경우 모두 **자동 완료하지 않고 pending rating만 3으로 미리 입력**한다.
  - 원본 남성 캐릭터가 여성으로 안정적으로 생성된 경우
  - 원본 여성 캐릭터가 정상적으로 여성으로 생성된 일반적인 경우
- `0`: 이번 검사 실행에서 자동 재생성 제한까지 실제로 모두 실패한 경우

`-1`, `1`은 confidence 0.85 이상에서만 자동 완료한다. `0`은 현재 실행의 재생성 제한 소진이 명확한 근거일 때만 confidence 1.0으로 취급한다. 과거 실행에서 남은 `generation_failed` 상태만으로 0성을 자동 확정하지 않는다.

자동 완료 대상의 기본 10%는 deterministic audit sample로 남겨 `review_status=pending` 상태에서 예측 rating만 입력한다. 사용자의 수정 결과는 `review_note`에 남은 자동 예측 정보와 비교하여 이후 threshold/규칙 보정에 사용할 수 있다.

기존에 사용자가 rating을 입력한 pending 항목은 자동 rating이 덮어쓰지 않는다.

## UI

Review -> V2 검수 상단의 `Pending 자동 검사` 패널에서 실행한다.

- `현재 페이지 최대 30개 테스트`: 아래 V2 검수 그리드에서 현재 실제로 화면에 표시된 카드 ID를 최대 30개 수집해 그 항목만 검사한다. 이미지가 없거나 이미 현재 checker 버전으로 검사된 항목은 건너뛴다.
- `남은 Pending 자동 검사`: 남은 대상 전체를 10개 배치로 순차 실행한다.
- `현재 배치 후 중지`: 진행 중인 현재 10개 배치 완료 후 안전하게 멈춘다.
- `테스트 결과 초기화 (N)`: 페이지 테스트에서 **실제로 검사 대상으로 들어간 캐릭터 ID만** 추적해 checker 결과와 자동 판정을 초기화한다. 재생성으로 만들어진 이미지 파일 자체는 삭제하거나 이전 이미지로 되돌리지 않는다.
- `상태 새로고침`: 현재 검사 완료/남은 수와 전체 pending/이미지 보유 여부를 갱신한다.

`테스트 결과 초기화`는 검증 기간용 임시 기능이다. 프런트의 `TEST_RESET_ENABLED` 플래그로 한 곳에서 비활성화할 수 있으며, 테스트 종료 후 false로 전환하거나 UI 블록을 제거한다. 추적 ID는 localStorage에 최대 1000개까지만 보존하므로 앱을 재시작해도 테스트 기간 동안 초기화 대상을 유지한다.

초기화 범위:

- 최신 이미지의 quality/identity checker status, score, reasons, version, checked_at
- 검사로 설정된 provisional 상태
- compact reference profile 캐시
- `review_note`에 `auto_inspection=...` 마커가 있는 자동 rating 및 자동 completed 상태

초기화하지 않는 것:

- 재생성으로 실제 생성된 이미지 파일
- generation attempt 누계
- `auto_inspection` 마커가 없는 사용자의 수동 rating/review 상태

### 전역 작업 목록 진행률

두 검사 모두 기존 전역 `작업 중` 목록에 하나의 상위 작업 카드로 등록한다. 별도의 대형 작업 시스템이나 로컬 모델을 추가하지 않고 기존 V2 작업 상태 저장소와 진행률 UI를 재사용한다.

- 현재 페이지 30개 테스트: `0/30 -> 10/30 -> 20/30 -> 30/30` 식으로 최대 10개 단위로 진행률을 갱신한다.
- 전체 검사: 실행 시점의 `자동 검사 남음`을 total로 고정하고 `10/31,053 -> 20/31,053 -> ...` 식으로 표시한다.
- 상위 작업 카드에는 `검사`, `재생성`, `자동완료`, `오류` 누계도 함께 표시한다.
- 완료/실패/사용자 중지 결과도 기존 작업 카드 상태로 남으며 `완료 지우기`로 정리할 수 있다.
- Pending 검사 상위 카드는 화면 오케스트레이션 작업이므로 서버의 V2 job polling 대상으로 보내지 않는다.

### 재생성 하위 작업 표시

검사 중 한 캐릭터가 reject되어 NAI 재생성이 시작되면, 해당 실제 작업은 서버 `V2GenerationJobManager`에 `kind=regenerate`인 별도 작업으로 등록한다.

- 작업명: `자동 검사 재생성 · {character_tag}`
- 작업 종류 배지: `검사 재생성`
- 진행: `현재 시도 / 최대 2회`
- 생성 후 checker 단계 메시지도 같은 카드에서 갱신
- 사용자는 해당 재생성 카드만 취소할 수 있다. capped inspector가 직접 실행하는 작업이므로 pause/resume은 제공하지 않는다.
- 상위 Pending 검사 카드와 재생성 하위 카드가 동시에 전역 작업 목록에 보인다.
- 브라우저는 Pending 검사 실행 중에만 서버 V2 job 목록을 1초 주기로 확인해서 새 하위 재생성 job을 발견한다. 발견 후에는 기존 개별 V2 job polling으로 진행 상태를 갱신한다.

현재 페이지 테스트에서 상위 작업 카드의 `current/total`은 현재 페이지 카드 중 몇 개까지 확인을 시도했는지를 뜻한다. 이 중 이미지 없음/최신 checker 적용 완료 등으로 실제 검사가 필요하지 않은 항목은 별도의 `검사` 누계에 포함되지 않는다.

자동 완료/평점 미리입력 결과를 카드에 다시 표시하려면 아래 V2 목록의 `새로고침`을 누른다.

완료된 리뷰는 대상 수에도 포함하지 않는다.

## API

- `GET /api/review/v2/pending-inspection/stats`
- `POST /api/review/v2/pending-inspection/run`
- `POST /api/review/v2/pending-inspection/run-selected`
- `POST /api/review/v2/pending-inspection/reset-selected` — 테스트 기간 임시 초기화 API

`run` 주요 파라미터:

- `limit` 기본 50, 최대 500
- `auto_regenerate` 기본 true
- `max_regenerations` 기본 2, 최대 5
- `auto_complete` 기본 true
- `audit_sample_rate` 기본 0.10
- `cleanup_rejected` 기본 true

`run-selected`는 JSON body의 `character_ids`를 사용하며 최대 30개까지 허용한다. 현재 페이지 테스트 UI에서는 진행률을 보이기 위해 최대 10개씩 나누어 이 엔드포인트를 호출한다. 전체 자동 검사와 동일한 검사/재생성/자동 레이팅 로직을 사용하되 후보 범위만 전달된 캐릭터로 제한한다. 응답의 `inspected_character_ids`에는 요청·후보 전체가 아니라 `_inspect_existing`까지 실제로 완료된 캐릭터 ID만 포함되어 임시 초기화 대상을 정확히 추적한다.

페이지 테스트가 실제로 검사한 캐릭터 ID는 서버가 `settings` 테이블의 `pending_inspection_test_character_ids`에 직접 기록한다. 브라우저 상태에 의존하지 않으므로 새로고침이나 다른 탭에서도 초기화 대상이 유지되며, `stats`의 `test_tracked`로 개수를 확인한다.

`run-selected`는 기본 `force_recheck=true`로 현재 페이지 카드를 checker version과 무관하게 다시 검사한다. 전체 `run`은 기존 증분 skip을 유지한다. WD 태거는 HF router를 먼저 시도하고, Provider 미지원 시 이미 설치된 로컬 ONNX(`data/models/wd-tagger`)로 폴백한다. `tagger_error`/`tagger_unavailable`/`tagger_no_predictions`는 identity checker version을 찍지 않아 재검사 대상에 남는다.

`reset-selected`는 캐릭터 ID를 최대 1000개까지 받아 최신 이미지 검사 메타데이터와 `auto_inspection=...;test=1` 자동 판정만 초기화한다. `character_ids`를 비워 보내면 서버가 기록한 페이지 테스트 대상을 사용하고, 초기화한 ID는 추적 목록에서 제거한 뒤 남은 개수를 `test_tracked_remaining`으로 돌려준다. 실제 이미지 파일과 테스트가 아닌 기존 자동검사/수동 결과는 보존한다.

추적 기록이 없을 때(예: 서버 기록 이전에 실행한 테스트) UI 버튼은 `현재 페이지 검사 결과 초기화`로 바뀌어 현재 화면에 보이는 카드만 대상으로 되돌린다.

HF Token이 없거나 기존 V2 생성/재생성 작업이 진행 중이면 실제 검사 작업을 시작하지 않고 409로 중단한다. 테스트 초기화도 V2 생성/재생성 작업 중에는 실행하지 않는다.

## 후속 보정

최초 운영 시 자동 완료된 `0/1/-1`의 audit sample을 우선 검수한다. 오분류는 `review_note`의 `auto_inspection=...` 예측과 최종 rating을 비교해 원인별로 집계한다.

2성은 개인 기피 취향에 의존하므로 현재 버전에서는 자동 판정하지 않는다. 충분한 audit 데이터가 쌓인 후 별도 개인화 규칙/경량 분류기로 추가하는 편이 안전하다.