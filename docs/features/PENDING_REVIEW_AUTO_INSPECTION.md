# Pending Review Auto Inspection

## 목적

이미 1회 생성이 끝난 V2 캐릭터 중 `review_status=pending`인 항목만 자동 검사하여 사람이 다시 볼 절대 수를 줄인다.

이 기능은 완료된 리뷰를 다시 검사하지 않는다. 이후 새로 생성하거나 재생성하는 V2 이미지에는 동일한 검사 로직이 기존 V2 quality/identity 파이프라인을 통해 자동 적용된다.

## 자원 절약 원칙

- 로컬 비전 모델을 추가하지 않는다.
- 이미 사용 중인 Hugging Face WD 태거의 1회 예측 결과를 semantic 검사에도 재사용한다.
- Danbooru 참조 이미지를 다운로드하거나 저장하지 않는다.
- `{character_tag} solo` 최대 60개 포스트의 태그 메타데이터만 1회 조회하고 작은 JSON profile로 캐시한다.
- 참조 profile은 자동 완료된 캐릭터에서 즉시 제거한다.
- 자동 재생성은 기본 최대 2회로 제한한다.
- 재생성 후 이전 reject 이미지는 cover/provisional이 아닌 경우 삭제하여 저장공간 증가를 제한한다.
- UI는 10개 단위 배치로 순차 처리한다. 같은 배치에서 진행이 멈추면 무한 재시도하지 않고 자동 중단한다.

## 검사 흐름

```text
pending + 기존 이미지 1장
  -> 기존 quality 검사
  -> 기존 HF WD identity 검사 1회
     -> 동일 WD 결과로 semantic 검사
     -> 필요할 때만 compact Danbooru reference profile 비교
  -> pass/warning: pending 유지
  -> reject: 기존 V2 재생성 파이프라인으로 최대 2회 재생성
       -> 생성될 때마다 quality -> identity -> semantic 재검사
  -> 성공: 최신 1장 유지 + 이전 reject 파일 정리
  -> 제한까지 실패: rating 0 자동 후보
```

## Semantic reject

보수적으로 명확한 실패만 자동 재생성한다.

- `multiple_views`, `character_sheet`, `reference_sheet`, `collage` 등 이미지 속 이미지/시트형 출력
- 카드, 포스터, 화면, 인쇄 의상 신호가 여러 개 겹치거나 다중 인물 신호와 같이 검출되는 경우
- reference profile에서 수영복/속옷 비중이 매우 낮은데 생성 이미지에서 해당 복장이 높은 confidence로 검출되는 경우
- 안정적인 여성 reference인데 생성 결과가 비인간으로 강하게 검출되는 경우

단일 `print_shirt` 같은 약한 신호 하나만으로는 자동 reject하지 않는다.

## Reference profile

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

- `-1`: reference가 안정적으로 비인간일 때 후보
- `1`: 원본 reference가 안정적으로 남성이고 생성 결과도 남성일 때 후보
- `3`: 원본 reference는 남성이지만 생성 결과가 여성으로 안정적으로 바뀐 경우. **자동 완료하지 않고 pending rating만 3으로 미리 입력**한다.
- `0`: 자동 재생성 제한까지 모두 실패한 경우

`-1`, `1`은 confidence 0.85 이상에서만 자동 완료한다. `0`은 재생성 제한 소진이 명확한 근거이므로 confidence 1.0으로 취급한다.

자동 완료 대상의 기본 10%는 deterministic audit sample로 남겨 `review_status=pending` 상태에서 예측 rating만 입력한다. 사용자의 수정 결과는 `review_note`에 남은 자동 예측 정보와 비교하여 이후 threshold/규칙 보정에 사용할 수 있다.

기존에 사용자가 rating을 입력한 pending 항목은 자동 rating이 덮어쓰지 않는다.

## UI

Review -> V2 검수 상단의 `Pending 자동 검사` 패널에서 실행한다.

- `남은 Pending 자동 검사`: 남은 대상 전체를 10개 배치로 순차 실행
- `현재 배치 후 중지`: 진행 중인 배치 완료 후 안전하게 멈춤
- `상태 새로고침`: 현재 검사 완료/남은 수 갱신

완료된 리뷰는 대상 수에도 포함하지 않는다.

## API

- `GET /api/review/v2/pending-inspection/stats`
- `POST /api/review/v2/pending-inspection/run`

`run` 주요 파라미터:

- `limit` 기본 50, 최대 500
- `auto_regenerate` 기본 true
- `max_regenerations` 기본 2, 최대 5
- `auto_complete` 기본 true
- `audit_sample_rate` 기본 0.10
- `cleanup_rejected` 기본 true

## 후속 보정

최초 운영 시 자동 완료된 `0/1/-1`의 audit sample을 우선 검수한다. 오분류는 `review_note`의 `auto_inspection=...` 예측과 최종 rating을 비교해 원인별로 집계한다.

2성은 개인 기피 취향에 의존하므로 현재 버전에서는 자동 판정하지 않는다. 충분한 audit 데이터가 쌓인 후 별도 개인화 규칙/경량 분류기로 추가하는 편이 안전하다.
