# F23: V2 리뷰 카드 — 이미지 즉시 로드 · 태그 노출 정리 · 색상 빠른 추가 (담당: gpt-5.5, 프론트 전용)

`frontend/src/components/review/V2ReviewRow.tsx`·`LazyReviewImage.tsx`·`V2ReviewPanel.tsx`·`frontend/src/utils/reviewPrompt.ts` 중심. 백엔드 수정 금지(이미 완료됨 — 아래 "사전 조치" 참고).

## 사전 조치 (오케스트레이터가 이미 완료, 참고만)

"추천: []" 표시 버그의 원인은 백엔드가 `suggested_multicolor_tags` 컬럼(JSON 문자열, 빈 배열이면 `"[]"`)을 파싱 없이 그대로 내려보내고 프론트가 이를 콤마 split 하던 것이었음. 다음을 이미 수정함:
- `backend/app/schemas/review.py`의 `V2ReviewImageResponse.suggested_multicolor_tags` → `list[str]`
- `backend/app/routers/review.py`에서 `parse_json_reason_list()`로 파싱해 내려줌
- `frontend/src/types/index.ts`의 `V2ReviewImage.suggested_multicolor_tags` → `string[]`
- `frontend/src/components/review/V2ReviewRow.tsx`의 `suggestedMulticolorTags()`가 배열을 직접 순회하도록 수정

결과: 실제 자동 재현 검사가 특정 multicolor 태그를 추천한 경우에만 "추천:" 칩이 뜨고, 추천이 없으면 칩 자체가 안 보임(더 이상 "추천: []" 노출 안 됨). 이 스펙은 이 위에서 **UI 배치**를 다룬다.

## 1. 페이지 내 이미지 즉시 로드 (30개 전부)

현재 `LazyReviewImage.tsx`는 `IntersectionObserver`(rootMargin 240px)로 화면에 가까워야 로드 — 그리드 첫 줄 정도만 로드되고 나머지는 스크롤해야 로드됨.

- `LazyReviewImage.tsx`에 `eager?: boolean` prop 추가. `eager`가 true면 IntersectionObserver를 사용하지 않고 `visible` 상태를 마운트 즉시 true로 시작(= 즉시 `<img loading="eager" decoding="async" src=... />` 렌더). `eager`가 false/미지정이면 기존 IO 기반 지연 로드 유지(다른 사용처인 `CatalogReviewRow.tsx`는 그대로 유지 — **건드리지 않음**, V1 리뷰는 이번 요청 범위 밖).
- `V2ReviewRow.tsx`의 `<LazyReviewImage>` 호출에 `eager` prop 전달(항상 true로 넘기면 됨).
- 페이지(스킵) 변경 시 `V2ReviewPanel.tsx`의 `items` 배열이 통째로 교체되고 각 행은 `key={item.id}`이므로, 새 페이지의 30개 항목은 자연히 새로 마운트되어 순서대로(=DOM 순서, 브라우저가 알아서 순차 큐잉) 로드됨 — 추가 코드 불필요. 검증만 할 것.
- 리뷰 완료(단건/일괄)로 `loadReviews()`가 같은 페이지를 재조회해도 `key={item.id}`가 그대로인 기존 행은 리마운트되지 않아 이미지가 재요청되지 않음 — 새로 채워진(완료 항목을 대체한) 행만 새로 마운트되어 이미지가 로드됨. 이 동작이 실제로 유지되는지 확인만 하고, 혹시 깨져 있으면(예: key가 index 기반으로 바뀌어 있다든지) 원인을 보고에 남길 것.

## 2. 태그 노출 위치 정리

`v2AppearanceTagChips()`가 만드는 칩 중 `optional: true`인 것들(멀티컬러 옵션 등, `appearanceTagChips` 124~131행)은 **활성화(enabled)되기 전까지는 카드에 전혀 표시되지 않는 것이 문제**였음 — 예: 캐릭터 원본 데이터에 없던 멀티컬러 태그를 C키로 켜도(F21에서 구현한 순환) 카드에 칩으로 안 보여서 사용자가 프롬프트 텍스트를 직접 읽어야만 확인 가능했음.

`V2ReviewRow.tsx`의 태그 렌더링 순서를 다음으로 변경:

1. 기존 `hairRowChips`(hair/multi/shape, `!optional && !suggested`) — 그대로.
2. 기존 `featureRowChips`(eyes/features) — 그대로.
3. **신규 `extraChips`**: `chips.filter(chip => chip.optional && enabledTags.has(chip.key))` — 그룹 무관, 현재 활성화된 optional 칩 전부(= C키로 켠 멀티컬러 태그, 아래 3번 항목에서 추가하는 색상 빠른 추가 태그 포함). 별도 CSS 클래스(예: `review-tag--extra`)로 살짝 구분되게 표시하되 클릭 시 기존과 동일하게 `onToggleTag`로 끌 수 있어야 함(다른 칩과 동일한 토글 버튼 컴포넌트 재사용). **태그 줄의 가장 마지막**, `suggestedChips`보다 앞에 위치.
4. 기존 `suggestedChips`(백엔드가 실제로 추천한 것만, 위 버그 수정 후 정상 동작) — 맨 끝, 그대로.

이러면 C키로 순환시킨 멀티컬러 태그가 태그 줄 가장 마지막 쪽(추천 칩 바로 앞)에 항상 보이게 됨.

## 3. 색상 빠른 추가 (하나의 select로 최소 변경)

목표: 관련도 수집에서 빠진 머리색/눈색/스트릭 색을 클릭 몇 번으로 base prompt에 추가. 카드 UI를 최소로 건드리기 위해 **팝업/모달 없이 작은 `<select>` 컨트롤 하나**로 구현(F21에서 방금 멀티컬러 팝업을 제거했으므로 같은 종류의 포지셔닝 버그를 다시 만들지 않기 위함).

`frontend/src/utils/reviewPrompt.ts`에 추가:

```ts
const EXTRA_HAIR_COLORS = ["aqua_hair","black_hair","blonde_hair","blue_hair","brown_hair","green_hair","grey_hair","light_brown_hair","orange_hair","pink_hair","platinum_blonde_hair","purple_hair","red_hair","silver_hair","white_hair"];
const EXTRA_EYE_COLORS = ["aqua_eyes","amber_eyes","black_eyes","blue_eyes","brown_eyes","green_eyes","grey_eyes","heterochromia","orange_eyes","pink_eyes","purple_eyes","red_eyes","white_eyes","yellow_eyes"];
const STREAK_COLORS = ["red_streaks","orange_streaks","blonde_streaks","green_streaks","aqua_streaks","blue_streaks","black_streaks","grey_streaks","white_streaks","brown_streaks"];
```

- `appearanceTagChips()`(`reviewPrompt.ts`)가 마지막에 `MULTI_HAIR_OPTIONS`를 optional 칩으로 추가하는 것과 같은 패턴으로, 위 세 목록도 optional 칩으로 추가: 머리색은 `group: "hair"`, 눈색은 `group: "eyes"`, 스트릭은 `group: "multi"`(키 `multi:{tag}`), 이미 존재하는 키(캐릭터가 이미 가진 태그)는 건너뜀. `MULTI_COLOR_PROMPT_TAGS`에 이미 스트릭 태그 목록이 있으니 재사용(중복 정의 금지).
- `V2ReviewRow.tsx`의 태그 줄 바로 아래(또는 태그 줄 끝)에 **`<select>` 하나** 추가: 기본 옵션 "+ 색상 추가"(빈 값, disabled 아님 — 매번 리셋됨), `<optgroup label="머리색">`/`<optgroup label="눈색">`/`<optgroup label="스트릭">`으로 위 세 목록을 넣고, 각 option의 value는 chip key(`hair:xxx`/`eyes:xxx`/`multi:xxx`), label은 사람이 읽기 쉬운 텍스트(`tagToPromptText` 재사용). 이미 활성화된 항목은 옵션에서 제외하거나 표시만 다르게(선택 사항, 필수 아님).
- `onChange` 시 선택된 key로 `onToggleTag(key)` 호출(이미 켜져 있으면 다시 끄지 않고 그대로 켠 채로 두는 게 자연스러움 — select는 "추가" 액션이므로), 그 후 select 값을 다시 빈 값(placeholder)으로 리셋.
- 이렇게 추가된 칩은 위 2번에서 만든 `extraChips`에 자동으로 포함되어 태그 줄 끝에 보이고, 클릭으로 제거 가능.
- `locked`(재생성 중/제출 중) 상태면 select도 disabled.

## 완료 기준

- `cd frontend && npx.cmd tsc --noEmit` 통과 시도 (차단 시 보고 명시)
- git commit 금지. 간결한 보고: 각 항목 구현 방식 요약 + 이미지 즉시 로드가 실제로 "새 항목만 재로드"되는지 확인한 근거.
