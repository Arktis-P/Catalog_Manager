# F21: V2 리뷰 패널 UX 3건 (담당: gpt-5.5, 프론트 전용)

`frontend/src/components/review/V2ReviewPanel.tsx` 중심. 백엔드 수정 금지.

## 1. 일괄 저장 후 목록 첫 항목으로 이동

현재 `bulkSaveRatedItems`(약 330~388행)는 성공 후 `loadReviews()`/`loadStats()`만 호출해 포커스(선택 영역)가 원래 인덱스에 남는다. 수정:

- 일괄 저장 성공 후 **첫 페이지의 첫 항목으로 이동**: `skip !== 0`이면 `setSkip(0)`(skip 변경 시 로드 effect가 재조회하므로 중복 호출 주의 — 현재 구조 확인 후 `loadReviews` 직접 호출과 겹치지 않게), 이미 0이면 기존처럼 `loadReviews()`. 그 후 `setFocusIndex(0)` + 스크롤 컨테이너(`scrollRef`) 최상단으로 스크롤.
- 실패(에러) 시에는 기존 동작 유지.

## 2. 'c' 키 멀티컬러 순환 (팝업 제거)

현재 'c'는 `v2-multicolor-popup`을 연다(popupOpen/popupIndex/popupPosition, keydown의 popupOpen 분기, 988행~ JSX). 이를 **팝업 없이 순환 토글**로 교체:

- 순환 목록: 기존 `multicolorChips`(`v2AppearanceTagChips(focusedItem)`의 `group === "multi"`, 팝업에 표시되던 순서 그대로).
- 'c' 동작 (focusedItem/focusedDraft 있고 잠금 아님):
  - 유효 enabled 집합 = `draft.enabledTags.size > 0 ? draft.enabledTags : defaultEnabledTagKeys(chips)` (다른 그룹 태그 보존을 위해 반드시 이 집합을 복사해 시작).
  - 현재 켜진 multi 칩이 **0개 또는 2개 이상**이면(기본 프롬프트에 multicolored+gradient처럼 복수 태그가 들어있는 경우 포함): multi 칩 전부 끄고 순환 목록의 **첫 번째**만 켠다.
  - 정확히 1개(index i)면: 끄고 `(i+1) % length` 켠다 (wrap).
  - `updateDraft`로 반영 — 프롬프트(`resolveV2FinalPrompt`)와 selected_tags에 자동 반영되는지 확인.
- 팝업 관련 코드 제거: popupOpen/popupIndex/popupPosition state, `updatePopupPosition`, 관련 effect, keydown의 popup 분기, JSX 블록, `frontend/src/styles/global.css`의 `v2-multicolor-popup` 규칙들.
- `frontend/src/components/review/ReviewShortcutGuide.tsx`의 multicolor 안내 문구를 "C: multicolor 순환" 형태로 갱신.

## 3. 페이지네이션 확장

현재 상/하단 두 곳(약 804·1035행)에 «(처음) ‹(이전) `{currentPage} / {pageCount}` ›(다음) 만 있음. 두 곳 모두:

- 버튼 구성: « 처음 · ‹ 이전 · **[페이지 숫자 입력]/{pageCount}** · › 다음 · **» 마지막**(`setSkip((pageCount-1)*PAGE_SIZE)`, `currentPage >= pageCount`면 disabled).
- 페이지 입력: number input, 표시값은 currentPage와 동기화. Enter 또는 blur 시 1~pageCount로 clamp 후 `setSkip((page-1)*PAGE_SIZE)`. 입력 중에는 전역 keydown 단축키가 발동하면 안 됨(`isEditableTarget`이 input을 걸러주는지 확인).
- 상·하단 중복이므로 작은 컴포넌트/함수로 추출 권장.

## 완료 기준

- `cd frontend && npx.cmd tsc --noEmit` 통과 시도 (차단 시 보고 명시)
- git commit 금지. 간결한 보고: 각 항목 구현 방식 요약.
