# WP1: V2 스키마·데이터 계층 (담당: gpt 5.5)

기준: `docs/PLAN_IMAGE_GENERATION_REVIEW_V2.md` §4, §13. 이 WP는 V2 전체의 DB 스키마 변경을 **한 번에** 처리한다 (이후 WP들이 모델 파일을 건드리지 않게 하기 위함).

## 범위 (이 파일들만 수정/생성)

- 신규: `backend/app/models/appearance_tag_relevance.py`
- 수정: `backend/app/models/global_character.py`
- 수정: `backend/app/models/global_character_image.py`
- 수정: `backend/app/models/global_character_review.py`
- 수정: `backend/app/models/__init__.py`
- 수정: `backend/app/database.py` (마이그레이션)
- 수정: `backend/app/services/settings_service.py`, `backend/app/schemas/settings.py` (기본값 추가)
- 신규: `backend/tests/test_v2_schema_migration.py`

## 1. 신규 테이블 `character_appearance_tag_relevance`

모델 클래스 `CharacterAppearanceTagRelevance`:

- `id` PK
- `global_character_id` FK global_characters.id ondelete CASCADE, index
- `tag` String(255) not null
- `tag_category` String(50) not null, index — 값: `hair_color | hair_shape | multicolor | eye_color | feature`
- `cooccurrence_count` Integer not null default 0
- `character_post_count` Integer not null default 0
- `relevance_score` Float not null default 0.0
- `is_prompt_candidate` Boolean not null default False
- `is_confirmed` Boolean not null default False
- `collected_at` DateTime nullable
- `created_at`/`updated_at` 기존 모델들과 동일 패턴
- UniqueConstraint(global_character_id, tag)
- GlobalCharacter에 `appearance_relevances` relationship (cascade all, delete-orphan)

## 2. `global_characters` 컬럼 추가

- `primary_hair_color` String(100) nullable
- `primary_hair_needs_review` Boolean not null default False
- `base_prompt` Text nullable (V2 기본 프롬프트)
- `previous_base_prompt` Text nullable
- `prompt_revision_reason` Text nullable
- `prompt_revision_level` Integer nullable
- `first_post_at` DateTime nullable (Danbooru 최초 포스트 날짜)
- `generation_status` String(50) not null default `'not_generated'` , index — 값: `not_generated | generating | generated | generation_failed | likely_untrained`
- `generation_attempts` Integer not null default 0

## 3. `global_character_images` 컬럼 추가

quality 계열:

- `quality_status` String(50) nullable, index — `quality_pass | quality_warning | quality_reject`
- `quality_score` Float nullable
- `quality_reasons` Text nullable (JSON 배열 문자열)
- `quality_checked_at` DateTime nullable
- `quality_checker_version` String(50) nullable

identity 계열:

- `identity_status` String(50) nullable, index — `identity_pass | identity_warning | identity_reject`
- `character_confidence` Float nullable
- `hair_color_confidence` Float nullable
- `conflicting_character_tag` String(255) nullable
- `conflicting_character_confidence` Float nullable
- `identity_reasons` Text nullable (JSON 배열 문자열)
- `suggested_multicolor_tags` Text nullable (JSON 배열 문자열)
- `identity_checked_at` DateTime nullable
- `identity_checker_version` String(50) nullable

기타:

- `is_provisional` Boolean not null default False, index (임시 대표 이미지)
- 기존 `auto_status` 등은 그대로 유지 (마이그레이션 기간 병행)

## 4. `global_character_reviews` 컬럼 추가

- `review_status` String(50) not null default `'pending'` — `pending | in_progress | completed`
- `rating_stage` String(50) not null default `'primary'` — `primary | refinement_pending | final`

기존 컬럼과 겹치는 것이 이미 있으면(예: 완료 플래그) 제거하지 말고 공존시킨다.

## 5. `database.py` 마이그레이션

기존 `_migrate_*_columns()` 패턴(inspector로 컬럼 존재 확인 후 ALTER TABLE)을 그대로 따라 위 컬럼 전부 추가. 신규 테이블은 `create_all`이 처리하므로 모델 import만 추가.

## 6. 설정 기본값 추가

`settings_service.py`의 기존 설정 관리 패턴을 파악해 동일한 방식으로 다음 키·기본값 추가 (`schemas/settings.py`에도 반영):

- `v2_relevance_min_cooccurrence` = 10
- `v2_relevance_threshold_hair_shape` = 0.35
- `v2_relevance_threshold_multicolor` = 0.30
- `v2_relevance_threshold_eye_color` = 0.35
- `v2_relevance_threshold_feature` = 0.20
- `v2_relevance_small_sample_bonus` = 0.10  (포스트 20~99 구간 가산치)
- `v2_relevance_min_posts_auto_confirm` = 20 (미만이면 자동 확정 금지)
- `v2_quality_retry_max` = 3
- `v2_recent_character_cutoff` = "2025-05-01"
- `v2_feature_tag_whitelist` = "glasses,horns,eyepatch,dark_skin,scar,animal_ears,halo,wings,tail" (확장 가능 문자열)

주의: 기존 설정 스키마가 타입별 구조를 가지면 그 구조에 맞춘다. 프론트엔드 설정 UI는 이번 범위가 아님.

## 7. 테스트

`backend/tests/test_v2_schema_migration.py`:

- 임시 SQLite 파일 DB로 init_db 실행 → 신규 테이블·컬럼 존재 검증
- 구버전 스키마(신규 컬럼 없는 테이블)를 수동 생성 후 마이그레이션 함수 실행 → 컬럼 추가 검증
- CharacterAppearanceTagRelevance CRUD + cascade 삭제 검증
- 기존 테스트 패턴(다른 test_*.py의 픽스처 방식) 참고

## 완료 기준

- `cd backend && python -m pytest tests/ -x` 전체 통과 (기존 테스트 포함)
- 스코프 밖 파일 수정 금지 (routers/serializers/frontend 금지)
- 커밋 금지 — 워킹 트리에 변경만 남길 것
