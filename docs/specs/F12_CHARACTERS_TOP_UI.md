# F12: Characters 탭 상단 UI 전면 정리 (담당: sonnet 5)

목표: 상단 기능 영역을 깔끔한 섹션 구분으로 재구성하고, **작업 진행 내역 표시는 좌측 GlobalTaskBar로 완전히 이관** (페이지 인라인 진행 표시 제거).

## 필독

- `frontend/src/pages/CharactersPage.tsx` (현 상단: 최소 포스트 수+목록 수집/태그 수집 버튼들/이미지 생성(구)/개별 추가/관련도 수집(F11)/V2 생성(F11) — 인라인 job 상태 표시 포함)
- `frontend/src/components/GlobalTaskBar.tsx`, `frontend/src/components/Layout.tsx` (좌측 작업 내역 영역 — 기존 job 종류들이 어떻게 표시되는지)
- `frontend/src/context/CharacterCatalogJobContext.tsx`, `GenerationJobContext.tsx` (F11이 추가한 관련도/V2 생성 job 상태)
- `frontend/src/styles/global.css` (`.characters-` / taskbar 관련 구역)

## 범위

- 수정: 위 파일들 + 필요시 `frontend/src/api/client.ts`, `types/index.ts`
- **global.css는 Characters/GlobalTaskBar 관련 구역만 수정** (review 관련 구역 금지 — 다른 작업자가 동시 수정 중)
- 금지: backend, review 컴포넌트, docs/

## 요구사항

1. **섹션 구분** (카드/패널 스타일로 시각적 구분, 제목 라벨):
   - 「목록 수집」: 최소 포스트 수 입력 + 신규만 체크 + 전체 캐릭터 목록 수집
   - 「태그 수집」: 대상 모드(선택/미수집 전체/포스트 n개 이상 + n 입력) + 시작 버튼. 기존 V1 버튼들(선택 캐릭터 통합 태그 수집/실패·부분완료 재시도/미수집 전체 태그 수집)도 이 섹션에 정리 (기능 제거 금지)
   - 「이미지 생성」: V2 대상 모드(4종 + n) + 시작 버튼. 구 파이프라인 버튼(선택/현재 페이지)은 "V1(구)" 라벨로 구분해 유지
   - 「캐릭터 개별 추가」
2. **진행 내역 이관**: F11이 CharactersPage에 인라인으로 넣은 관련도 수집/V2 생성 job 진행·상태 표시를 GlobalTaskBar에 항목 유형으로 추가하고 페이지에서는 제거. 취소/닫기 동작도 taskbar에서. 기존 taskbar 항목들의 패턴(진행률/성공/실패/취소 버튼) 준수.
3. 시작 버튼 근처 피드백은 시작 성공/실패 토스트 또는 1줄 안내 정도만 (진행 상황은 taskbar 소관).
4. 반응형: 좁은 화면에서 섹션이 세로로 쌓이게.

## 완료 기준

- `cd frontend && npx.cmd tsc --noEmit` 시도 (차단 시 보고 명시)
- 기능 손실 없음 (모든 기존 버튼·입력 동작 유지)
- git commit 금지, 간결한 변경 보고
