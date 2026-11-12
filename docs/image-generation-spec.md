# Image Generation Spec

주식 경제리포트의 hero 이미지 생성 규칙입니다.

## 목적

- 모든 최종 리포트는 문서 상단에 hero 이미지 1장을 가진다.
- 이미지는 장식용이 아니라 **리포트 전체 메시지를 압축한 시각 요약**이어야 한다.
- 제목만 보고 만들지 말고, **리포트 전체 내용**을 기반으로 프롬프트를 만든다.

## 기본 워크플로

1. build 직전에 리포트 전체를 읽고 프롬프트 3종 생성
2. `python3 scripts/run_stock_image_pollinations.py <slug>`가 Pollinations.ai gen API로 후보 3장 생성(상태 `images_generated`)
3. Claude 세션이 PNG 3장을 직접 열어 아래 리뷰 기준 5개로 채점해 점수 JSON 생성
4. 최고점 1장 선택(`image-review.txt`, `selected-image.json` 작성). 텍스트·숫자·로고·워터마크가 보이는 후보는 감점/탈락, 3장 모두 탈락하면 `--seed`를 바꿔 2번부터 재시도(최대 2회)
5. `python3 scripts/run_stock_image_pollinations.py <slug> --finalize`로 파일 계약 검증 후 manifest를 `complete`로 전환
6. 선택된 1장만 최종 HTML hero 이미지로 렌더

## 필수 산출물

- `output/assets/<slug>-hero-v1.prompt.txt`
- `output/assets/<slug>-hero-v2.prompt.txt`
- `output/assets/<slug>-hero-v3.prompt.txt`
- `output/assets/<slug>-hero-v1.png`
- `output/assets/<slug>-hero-v2.png`
- `output/assets/<slug>-hero-v3.png`
- `output/assets/<slug>-hero-v1.score.json`
- `output/assets/<slug>-hero-v2.score.json`
- `output/assets/<slug>-hero-v3.score.json`
- `output/assets/<slug>-image-review.txt`
- `output/assets/<slug>-image-manifest.json`
- `output/assets/<slug>-selected-image.json`

`image-manifest.json`은 최소 아래 provenance 필드를 포함한다.

```json
{
  "slug": "<slug>",
  "status": "complete",
  "generation_method": "pollinations-api",
  "generated_with": "Pollinations.ai gen API (model: black-forest-labs/flux.1-schnell)"
}
```

허용 `generation_method`는 `pollinations-api`와 레거시 `codex-cli-imagegen`이며 `scripts/report_contract_lib.py`의 `ALLOWED_IMAGE_GENERATION_METHODS`가 단일 출처다. 생성 직후 manifest는 `status: images_generated`이고 `variants[]`에 후보별 `seed`, 실제 전송 프롬프트(`sent_prompt`)가 기록된다.

`selected-image.json`은 최소 아래 필드를 포함한다. 이미지 경로는 `assets/<file>.png` 또는
`output/assets/<file>.png`처럼 검증기가 실제 파일로 해석할 수 있어야 한다.

```json
{
  "slug": "<slug>",
  "selected_candidate": 2,
  "image_path": "assets/<slug>-hero-v2.png",
  "reason": "리포트 결론과 가장 잘 맞음",
  "generated_with": "Pollinations.ai gen API (model: black-forest-labs/flux.1-schnell)"
}
```

## 필수 규칙

- 이미지 생성은 Pollinations.ai API(`POST https://gen.pollinations.ai/v1/images/generations`, 후보당 1회 요청, 후보마다 다른 seed)가 수행한다. 인증은 `POLLINATIONS_API_KEY` 환경변수만 사용하며 키는 코드·로그·manifest·커밋에 남기지 않는다.
- 로컬 스크립트는 프롬프트 준비, API 호출, 응답의 PNG 정규화(필요 시 포맷 변환만), 백업, 계약 검증만 담당한다. 채점·선택은 Claude 세션이 한다.
- 모델에는 영어 시각 묘사 위주로 압축한 프롬프트(약 1,500자 이내)를 보낸다. 원본 프롬프트는 `hero-v{n}.prompt.txt`에, 실제 전송분은 manifest `variants[].sent_prompt`에 기록한다.
- 429/503은 `Retry-After`만큼 기다려 최대 3회 재시도하고, 402(크레딧 소진)는 재시도 없이 `blocked` 처리한다. API 실패 시 로컬 대체 이미지를 만들지 않는다.
- 기존 산출물이 있으면 덮어쓰기 전에 `output/assets/_backup_<timestamp>/`로 복사한다.
- Pillow/SVG/빈 이미지 같은 절차적 placeholder를 실제 hero 이미지로 대체하지 않는다.
- `status: complete`라도 `generation_method`, `generated_with`, 선택 이미지 메타데이터에 procedural/Pillow/SVG/placeholder 흔적이 있으면 build 검증 실패로 본다.
- **최종 리포트에는 선택된 이미지 1장이 반드시 있어야 한다.**
- 선택 이미지가 없으면 build를 성공 처리하면 안 된다.

## 실행 명령

```bash
python3 scripts/run_stock_image_pollinations.py <slug> --motif "<영어 시각 묘사 1~2문장>"
python3 scripts/run_stock_image_pollinations.py <slug> --finalize
```

디버깅 시에는 실제 생성 없이 전송 프롬프트와 요청 형태(키 마스킹)만 확인할 수 있다.

```bash
python3 scripts/run_stock_image_pollinations.py <slug> --dry-run
```

모델은 `--model` 또는 `STOCK_IMAGE_POLLINATIONS_MODEL`로 바꾼다(기본 `black-forest-labs/flux.1-schnell`, 무료 계층). Codex CLI 경로(`scripts/run_stock_image_codex.py`)는 레거시로 남아 있다.

## 프롬프트 작성 규칙

프롬프트는 반드시 아래 정보를 반영한다.

- 리포트 제목
- 부제
- ticker / 기업 맥락
- 요청 기간
- 각 주요 섹션의 핵심 메시지
- 결론의 톤(성장, 부담, 변곡점, 리스크 등)

금지:

- 텍스트, 숫자, 티커, 로고, 워터마크 삽입
- 실제 앱/대시보드 스크린샷처럼 보이는 구성
- 리포트와 무관한 범용 이미지 재사용

## 리뷰 기준

1. 리포트 전체 적합성
2. 기업/섹터/촉매 맥락 적합성
3. 시각적 명확성
4. 프리미엄 프레젠테이션 품질
5. 절제된 구성
