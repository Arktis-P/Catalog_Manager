# F16: 작업 영역 일시정지 버튼 — 관련도 수집·V2 생성 (담당: sonnet 5, 프론트 전용)

배경: 백엔드에 다음 엔드포인트가 추가된다(다른 작업자가 병행 구현 중 — 이 경로를 확정 계약으로 삼아 코딩):
- `POST /api/character-catalog/relevance/jobs/{job_id}/pause` · `/resume`
- `POST /api/generation/v2/jobs/{job_id}/pause` · `/resume`
- 두 job state의 `status`에 `"paused"` 값 추가 (현재 캐릭터 처리 후 정지 시맨틱)

## 필독

- `frontend/src/components/GlobalTaskBar.tsx` — 기존 job 유형들(수집/생성/카탈로그)의 pause/resume 버튼 연결 방식
- `frontend/src/context/CharacterCatalogJobContext.tsx`(relevance), `GenerationJobContext.tsx`(V2 생성) — F11/F12에서 추가된 폴링·취소 로직
- `frontend/src/api/client.ts`, `frontend/src/types/index.ts`

## 범위

- 수정: 위 파일들 + `RelevanceProgressPanel.tsx`, `V2GenerationProgressPanel.tsx`
- 금지: backend, 그 외 frontend, global.css의 다른 구역

## 구현

1. client.ts에 pause/resume API 함수 4개 추가, 타입의 status 유니온에 `"paused"` 반영.
2. 두 Context에 pauseJob/resumeJob 추가 (기존 다른 job Context와 동일 시그니처 스타일). paused 상태에서도 폴링 유지.
3. GlobalTaskBar에서 관련도 수집·V2 생성 항목에 기존 패턴 그대로 일시정지/재개 버튼 노출 (running → 일시정지, paused → 재개). 취소·닫기 기존 동작 유지.
4. 진행 패널 컴포넌트들이 `paused` 상태 배지/문구를 기존 job들과 동일한 스타일로 표시.

## 완료 기준

- `cd frontend && npx.cmd tsc --noEmit` 시도 (차단 시 보고 명시)
- git commit 금지, 간결한 보고
