# Pending 이미지 재검사

## `tagger_error` 원인과 현재 방침

기존 구현은 종료된 Hugging Face 레거시 주소
`https://api-inference.huggingface.co/models/{model}` 를 호출했습니다. WD 모델
(`SmilingWolf/wd-eva02-large-tagger-v3` 등)은 Hub에 있어도 **Inference Provider에
배포되어 있지 않아** 라우터/`hf-inference` 로 고쳐도 서버리스 호출이 실패합니다.

공용 Gradio Space [SmilingWolf/wd-tagger](https://huggingface.co/spaces/SmilingWolf/wd-tagger) 는
브라우저 없이 `gradio_client` 로 호출 가능하지만 `queue(max_size=10)`·공유 부하·콜드스타트
때문에 **배치 identity 검사에는 사용하지 않습니다.**

현재 identity / Pending 재검사는 **로컬 ONNX** 만 사용합니다.

- 기본 모델: `SmilingWolf/wd-swinv2-tagger-v3`
- 캐시: `data/models/wd-tagger/SmilingWolf__wd-swinv2-tagger-v3/`
- 필수 파일: `model.onnx`, `selected_tags.csv`
- Settings → **WD 태거 모델 (로컬)** 에서 다운로드

로컬 모델이 없으면 `tagger_model_unavailable` warning 을 기록하며 HF Inference 로
폴백하지 않습니다.

태거 연결 실패는 캐릭터 불일치로 간주하지 않고 `warning` 으로 기록합니다.

## 사용 방법

1. Settings → **WD 태거 모델 (로컬)** 에서 모델을 다운로드하고 설치됨을 확인합니다.
2. **Pending 이미지 재검사** 에서 미리보기를 새로고침합니다.
3. 기본값은 **태거 실패 이미지만** (`tagger_error`, `tagger_unavailable`,
   `tagger_model_unavailable` 등). 필요 시 체크를 끄면 리뷰 미완료 pending 전체를
   재검사합니다.
4. 배치 크기(100~500)를 고르고 **재검사 시작**을 누릅니다.
5. 성공·경고·거절·실패·건너뜀 수치와 최근 판정 사유를 확인합니다.
6. 필요하면 실행 중 **취소**할 수 있습니다. 취소 후 다시 실행해도 안전합니다.

## 대상과 데이터 안전성

다음 이미지가 대상입니다.

- 이미 생성되어 DB에 등록된 이미지
- 리뷰가 없거나 `review_status != completed` 인 캐릭터의 이미지
- 거절(`is_rejected`) 처리되지 않은 이미지
- (기본) `identity_reasons` 에 태거 실패 reason 이 포함된 이미지

파일이 없는 행은 건너뜁니다. 다음 identity 검사 필드만 갱신합니다.

- `identity_status`, `identity_reasons`
- `character_confidence`, `hair_color_confidence`
- `conflicting_character_tag`, `conflicting_character_confidence`
- `suggested_multicolor_tags`
- `identity_checked_at`, `identity_checker_version` (`v2.2-local-wd-only`)

평점, 리뷰 상태, 리뷰 완료 시점, 담당자 메모, 커버 이미지, 수동 태그,
생성 프롬프트, 생성 변수, 이미지 경로와 이미지 파일은 변경하지 않습니다.
작업은 ID cursor 로 나눈 배치로 돌며 배치마다 커밋하므로 전체 ORM 객체를 한 번에
메모리에 올리지 않습니다.
