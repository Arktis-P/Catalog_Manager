# F20(=F19 2/2): 리뷰 일괄 저장 버튼·단축키 (담당: sonnet 5, 프론트 전용)

백엔드 `POST /review/v2/bulk-complete`는 이미 구현돼 있음(F19). 요청/응답 형태는 `backend/app/routers/review.py`·`schemas/review.py`에서 직접 확인.

## 필독

- `backend/app/routers/review.py`의 bulk-complete (계약 확인)
- `frontend/src/components/review/V2ReviewPanel.tsx` (draft 구조: `V2CharacterDraft.rating`, `imageIndex`, `resolveV2FinalPrompt`, `v2SelectedTagsPayload`, 기존 completeItem 흐름 — **F17이 방금 수정한 최신 코드 기준**)
- `frontend/src/api/client.ts`, `types/index.ts`

## 범위

- 수정: V2ReviewPanel.tsx, client.ts, types/index.ts, 필요시 review 구역 CSS
- 금지: backend, 다른 컴포넌트

## 구현

1. 상단 기능 영역에 **「레이팅된 항목 일괄 저장」 버튼** + **Ctrl+Enter** 단축키 (입력 필드 포커스 중엔 단축키 무시 — 기존 isEditableTarget 규칙).
2. 대상: 현재 페이지 항목 중 **유효 레이팅이 있는 것** — `draft.rating ?? item.rating`이 null이 아닌 항목 (0·-1도 유효 레이팅).
3. 항목별 페이로드: rating(유효 레이팅), gender(draft 우선), base_prompt(`resolveV2FinalPrompt`), selected_tags(`v2SelectedTagsPayload`), cover_image_id는 **사용자가 카드에서 다른 이미지를 선택했다면 그 이미지, 아니면 미지정**(백엔드가 첫 이미지로 기본 처리).
4. 레이팅 없는 항목은 요청에 포함하지 않음. 재생성 중(잠금) 항목 제외.
5. 완료 후: 목록·통계 재조회, "완료 n · 건너뜀 n · 실패 n" 1줄 피드백. 실패 항목은 에러 배너에 캐릭터 태그 나열.
6. 대상 0개면 안내만 하고 요청 안 보냄.

## 완료 기준

- `cd frontend && npx.cmd tsc --noEmit` 시도 (차단 시 보고 명시)
- git commit 금지, 간결한 보고
