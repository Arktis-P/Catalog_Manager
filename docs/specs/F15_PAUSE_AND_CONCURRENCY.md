# F15: 관련도 수집·V2 생성 일시정지 + 관련도 수집 동시성 (담당: gpt-5.5, 백엔드 전용)

## 필독

- `backend/app/services/collect_job_manager.py` — 기존 일시정지 패턴(`_pause_cond`/`_paused_jobs`/`pause_job`/`resume_job`, "현재 항목 처리 후 정지" 시맨틱)과 동시성 패턴(`_get_max_concurrent`가 settings의 danbooru 동시 작업 수를 매 시점 조회, 슬롯 기반 디스패치)
- `backend/app/services/relevance_collect_job_manager.py` (수정 대상 1 — 현재 캐릭터 단위 순차 루프)
- `backend/app/services/v2_generation_job_manager.py` (수정 대상 2)
- `backend/app/routers/character_catalog.py` (relevance 라우트 55~105행), `backend/app/routers/generation.py` (v2 라우트 93~157행)
- `backend/app/services/db_write_queue.py`의 `job_write_context` (병렬 사용 가능 여부 확인 — 큐가 직렬화하므로 스레드별 컨텍스트 사용)

## 범위

- 수정: 위 서비스 2개 + 라우터 2개 + 필요시 관련 스키마
- 테스트: `backend/tests/`
- 금지: frontend, 그 외 backend. 실제 DB·output 수정 금지.

## 1. 일시정지 (두 job manager 공통)

- `pause(job_id)` / `resume(job_id)`: running → 현재 **처리 중인 캐릭터(들)까지 완료 후** 대기 상태(`paused`)로. resume 시 이어서 진행. collect_job_manager의 Condition 패턴 재사용.
- 취소는 기존 동작 유지 (paused 상태에서도 취소 가능해야 함).
- 라우터: `POST /character-catalog/relevance/jobs/{job_id}/pause`·`/resume`, `POST /generation/v2/jobs/{job_id}/pause`·`/resume` — 기존 catalog job pause/resume 라우트(~382행)와 동일한 상태 검증·에러 메시지 스타일.
- job state에 `paused` status 노출 (기존 status 필드 확장).

## 2. 관련도 수집 동시성

- `RelevanceCollectJobManager._run`의 순차 for 루프를 **동시 워커 방식**으로: settings의 danbooru 동시 작업 수(`get_collect_max_concurrent`)를 collect_job_manager처럼 **실행 중에도 매 디스패치 시점에 조회**해 반영.
- 워커별로 독립 `SessionLocal()` + `TagRelevanceService` (DanbooruClient 각자 생성). 진행 카운터/성공/실패/에러 목록 갱신은 기존 `_update` 락 경유.
- `current_character_tag`/message는 "N/M · 처리 중 K명" 형태로 자연스럽게 (동시 진행이라 단일 태그 표기가 안 맞으면 형식 조정 허용).
- 일시정지와 조합: pause 시 새 캐릭터 디스패치 중단, 진행 중인 워커는 마무리.
- V2 생성 쪽 동시성은 **하지 않는다** (요구 밖).

## 테스트

- pause → 현재 항목 완료 후 정지, resume → 재개, paused 중 cancel 동작 (양쪽 manager)
- 관련도 수집이 max_concurrent>1일 때 병렬로 처리되고 카운트가 정확함 (가짜 service/client로 검증)

## 완료 기준

- `../.venv/Scripts/python.exe -m pytest tests/ -q --basetemp=.pytest_tmp_f15 -p no:cacheprovider` 관련 통과 (기존 실패 3종: test_db_write_queue/test_series_merge_service/test_wiki_and_membership 제외)
- git commit 금지, 간결한 보고 (엔드포인트 경로·상태 전이 요약 포함)
