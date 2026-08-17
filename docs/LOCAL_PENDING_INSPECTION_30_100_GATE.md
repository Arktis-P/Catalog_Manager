# Pending 자동 검사 — D/E 보강 및 30→100 파일럿 게이트

기준 브랜치: `agent/pending-review-auto-inspection`
기준 HEAD: `4318351b932bfa454a74ae58141e037baf96044d` 이상

## 목적

A(undetected 정상), B(hair mismatch), C(gallery)는 실제 NAIA E2E를 통과했다. 전체 Pending 자동 검사로 확대하기 전에 아직 live로 확인되지 않은 D(atypical swimsuit/underwear), E(female low-confidence → multicolor/eye)와 실제 30/100개 표본에서의 오탐·재생성 비용을 검증한다.

## 0. 현재 코드는 유지

현재 수정된 정책을 먼저 다시 바꾸지 않는다.

- page test: `force_recheck=true`, `auto_complete=false`, `cleanup_rejected=false`
- production `/run`: 기존 자동완료 정책 유지
- 각 repair stage의 generation job은 1장씩만 생성
- semantic/quality 동일 stage는 outer loop에서 최대 2회
- `character_tag_undetected` / `boy_character_tag_undetected` 단독은 non-actionable
- hair mismatch: expected hair < 0.30 이면서 다른 plain hair color >= 0.55인 경우에만 actionable
- hair repair는 `character.primary_hair_color`를 우선하며 relevance top이 이를 덮지 못함

## 1. D: atypical swimsuit/underwear를 무작위 30에서 기다리지 말고 표적 검증

먼저 기존 DB에서 다음 순서로 후보를 찾는다.

1. 과거 검사 결과/이미지 중 `identity_reasons`에 `atypical_swimwear:` 또는 `atypical_underwear:`가 있었던 pending 캐릭터
2. 이전 실험에서 실제 atypical swimsuit가 확인됐던 캐릭터(예: 해당 데이터가 아직 pending이라면 `senpai-san_(douki-chan)` 같은 기존 표본)
3. 없으면 latest WD 결과에 bikini/swimsuit/underwear score가 높고, cached reference profile의 `swimwear_ratio`/`underwear_ratio`가 낮은 pending 캐릭터를 조회

표적 1~3개만 `run-selected`로 force 검사한다.

성공 조건:

- 머리색 conflict가 있으면 `identity_hair`가 먼저 실행
- identity가 허용된 뒤에만 `semantic_outfit`
- `semantic_outfit` 1회 생성 → 새 latest image 재검사
- 계속 atypical이면 동일 semantic stage 최대 1회 추가(총 2장)
- reference sample 부족/실패면 억지 reject하지 않음
- page test이므로 최종 0성 후보가 나와도 실제 review 자동완료는 하지 않음

`swimwear_ratio`가 높은 실제 수영복 버전/캐릭터는 reject하지 않는 것이 정상이다. D 검증을 위해 canonical swimsuit 캐릭터를 억지로 atypical로 만들지 말 것.

## 2. E: female low-confidence → multicolor/eye 표적 검증

무작위 30개에 후보가 없으면 DB에서 후보를 찾는다.

우선순위:

1. pending + `CharacterAppearanceTagRelevance(tag_category='multicolor')` prompt candidate 존재
2. pending + eye_color relevance 존재
3. 현재/과거 WD 결과에서 `character_tag_low_confidence`가 나온 캐릭터

자연 발생 후보가 있으면 1~2개만 live NAIA 실행한다.

기대 순서:

- hair mismatch가 있으면 `identity_hair` 우선
- hair conflict가 없고 actionable low-confidence가 지속되면 여캐만 `identity_multicolor`
- multicolor 근거가 없으면 generation 없이 stage unavailable → eye로 진행
- eye 근거가 없으면 generation 없이 unavailable
- 실제 variant가 있는 stage만 generation budget 소비
- 각 생성 후 latest image 재검사

자연 발생 low-confidence 후보가 없으면 E를 억지로 만들기 위해 실제 DB/WD threshold를 변경하지 말 것. 실제 DB relevance + mocked identity result 조합의 integration test로 stage prompt를 검증한 뒤, 30/100 파일럿에서 자연 발생 시 live 확인한다.

## 3. 페이지 30개 파일럿

D/E 표적 검증 후 현재 페이지 30개를 실행한다.

반드시 기록:

- requested / inspected
- tagger success / error
- pass / warning / reject
- regeneration character 수
- regeneration image 수
- stage별 횟수: identity_hair / multicolor / eye / semantic_outfit / semantic_gallery / quality
- reinspection count
- final_action: pass / manual / 0성 후보
- 실제 exception 수

수동 육안 확인:

- 모든 재생성 캐릭터의 before/latest-after 이미지
- 재생성하지 않은 정상 이미지 중 최소 10개
- 0성 후보 전부

즉시 중지 조건:

- 정상으로 보이는 이미지가 외형 repair에 들어감
- primary hair가 수집값과 다른 색으로 변경됨
- `character_tag_undetected` 단독 재생성 발생
- 동일 stage가 2회를 초과
- 생성된 최신 이미지가 재검사되지 않음
- `identity_result_missing`이 identity warning/result가 존재하는 상황에서 재발
- stage handoff가 빨간 failed로 표시

## 4. 100개 파일럿

30개에서 위 문제 0건이면 100개로 확대한다.

현재 UI에 100개 제한 실행 기능이 없다면 **전체 자동 검사 버튼을 사용하지 말고**, 로컬에서 API/스크립트로 100개만 제한하거나 UI에 임시 `100개 파일럿` 버튼을 추가한다.

100개에서는 저장/API 비용을 추정한다.

보고할 지표:

- inspected = 100
- regenerated characters / 100
- regeneration images / 100
- 평균 regeneration images per regenerated character
- stage별 regen 분포
- 0성 후보 수
- 수동 확인 false regeneration 수
- semantic miss 수(사람 눈에는 실패인데 자동 pass)
- tagger error 수

안전 정지 기준(초기 보수 기준):

- false regeneration >= 1건: 전체 확대 금지, 원인부터 수정
- tagger error > 0: 전체 확대 금지
- regenerated characters > 10%: 원인 샘플링 후 threshold/규칙 재검토
- 0성 후보 > 5%: 전부 육안 검토 후 확대 여부 판단
- 평균 regen images/regenerated character > 2.0: stage 낭비 여부 조사

위 비율은 품질 목표가 아니라 대량 실행 전 이상 징후를 잡기 위한 임시 안전선이다. 실제 데이터 특성상 정당한 실패율이 높다는 근거가 확인되면 조정할 수 있다.

## 5. 테스트 모드의 prompt mutation 주의

현재 identity repair는 실제 생성에 사용할 `character.base_prompt` / `primary_hair_color` 등을 갱신할 수 있다. `테스트 결과 초기화`는 생성 이미지 자체를 롤백하지 않는 것과 마찬가지로, 이 prompt revision까지 완전한 과거 상태로 복원하는 기능으로 가정하지 않는다.

따라서 30/100 파일럿에서 identity repair가 발생한 캐릭터는 다음을 반드시 기록한다.

- before_base_prompt
- after_base_prompt
- revision_reason
- primary_hair_color before/after

잘못된 수정이면 즉시 해당 캐릭터를 수동 복원하고 원인을 고친다.

테스트 초기화를 완전한 sandbox rollback으로 만들 필요가 생기면 별도 작업으로 설계한다. 현재는 대규모 snapshot 저장을 추가하지 않는다.

## 6. 전체 Pending 실행 전 마지막 게이트

전체 실행 허용 조건:

- A/B/C live E2E PASS
- D live E2E PASS 또는 실제 atypical 후보 부재가 명확하고 관련 integration test PASS
- E live E2E PASS 또는 자연 후보 부재 + actual DB relevance integration test PASS
- 30개 파일럿 PASS
- 100개 파일럿에서 false regeneration 0
- tagger error 0
- 재생성 비용이 예상 범위
- 0성 후보를 사용자가 납득할 수 있음

그 다음에도 한 번에 전체 31k를 무감시 실행하지 않는다. 가능하면 500~1000개 단위 제한 실행 기능을 추가한 뒤 단계적으로 확대한다.

## 7. 로컬 작업자 보고 형식

1. D 표적 live 결과
2. E 표적 live 또는 후보 부재 근거
3. 30개 집계 + 잘못 재생성된 이미지 수
4. 100개 집계 + 위 비용/오탐 지표
5. 발견 버그와 수정 SHA
6. 전체 확대 가능 / 보류 판정
