# Pending 자동 검사 — Production Hardening / 무추가 수동 테스트 전환

기준 브랜치: `agent/pending-review-auto-inspection`
기준 HEAD: `47cfa5d2ebfb831f61a33a55dfcf86237738b673` 이상

## 목적

현재까지 실제 NAIA E2E, 30개/100개 파일럿, backend 338개 수준의 회귀 테스트와 frontend build가 수행되었다. 이제 사용자가 동일한 이미지 테스트를 계속 반복하지 않도록 한다.

다음 단계는 **판정 알고리즘을 더 튜닝하는 테스트가 아니라, 대량 실행 시 자동으로 멈추는 production guardrail을 추가하는 것**이다.

이번 작업 후 사용자가 해야 할 것은 전체 검사를 시작하고, 자동 안전 중지가 발생한 경우에만 원인을 확인하는 정도여야 한다.

---

## 1. 현재 정책은 동결

이번 작업에서는 다음 판정 규칙을 다시 튜닝하지 않는다.

- WD local-first
- `character_tag_undetected` 단독은 non-actionable
- hair match >= 0.30
- 다른 plain hair >= 0.55일 때만 actionable hair conflict
- primary hair는 relevance top보다 우선
- identity → semantic 순서
- semantic/quality stage 최대 2회
- 한 stage job당 이미지 1장
- 재생성 이미지 즉시 재검사
- page test는 `auto_complete=false`
- production은 기존 `auto_complete=true` + audit 10%
- semantic v1.7의 비인물 -1 후보 정책 유지

새 threshold를 더 찾거나 30개 수동 테스트를 다시 수행하지 않는다.

---

## 2. 전체 실행에 자동 circuit breaker 추가

관련 파일 우선:

- `frontend/src/components/review/PendingInspectionPanel.tsx`
- 필요하면 작은 helper/test 파일 추가

현재 production `run()`은 remaining이 0이 될 때까지 10개 batch를 계속 실행한다. 이를 **guarded full run**으로 바꾼다.

### 즉시 중지 조건

아래 중 하나라도 발생하면 현재 10개 batch 종료 후 전체 작업을 자동으로 `failed`가 아니라 **`안전 중지` 상태/메시지**로 끝낸다.

1. `result.errors.length > 0`
2. `result.tagger_error > 0`
3. 진행량이 줄지 않는 기존 안전장치 발동

실제 예외가 아닌 guardrail stop은 UI에서 `시스템 오류`와 구분되는 메시지를 사용한다.

예:

`Pending 자동 검사 안전 중지 · tagger 오류 1건 감지 · 340/31,053 처리`

### 누적 비율 안전선

최소 100개 실제 inspected 이후에만 계산한다.

배치별 `character_diagnostics`에서 캐릭터 단위로 집계한다.

- `regenerated_character_count`: 해당 캐릭터 `regeneration_requested > 0`
- `auto_zero_count`: `final_action == "0성"`
- `regeneration_images`: summary의 실제 생성 이미지 수
- `minus_one_count`: 가능하면 `ratings["-1"]` 누적

초기 보수 circuit breaker:

- unique regenerated character / inspected > **15%** → 안전 중지
- auto-zero / inspected > **8%** → 안전 중지
- auto -1 / inspected > **10%** → 안전 중지
- regenerated character가 있을 때 `regeneration_images / regenerated_character_count > 2.5` → 안전 중지

이 수치는 판정 품질 기준이 아니라 **대량 폭주 방지용 비상 브레이크**다. 100개 파일럿의 regen 5%보다 충분한 여유를 둔다.

주의:
현재 `characters_regenerated`는 stage 단위 증가일 수 있으므로 비율 계산에 직접 쓰지 말고 `character_diagnostics`로 unique character를 센다.

---

## 3. 500개 checkpoint 표시 — 자동 계속

사용자에게 500개마다 클릭하게 하지 않는다.

대신 누적 inspected가 500, 1000, 1500...을 넘을 때 작업 카드 message에 checkpoint를 표시하고 **문제가 없으면 자동 계속**한다.

예:

`안전 체크포인트 1,000 · regen 4.8% · 0성 0.7% · -1 1.2% · 오류 0 · 계속 진행`

사용자는 작업 목록만 보더라도 정상 동작을 확인할 수 있어야 한다.

---

## 4. 작업 카드에 production 안전 지표 노출

기존 `prompt_variant_attempts`를 재사용해 별도 DB 저장을 늘리지 않는다.

추가 가능한 lightweight metrics:

- `tagger_error`
- `regen_characters_unique`
- `regeneration_images`
- `auto_zero`
- `auto_minus_one`
- `safety_checkpoints`

작업 카드 message에는 최소:

- 처리 N / total
- 검사 수
- unique 재생성 캐릭터 수
- 실제 추가 생성 이미지 수
- 0성 수
- -1성 수
- 오류 수

를 표시한다.

---

## 5. 자동완료/audit 정책

production의 기존 `auto_complete=true`, `audit_sample_rate=0.10`은 유지한다.

이유:

- 사용자의 최종 목적은 사람의 검수 부담 감소다.
- 30/100 파일럿과 E2E를 이미 거쳤다.
- 자동 결과 10%가 audit pending으로 남아 후속 품질 확인 표본 역할을 한다.

따라서 전체 실행을 다시 `auto_complete=false`로 바꾸지 않는다.

다만 circuit breaker가 발동하면 그 시점 이후 항목은 처리하지 않는다.

---

## 6. cleanup 정책은 현재 유지하되 범위 검증

기본 `cleanup_rejected=true`는 저장공간 절약 목표 때문에 유지한다.

다만 코드 확인으로 다음을 보장한다.

- 현재 최종/latest image는 삭제하지 않음
- cover 선택 이미지 삭제하지 않음
- provisional 선택 이미지 삭제하지 않음
- 실제 superseded reject만 삭제
- DB row 삭제와 파일 삭제가 일치

이 조건의 기존 회귀 테스트가 부족하면 단위 테스트만 추가한다. 실제 이미지 수동 테스트는 필요 없다.

---

## 7. 테스트는 자동화만 수행

사용자에게 추가 이미지 테스트를 요구하지 않는다.

필수 automated validation:

### frontend

- `npm run build`
- 가능하면 helper를 분리하여 circuit breaker unit test

테스트 시나리오:

1. inspected < 100 → 비율 guard 미발동
2. tagger_error 1 → 즉시 stop
3. errors 1 → 즉시 stop
4. 100 inspected / regen 16 → stop
5. 100 inspected / regen 5 → continue
6. 100 inspected / auto-zero 9 → stop
7. 100 inspected / -1 11 → stop
8. regen 10 chars / generation images 26 → stop
9. 500 checkpoint → stop 없이 continue

### backend

기존 관련 tests만 재실행:

- pending inspection service
- semantic image checker
- inspection repair
- v2 generation pipeline / inspection regeneration job

전체 suite는 가능하면 실행하되 기존 unrelated 3 failures는 그대로 분리 보고.

---

## 8. 추가 수동 테스트 금지 / 완료 조건

이 작업 완료 후 다시 30장 페이지 테스트를 요구하지 않는다.

완료 조건:

- circuit breaker automated tests PASS
- frontend build PASS
- 기존 backend 관련 tests PASS
- production run은 10개씩 처리하며 guardrail 자동 감시
- 오류/이상 비율이면 스스로 안전 중지
- 이상 없으면 전체 remaining까지 자동 계속
- 10% audit sample 유지

사용자에게 필요한 동작:

1. 앱 업데이트 후 `남은 Pending 자동 검사` 1회 시작
2. 이후 작업 카드가 정상 진행하는지만 확인
3. 안전 중지가 발생했을 때만 해당 이유를 로컬 작업자/오케스트레이터에게 전달

즉, **더 이상의 반복 수동 품질 테스트를 완료 조건으로 삼지 않는다.**

---

## 9. 완료 보고 형식

1. 변경 파일
2. safety guard 조건
3. automated test/build 결과
4. 기존 unrelated failure 여부
5. 최종 commit SHA
6. 사용자가 실제로 해야 할 일 1~2줄