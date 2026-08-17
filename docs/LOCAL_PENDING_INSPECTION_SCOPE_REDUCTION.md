# Pending 자동 검사 기능 축소안 — Artifact-only 운영 모드

기준 브랜치: `agent/pending-review-auto-inspection`
기준 HEAD: `889e724c841e0d030b1430a92cd74d00a264562a` 이상

## 결정

현재 broad auto-inspection은 identity / hair / multicolor / eye / gender / non-human / semantic / 0/-1/1 auto-rating / suspect queue까지 너무 많은 결정을 한 번에 소유한다. 실제 사용자 체감 정확도가 약 50%라면 이 구조는 검수 부담을 줄이기보다 "자동 판정이 맞는지 다시 확인"하는 새로운 부담을 만든다.

따라서 production 기본 모드는 **artifact-only**로 축소한다.

유지:
- V2 기본 rating 3 prefill
- 생성/재생성 직후 검사 hook
- 작은 얼굴 / 옷 프린트 / side panel / embedded gallery / character sheet 등 명백한 artifact의 자동 재생성
- 재생성본 재검사
- 최대 재생성 횟수 cap
- 작업 목록 표시
- local WD 사용 및 reference image 비저장

기본 비활성:
- 자동 0성
- 자동 -1성
- 자동 1성
- hair / multicolor / eye 자동 repair
- gender 기반 자동 완료
- broad identity failure에 의한 자동 재생성
- suspect/local-review 큐를 일반 사용자가 반드시 처리해야 하는 흐름
- 전체 31k를 semantic v1.8 기준으로 강제 재검사하는 동작

선택 기능:
- atypical swimsuit/underwear 자동 재생성은 별도 feature flag로 둔다. 현재 live 검증 결과가 나쁘지 않았으므로 코드는 유지하되 기본 OFF로 두어 artifact-only의 정확도를 먼저 확보한다.

## 1. Ctrl+Enter 후 결과가 사라져 보이는 현상

현재 V2 Ctrl+Enter 일괄 저장은 rating이 있는 visible item을 `completed`로 저장한 뒤 pending 목록을 다시 불러온다. 따라서 저장한 캐릭터는 pending 페이지에서 사라지는 것이 정상이다.

`auto_inspection_result=` provenance 자체가 삭제되는 것으로 단정하지 말고, completed filter에서 동일 항목을 조회해 marker가 남는지 확인한다.

artifact-only로 축소한 뒤에는 일반 사용자에게 provenance/suspect queue를 주요 UX로 강제하지 않는다. 필요하면 카드에 `자동 재생성됨` 정도만 유지한다.

## 2. Artifact-only 판정

자동 재생성 허용 reason을 allowlist로 제한한다.

예:
- `embedded_gallery:*`
- `printed_character_gallery`
- `weak_print_gallery` 중 복합 신호 충족 케이스
- `goods_or_screen_character_gallery`
- `multi_subject_output:*` 중 실제 cover에 다중 얼굴/인물이 출력된 경우

단순 warning / weak single signal은 자동 재생성 금지.

`gallery_suspect:*`는 기본적으로 pass-through. 개발/진단 필터로는 남겨도 되지만 사용자가 반드시 확인해야 하는 queue로 만들지 않는다.

## 3. 작은 얼굴 miss를 위한 targeted 2-stage

WD만으로 약한 작은 얼굴/옷 프린트가 누락될 수 있다. 전체 이미지에 더 무거운 모델을 추가하지 않는다.

1차: 현재 WD semantic strong compound rule.

2차 후보는 다음 약신호가 있을 때만:
- `character_print >= 0.10`
- `print_* >= 0.20`
- `multiple_views >= 0.20`
- `multiple_girls|multiple_boys >= 0.10`
- `card|poster|screen|text` 조합

2차에서 사용할 lightweight detector를 로컬 작업자가 조사한다.
우선순위:
1. 이미 설치되어 있는 모델/라이브러리 재사용
2. 100MB 이하 ONNX anime face/person detector
3. 새 대형 모델 다운로드는 금지

목적은 identity가 아니라 **작은 얼굴 개수/크기 분포**만 판정하는 것.

권장 feature:
- main face 1개가 크고
- 추가 face가 2개 이상이며 각각 main face 면적의 5~35% 정도
- 또는 clothing/body 영역 주변에 여러 작은 face가 반복

이면 artifact suspect/reject를 보강한다.

정확한 threshold는 known miss 5~10장 + 정상 10장으로 로컬 작업자가 한 번만 검증한다. 랜덤 30/100 반복 테스트는 하지 않는다.

## 4. 기존 Pending 처리

기존 31k 전체에 broad v1.8 재검사를 강제하지 않는다.

옵션 A (권장): 앞으로 생성/재생성되는 이미지에 artifact-only를 자동 적용.

옵션 B: 기존 pending에 대해 사용자가 원할 때만 `Artifact cleanup` 배치 실행.
이 배치는:
- rating/status 자동 완료 금지
- prompt identity mutation 금지
- artifact strong reject만 regeneration
- 최대 1~2회 재생성
- 나머지는 건드리지 않음

## 5. UI 단순화

PendingInspectionPanel의 기본 UI는 다음만 노출:
- `기존 Pending artifact 정리` (선택)
- 진행 수 / 재생성 수 / 오류

숨기거나 개발자용으로 이동:
- 0/-1/1 자동판정 지표
- suspect/local-review queue
- provenance outcome 복잡한 필터
- broad identity stage diagnostics

V2 카드에는 필요한 경우만:
- `자동 재생성됨 N회`
- `artifact 검사 통과`
정도의 간단한 badge를 표시.

## 6. 완료 조건

- 생성/재생성 직후 artifact strong reject는 자동 재생성됨
- 재생성본도 다시 artifact 검사됨
- normal image가 identity/gender/hair 사유로 자동 재생성/0/-1/1 처리되지 않음
- Ctrl+Enter 저장은 기존대로 completed 처리하며 inspection marker가 필요하다면 completed에서도 유지됨
- known small-face misses 5~10장 중 탐지율을 보고하되 false positive 0을 우선
- frontend build PASS
- 관련 backend tests PASS

## 7. 보고 형식

1. broad 기능 중 실제 비활성화한 항목
2. artifact allowlist
3. known miss 탐지 결과 / 정상 false positive
4. lightweight 2차 detector를 사용했는지와 추가 리소스 크기
5. Ctrl+Enter 후 provenance가 실제 삭제되는지 vs pending에서 숨겨지는지 확인
6. 최종 commit SHA
