# F9: 외형 태그·이미지 전면 리셋 스크립트 + 태그 사전 확장 (담당: gpt-5.5)

배경: V2 플로우 전환에 따라 (1) 이전 로직으로 수집된 캐릭터 외형 태그를 전부 지우고 새로 수집, (2) 기존 선택/생성 이미지를 전부 지우고 V2 파이프라인(품질+재현 2종 자동 검사)으로 재생성할 예정. 이번 작업은 **실행이 아니라 도구 준비**다. 실제 삭제 실행은 오케스트레이터/사용자가 한다.

## 착수 전 필독

- `backend/app/models/global_character.py`, `global_character_image.py`, `global_character_review.py`, `appearance_tag_relevance.py`
- `backend/app/services/character_image_service.py` (파일 경로 규약: `image_path`는 project_root 기준 상대경로, 선택 이미지는 `output/generated_images/catalog_selected/`, 생성 대기는 `pending_review/`, 썸네일은 `output/generated_images/thumbs/<subdir>/<size>/`)
- `backend/app/services/tag_relevance_service.py` (새 수집 로직 — 후보 = related tags + 레거시 컬럼 + whitelist)
- `backend/app/integrations/danbooru/appearance_extractor.py` (`_load_tag_dictionary`, `load_hair_style_candidates`, `load_feature_tag_candidates`)
- `backend/scripts/v2_validation_batch.py` (기존 스크립트의 세션/설정 사용 패턴 참고)
- collect_status 재계산 로직: `backend/app/services/` 내 danbooru 수집 서비스에서 appearance/gender/series_status로 collect_status를 갱신하는 헬퍼를 찾아 재사용

## 범위

- 신규: `backend/scripts/v2_reset_for_recollection.py`
- 신규: `backend/tests/test_v2_reset_for_recollection.py`
- 수정: `input/tag_dictionaries/*.txt` (데이터 확장)
- 수정 최소 허용: `backend/app/services/settings_service.py`의 `DEFAULT_V2_FEATURE_TAG_WHITELIST` 값 1줄
- 금지: 그 외 모든 파일. **스크립트를 실제 DB에 대해 실행하지 말 것** (테스트는 in-memory SQLite만).

## 1. 리셋 스크립트

CLI (argparse):
- `--apply` 없으면 **dry-run** (삭제/변경 대상 건수·파일 수·용량만 출력)
- `--scope images|appearance|all` (기본 all)
- `--character-tag <tag>` 단일 캐릭터만 (테스트용)

동작 (scope=images):
- 전체 `GlobalCharacterImage` 행 삭제 + `image_path` 실제 파일 삭제 (존재하지 않으면 무시)
- `pending_review/`, `catalog_selected/`, `thumbs/` 하위의 잔여(orphan) 파일도 삭제 (디렉터리 자체는 유지)
- `GlobalCharacterReview`: `cover_image_id=None`, `review_status="pending"`, `final_prompt=None`, `selected_tags=None` — **rating·gender·review_note는 보존** (사용자 입력)
- `GlobalCharacter` 생성 필드 리셋: `generation_status="not_generated"`, `generation_attempts=0`, `total_generation_attempts=0`, `prompt_variant_attempts=None`, `last_failure_reason=None`, `prompt_revision_reason/level=None`, `error_message=None`

동작 (scope=appearance):
- `CharacterAppearanceTagRelevance` 전 행 삭제
- `GlobalCharacter`: `hair_color/hair_shape/multi_color_hair/eye_color/feature_tags=None`, `primary_hair_color=None`, `primary_hair_needs_review=False`, `base_prompt=None`, `previous_base_prompt=None`, `appearance_status="uncollected"` + 기존 헬퍼로 `collect_status` 재계산 (헬퍼가 없으면 appearance만 uncollected로 두고 collect_status 갱신 규칙을 주석으로 명시)

공통: 진행 로그(1000건 단위), 종료 시 요약(캐릭터/이미지/relevance 행/파일 수). 커밋은 배치로. WAL SQLite이므로 단일 세션 사용.

## 2. 태그 사전 확장 (`input/tag_dictionaries/`)

새 수집 로직은 related tags 응답에서 사전에 있는 태그만 외형 후보로 인식하므로 사전이 빈약하면 후보를 놓친다. Danbooru에서 실제 쓰이는 태그명(언더스코어 포함)으로 확장:
- `hair_shape.txt` (현재 7개): ahoge, drill_hair, hair_bun, double_bun, side_ponytail, one_side_up, two_side_up, hime_cut, blunt_bangs, sidelocks, very_long_hair, absurdly_long_hair, wavy_hair, curly_hair, messy_hair, hair_intakes, low_twintails, single_braid, twin_braids, braided_ponytail, folded_ponytail, short_ponytail, high_ponytail 등
- `eye_color.txt` (현재 7개): aqua_eyes, orange_eyes, pink_eyes, grey_eyes, black_eyes, white_eyes, amber_eyes 추가
- `feature_tags.txt` (현재 8개): scar, scar_across_eye, scar_on_face, dark_skin, dark-skinned_female, dark-skinned_male, eyepatch, halo, fang, fangs, mole, mole_under_eye, mole_under_mouth, freckles, pointy_ears, demon_horns, dragon_horns, animal_ear_fluff, fox_ears, cat_ears, cat_tail, fox_tail, demon_tail, demon_wings, angel_wings, feathered_wings, heterochromia는 eye_color 사전 소속이므로 중복 금지
- `hair_color.txt`, `multi_color_hair.txt`: 누락 확인 후 필요시만 보강 (hair_color에 light_brown_hair, platinum_blonde_hair 등)
- `DEFAULT_V2_FEATURE_TAG_WHITELIST`에 `heterochromia`는 넣지 말 것(눈색 카테고리). `fang,mole,freckles,pointy_ears` 추가 여부는 판단해서 결정하고 근거를 보고.

주의: `load_hair_style_candidates()`가 HAIR_COLORS/HAIR_LENGTH/multicolor를 차집합 처리하므로 hair_shape.txt에 색 태그가 섞여도 안전하지만, 애초에 넣지 말 것.

## 3. 테스트 (`backend/tests/test_v2_reset_for_recollection.py`)

in-memory SQLite + tmp_path로:
- dry-run이 아무것도 변경/삭제하지 않음
- apply + scope=images: 이미지 행·파일 삭제, review 리셋(rating 보존), generation 필드 리셋
- apply + scope=appearance: relevance 행 삭제, 컬럼 초기화
- `--character-tag` 필터가 다른 캐릭터를 건드리지 않음

## 완료 기준

- `../.venv/Scripts/python.exe -m pytest tests/test_v2_reset_for_recollection.py -q` 통과 (backend에서, 실행 불가 시 보고에 명시)
- 실제 DB(`data/*.db`)·실제 output 디렉터리 무변경
- git commit 금지, 변경 요약 + 화이트리스트 판단 근거 보고
