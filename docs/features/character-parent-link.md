# 캐릭터 부모/자식(Alternative) 연결

의상 차이 등으로 하나의 캐릭터가 danbooru 태그 상 여러 개로 분리된 경우, 이를 부모/자식 관계로 묶어
동일 캐릭터임을 표시하는 기능. **캐릭터 목록(GlobalCharacter, `/characters` 탭)에만 적용되며,
시리즈 탭(Character)에는 영향을 주지 않는다.**

## 데이터 모델

- `global_characters.parent_character_id` (self FK, `ON DELETE SET NULL`, nullable) 추가.
  - Series의 `parent_series_id`와 동일한 패턴으로 **1단계 깊이만 허용**한다.
    - 부모가 될 캐릭터는 이미 다른 캐릭터의 자식이면 안 됨.
    - 자식이 될 캐릭터는 이미 부모가 있거나, 자신의 하위 캐릭터를 가지고 있으면 안 됨.
  - 마이그레이션은 Alembic이 아니라 `backend/app/database.py`의
    `_migrate_global_character_columns()`(hand-rolled `ALTER TABLE`)를 통해 적용된다 (`_migrate_series_columns`와 동일한 패턴).

## 백엔드

- `backend/app/services/character_link_service.py` (신규)
  - `similarity_score()` : `series_merge_service.py`의 토큰 중복 기반 유사도 로직을 캐릭터 태그/표시명에 맞게 재구현.
  - `list_parent_candidates()` / `list_child_candidates()` : 후보 검색(검색어 있으면 텍스트 매칭, 없으면 유사도 순 추천).
  - `link_parent()` / `unlink_parent()` : 연결/해제, 1단계 깊이 제약 검증.
- `backend/app/routers/character_catalog.py`
  - `GET /character-catalog/characters/{id}/link/candidates?mode=parent|child&search=&limit=&exclude_ids=`
  - `POST /character-catalog/characters/{id}/link` — body `{parent_character_id}`
  - `DELETE /character-catalog/characters/{id}/link` — 연결 해제
  - `GET /character-catalog/characters` 목록 필터에 `is_alternative: bool` 추가 (Alternative만/일반만 필터링).
- `backend/app/schemas/character_catalog.py`
  - `GlobalCharacterResponse`에 `parent_character_id`, `parent_character_tag`, `parent_display_name`,
    `is_alternative`, `child_count` 필드 추가.
  - `CharacterLinkCandidate` / `CharacterLinkRequest` / `CharacterLinkResponse` / `CharacterUnlinkResponse` 신규.
- `backend/app/schemas/review.py` (`GlobalCatalogReviewItemResponse`) / `backend/app/services/review_catalog_serializer.py`
  - `parent_character_tag`, `parent_display_name`, `is_alternative`, `child_count` 필드 추가 — 리뷰 카드에서 부모 정보를
    보여주고, 리뷰 화면에서도 연결 가능 여부(하위 보유 여부)를 판단하기 위함 (시리즈 스코프 `CatalogReviewItemResponse`에는 추가하지 않음).
  - `backend/app/services/review_service.py`의 `list_catalog_reviews_global` 쿼리에 `GlobalCharacter.parent`/`.children`
    eager load 추가.

## 프론트엔드

- `frontend/src/types/index.ts`
  - `LinkableCharacterSummary` 인터페이스 추가 — `CharacterLinkModal`이 `GlobalCharacter`(캐릭터 관리 탭)와
    `CatalogReviewItem`(리뷰 탭) 양쪽에서 공통으로 다룰 수 있도록 필요한 필드(`id`, `character_tag`, `display_name`,
    `is_alternative`, `parent_character_tag`, `parent_display_name`, `child_count`)만 뽑아낸 최소 타입.
  - `CatalogReviewItem`에 `child_count?: number` 추가.
- `frontend/src/components/CharacterLinkModal.tsx` — `SeriesMergeModal.tsx`의 UI 패턴(후보 리스트/검색/유사도 배지)을 재사용.
  이제 `character` prop 타입이 `GlobalCharacter`가 아니라 `LinkableCharacterSummary`이므로, 캐릭터 관리 탭과 리뷰 탭
  양쪽에서 동일한 모달을 그대로 재사용할 수 있다.
  - 캐릭터에 하위가 없으면: "이 캐릭터를 다른 캐릭터의 하위로 연결" / "다른 캐릭터를 이 캐릭터의 하위로 연결" 모드 전환 가능.
  - 하위가 있는 캐릭터는 "다른 캐릭터를 하위로 연결"만 가능 (자기 자신이 자식이 될 수 없음).
  - 이미 연결된 캐릭터를 열면 현재 부모 정보와 "연결 해제" 버튼만 표시.
- `frontend/src/pages/CharactersPage.tsx`
  - 툴바에 "Alternative" 필터(select: All / Alternative만 / 일반만) 추가.
  - 이름 셀에 `Alternative · ↳ {부모명}` 배지(자식인 경우), `하위 N` 배지(부모인 경우) 표시.
  - 행 액션에 "Merge"(미연결 시) / "연결 해제"(연결된 자식인 경우) 버튼 추가 → `CharacterLinkModal` 오픈.
- `frontend/src/components/review/CatalogReviewRow.tsx`
  - 리뷰 카드 메타 배지 줄에 `item.is_alternative`가 true면 `Alternative · ↳ {부모명}` 배지 표시
    (캐릭터 목록 탭에서만 값이 채워지며, 시리즈 탭 데이터에는 필드 자체가 없어 아무 것도 표시되지 않음).
  - Posts/Wiki 링크 옆에 `onOpenLinkModal` prop이 주어졌을 때만 "Merge"(미연결)/"연결 해제"(연결됨) 버튼을
    렌더링 — 시리즈 탭(`CatalogReviewPanel.tsx`)은 이 prop을 넘기지 않으므로 버튼이 나타나지 않는다.
- `frontend/src/components/review/GlobalCatalogReviewPanel.tsx` (**리뷰 탭에서 연결 가능하게 하는 핵심 변경**)
  - `linkingItem` state 추가, 각 행에 `onOpenLinkModal={() => setLinkingItem(item)}` 연결.
  - `toLinkableSummary()` 어댑터로 `CatalogReviewItem` → `LinkableCharacterSummary` 변환 후 `CharacterLinkModal` 렌더.
  - `onLinked`에서 `loadReviews()`를 호출해 목록/배지를 새로고침한다.
  - 즉, 리뷰 화면(캐릭터 목록 스코프)에서 캐릭터 관리 탭(`/characters`)으로 이동하지 않고도 바로 부모/자식을
    검색·연결·해제할 수 있다.
  - 단축키 `a` : 포커스된 캐릭터의 Merge 창을 연다 (`focusedLocked` 상태에서도 `q`/`w`처럼 허용). 시리즈 탭에는
    이 단축키가 없다.
- `frontend/src/components/review/ReviewShortcutGuide.tsx`
  - `includeMerge` prop 추가 — 캐릭터 목록 탭에서만 `<ReviewShortcutGuide includeMerge />`로 켜서
    "a Merge (부모/자식 연결)" 항목을 노출한다.

## 카탈로그(이미지) 반영

이번 작업 범위에는 포함하지 않음. 최종 이미지 카탈로그(`CatalogPage.tsx`/`catalog_service.py`)에 부모/자식 정보와
"Alternative" 배지를 노출하는 것은 후속 작업으로 남겨둔다 (요청자 확인: "추후 카탈로그에서도 표시되도록 할 예정").

## 확인 방법 (수동 QA, 코드 리뷰 대상 아님)

1. 백엔드/프론트 개발 서버 기동 후 `/characters` 탭 진입.
2. 임의의 캐릭터 행에서 "Merge" 클릭 → 모달에서 후보 목록(유사도 `match N%` 배지 포함)이 뜨는지 확인.
3. 후보 선택 후 "연결" 클릭 → 모달이 닫히고 목록이 새로고침되며, 자식 행에는 `Alternative · ↳ {부모명}` 배지,
   부모 행에는 `하위 1` 배지가 표시되는지 확인.
4. 상단 "Alternative" 필터를 "Alternative만"/"일반만"으로 바꿔 필터링이 되는지 확인.
5. 자식 캐릭터에서 다시 "연결 해제" 클릭 → 배지가 사라지고 버튼이 "Merge"로 돌아오는지 확인.
6. `/review` → "Catalog Review" 모드 → "캐릭터 목록" 스코프에서, 연결된 자식 캐릭터의 리뷰 카드에도
   동일한 `Alternative · ↳ {부모명}` 배지가 뜨는지 확인 (시리즈 스코프 카드에는 배지가 없어야 정상).
7. **(리뷰 탭에서 직접 연결)** `/review` → "캐릭터 목록" 스코프에서 `/characters` 탭으로 이동하지 않고,
   각 리뷰 카드의 Posts/Wiki 링크 옆 "Merge" 버튼을 클릭 → 동일한 `CharacterLinkModal`이 뜨는지,
   연결 후 카드에 바로 `Alternative · ↳ {부모명}` 배지가 붙고 버튼이 "연결 해제"로 바뀌는지, 다시 "연결 해제"로
   원상복구되는지 확인. (시리즈 스코프 `CatalogReviewPanel`에는 이 버튼이 나타나지 않아야 정상.)
8. **(단축키)** "캐릭터 목록" 스코프에서 포커스된 카드에 대해 `a` 키를 누르면 Merge 창이 즉시 열리는지 확인.
   단축키 안내(`단축키` 접이식 패널)에 "a Merge (부모/자식 연결)" 항목이 표시되는지, 시리즈 스코프에는
   해당 항목이 없는지 확인.
