# F18: V2 생성 파이프라인 — 생성 큐와 검사 분리 (담당: gpt-5.6-sol)

## 목표 (사용자 요구)

현재는 이미지 1장 생성 → 검사(WD/품질/재현) 완료 → 다음 생성 순차 진행으로 보임. 이를:

1. 이미지 1장 생성 후 **0.5~2초 사이 랜덤 대기** 뒤 바로 다음 이미지 생성 (생성 큐는 생성만 담당)
2. **검사는 생성 큐와 분리해 동시(비동기) 진행**
3. 검사 결과 reject로 재생성이 필요하면: **현재 생성 큐를 일시정지하고 그 사이에 재생성이 끼어든 뒤 재개** (F17이 구현한 우선 삽입/auto-pause/auto-resume 메커니즘 재사용)

먼저 기존 로직 흐름을 확인해 **수정 가능 여부를 판단**하고, 가능하면 구현하라. 구조적으로 불가능하거나 위험이 크면 근거와 대안을 보고로 남겨라(부분 구현 허용). 필수 보장: ① 모든 생성 이미지는 검사가 반드시 완료되고 리뷰 목록에 정확히 연결(quality/identity 상태, provisional 지정) ② reject 재생성은 확실히 큐를 일시정지하고 삽입 ③ job 완료 처리는 미완료 검사가 남아 있으면 대기.

## 필독

- `backend/app/services/v2_generation_pipeline.py` (상태 머신 전체 — 생성·검사·재시도·variant 로직)
- `backend/app/services/v2_generation_job_manager.py` (F15 pause/resume + F17 우선 삽입·auto-pause/resume — **F17 커밋 이후 코드 기준**)
- `backend/app/services/character_image_service.py`의 `run_v2_quality_identity_checks`
- `backend/app/services/db_write_queue.py` (쓰기 직렬화 — 검사 워커에서도 준수)

## 범위

- 수정: 위 파이프라인·job manager·필요시 character_image_service
- 테스트: `backend/tests/` (동기화·완료 대기·reject 삽입 시나리오)
- 금지: frontend, 라우터 API 형태 변경, 그 외. 실제 DB·output 수정 금지.

## 구현 지침

- 생성 간 대기: `random.uniform(0.5, 2.0)`초. 일시정지/취소 체크는 대기 중에도 반응해야 함.
- 검사 워커: 스레드풀(작은 고정 크기, 2~3). 워커별 독립 DB 세션. 이미지 저장 직후 검사 큐에 제출.
- reject → 재시도 한도(`v2_quality_retry_max` 등 기존 규칙) 내에서 재생성 필요 시: F17 우선 삽입 경로로 해당 캐릭터 재생성 job 등록 (또는 동일 job 내 재생성 태스크를 큐 선두 삽입 — 기존 구조에 맞는 쪽을 선택하고 근거 보고).
- 캐릭터 단위 상태(generation_status, attempts, provisional) 갱신 시점이 비동기화로 어긋나지 않게 주의 — 검사 완료 콜백에서 일관되게 처리.
- job 진행 카운트: 생성 완료 수와 검사 완료 수를 구분 표기 (message 형식 자유).

## 완료 기준

- `../.venv/Scripts/python.exe -m pytest tests/ -q --basetemp=.pytest_tmp_f18 -p no:cacheprovider` 관련 통과 (기존 실패 3종 제외)
- git commit 금지. 보고: 기존 흐름 분석 요약 → 가능/불가 판단 → 구현 내용 → 보장 3항목이 어떻게 지켜지는지.
