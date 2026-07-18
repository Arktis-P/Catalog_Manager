# V2 후속 개선 실행 계획: 작업 분해 및 작업자 분배

기준 문서: `docs/PLAN_IMAGE_REVIEW_V2_FOLLOWUP.md`
작업 브랜치: `feature/image-review-v2` (계속)
오케스트레이터: fable 5 — 스펙 작성, 지시, diff 리뷰, 통합 검증, 커밋

## 작업 패키지 분해 (F1~F6)

| WP | 내용 (후속 문서 §) | 담당 | 주요 파일 |
|---|---|---|---|
| F1 | 파이프라인 보정: 수동 재생성 V2 통합 API(§2.3 백엔드), 보정 프롬프트 품질 재시도 통일(§2.4), feature 자동 추가 제거(§2.5), 위키 단계 제거(§2.2 일부), 시도 횟수 기록 필드+마이그레이션 | gpt 5.6 sol | v2_generation_pipeline.py, v2_generation_job_manager.py, routers/generation.py, models, database.py |
| F2 | identity 검사 단순화·성능(§2.6): 전체 캐릭터 전수 비교 제거, 입력 프롬프트 중심 판정 | gpt 5.5 | identity_checker.py, character_image_service.py |
| F3 | related tags 기반 관련도 후보 수집(§2.2, Phase 5) | gpt 5.5 | tag_relevance_service.py, danbooru client 재사용 |
| F4 | 병합: V2 응답 병합 상태 필드(§2.7 백엔드), 추천 후보 정규화·점수 개선+회귀 테스트(§4) | sonnet 5 | character_link_service.py, review_service.py, schemas |
| F5 | V2 리뷰 UI 개편(§3): 세로형 카드 그리드, 크기 설정, 상태 오버레이, 기본 탭 V2, 수동 재생성 V2 API 연결(§2.3 프론트), 병합 UI 연결(§2.7 UI) | sonnet 5 | V2ReviewPanel/Row, ReviewPage, SettingsPage, settings 백엔드 키 |
| F6 | bad anatomy 품질 검사 확장(§2.1): Gemini Vision 기반 구조화 분석(설정으로 on/off), 사유 코드 저장 | gpt 5.6 sol | quality_checker.py 확장 + 신규 anatomy 모듈 |

## 실행 순서

```text
Phase A: F1 (sol) ∥ F2 (5.5) ∥ F4 (sonnet)   — 파일 비중첩
Phase B: F3 (5.5) ∥ F6 (sol) ∥ F5 (sonnet, F1·F4 산출 API 사용)
Phase C: fable 5 통합 검증 (테스트·빌드·실서버 브라우저 확인)
```

- 충돌 관리: identity_checker 시그니처는 하위 호환 유지(F2), pipeline 쪽 호출부 정리는 F1 담당으로 분리.
- 각 WP 완료 시 fable 5 diff 리뷰 후 WP 단위 커밋. 작업자 직접 커밋 금지.

## F6 접근 방식 결정 (bad anatomy)

픽셀 휴리스틱으로는 신체 구조 판정이 불가능하므로, 멀티모달 비전 분석을 채택한다:

- Gemini API (사용자 환경에 키 존재) 호출 기반 `anatomy_checker` 모듈
- 구조화 프롬프트로 사유 코드(`body_proportion_anomaly`, `extra_limb`, `missing_limb`, `joint_anomaly`, `hand_anomaly`, `finger_count_anomaly`, `body_fusion`) JSON 응답 요구
- 설정 `v2_anatomy_check_enabled`(기본 off), `v2_anatomy_check_model` — 비용·속도는 사용자가 제어
- 명확한 오류만 reject, 불확실은 warning, API 실패는 검사 생략(파이프라인 진행 유지)
