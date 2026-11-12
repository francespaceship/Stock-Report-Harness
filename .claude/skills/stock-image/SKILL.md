---
name: stock-image
description: 주식 리포트 히어로 이미지를 생성하고 선택한다. plan, research, draft가 존재한 뒤 /stock-image <slug>로 사용하며, 프롬프트 3개, PNG 후보 3장, 스코어 JSON, image-manifest.json, image-review.txt, selected-image.json을 생성한다.
---

# 주식 이미지 스킬

리포트 slug에 필요한 히어로 이미지 에셋 세트를 만든다.
래스터 생성은 Pollinations.ai API(`scripts/run_stock_image_pollinations.py`)가 담당하고,
채점·선택은 이 스킬을 실행하는 Claude 세션이 생성된 PNG를 직접 보고 수행한다.
로컬에서 이미지를 그려 대체하지 않는다.

## 선행 조건

- `plan/<slug>.md`, `research/<slug>.md`, `drafts/<slug>.md`가 존재해야 한다.
- 프롬프트 작성 전 세 파일을 모두 읽는다. 제목만으로 프롬프트를 작성하지 않는다.
- 환경변수 `POLLINATIONS_API_KEY`가 필요하다(없으면 스크립트가 `blocked` manifest를 쓰고 종료한다). 키 값은 출력·기록하지 않는다.

## 절차

### (a) 생성

리포트 메시지와 톤을 영어 시각 묘사 1~2문장(텍스트·숫자·로고 없는 추상 에디토리얼 비주얼)으로 압축해 `--motif`로 넘긴다.

```bash
python3 scripts/run_stock_image_pollinations.py <slug> --motif "<English visual motif>"
```

- `hero-v{1..3}.prompt.txt`(원본 프롬프트), `hero-v{1..3}.png`, `image-manifest.json`(`status: images_generated`)이 생성된다.
- 후보마다 seed가 다르며, 실제 전송 프롬프트와 seed는 manifest `variants[]`에 기록된다.
- 기존 산출물은 `output/assets/_backup_<timestamp>/`로 먼저 복사된다.
- 실제 호출 없이 확인하려면 `--dry-run`. 모델은 `--model` 또는 `STOCK_IMAGE_POLLINATIONS_MODEL`.

### (b) 채점·선택 (이 세션이 직접)

PNG 3장을 Read로 직접 열어 `docs/image-generation-spec.md`의 리뷰 기준 5개로 채점한다:
리포트 전체 적합성, 기업/섹터/촉매 맥락 적합성, 시각적 명확성, 프리미엄 프레젠테이션 품질, 절제된 구성.

작성할 파일(모두 `output/assets/`):

- `<slug>-hero-v{1..3}.score.json`: `{slug, candidate, image_path, prompt_path, report_fit, company_sector_fit, visual_clarity, premium_quality, restraint, total, notes}` (`total`은 숫자 필수)
- `<slug>-image-review.txt`: 선택 이유와 탈락 이유 요약
- `<slug>-selected-image.json`: `{slug, selected_candidate, image_path, reason, generated_with}`
  - `image_path`는 `assets/<slug>-hero-vN.png` 형태, `generated_with`는 manifest 값(`Pollinations.ai gen API (model: <모델 ID>)`)과 동일하게

### (c) 탈락 규칙과 재시도

- 텍스트·숫자·티커·로고·워터마크·UI/대시보드처럼 보이는 요소가 있는 후보는 감점하거나 탈락시킨다.
- 3장이 모두 탈락하면 `--seed`를 바꿔 (a)부터 다시 실행한다(최대 2회). 모델 변경이 필요하면 `--model`.
- 재시도 후에도 통과 후보가 없으면 `blocked`로 보고한다. 로컬 대체 이미지를 만들지 않는다.

### (d) 완료 처리

```bash
python3 scripts/run_stock_image_pollinations.py <slug> --finalize
```

점수 JSON 3개, `image-review.txt`, `selected-image.json`, PNG 시그니처, 선택 후보와 경로 일치 여부를 검증하고 통과하면 manifest를 `status: complete`로 바꾼다.
실패하면 `blocked` manifest(`blocked_stage: finalize`)를 쓰며, 파일을 고친 뒤 `--finalize`를 다시 실행할 수 있다.

## provenance 규칙

- `generation_method: "pollinations-api"`, `generated_with: "Pollinations.ai gen API (model: <실제 모델 ID>)"`.
- manifest·selected-image·점수 기록의 어떤 문자열에도 `report_contract_lib.PROHIBITED_IMAGE_GENERATION_TERMS`에 걸리는 단어(검증기가 막는 절차적 생성 관련 용어)를 쓰지 않는다. 설명 문구를 쓸 때도 해당 단어를 피한다.

## 이미지 규칙

- 텍스트, 숫자, 티커 심볼, 로고, 워터마크, UI 스크린샷, 가짜 대시보드 화면을 포함하지 않는다.
- 추상적/에디토리얼 비주얼을 사용한다: 웨이퍼, 메모리 스택, 시장 라인, 매크로/섹터 메타포, 스튜디오 조명.
- 이미지가 리포트의 실제 톤과 일치해야 한다. 리스크 중심 리포트에 일반적인 상승 이미지를 사용하지 않는다.
- Pollinations.ai 외의 직접 LLM/이미지 API 키 호출은 하지 않는다.

## 차단 규칙

키 없음, 402(크레딧 소진), 429/503 재시도 초과, 네트워크·응답 오류가 발생하면 스크립트가 `status: blocked` manifest와 `blocked_reason`을 남긴다. 이미지 단계를 완료로 표시하지 않으며 `/stock-build` 통과를 허용하지 않는다.

## 완료 보고

선택된 이미지 경로, 매니페스트 경로, 다음 명령어를 보고한다: `/stock-review <slug>`.

`stock-goal`에서 호출된 경우 이 보고는 내부 체크포인트일 뿐이다. 멈추거나 사용자를 기다리지 않고 즉시 `/stock-review <slug>`로 진행한다.
