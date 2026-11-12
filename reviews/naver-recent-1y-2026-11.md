---
slug: naver-recent-1y-2026-11
status: pass
reviewed_at: 2026-11-12
plan_source: plan/naver-recent-1y-2026-11.md
research_source: research/naver-recent-1y-2026-11.md
draft_source: drafts/naver-recent-1y-2026-11.md
review_type: separate-session-4way
review_execution: separate_subagent_sessions
reviewers:
  - fact-checker
  - report-designer
  - content-editor
  - blind-spot (independent general-purpose session, codex-independent equivalent)
---

# Review: naver-recent-1y-2026-11

## 라운드 요약

- 1차: fact-checker needs_fix(Medium 3), content-editor needs_fix(High 5), report-designer PASS, blind-spot 조건부 PASS.
- 2차 수정 후 재리뷰: fact-checker needs_fix(근거 초과 서술 2건), content-editor needs_fix(Medium 3).
- 3차 수정 후 재리뷰: fact-checker PASS, content-editor PASS. 수정 라운드 2회로 종료.

## Fact-Checker — PASS

- ticker 035420.KS, 기간 2025-11-12 ~ 2026-11-12가 plan/research/draft에서 일치한다.
- yfinance-raw.json 재계산: 263,500원 → 194,300원(-26.26%), 고점 287,000원(2026-01-29), 저점 169,000원(2026-11-03, -41.11%), 5% 이상 변동일 24일(상승 14/하락 10, 11-11 종가까지), 주요 급등락일 수치 모두 일치한다.
- 근거 범위를 넘은 서술(두나무 설명, 네이버 금융 403 서술)을 제거하고 research에 시도 경위를 기록했다.
- 본문 [S#]/[N#]은 모두 References에 있고 뉴스 5건 URL은 latest100 JSON과 일치한다.

## Report-Designer — PASS

- 필수 섹션, price-chart 블록 1개(aria_label 포함), stat-card 2개가 spec에 맞는다. 선택 이미지(후보 1)에 읽히는 글자·숫자·로고가 없다.
- 최종 HTML 시각 검증(560px 셸, 앱바, 차트 Y축, 히어로 카드 alt, 링크 줄바꿈)은 stock-build 검증기로 이관한다.

## Content-Editor — PASS

- 인과 단정 완화, 06-10 코스피 하락 교란 요인 명시, S8 시간 순서 정정, 면책 템플릿 4문장, 용어 풀이, KST 표기, References 형식이 반영되었다.
- 투자 권유·수익 보장·FOMO 표현 없음.

## Blind-Spot (독립 세션) — PASS (조건부)

- 계약 파일/provenance/한계 고지는 통과. Tier 표기, 인용 정합성 지적을 반영했다.

## 남은 한계 (차단 아님)

- 외국인·기관·개인 수급 수치를 확보하지 못했다. docs/finance-style-guide.md의 '수급 데이터 의무 포함'은 미충족이며, AGENTS.md는 '가능하면 참고'로 완화돼 있다. 시도 경위(토스 400, 네이버 금융 403, KRX/pykrx 미시도)는 research에 기록했다. 사용자 판단이 필요한 정책 예외다.
- 뉴스 100건은 실적 발표일(11-12) 일부 시간대 표본이며 링크는 Google News 제공자 링크(url_is_fallback)다.
- 2026-11-12 가격은 장중 값이다. 빌드 시 마지막 행이 달라질 수 있다.
- S1·S3은 자사 보도자료이나 링크가 제공자 링크라 Tier B로 표기했다.
- 빌드 후 확인: stat-card tone 색, 히어로 alt, 긴 링크 줄바꿈, design 문서 간 충돌(visual-system vs toss_design).
