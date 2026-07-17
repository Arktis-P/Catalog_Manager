# WP5: 자동 재생성 파이프라인 (담당: gpt 5.6 sol)

기준: `docs/PLAN_IMAGE_GENERATION_REVIEW_V2.md` §3, §7, §9, §13(생성 상태).
선행: WP3 (base_prompt·V2 프롬프트 빌더), WP4 (quality/identity 검사기).

## 착수 전 필독 파일

- `backend/app/services/quality_checker.py`, `identity_checker.py` (WP4 산출물 — 소비만, 수정 금지)
- `backend/app/services/generation_job_manager.py`, `review_regenerate_job_manager.py` (기존 Job 패턴)
- `backend/app/services/generation_service.py`, `character_image_service.py`
- `backend/app/services/prompt_service.py` (`build_v2_base_prompt`, `refresh_global_character_base_prompt`)
- `backend/app/services/generation_prompt_builder.py` (`build_full_prompt_v2`)
- `backend/app/integrations/naia/generation_runner.py`
- `backend/app/services/tag_relevance_service.py` (관련도 조회)
- `backend/app/integrations/danbooru/wiki_dtext.py` (위키 확인용)

## 범위

- 신규: `backend/app/services/v2_generation_pipeline.py` (핵심 상태 머신)
- 수정: `backend/app/services/generation_service.py` 또는 신규 Job Manager — 기존 패턴에 맞춰 판단 (V1 경로 불변 유지)
- 신규/수정: 파이프라인 트리거·상태 조회 API (`backend/app/routers/generation.py` 확장 가능)
- 신규: `backend/tests/test_v2_generation_pipeline.py`
- 스코프 밖: 검사기 내부, 모델 파일, 프론트엔드, review 라우터

## 1. 파이프라인 흐름 (캐릭터 단위)

```
generation_status: not_generated → generating
1) base_prompt로 1장 생성 → generation_attempts += 1
2) quality 검사
   - quality_reject → 동일 프롬프트 재생성 (총 시도 v2_quality_retry_max=3, 설정값 사용)
     3회 모두 reject → generation_status=generation_failed, 종료
   - warning 이상 → 3)
3) identity 검사
   - identity_reject:
     a) first_post_at >= v2_recent_character_cutoff(2025-05-01) → generation_status=likely_untrained, 종료 (재생성 금지)
     b) 아니면 프롬프트 보정 단계 진행 (아래 §2)
   - warning 이상 → 4)
4) 임시 대표 등록(is_provisional, WP4의 등록 함수 재사용) → generation_status=generated, 종료
```

## 2. identity reject 프롬프트 보정 상태 머신

`prompt_revision_level` 1~4 순서로, 각 레벨마다 1장 생성→검사:

1. **레벨 1 — 대표 머리색 재검토**: 관련도 2위 머리색으로 교체 (2위가 없으면 스킵)
2. **레벨 2 — multicolor 조정**: 현재 포함된 multicolor 제거, 또는 임계값 근접(통과 실패했지만 상위) multicolor 추가
3. **레벨 3 — 눈색 추가**: 관련도 1위 눈색 태그 추가
4. **레벨 4 — 기타 외형 태그 추가**: is_prompt_candidate인 feature 태그(scar, dark_skin, horns, eyepatch, glasses, animal_ears 등) 추가

- 각 레벨 시도 후 identity_warning 이상이면: 해당 보정 프롬프트를 `base_prompt`로 승격, `previous_base_prompt`·`prompt_revision_reason`·`prompt_revision_level` 기록, §1-4)로 진행
- 각 보정 생성물도 quality 검사를 먼저 통과해야 함 (reject면 해당 레벨 내 재시도 없이 다음 레벨로)
- 레벨 4까지 실패 → 마지막 이미지의 identity_reject 유지, generation_status=generation_failed
- Danbooru 위키 확인(§9.2-1)은 이번 구현에서 로그 참고용 정보 수집까지만 (위키 기반 자동 판단은 제외)

## 3. Job 관리

- 대상: generation_status가 not_generated(또는 재실행 요청된) 캐릭터 배치
- 기존 Job Manager 패턴 재사용: 진행률, 취소, 캐릭터별 에러 기록 후 계속
- 동시성: NAIA 생성은 기존 runner의 직렬 처리 준수
- API: 파이프라인 시작(전체/선택), 진행 조회, 취소

## 4. 테스트

생성 runner·검사기·Danbooru를 전부 mock으로:

- quality reject 3회 → generation_failed
- quality 2회 reject 후 3회째 pass → identity로 진행
- identity reject + 최근 캐릭터 → likely_untrained (재생성 호출 없음 검증)
- identity reject → 레벨 1 보정 성공 → base_prompt 승격·이력 기록 검증
- 레벨 4까지 실패 → generation_failed
- provisional 등록 조건 검증

## 완료 기준

- `cd backend && ../.venv/Scripts/python.exe -m pytest tests/ -q` 기존 실패 3건 외 전부 통과
- 커밋 금지, 스코프 밖 파일 수정 금지
