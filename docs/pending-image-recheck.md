# Pending 이미지 재검사

## `tagger_error` 원인과 설정

기존 구현은 종료된 Hugging Face 레거시 주소
`https://api-inference.huggingface.co/models/{model}`를 호출했습니다. 현재 구현은
`https://router.huggingface.co/hf-inference/models/{model}`를 사용합니다.

기본 모델 `SmilingWolf/wd-eva02-large-tagger-v3`는 Hugging Face Hub에는 있지만
현재 Inference Provider에 배포되어 있지 않을 수 있습니다. 이 경우 Settings의
**HF WD Model ID**에 직접 배포한 Hugging Face Inference Endpoint의 전체 HTTPS
URL(`https://*.endpoints.huggingface.cloud`)을 입력해야 합니다. HF Token 유출을
막기 위해 다른 도메인의 URL은 거부됩니다.

태거 오류는 다음 reason code로 저장됩니다.

- `tagger_auth_error`
- `tagger_model_not_found`
- `tagger_rate_limited`
- `tagger_timeout`
- `tagger_invalid_response`
- `tagger_service_unavailable`
- `tagger_error`

태거 연결 실패는 캐릭터 불일치로 간주하지 않고 `warning`으로 기록됩니다.
진단 로그에는 모델, URL, HTTP 상태, Content-Type, 응답 일부와 reason code가
남지만 HF Token은 남지 않습니다.

## 사용 방법

1. Settings 페이지에서 HF Token과 WD 모델 또는 전용 Endpoint URL을 저장합니다.
2. **Pending 이미지 재검사**에서 **미리보기 새로고침**을 누릅니다.
3. 대상 수, 리뷰 완료 제외 수, 파일 누락 수를 확인합니다.
4. 배치 크기(100~500)를 선택하고 **재검사 시작**을 누릅니다.
5. 성공·경고·거부·실패·건너뜀 수와 현재 처리 항목을 확인합니다.
6. 필요하면 실행 중 **취소**를 누릅니다. 취소 후 다시 실행해도 안전합니다.

## 대상과 데이터 안전성

다음 이미지만 대상입니다.

- 기존에 생성되어 DB에 등록된 이미지
- 리뷰가 없거나 `review_status != completed`인 캐릭터의 이미지
- 삭제(`is_rejected`) 처리되지 않은 이미지

파일이 없는 항목은 건너뜁니다. 다음 identity 검사 필드만 갱신합니다.

- `identity_status`, `identity_reasons`
- `character_confidence`, `hair_color_confidence`
- `conflicting_character_tag`, `conflicting_character_confidence`
- `suggested_multicolor_tags`
- `identity_checked_at`, `identity_checker_version`

평점, 리뷰 상태, 리뷰 완료 시점에 해당하는 데이터, 커버 이미지, 수동 태그,
생성 프롬프트, 생성 횟수, 이미지 경로와 이미지 파일은 변경하지 않습니다.
대상은 ID cursor와 제한된 배치로 읽고 배치마다 커밋하므로 전체 ORM 객체를
한 번에 메모리에 적재하지 않습니다.
