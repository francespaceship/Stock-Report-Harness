---
description: 리포트 기반 hero 이미지 후보 3개를 만들고 1개를 선택합니다.
argument-hint: "<slug>"
---

사용자가 stock-report-harness image 단계를 요청했습니다.

**slug**: $ARGUMENTS

`.claude/skills/stock-image/SKILL.md`를 읽고 그대로 수행하세요.
이미지 생성은 `scripts/run_stock_image_pollinations.py`(Pollinations.ai API)로 수행하고, 채점·선택은 이 세션이 생성된 PNG를 직접 보고 수행합니다. 로컬에서 이미지를 그려 대체하지 마세요.
완료 후 선택된 hero 이미지와 다음 단계 `/stock-review <slug>`를 알려주세요.
