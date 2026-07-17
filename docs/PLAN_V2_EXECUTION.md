# V2 실행 계획: 구현 분해 및 작업자 분배

기준 문서: `docs/PLAN_IMAGE_GENERATION_REVIEW_V2.md`
작업 브랜치: `feature/image-review-v2` (master에서 분기)
오케스트레이터: fable 5 (Claude Code) — 작업 지시, 코드 리뷰, 통합, 커밋 담당

---

## 1. 작업자 모델 및 접근 상태

전 모델 접근 확인 완료 (2026-07-17 스모크 테스트 통과).

| 작업자 | 호출 방법 | 상태 | 역할 |
|---|---|---|---|
| fable 5 | (본 세션) | ✅ | 오케스트레이터: 작업 분배, 스펙 작성, 리뷰, 통합, 커밋 |
| sonnet 5 | `claude -p --model sonnet "<지시>"` | ✅ `OK-SONNET` | 주요 작업자: 프론트엔드·리팩터링 |
| gpt 5.5 | `codex exec --model gpt-5.5 --full-auto "<지시>"` | ✅ `OK-5.5` | 주요 작업자: 백엔드 CRUD·스크립트 |
| gpt 5.6 sol | `codex exec --model gpt-5.6-sol --full-auto "<지시>"` | ✅ `OK-SOL` | 고급 작업자: 복잡 로직·알고리즘 |
| gemini | `gemini -p "<지시>"` (필요시 `--yolo`) | ✅ `OK-GEMINI` | 보조: 대량 단순 작업, 문서, 교차 검증 |

호출 시 주의사항:

- codex는 stdin을 기다리므로 비대화형 실행 시 반드시 stdin을 닫는다 (bash: `</dev/null`).
- codex 쓰기 작업은 `--full-auto`(workspace-write), 읽기 전용 분석은 `-s read-only`.
- 이 프로젝트는 codex trusted 목록에 이미 등록되어 있음.
- 각 작업자에게는 자족적(self-contained) 지시문을 전달한다: 대상 파일 경로, 기존 코드 규약, 완료 기준, 금지 사항(스코프 밖 파일 수정 금지) 포함.
- 작업 완료 후 fable 5가 diff 리뷰 → 필요시 반려·재지시 → 통합 커밋.

---

## 2. 작업 패키지(WP) 분해

계획 문서의 구현 순서(15장) 5단계를 8개 작업 패키지로 분해한다.
괄호는 계획 문서의 해당 섹션.

### WP1. 외형 태그 관련도 수집 — 데이터 계층 (§4, §13)

- 신규 모델 `CharacterAppearanceTagRelevance` (character_id, tag, tag_category, cooccurrence_count, character_post_count, relevance_score, is_prompt_candidate, is_confirmed, collected_at)
- `GlobalCharacter`에 `primary_hair_color`, `primary_hair_needs_review`, `base_prompt`, `first_post_at`(Danbooru 최초 포스트 날짜) 등 필드 추가
- 관련도 기준값 설정 스키마 (`settings_service` 확장: 카테고리별 임계값, 최소 동시 등장 수, 포스트 수 구간 보정)
- 기타 외형 태그 분류 테이블(설정 기반 확장 가능)
- SQLite 마이그레이션 (기존 방식 준수)

의존: 없음 (최우선 착수)
난이도: 중 / **담당: gpt 5.5**

### WP2. 관련도 수집기 + 선정 로직 (§4.2~4.4)

- Danbooru 동시 등장 카운트 수집기 (`integrations/danbooru/` 기존 client·rate limit 재사용)
- `tag_relevance = 동시 등장 수 ÷ 캐릭터 전체 포스트 수` 계산·저장
- 대표 머리색 1위 선정, 동률/근소 차이 `needs_review`
- multicolor 그룹 별도 관리, 기준 통과 태그만 프롬프트 후보
- 포스트 20 미만 자동 확정 금지, 20~99 기준 +0.10
- 캐릭터 최초 포스트 날짜 조회 저장 (§9.1 대비)
- 재수집 Job (기존 `collect_job_manager` 패턴 재사용, 진행 표시)

의존: WP1
난이도: 상 (API 예산·레이트리밋·부분 실패 처리) / **담당: gpt 5.6 sol**

### WP3. 기본 프롬프트 생성 규칙 (§5)

- `frontend/src/utils/reviewPrompt.ts` + `backend/app/services/generation_prompt_builder.py` 양쪽 수정
- 숫자로 끝나는 이름: 닫는 `::` 앞 공백 삽입
- 관련도 기반 대표 머리색·multicolor 기본 활성화
- `{prefix}, {base_prompt}, {suffix}` 조합은 기존 설정값 재사용
- 프론트·백엔드 규칙 일치 보장 (동일 케이스 단위 테스트)

의존: WP1 (필드), WP2와 병행 가능
난이도: 하~중 / **담당: gpt 5.5**

### WP4. 자동 검사 분리: quality / identity (§6, §8, §13)

- `image_auto_checker.py`를 `quality_checker.py` + `identity_checker.py`로 분리 리팩터링 (기존 Pillow·선명도·WD 태거 로직 재사용)
- 품질: 기본 유효성 → 얼굴 → 신체 3단계, 픽셀 검사는 보조 지표화
- 재현: 기본 프롬프트 포함 태그만 검사, boy·미검출은 warning, 고신뢰 타 캐릭터만 reject, 예상 밖 multicolor 고신뢰 태그는 추천 저장
- `GlobalCharacterImage`에 quality_*/identity_* 필드 추가 (§6.4, §8.3 권장 필드 전부)
- 스키마·serializer·API 응답 확장, `auto_status`는 마이그레이션 기간 유지
- 이미지 저장 파이프라인에 새 검사 연결

의존: WP1 (일부 필드), WP2 결과 활용
난이도: 상 / **담당: sonnet 5** (백엔드 리팩터링 + 판정 정책 섬세함 필요)

### WP5. 자동 재생성 파이프라인 (§7, §9)

- quality_reject → 동일 프롬프트 최대 3회, 실패 시 `generation_failed`
- identity_reject → 최초 포스트 2025-05-01 이후면 `likely_untrained` 처리
- identity_reject 단계별 프롬프트 보정(머리색 재검토 → multicolor 조정 → 눈색 → 기타 외형 태그) 상태 머신
- 보정 성공 프롬프트의 기본 프롬프트 승격 + `previous_base_prompt` 등 이력 저장
- 기존 재생성 Job Manager·카드 진행 표시 재사용
- 생성 상태 전이(`not_generated`~`likely_untrained`) 관리

의존: WP4
난이도: 최상 (상태 머신 + Job 동시성) / **담당: gpt 5.6 sol**

### WP6. V2 리뷰 UI (§10, §11)

- `ReviewPage`에 V2 탭 추가, `GlobalCatalogReviewPanel`/`CatalogReviewRow` 기반 V2 패널·카드
- 카드 표시: quality/identity 배지(독립 warning 2종), 사유, 생성 시도 횟수, 최초 포스트 날짜, likely_untrained
- 기존 단축키 전부 재사용 + `c` multicolor 선택 팝업 신설
- Space 원본 이미지 보기(실제 크기/화면 맞춤 전환, 스크롤)
- §11.4 필터 전체 구현
- 임시 대표 이미지(provisional) 표시

의존: WP4 (API 스키마), WP5 (상태값) — 스키마 확정 후 착수 가능
난이도: 상 (프론트 대형) / **담당: sonnet 5**

### WP7. 리뷰 완료·1차 레이팅 (§12, §13)

- 리뷰 완료 API 확장: 레이팅·성별·프롬프트·선택 태그 + V2 상태(리뷰 상태, 레이팅 단계 `primary`)
- 1차 레이팅 값 `-1/0/1/2/3/5/6` 처리 (4 비권장 안내)
- 리뷰 상태 `pending/in_progress/completed` 관리

의존: WP6와 병행 (백엔드 선행)
난이도: 중 / **담당: gpt 5.5**

### WP8. 검증 배치·튜닝 (§15 5단계, §16)

- 500명 테스트 배치 실행 스크립트
- 품질·재현 오탐/미탐 기록 및 통계 리포트
- 임계값 조정 인터페이스 확인
- 자동 재생성 성공률·리뷰 속도 측정

의존: WP1~WP7 전체
난이도: 중 / **담당: gpt 5.5 + gemini** (통계 리포트 교차 검증), 판정 튜닝은 fable 5

---

## 3. 실행 순서와 병렬화

```text
Phase A: WP1 (gpt 5.5)
Phase B: WP2 (gpt 5.6 sol) ∥ WP3 (gpt 5.5)
Phase C: WP4 (sonnet 5) ∥ WP7 백엔드 선행분 (gpt 5.5)
Phase D: WP5 (gpt 5.6 sol) ∥ WP6 (sonnet 5)
Phase E: WP8 (gpt 5.5 + gemini)
```

- 각 Phase 종료 시 fable 5가 diff 리뷰 → 테스트 실행 → `feature/image-review-v2`에 커밋.
- 서로 다른 작업자가 같은 파일을 동시에 수정하지 않도록 WP 경계를 파일 단위로 유지한다.
  충돌 위험 파일(`types/index.ts`, `schemas/review.py`, serializer)은 fable 5가 직접 조정하거나 순차 처리.
- 각 WP는 작업자에게 전달하기 전에 fable 5가 상세 스펙(대상 파일, 인터페이스, 완료 기준, 테스트 방법)을 작성해 지시문에 포함한다.

## 4. 품질 관리

- 작업자 산출물은 무조건 fable 5 리뷰 통과 후 커밋 (직접 커밋 금지)
- 백엔드: 기존 테스트 + WP별 신규 단위 테스트 필수
- 프론트: 타입 체크·빌드 통과 + 브라우저 프리뷰로 동작 확인
- 판정 임계값 등 정책성 결정은 fable 5가 사용자와 확인 후 확정
- 커밋 단위는 WP 단위, 메시지는 기존 컨벤션(`feat:`/`docs:` 등) 준수
