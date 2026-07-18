# F5: V2 리뷰 UI 개편 (담당: sonnet 5)

기준: `docs/PLAN_IMAGE_REVIEW_V2_FOLLOWUP.md` §2.3(프론트), §2.5(feature 후보 표시), §2.7(UI), §3 전체.
선행: F1(수동 재생성 API)·F4(병합 필드·추천 근거) 커밋 후 착수.

## 착수 전 필독

- `frontend/src/components/review/V2ReviewPanel.tsx`, `V2ReviewRow.tsx` (개편 대상 — 네가 작성한 코드다)
- `backend/app/routers/generation.py`의 V2 수동 재생성 API (F1 산출 — 요청/응답 스키마 확인)
- `backend/app/schemas/review.py`의 병합 상태 필드 (F4 산출)
- `frontend/src/pages/SettingsPage.tsx`, `frontend/src/pages/CatalogPage.tsx`(카드 그리드 참고)
- `frontend/src/components/CharacterLinkModal.tsx`

## 범위

- 수정: `frontend/src/components/review/V2ReviewPanel.tsx`, `V2ReviewRow.tsx`, `ReviewImagePreview.tsx`(필요시), `ReviewShortcutGuide.tsx`(필요시)
- 수정: `frontend/src/pages/ReviewPage.tsx` (기본 탭 V2), `frontend/src/pages/SettingsPage.tsx` (카드 크기 설정 UI)
- 수정: `frontend/src/api/client.ts`, `frontend/src/types/index.ts`, `frontend/src/styles/global.css`
- 수정(백엔드 최소): `backend/app/services/settings_service.py`, `backend/app/schemas/settings.py` — `v2_review_card_size`(small/medium/large, 기본 medium)와 `v2_review_card_width_px`(사용자 지정, 0=사전설정 사용) 키 추가만
- 금지: 그 외 backend 전부, docs/

## 1. 세로형 카드 그리드 (§3.1)

- 가로 행 → CSS Grid 세로 카드 (`repeat(auto-fill, minmax(카드너비, 1fr))`)
- 카드당 현재 선택 이미지 1장, `object-fit: contain`으로 전체 표시, 좌우 키/카드 내 컨트롤로 전환
- 카드가 키보드 포커스 단위 (기존 focus 로직 유지)
- 카드 배치 순서: ① 이미지(하단 오버레이에 quality/identity 상태 — pass 무색, warning 노랑, reject 빨강) ② 이름(언더바→공백)+`altered` 태그(병합 시, 클릭하면 상위 캐릭터 정보 표시) ③ 시리즈 표시명(좌)+포스트 수(우) ④ 캐릭터 태그 chip(성별·대표/후보 머리색·multicolor·머리모양·눈색·기타 특징 — feature 태그는 §2.5에 따라 선택 후보로만, 자동 포함 아님) ⑤ 자주 쓰는 추가 태그(multicolored/gradient/colored inner/streaked) ⑥ 기본 프롬프트 textarea ⑦ 하단 버튼: Posts · Wiki · Merge · Regenerate · Complete(파란색 강조)
- 품질·재현 상세 사유는 툴팁 또는 펼침 영역

## 2. 카드 크기 설정 (§3.2)

- SettingsPage에 V2 카드 크기 설정 추가 (small/medium/large + 사용자 지정 px)
- V2 패널이 설정을 읽어 CSS 변수로 반영, 변경 즉시 적용
- Space 원본 보기 유지

## 3. 기본 탭 변경 (§3.3)

- `/review` 진입 시 V2가 기본. 잘못된 mode 값도 V2로 fallback. catalog/appearance는 명시 쿼리로 접근 (기존 링크 동작 유지)

## 4. 수동 재생성 V2 통합 (§2.3)

- `r` 키·Regenerate 버튼 → F1의 `POST /api/generation/v2/characters/{id}/regenerate` 호출 (카드에서 편집한 프롬프트를 body로 전달)
- 진행 중 카드 잠금·진행 표시(기존 방식), 완료 후 **V2 응답으로 카드 직접 갱신** (V1 재생성 Job Context 사용 제거)
- 실행 중 중복 재생성 시도는 무시 (409 처리)

## 5. 병합 UI (§2.7)

- `altered` 태그: is_alternative일 때 표시, 클릭 시 parent 정보(태그·표시명) 표시
- Merge 버튼/`a` 키: CharacterLinkModal을 실제 링크 정보와 함께 열기, 연결 해제 지원(기존 API), 완료 후 현재 카드·목록 재조회
- 추천 근거(match_reason) 표시 (F4 산출 필드)

## 완료 기준

- `cd frontend && npx.cmd tsc --noEmit` 통과, `npm run build` 통과
- V1 리뷰 탭·Appearance 탭 동작 불변
- 커밋 금지, 스코프 밖 파일 수정 금지
