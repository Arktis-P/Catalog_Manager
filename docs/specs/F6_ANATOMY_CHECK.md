# F6: bad anatomy 품질 검사 확장 (담당: gpt 5.6 sol)

기준: `docs/PLAN_IMAGE_REVIEW_V2_FOLLOWUP.md` §2.1, §5 Phase 2.
선행: F1 커밋 후 착수.

## 접근 방식 (오케스트레이터 결정 — 변경 금지)

픽셀 휴리스틱으로 신체 구조 판정이 불가능하므로 **Gemini Vision API 기반 구조화 분석**을 채택한다.

- 기본 **비활성**(`v2_anatomy_check_enabled=false`) — 비용·속도는 사용자가 제어
- API 실패·키 없음 → 검사 생략하고 기존 quality 결과 유지 (파이프라인 진행 유지, 사유에 `anatomy_check_skipped` 기록하지 않음 — 조용히 생략)

## 범위 (이 파일들만)

- 신규: `backend/app/integrations/vision/__init__.py`, `backend/app/integrations/vision/gemini_anatomy.py`
- 수정: `backend/app/services/quality_checker.py` (anatomy 단계 통합 — 기존 검사 유지)
- 수정: `backend/app/services/settings_service.py`, `backend/app/schemas/settings.py` (설정 키 추가)
- 신규: `backend/tests/test_anatomy_check.py`
- 금지: v2_generation_pipeline.py, identity_checker.py, character_image_service.py, review_service.py, frontend/, docs/

## 1. gemini_anatomy 모듈

- `GEMINI_API_KEY` 환경변수(또는 `input/` 하위 키 파일 — 기존 danbooru.env 패턴 참고) 사용, REST 호출 (`generativelanguage.googleapis.com`, 모델은 설정 `v2_anatomy_check_model`, 기본 `gemini-2.5-flash`)
- 이미지 바이트 + 구조화 프롬프트 전송, JSON 응답 강제 (response_mime_type application/json)
- 요구 스키마:

```json
{
  "verdict": "ok | uncertain | anomaly",
  "reasons": ["body_proportion_anomaly", "extra_limb", "missing_limb", "joint_anomaly", "hand_anomaly", "finger_count_anomaly", "body_fusion"],
  "confidence": 0.0
}
```

- 프롬프트: 애니메이션 일러스트 기준으로 §2.1의 검사 항목(신체 비율, 팔다리 개수·연결, 목·어깨·허리 붕괴, 손가락 개수·융합, 인물 융합)을 명시하고, 양식화된 과장(만화적 비율)은 오류로 보지 말 것을 지시
- 타임아웃·1회 재시도, 실패 시 None 반환

## 2. quality_checker 통합

- 3단계(기본 유효성→얼굴→신체) 뒤에 anatomy 단계 추가: 설정 활성 + 기존 결과가 reject가 아닐 때만 호출
- 판정 반영:
  - `verdict=anomaly` + confidence >= `v2_anatomy_reject_confidence`(기본 0.8) → `reject`, reasons를 quality_reasons에 병합
  - `verdict=anomaly` (저신뢰) 또는 `uncertain` → `warning`
  - `verdict=ok` → 기존 상태 유지
- checker_version을 "v2.1"로 올려라

## 3. 설정 키

- `v2_anatomy_check_enabled` (bool, 기본 false)
- `v2_anatomy_check_model` (str, 기본 "gemini-2.5-flash")
- `v2_anatomy_reject_confidence` (float, 기본 0.8)

기존 v2_* 키 패턴 그대로.

## 테스트

- Gemini 호출 mock: anomaly 고신뢰→reject, 저신뢰→warning, ok→불변, 실패→불변(생략)
- 설정 비활성 시 호출 자체가 없음 검증
- 실 API 호출 테스트 금지

## 완료 기준

- `cd backend && ../.venv/Scripts/python.exe -m pytest tests/ -q` 기존 실패 3건 외 통과
- 커밋 금지, 스코프 밖 파일 수정 금지
