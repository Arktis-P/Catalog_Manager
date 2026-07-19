# F17: V2 리뷰 재생성 — 작업 목록 표시 + 생성 큐 우선 삽입 (담당: gpt-5.5)

## 목표

1. 리뷰 탭에서 재생성을 누르면 그 작업이 **좌측 작업 목록 영역에 표시**된다.
2. 대량 V2 생성 job이 실행 중이면: **실행 중 job을 자동 일시정지**(현재 캐릭터까지 처리) → 재생성 job을 먼저 실행 → 끝나면 **자동 재개**. 사용자가 직접 정지시킨 job은 자동 재개하지 않는다.

## 필독

- `backend/app/services/v2_generation_job_manager.py` — `start_regeneration`(현재 큐 뒤에 붙음), F15의 `pause`/`resume`/`_check_pause`, `_dispatch_next`
- `backend/app/routers/generation.py`의 `/v2/characters/{id}/regenerate`, `/v2/jobs` 목록
- V1 참조: `backend/app/services/review_regenerate_job_manager.py` (있으면 — 리뷰 재생성 job이 어떻게 목록에 노출되는지)
- `frontend/src/components/review/V2ReviewPanel.tsx`의 v2Jobs 로컬 폴링 (규모 파악용 — 이 파일 수정은 최소한으로: 재생성 시작 함수를 context 것으로 교체하는 정도만. 다른 작업자가 곧 이 파일을 크게 수정할 예정)
- `frontend/src/context/GenerationJobContext.tsx`, `frontend/src/components/V2GenerationProgressPanel.tsx`, `GlobalTaskBar.tsx`

## 범위

- 수정: 위 backend 2개 + frontend는 GenerationJobContext/V2GenerationProgressPanel/GlobalTaskBar 중심, V2ReviewPanel은 재생성 시작·폴링 연결부만 최소 수정
- 테스트: `backend/tests/`
- 금지: v2_generation_pipeline.py 내부 로직, 그 외 전부. 실제 DB·output 수정 금지.

## 구현

### 백엔드

1. `start_regeneration`을 **우선 삽입**으로: 큐 맨 앞(`appendleft`)에 넣고, 실행 중인 job이 있으면 auto-pause 표시와 함께 `pause` 호출. 재생성 job 종료(성공/실패/취소) 시 auto-pause된 job만 자동 `resume`. 여러 재생성이 연달아 삽입되는 경우도 안전하게 (auto-resume은 마지막 재생성이 끝난 뒤).
2. job state에 재생성 구분 필드(예: `kind: "generate"|"regenerate"`, `character_tag`)가 없으면 추가해 프론트가 라벨을 구분할 수 있게.
3. `/v2/jobs` 목록에 재생성 job 포함 (이미 포함되면 확인만).

### 프론트엔드

4. 재생성 job이 작업 목록(GlobalTaskBar)에 "V2 재생성 · {캐릭터}"로 표시. 일시정지/재개/취소는 기존 V2 생성 패턴 그대로. auto-pause된 대량 job은 "일시정지(자동)" 같은 문구로 구분되면 좋음 (백엔드 message 활용 가능).
5. V2ReviewPanel의 재생성 시작을 GenerationJobContext 경유로 교체하되, **카드 잠금·완료 후 카드 갱신 동작은 유지** (기존 로컬 폴링을 context 상태 구독으로 대체).

## 완료 기준

- `../.venv/Scripts/python.exe -m pytest tests/ -q --basetemp=.pytest_tmp_f17 -p no:cacheprovider` 관련 통과 (기존 실패 3종 제외)
- `cd frontend && npx.cmd tsc --noEmit` 통과
- git commit 금지, 간결한 보고 (auto-pause/resume 상태 전이 요약 포함)
