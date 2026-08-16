# Pending 자동 검사 재생성 실패 - 로컬 수정/검증 지시서

기준 브랜치: `agent/pending-review-auto-inspection`

## 현재 관찰

실제 페이지 테스트에서 `자동 검사 재생성` 작업이 다수 빨간 `실패`로 표시되며 `identity_result_missing`이 반복된다. 같은 캐릭터가 2회씩 보이는 경우도 있고, 상위 `현재 페이지 Pending 자동 검사`는 한동안 `0/30`에 머문다.

이 상태는 **NAIA 이미지 생성 자체가 실패했다는 뜻이 아닐 가능성이 매우 높다.** 현재 코드에서 stage 전환을 실패로 표현하는 버그가 확인된다.

## 이미 원격에서 반영한 안전 수정

`inspection_repair.py`에서 다음을 변경했다.

- `character_tag_undetected`
- `boy_character_tag_undetected`

위 두 warning은 더 이상 identity repair / auto-0 근거로 사용하지 않는다.

이유: 실제 첫 페이지 진단에서 30개 중 대부분이 `character_tag_undetected`였으며, WD vocabulary에 없는 캐릭터가 매우 많다. 이를 실패 신호로 사용하면 정상 이미지까지 hair → multicolor → eye 재생성을 연쇄 실행하고 대량 0성 처리할 위험이 있다.

현재부터 identity repair 예산을 쓰는 핵심 신호는 실제 외형 증거인 `hair_color_mismatch`, `character_tag_low_confidence` 등으로 제한한다.

## 확인된 `identity_result_missing` 원인

### 1. `_failure_reason()`의 잘못된 fallthrough

파일:

`backend/app/services/v2_generation_pipeline.py`

현재 `_failure_reason(image, identity)`는:

- quality reject → `quality_reject:*`
- identity reject → `identity_reject:*`
- 그 외 → `identity_result_missing`

이다.

하지만 stage repair는 **identity warning** (`hair_color_mismatch`, `character_tag_low_confidence`)도 정상적인 repair trigger로 사용한다.

따라서 identity 결과가 실제로 존재해도 warning이면 `identity_result_missing`으로 잘못 기록된다.

수정:

- `identity is None`일 때만 `identity_result_missing`
- `identity.status == "warning"`이면 실제 reasons를 기록

예:

```python
if identity is None:
    return "identity_result_missing"
if identity.status == "reject":
    return f"identity_reject:{...}"
if identity.status == "warning":
    return f"identity_warning:{...}"
return "identity_pass"
```

### 2. stage handoff를 job failure로 표시

파일:

- `backend/app/services/v2_generation_pipeline.py`
- `backend/app/services/pending_review_inspection_service.py`

`check_async_attempt(..., external_stage_control=True)`는 hair/multicolor/eye 같은 warning이 남으면 outer stage loop에 넘기기 위해 내부적으로 `generation_failed` 결과를 만든다.

그 다음 `_regenerate_capped()`가:

```python
final_status = "completed" if checked.result.generation_status == "generated" else "failed"
```

로 처리한다.

즉:

**이미지 생성 성공 → WD 검사 성공 → 다음 repair stage 필요**

인 정상 stage handoff조차 UI에는 빨간 실패 작업으로 남는다.

수정 원칙:

- 실제 generation exception / NAIA 실패 / cancel만 `failed` 또는 `cancelled`
- `external_stage_control=True`에서 이미지 생성과 검사가 끝났고 outer stage가 다음 판정을 맡는 경우는 sub-job을 `completed`로 종료
- 메시지는 `자동 검사 재생성 단계 완료 · {stage} · 다음 판정 대기` 등으로 표시
- character의 최종 `generation_status`와 UI sub-job status를 같은 의미로 강제하지 말 것

가능하면 `V2PipelineResult`에 stage 전용 상태를 새로 넣기보다 `_regenerate_capped`가 `external_stage_control` 여부를 보고 UI job status만 정상화하는 최소 변경을 우선한다.

## 같은 캐릭터 실패 카드가 2개씩 보이는 이유

hair/multicolor/eye 또는 semantic stage가 각각 별도 `inspection_regeneration` job을 만들기 때문이다.

현재는 각 stage가 위 버그 때문에 모두 `failed`가 되어 동일 캐릭터의 빨간 카드가 여러 개 쌓인다.

수정 후에는:

- stage 1 완료
- stage 2 완료
- 최종 pass 또는 0성

처럼 보이게 할 것.

각 job 메시지/표시에 `repair_stage`를 노출해 어떤 단계인지 구분할 것.

예:

- `자동 검사 재생성 · ranni · identity_hair`
- `자동 검사 재생성 · ranni · identity_multicolor`
- `자동 검사 재생성 · ranni · semantic_gallery`

## 상위 작업이 `0/30`에 오래 머무는 이유

파일:

`frontend/src/components/review/PendingInspectionPanel.tsx`

현재 page test도 `BATCH_SIZE = 10`을 사용한다.

프론트 progress는 `/run-selected` 한 요청이 반환된 뒤에만 갱신된다. 그런데 backend는 한 캐릭터 안에서 여러 stage regeneration을 모두 동기 처리한다.

따라서 첫 10명 중 여러 명이 2~3회 재생성되면 하위 job은 계속 뜨지만 상위 작업은 오랫동안 `0/30`으로 보인다.

테스트 모드만 별도:

```ts
const PAGE_TEST_BATCH_SIZE = 1;
```

을 두는 것을 권장한다.

- 전체 backfill: 기존 10 유지
- 현재 페이지 30개 테스트: 1개씩 요청

그러면 1/30, 2/30...으로 실제 진행 상황을 확인 가능하고 중지도 더 빠르게 반영된다.

## 추가로 발견한 repair stage 설계 위험

### 1. hair repair가 '수집된 올바른 머리색'이 아니라 alternate hair로 바꿀 수 있음

파일:

`backend/app/services/v2_generation_pipeline.py::_revision_variants`

현재 level 1은 `primary_hair_color`와 다른 relevance row를 찾아 `alternate_hair`로 교체한다.

하지만 현재 요구사항은:

> 생성 이미지의 머리색이 수집된 대표 머리색과 다르면 **수집된 올바른 머리색을 강화/반영해서 다시 생성**

이다.

따라서 기존 generic revision 로직을 그대로 stage repair에 재사용하지 말고 실제 DB 데이터를 확인할 것.

필수 검증:

- `character.primary_hair_color`가 수집된 최우선 hair인지
- `CharacterAppearanceTagRelevance(hair_color)` 1위가 무엇인지
- 생성 이미지의 WD hair tag가 무엇인지

권장:

- expected hair가 prompt에 없으면 expected hair를 추가/교체
- expected hair가 이미 prompt에 있는데 생성 결과만 틀렸다면 **머리색을 바꾸지 말고 같은 expected hair를 유지한 채 1회 재생성**
- 임의로 2순위 alternate hair를 넣지 말 것

### 2. stage variant가 없는데 같은 prompt로 재생성할 수 있음

현재 `_regenerate_capped()`에서:

```python
variant = pipeline.build_stage_variant(...)
if variant is not None:
    pipeline.apply_variant_to_character(...)
# variant None이어도 아래 generation 계속
```

이므로 해당 stage에 적용할 태그 데이터가 없을 때 **아무 것도 수정하지 않은 동일 prompt를 identity repair라고 재생성**할 수 있다.

수정:

- identity stage에서 variant가 `None`이면 generation을 실행하지 말 것
- `stage_unavailable` 결과로 outer loop에 반환
- 다음 stage가 가능하면 다음 stage로 이동
- 남캐 hair stage가 불가능하고 actionable identity 실패가 확실하면 정책대로 0성 후보
- 여캐 multicolor 자료 없음 → eye stage로 skip
- eye 자료 없음 → 최종 정책으로 진행

stage unavailable은 regeneration budget을 소비하지 않는 편이 바람직하다.

### 3. multicolor stage도 기존 generic revision 의미를 그대로 사용하지 말 것

현재 `_revision_variants`는 기존 multicolor가 있으면 **제거**하는 level 2를 만들 수 있다.

이번 정책은 수집된 multicolor 정보를 **보수적으로 추가/보정**하는 단계다.

로컬 DB의 relevance 데이터를 실제 샘플 5~10개로 확인해서:

- 이미 prompt에 있는 정확한 multicolor는 유지
- 강한 relevance가 있을 때만 하나 추가
- 아무 근거 없으면 stage skip

하도록 수정할 것.

## 로컬 작업 순서

### 1. 더 이상 30개 전체를 바로 돌리지 말 것

먼저 현재 실행을 중지하고 아래 3~5개 캐릭터만 사용한다.

- hair mismatch가 실제 있는 1개
- semantic gallery 1개
- atypical swimsuit 1개
- `character_tag_undetected`지만 사람이 보기엔 정상인 1개
- 가능하면 여캐 multicolor 사례 1개

테스트 설정:

- `cleanup_rejected=false`
- 각 semantic same-prompt retry는 우선 1회
- 실제 파일 보존

### 2. stage별 prompt diff 로그 추가

개발/페이지 테스트에서만 다음을 기록한다. API key/token은 기록 금지.

- character id/tag
- repair stage
- before base_prompt
- after base_prompt
- selected expected hair
- selected multicolor
- selected eye
- generated image id
- identity status/reasons
- semantic reasons
- next stage

전체 backfill에서는 verbose prompt log를 끄거나 debug flag에서만 사용.

### 3. `identity_result_missing` 회귀 테스트

필수:

1. identity warning + `hair_color_mismatch`
   - failure reason이 `identity_result_missing`이 아니어야 함
2. external stage control에서 image generate/check 성공 + 다음 stage 필요
   - visible inspection regeneration job이 `failed`가 아니어야 함
3. identity 진짜 None일 때만 `identity_result_missing`

### 4. WD character tag 미검출 안전성 테스트

필수:

- 여캐 + `character_tag_undetected` only → regeneration 0, auto-zero 아님
- 남캐 + `boy_character_tag_undetected` only → regeneration 0, auto-zero 아님
- 위 상황에 `weak_print_gallery`가 같이 있으면 semantic gallery repair는 정상 실행

원격에서 해당 순수 decision 테스트는 이미 추가했으므로 로컬에서 실행해서 통과 여부를 확인한다.

### 5. stage unavailable 테스트

필수:

- hair relevance 없음 → hair repair가 동일 prompt 재생성을 하지 않음
- multicolor relevance 없음 → multicolor stage skip
- eye relevance 없음 → eye stage skip
- skip된 stage는 regeneration count를 증가시키지 않음

### 6. 실제 NAIA E2E

아래 각각 1건씩만 수행한다.

#### A. semantic gallery

initial reject
→ semantic_gallery job
→ 새 image
→ WD/semantic 재검사
→ pass면 종료
→ 또 reject면 지정 retry 한도 내 1회 추가

#### B. hair mismatch

initial hair mismatch
→ expected hair를 적용한 prompt 확인
→ image 생성
→ 재검사
→ 정상 stage 전환 확인

#### C. character tag undetected only

→ 재생성 **0회**인지 확인

## 권장 테스트 명령

```bash
pytest backend/tests/test_inspection_repair.py -q
pytest backend/tests/test_pending_review_inspection_service.py -q
pytest backend/tests/test_v2_inspection_regeneration_job.py -q
pytest backend/tests/test_identity_checker.py -q
pytest backend/tests/test_semantic_image_checker.py -q
```

추가 회귀 테스트를 넣은 후 같은 명령 재실행.

프론트 수정 후:

```bash
cd frontend
npm run build
```

가능하면 관련 테스트 통과 후에만 실제 page test 5개 → 30개 순으로 확대한다.

## 완료 조건

- `identity_result_missing`이 실제 identity None에서만 나타남
- 정상 stage handoff가 빨간 failed job으로 표시되지 않음
- job에서 repair stage를 확인 가능
- 페이지 테스트 상위 progress가 캐릭터 단위로 증가
- `character_tag_undetected`만으로 regeneration/0성 발생하지 않음
- hair stage가 임의 alternate hair로 바꾸지 않음
- stage data가 없으면 동일 prompt 낭비 재생성하지 않음
- regeneration 결과가 latest image로 재검사됨
- semantic gallery/swimsuit 정상 재시도 확인
- 실제 generation exception만 failure로 표시

## 완료 보고 형식

1. `identity_result_missing` 실제 원인 및 수정
2. job status 수정 결과
3. page progress 수정 결과
4. hair/multicolor/eye prompt diff 실제 샘플
5. stage unavailable 처리 결과
6. 5개 live E2E 결과
7. 관련 pytest / frontend build 결과
8. 최종 commit SHA
