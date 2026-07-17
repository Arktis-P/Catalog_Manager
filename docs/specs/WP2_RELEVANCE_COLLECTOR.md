# WP2: 외형 태그 관련도 수집기 + 선정 로직 (담당: gpt 5.6 sol)

기준: `docs/PLAN_IMAGE_GENERATION_REVIEW_V2.md` §4 전체, §9.1(최초 포스트 날짜).
선행: WP1 완료 (모델 `CharacterAppearanceTagRelevance`, `global_characters` 신규 컬럼, v2_* 설정 존재).

## 착수 전 필독 파일

- `backend/app/integrations/danbooru/client.py` (레이트리밋·요청 패턴)
- `backend/app/integrations/danbooru/appearance_extractor.py` (기존 외형 태그 수집 방식)
- `backend/app/services/collect_job_manager.py` (Job 진행 관리 패턴)
- `backend/app/services/db_write_queue.py`
- `backend/app/services/settings_service.py` (v2_* 설정 읽기)

## 범위

- 신규: `backend/app/services/tag_relevance_service.py` (수집·계산·선정 핵심 로직)
- 신규: `backend/app/services/relevance_collect_job_manager.py` (또는 기존 collect_job_manager 확장 — 기존 패턴에 맞춰 판단)
- 신규: `backend/app/routers/` 에 수집 트리거·진행 조회 API (기존 라우터 패턴 준수, 적절한 파일 선택/신설)
- 신규: `backend/tests/test_tag_relevance_service.py`
- 스코프 밖: 프론트엔드, 이미지 생성, 검사기

## 기능 요구

### 1. 동시 등장 수집

캐릭터 태그별로, 수집 대상 카테고리(머리색/머리모양/multicolor/눈색/기타 외형)의 각 태그에 대해:

```
relevance = {character_tag AND appearance_tag 동시 등장 포스트 수} ÷ {character_tag 전체 포스트 수}
```

- Danbooru counts API(`/counts/posts.json?tags=A B`) 사용, 기존 client의 레이트리밋 준수
- 태그 후보군: 기존 appearance_extractor가 수집해 둔 캐릭터별 태그(hair_color, hair_shape, multi_color_hair, eye_color, feature_tags) + 설정 `v2_feature_tag_whitelist`
- 결과를 `character_appearance_tag_relevance`에 upsert (unique: character+tag), `collected_at` 갱신
- 부분 실패 시 캐릭터 단위로 에러 기록 후 다음 캐릭터 진행 (기존 collect 패턴과 동일)

### 2. 최초 포스트 날짜

- 캐릭터당 Danbooru posts API로 가장 오래된 포스트 1건 조회(`order:id_asc limit 1`) → `global_characters.first_post_at` 저장
- 관련도 수집과 같은 Job에서 함께 수행

### 3. 선정 로직 (설정값 기반, 하드코딩 금지)

- 임계값: 카테고리별 `v2_relevance_threshold_*`, 최소 동시 등장 `v2_relevance_min_cooccurrence`
- 전체 포스트 < `v2_relevance_min_posts_auto_confirm`(20): `is_prompt_candidate`만 표시, `is_confirmed`는 False 유지 (추천만)
- 전체 포스트 20~99: 임계값 + `v2_relevance_small_sample_bonus`
- 대표 머리색: hair_color 카테고리 중 relevance 1위 → `global_characters.primary_hair_color`. 2위와의 차이가 0.05 미만이거나 동률이면 `primary_hair_needs_review=True` (값은 그래도 1위로 저장)
- multicolor: 임계값 통과 태그만 `is_prompt_candidate=True`
- 선정 후 기준 통과 태그로 `is_prompt_candidate` 일괄 갱신

### 4. Job·API

- 전체/선택 캐릭터 대상 재수집 Job (진행률, 취소, 에러 카운트 — 기존 Job Manager 패턴 재사용)
- API: 수집 시작, 진행 조회, 캐릭터별 관련도 목록 조회 (스키마는 `backend/app/schemas/`에 신규 파일로)

## 테스트

- 관련도 계산·임계값·소표본 보정·대표 머리색 동률 판정을 Danbooru 호출 mock으로 단위 테스트
- upsert 재실행 시 중복 생성 없음 검증

## 완료 기준

- `cd backend && python -m pytest tests/ -x` 전체 통과
- Danbooru 실호출 없는 테스트 구성 (mock)
- 커밋 금지, 스코프 밖 파일 수정 금지
