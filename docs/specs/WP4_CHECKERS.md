# WP4: 자동 검사 분리 — quality / identity (담당: sonnet 5)

기준: `docs/PLAN_IMAGE_GENERATION_REVIEW_V2.md` §2.2(자동 검사), §6, §8, §10, §13.
선행: WP1 (이미지 모델의 quality_*/identity_* 필드), WP3 (base_prompt).

## 착수 전 필독 파일

- `backend/app/services/image_auto_checker.py` (분리 리팩터링 대상 — 폐기 아님)
- `backend/app/integrations/image_tagger/hf_wd_tagger.py`, `wd14_tagger.py`
- `backend/app/services/character_image_service.py` (이미지 저장 파이프라인)
- `backend/app/services/review_catalog_serializer.py` (응답 직렬화)
- `backend/app/models/global_character_image.py` (저장 필드 — 수정 금지, 읽기만)

## 범위

- 신규: `backend/app/services/quality_checker.py`
- 신규: `backend/app/services/identity_checker.py`
- 수정: `backend/app/services/image_auto_checker.py` (공용 유틸 추출 후 V1 호환 유지 — V1 경로가 깨지면 안 됨)
- 수정: `backend/app/services/character_image_service.py` (V2 검사 연결)
- 수정: `backend/app/services/review_catalog_serializer.py`, `backend/app/schemas/` 해당 스키마 (quality/identity 필드 노출)
- 신규: `backend/tests/test_quality_checker.py`, `backend/tests/test_identity_checker.py`
- 스코프 밖: 모델 파일, 재생성 Job 로직(WP5), 프론트엔드

## 1. quality_checker

3단계 검사, 각 단계 결과와 사유를 누적:

1. **기본 유효성**: 디코딩 실패, 해상도 미달, 완전 검정/흰 이미지, 심각한 흐림(기존 선명도 로직 재사용), 압축 손상 → 실패 시 `quality_reject`
2. **얼굴**: 얼굴 검출 여부·개수, 눈 대칭성·로컬 대비(기존 로직을 보조 지표로), 얼굴 흐림. 얼굴 미검출 단독으로는 reject 금지 → warning
3. **신체**: 기존 손 영역·손가락 추정을 보조 지표로만 사용. 확실한 이상만 warning (픽셀 휴리스틱으로 reject 금지)

출력: `quality_status`(pass/warning/reject), `quality_score`(0~1), `quality_reasons`(JSON 배열: 사유 코드 문자열), `quality_checker_version`("v2.0").

주의: OCR·인물 검출 등 신규 모델 도입은 이번 범위에서 제외. 기존 Pillow 휴리스틱 범위 내에서 보수적으로 판정하고, 불확실하면 warning.

## 2. identity_checker

`quality_warning` 이상에만 수행. HF WD 태거 결과 사용 (기존 연동 재사용).

검사 대상은 **base_prompt에 포함된 태그만**: 캐릭터 태그 + 대표 머리색 + 포함된 multicolor.

판정 규칙 (문서 §8.2):

- 다른 캐릭터 태그가 고신뢰(>=0.75)로 검출 → `identity_reject` (+conflicting_character_tag/confidence 저장)
- 캐릭터 태그 단순 미검출 → `identity_warning`
- boy 캐릭터(gender='boy')의 캐릭터 태그 미검출 → `identity_warning` (reject 금지)
- 캐릭터 태그 고신뢰 검출 + 머리색 불일치 없음 → `identity_pass`
- 예상하지 않은 multicolor 고신뢰 태그 → `suggested_multicolor_tags`에 JSON 배열로 저장 (판정에는 불사용)

출력: `identity_status`, `character_confidence`, `hair_color_confidence`, `conflicting_*`, `identity_reasons`(JSON 배열), `identity_checker_version`("v2.0").

임계값은 상수로 두되 모듈 상단에 모아 조정 가능하게.

## 3. 파이프라인 연결

- V2 생성 이미지 저장 시: quality 검사 → (warning 이상이면) identity 검사 → 결과 저장
- 임시 대표 등록: `quality_status >= warning AND identity_status >= warning`이면 `is_provisional=True` (해당 캐릭터의 기존 provisional은 해제, 캐릭터당 1장)
- V1 경로(`auto_status`)는 기존 그대로 동작 유지
- 재생성 트리거는 여기서 하지 않는다 — 검사 결과 저장까지만 (WP5가 소비)

## 4. 테스트

- 합성 이미지(Pillow로 생성한 검정/흰/노이즈/정상 패턴)로 quality 단계별 판정 검증
- WD 태거 mock으로 identity 규칙 전체 케이스 검증 (타 캐릭터 고신뢰 / 미검출 / boy / multicolor 추천)
- provisional 등록 조건 4조합 검증

## 완료 기준

- `cd backend && ../.venv/Scripts/python.exe -m pytest tests/ -q` 통과 (기존 실패 3건 무시: test_db_write_queue, test_series_merge_service, test_wiki_and_membership)
- 커밋 금지, 스코프 밖 파일 수정 금지
