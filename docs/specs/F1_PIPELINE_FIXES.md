# F1: V2 파이프라인 보정 (담당: gpt 5.6 sol)

기준: `docs/PLAN_IMAGE_REVIEW_V2_FOLLOWUP.md` §2.3(백엔드), §2.4, §2.5, §2.2(위키 단계), §5 Phase 1.
기존 구현: `backend/app/services/v2_generation_pipeline.py` (네가 작성한 코드다), `v2_generation_job_manager.py`.

## 범위 (이 파일들만)

- 수정: `backend/app/services/v2_generation_pipeline.py`, `v2_generation_job_manager.py`
- 수정: `backend/app/routers/generation.py`, `backend/app/schemas/generation.py`
- 수정: `backend/app/models/global_character.py`, `backend/app/database.py` (필드 추가)
- 수정: `backend/tests/test_v2_generation_pipeline.py`
- 금지: identity_checker.py, quality_checker.py, character_image_service.py, review_service.py, frontend/, docs/

## 1. 보정 프롬프트 품질 재시도 통일 (§2.4)

현재: 초기 프롬프트만 quality retry 루프, 보정 변형은 quality_reject 시 즉시 다음 레벨.
변경: **각 보정 변형도 동일하게 `v2_quality_retry_max`회 품질 재시도** 후에 다음 레벨로 이동.

- Negative 프롬프트 불변, identity 검사는 품질 통과 이미지에만 (현행 유지)
- 기록 필드 추가 (`global_characters` + 마이그레이션, 기존 `_migrate_global_character_columns` 패턴):
  - `total_generation_attempts` INTEGER NOT NULL DEFAULT 0 (전체 누적 — 기존 generation_attempts를 이 용도로 계속 쓰되, 별칭이 아니라 명시 필드 신설이 깔끔하면 신설)
  - `prompt_variant_attempts` TEXT (JSON: 변형 레벨별 시도 횟수, 예 `{"initial":3,"level_1":2}`)
  - `last_failure_reason` TEXT

## 2. feature 태그 자동 추가 제거 (§2.5)

`_revision_variants()`에서 기타 feature 태그(scar, glasses 등) 일괄 추가 레벨을 제거한다.
자동 보정 레벨은 3개만: 1) 대표 머리색 변경 2) multicolor 제거/추가 3) 눈색 추가. 이후 실패 시 현행대로 generation_failed.

## 3. 위키 조회 단계 제거 (§2.2)

`_collect_wiki_reference()` 및 호출부를 제거한다 (로그만 남기는 형식적 단계였음). 위키 실패가 파이프라인을 막을 여지 자체를 없앤다.

## 4. V2 수동 재생성 API (§2.3 백엔드)

V2 리뷰 카드의 수동 재생성을 위한 단건 실행 API 추가:

- `POST /api/generation/v2/characters/{id}/regenerate` (routers/generation.py 기존 V2 라우트 패턴)
- 요청 body: `{ "base_prompt": str | null }` — 사용자가 카드에서 편집한 프롬프트. 주어지면 **첫 시도 프롬프트로 사용하고 캐릭터 base_prompt에 저장** 후 파이프라인 실행. null이면 현재 base_prompt 사용.
- 동작: 해당 캐릭터를 V2GenerationPipeline.run_character로 실행 (품질 재시도·identity 보정 전 과정 포함). 기존 배치 Job Manager를 단건에도 재사용하거나 단건 실행 엔드포인트를 별도 제공 — 진행 조회 가능해야 함 (프론트 폴링용: job_id 또는 character 단위 상태).
- 응답: generation_status, 시도 횟수, 최종 이미지의 quality/identity 상태·사유, is_provisional 포함 (프론트가 V2 카드를 직접 갱신할 수 있는 형태 — schemas/generation.py에 응답 스키마 정의)
- 실행 중 동일 캐릭터 중복 실행은 409

## 5. pipeline 내 known_character_tags 정리

pipeline의 `known_character_tags` 조회·전달부(약 206행)를 제거하라 (전달 인자 삭제. identity_checker 시그니처는 다른 작업자가 하위 호환으로 유지하므로 인자를 안 넘기면 된다).

## 테스트

기존 test_v2_generation_pipeline.py 갱신 + 추가:

- 보정 레벨 1에서 quality_reject 2회 후 3회째 pass → identity 진행 (레벨 이동 없음 검증)
- 변형별 시도 횟수 기록(prompt_variant_attempts) 검증
- feature 레벨이 더 이상 생성되지 않음 검증
- 수동 재생성 API: 편집 프롬프트 반영·중복 실행 409

## 완료 기준

- `cd backend && ../.venv/Scripts/python.exe -m pytest tests/ -q` 기존 실패 3건(test_db_write_queue, test_series_merge_service, test_wiki_and_membership) 외 전부 통과
- 커밋 금지, 스코프 밖 파일 수정 금지
