# Pending 자동 검사 - Live E2E 진입 전 최종 게이트

기준 브랜치: `agent/pending-review-auto-inspection`

현재 HEAD 기준 결정 로직/회귀 테스트는 충분히 정리되었지만, 전체 Pending 자동 검사를 돌리기 전에 **실제 NAIA + 실제 로컬 WD + 실제 DB**로 최소 E2E를 통과해야 한다.

## 0. 먼저 고칠 것: stage 재생성 횟수 중복

현재 `PendingReviewInspectionService._repair_with_stages()`는 semantic/quality stage에서 `per_job_attempts=max_regenerations`를 사용하고, 동시에 `RepairContext.attempted_stages`로 같은 stage를 최대 2회 다시 허용한다.

`max_regenerations=2`라면 semantic stage가:

- stage job #1 안에서 최대 2장
- 여전히 reject면 stage job #2 안에서 최대 2장

즉 **최대 4장**까지 생성될 수 있다. 이는 로컬/API/저장공간 절약 목표와 "재생성 후에도 남아 있으면 한 번 더"라는 정책에 맞지 않는다.

수정 원칙:

- pending inspection의 **외부 stage loop가 재시도 횟수를 단독 소유**한다.
- `_regenerate_capped(... external_stage_control=True)`에는 stage당 `max_regenerations=1`만 전달한다.
- semantic_outfit / semantic_gallery / quality는 `RepairContext`에서 각각 최대 2회 stage 실행을 허용한다.
- identity_hair / identity_multicolor / identity_eye는 각각 최대 1회다.

완료 테스트:

- semantic_gallery가 계속 reject인 fixture에서 생성 함수 호출 총합이 정확히 2회인지 확인.
- quality reject 지속 시에도 총합이 정확히 2회인지 확인.
- hair -> multicolor -> eye는 각 1회 이하인지 확인.

## 1. 페이지 테스트는 자동 rating 완료를 막을 것

현재 페이지 테스트는 검증용이다. 실제 이미지/프롬프트 변경은 필요하지만 테스트 중 `-1/0/1`을 completed 처리할 필요는 없다.

`PendingInspectionPanel.tsx`의 현재 페이지 `/run-selected` 요청에만:

- `auto_complete=false`
- `cleanup_rejected=false`
- `force_recheck=true`

를 명시한다.

전체 Pending `/run`의 production 정책은 기존 `auto_complete=true`를 유지한다.

페이지 테스트에서도 backend `character_diagnostics.final_action`으로 `0성` 후보 여부는 확인할 수 있으므로 자동 완료를 막아도 로직 검증에는 문제가 없다.

## 2. 아직 남은 appearance 검사 blind spot: character tag 미검출 시 hair mismatch

현재 `identity_checker.evaluate_identity()`는 character tag 판정을 `if/elif`로 먼저 처리한다.

따라서 WD vocabulary에 캐릭터 태그가 없으면 `character_tag_undetected`만 남고, **생성 이미지 머리색이 수집된 대표 머리색과 명백히 달라도 `hair_color_mismatch`가 추가되지 않는다.**

첫 페이지 실험에서 대부분 캐릭터가 `character_tag_undetected`였으므로 이 상태로는 사용자가 요구한 "캐릭터 태그가 없어도 수집된 머리색을 기준으로 외형 repair"가 상당수 작동하지 않을 수 있다.

단, 단순히 expected hair tag가 안 잡혔다고 전부 mismatch로 만들면 모자/가림/저신뢰 이미지 때문에 대량 오탐 재생성이 생길 수 있다.

### 권장 보수 판정

`appearance_extractor.HAIR_COLORS`를 이용한다.

- expected primary hair score >= 0.30: hair match
- expected primary hair score < 0.30 **그리고 다른 HAIR_COLORS 중 하나가 >= 0.55**: `hair_color_mismatch`
- expected가 안 잡혔지만 강한 다른 머리색도 없음: `hair_color_unknown` 또는 아무 actionable reason도 만들지 않음
- `character_tag_undetected` 자체는 계속 non-actionable

진단용으로 가능하면:

- `hair_color_mismatch`
- `hair_color_conflict:<detected_tag>:<score>`

두 reason을 같이 남긴다.

이 변경을 하면 identity checker version을 올려 기존 pending 이미지가 새 외형 판정으로 다시 검사되게 한다.

### 실제 샘플 확인 후 임계값 확정

아래 3종을 각각 2~3장만 조사한다.

1. character tag 미검출 + 실제 머리색 정상
2. character tag 미검출 + 실제 머리색 명백히 틀림
3. 머리카락 가림/모자 등으로 hair tag 자체가 약함

각 이미지의 HAIR_COLORS top scores를 출력하고 0.30/0.55가 실제로 안전한지 확인한 뒤 조정한다. 전체 큐를 대상으로 임계값 튜닝하지 않는다.

## 3. Live E2E는 5건부터

30개를 바로 실행하지 않는다. 실제 데이터를 보면서 아래 5건만 골라 실행한다.

A. 정상 이미지 + character_tag_undetected
- 기대: 재생성 0
- auto-zero 0

B. 실제 hair mismatch
- 기대: identity_hair 1회
- prompt는 수집 대표 머리색 유지/강화
- 새 이미지 재검사

C. semantic_gallery
- 기대: semantic_gallery 1회 -> 재검사
- 새 이미지도 gallery면 최대 1회 추가 -> 총 2회 이내

D. atypical swimsuit/underwear
- identity가 허용될 때만 semantic_outfit
- 총 semantic 재생성 2회 이내

E. 여캐 identity low-confidence + 수집 multicolor/eye 데이터 존재
- hair가 맞으면 multicolor -> eye 순서
- 데이터 없는 stage는 생성 없이 skip

공통 설정:

- `auto_complete=false`
- `cleanup_rejected=false`
- 실제 이미지 보존
- test reset은 검사 메타데이터 확인용으로만 사용

## 4. Live E2E에서 반드시 수집할 값

캐릭터별:

- character id/tag
- 시작 latest image id
- 시작 image count
- WD character confidence
- WD primary hair score
- WD 다른 hair color top 3
- identity reasons
- semantic reasons
- attempted stages
- unavailable stages
- 각 stage before/after prompt
- 각 stage generated image id
- regeneration 총 이미지 수
- reinspection 횟수
- final_action

`stage_events`는 backend diagnostics에 존재한다. 실제 검증 시 API response 또는 debug log에서 확인한다. 토큰/API key는 출력하지 않는다.

## 5. 성공 기준

5건 검증에서 다음을 모두 만족해야 한다.

- `identity_result_missing` 오탐 0
- 정상 stage handoff의 빨간 failed job 0
- character_tag_undetected만으로 재생성 0
- hair mismatch는 대표 머리색으로 1회 repair
- semantic stage는 종류별 최대 2장
- 재생성된 새 latest image가 반드시 검사됨
- stage unavailable은 생성 횟수 0
- 실제 NAIA/network exception만 failed 표시

하나라도 실패하면 30개 테스트로 확대하지 않는다.

## 6. 다음 확대 순서

### Gate 1: curated 5건
위 5종 수동 선택. 성공해야 다음 단계.

### Gate 2: 현재 페이지 30건
- 사용자 육안으로 false regeneration 확인
- 자동 재생성 이유가 명백하지 않은 항목을 기록
- 특히 hair repair 오탐을 확인

권장 목표:
- 명백한 semantic 실패 재생성 성공
- 정상 이미지의 불필요 재생성 0~1건 수준
- 예상 밖 auto-zero 후보 0

### Gate 3: 100건 제한 실행
30건 결과가 안정적인 경우에만 100건 샘플 실행.

확인:
- 평균 regeneration images / inspected character
- tagger_error
- semantic reject 비율
- identity repair 비율
- 0성 후보 비율
- false positive 표본

이 지표가 비정상적으로 크면 전체 큐 실행 금지.

### Gate 4: 전체 Pending
위 3단계를 통과한 뒤에만 전체 자동 검사를 실행한다.

## 7. 완료 보고 형식

1. stage retry 중복 수정 여부 + 테스트
2. page test auto_complete=false 여부
3. hair conflict 샘플 점수와 확정 threshold
4. curated 5건 결과 표
5. 각 케이스 실제 regeneration 수
6. 잘못 재생성된 정상 이미지 유무
7. commit SHA
8. 30건 확대 실행 가능 / 불가 판정
