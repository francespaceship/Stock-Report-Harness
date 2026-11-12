#!/usr/bin/env python3
"""Generate stock-image hero candidates through the Pollinations.ai gen API.

Only raster generation is handled here.  Scoring and selection are done by the
Claude session that runs `/stock-image` (see .claude/skills/stock-image/SKILL.md).

  python3 scripts/run_stock_image_pollinations.py <slug>             # generate 3 candidates
  python3 scripts/run_stock_image_pollinations.py <slug> --dry-run   # show prompts/request only
  python3 scripts/run_stock_image_pollinations.py <slug> --finalize  # validate scoring files -> complete

Auth: POLLINATIONS_API_KEY environment variable only (never written anywhere).
Model: --model or STOCK_IMAGE_POLLINATIONS_MODEL (default black-forest-labs/flux.1-schnell, free tier).
"""
from __future__ import annotations

import argparse
import base64
import io
import json
import os
import re
import shutil
import sys
import time
import urllib.error
import urllib.request
import zlib
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

from report_contract_lib import (
    ASSET_DIR,
    prohibited_image_generation_hits,
    rel,
    selected_image_path,
)
from run_stock_image_codex import (  # Codex 실행기와 공통인 컨텍스트/경로/프롬프트 로직 재사용
    StagePaths,
    load_context,
    paths_for,
    render_candidate_prompt,
    require_inputs,
    write_prompt_files,
)

GENERATION_METHOD = "pollinations-api"
DEFAULT_MODEL = "black-forest-labs/flux.1-schnell"
DEFAULT_BASE_URL = "https://gen.pollinations.ai"
GENERATIONS_PATH = "/v1/images/generations"
DEFAULT_SIZE = "1536x1024"
MAX_SENT_PROMPT_CHARS = 1500
MAX_RETRIES = 3
MAX_RETRY_WAIT = 120
KEY_ENV = "POLLINATIONS_API_KEY"
MODEL_ENV = "STOCK_IMAGE_POLLINATIONS_MODEL"
PNG_SIG = b"\x89PNG\r\n\x1a\n"

# 후보별 영어 시각 구성 (모델에 실제 전송). 한국어 리포트 본문은 보내지 않는다.
COMPOSITIONS = {
    1: "sector-mechanism close-up: abstract materials tied to the subject industry, showing supply, product cycle, demand and risk in one restrained composition",
    2: "market-forces landscape: market currents, capital flow and industry catalysts implied through light, depth and geometry, not literal charts",
    3: "risk-opportunity balance: tension between growth optionality and execution or macro risk, using contrast, layered materials and calm studio lighting",
}
STYLE = (
    "Premium editorial finance illustration, 16:9 magazine opening image, sophisticated depth, "
    "realistic materials, cinematic studio lighting, restrained color palette, calm and sober tone."
)
AVOID = (
    "Strictly avoid: any visible text, letters, numbers, ticker symbols, logos, watermarks, "
    "interface screenshots, dashboards, chart labels, buy or sell signals, cartoon mascots."
)
_SLUG_NOISE = re.compile(r"^(recent|latest|last|\d+[dwmy]|\d{4}|\d{1,2}|report|analysis)$", re.I)


class Blocked(Exception):
    """Generation cannot continue; the reason is written to a blocked manifest."""


# --------------------------------------------------------------------------- helpers
def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def generated_with(model: str) -> str:
    return f"Pollinations.ai gen API (model: {model})"


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def stage_files(paths: StagePaths) -> list[Path]:
    return [*paths.prompts, *paths.images, *paths.scores, paths.manifest, paths.review, paths.selected]


def backup_existing(paths: StagePaths) -> Path | None:
    """덮어쓰기 전에 기존 산출물을 output/assets/_backup_<timestamp>/ 로 복사한다."""
    existing = [p for p in stage_files(paths) if p.is_file()]
    if not existing:
        return None
    dest = ASSET_DIR / f"_backup_{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    dest.mkdir(parents=True, exist_ok=True)
    for p in existing:
        shutil.copy2(p, dest / p.name)
    return dest


def clear_stale_scoring(paths: StagePaths) -> None:
    """새 이미지가 생성되면 이전 후보의 채점/선택 기록은 무효이므로 제거한다(백업 이후)."""
    for p in (*paths.scores, paths.review, paths.selected):
        p.unlink(missing_ok=True)


def get_api_key() -> str:
    """프로세스 환경변수 우선. Windows에서 셸이 사용자 변수 등록 전에 시작된 경우 레지스트리 HKCU 아래 Environment 항목에서 읽는다."""
    key = os.environ.get(KEY_ENV, "").strip()
    if key or sys.platform != "win32":
        return key
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as reg:
            value, _kind = winreg.QueryValueEx(reg, KEY_ENV)
        return str(value).strip()
    except (OSError, ImportError):
        return ""


def mask(secret: str) -> str:
    return "<unset>" if not secret else f"****(len={len(secret)})"


# --------------------------------------------------------------------------- prompts
def _slug_terms(slug: str) -> str:
    words = [w for w in re.split(r"[^A-Za-z]+", slug) if w and not _SLUG_NOISE.match(w)]
    return " ".join(words)


def build_sent_prompt(context: dict[str, str], variant: int, motif: str | None) -> str:
    """모델에 실제 전송하는 영어 시각 묘사 프롬프트(≤1500자)."""
    subject = (motif or "").strip() or (
        f"abstract visual metaphor for the {_slug_terms(context['slug'])} industry and its key business drivers"
        if _slug_terms(context["slug"])
        else "abstract visual metaphor for a listed company's business drivers"
    )
    parts = [
        f"Hero image. Subject: {subject}.",
        f"Composition: {COMPOSITIONS[variant]}.",
        STYLE,
        AVOID,
    ]
    prompt = " ".join(p.strip() for p in parts)
    if len(prompt) > MAX_SENT_PROMPT_CHARS:
        raise Blocked(f"전송 프롬프트가 {MAX_SENT_PROMPT_CHARS}자를 초과함({len(prompt)}자): --motif를 줄여라")
    return prompt


def check_prompt_safety(prompts: list[str]) -> None:
    hits = prohibited_image_generation_hits(prompts)
    if hits:
        raise Blocked("전송 프롬프트에 금지 provenance 단어가 포함됨(검증기 충돌): " + "; ".join(hits[:3]))


# --------------------------------------------------------------------------- HTTP
def build_request_body(model: str, prompt: str, size: str, seed: int) -> dict[str, Any]:
    return {"model": model, "prompt": prompt, "size": size, "seed": seed, "response_format": "b64_json"}


def _retry_after_seconds(value: str | None, default: int) -> int:
    if not value:
        return default
    value = value.strip()
    try:
        return max(0, min(int(float(value)), MAX_RETRY_WAIT))
    except ValueError:
        pass
    try:
        delta = (parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds()
        return max(0, min(int(delta), MAX_RETRY_WAIT))
    except Exception:
        return default


def request_image(url: str, key: str, body: dict[str, Any], *, timeout: int, sleep=time.sleep) -> tuple[bytes, int]:
    """POST 1회(+429/503 재시도 최대 3회). (이미지 바이트, 재시도 횟수) 반환."""
    data = json.dumps(body).encode("utf-8")
    retries = 0
    while True:
        req = urllib.request.Request(
            url,
            data=data,
            method="POST",
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "stock-report-harness/1.0",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            item = (payload.get("data") or [None])[0] or {}
            b64 = item.get("b64_json")
            if not b64:
                raise Blocked("응답에 data[0].b64_json 없음")
            return base64.b64decode(b64), retries
        except urllib.error.HTTPError as exc:
            status = exc.code
            if status in (429, 503):
                if retries >= MAX_RETRIES:
                    raise Blocked(f"HTTP {status}: 재시도 {MAX_RETRIES}회 후에도 실패") from exc
                wait = _retry_after_seconds(exc.headers.get("Retry-After"), 5 * (retries + 1))
                retries += 1
                print(f"[retry {retries}/{MAX_RETRIES}] HTTP {status}, {wait}s 대기", file=sys.stderr)
                sleep(wait)
                continue
            if status == 402:
                raise Blocked("HTTP 402: 크레딧/예산 소진(재시도하지 않음)") from exc
            if status == 401:
                raise Blocked(f"HTTP 401: {KEY_ENV}가 없거나 유효하지 않음") from exc
            raise Blocked(f"HTTP {status}: {exc.reason}") from exc
        except urllib.error.URLError as exc:
            raise Blocked(f"네트워크 오류: {exc.reason}") from exc
        except (json.JSONDecodeError, ValueError) as exc:
            raise Blocked(f"응답 파싱 실패: {exc}") from exc


# --------------------------------------------------------------------------- image
def image_format(data: bytes) -> str:
    if data.startswith(PNG_SIG):
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return "unknown"


def to_png_bytes(data: bytes) -> tuple[bytes, str, bool]:
    """(png bytes, 원본 포맷, 변환 여부). PNG가 아니면 Pillow로 포맷 변환만 한다(그리기 금지)."""
    fmt = image_format(data)
    if fmt == "png":
        return data, fmt, False
    if fmt == "unknown":
        raise Blocked("응답이 이미지(PNG/JPEG/WEBP)로 인식되지 않음")
    try:
        from PIL import Image  # type: ignore
    except ImportError as exc:
        raise Blocked(f"응답이 {fmt}인데 PNG 변환용 Pillow가 설치되어 있지 않음") from exc
    with Image.open(io.BytesIO(data)) as im:
        im.load()
        out = io.BytesIO()
        im.save(out, format="PNG")
    return out.getvalue(), fmt, True


# --------------------------------------------------------------------------- manifests
def base_manifest(paths: StagePaths, model: str, status: str) -> dict[str, Any]:
    return {
        "slug": paths.slug,
        "status": status,
        "generation_method": GENERATION_METHOD,
        "generated_with": generated_with(model),
        "model": model,
        "prompt_files": [rel(p) for p in paths.prompts],
        "required_images": [rel(p) for p in paths.images],
        "required_scores": [rel(p) for p in paths.scores],
        "updated_at": _now(),
    }


def write_blocked(paths: StagePaths, model: str, reason: str, *, stage: str, extra: dict[str, Any] | None = None) -> None:
    payload = base_manifest(paths, model, "blocked")
    payload.update({"blocked_reason": reason, "blocked_stage": stage})
    if extra:
        payload.update(extra)
    write_json(paths.manifest, payload)
    print(f"[BLOCKED] {reason}", file=sys.stderr)


# --------------------------------------------------------------------------- generate
def cmd_generate(args: argparse.Namespace, paths: StagePaths) -> int:
    model = args.model
    context = load_context(paths)
    base_seed = args.seed if args.seed is not None else zlib.crc32(paths.slug.encode("utf-8")) % 1_000_000
    seeds = [base_seed + (v - 1) * 1009 for v in (1, 2, 3)]
    url = args.base_url.rstrip("/") + GENERATIONS_PATH
    key = get_api_key()

    if args.dry_run:
        try:
            sent = [build_sent_prompt(context, v, args.motif) for v in (1, 2, 3)]
            check_prompt_safety(sent)
        except Blocked as exc:
            print(f"[BLOCKED] {exc}", file=sys.stderr)
            return 2
        print(f"# endpoint: POST {url}")
        print(f"# model: {model}  size: {args.size}  seeds: {seeds}")
        print(f"# headers: Authorization: Bearer {mask(key)} | Content-Type: application/json")
        for v in (1, 2, 3):
            print(f"\n## candidate v{v}  (sent prompt {len(sent[v-1])} chars)")
            print(f"request body: {json.dumps(build_request_body(model, '<sent prompt>', args.size, seeds[v-1]), ensure_ascii=False)}")
            print(f"sent prompt: {sent[v-1]}")
        print("\n(prompt.txt 원본은 실제 실행 시 기존 render_candidate_prompt 결과로 저장됨)")
        return 0

    backup = backup_existing(paths)
    if backup:
        print(f"[backup] {rel(backup)}")
    write_prompt_files(paths, context)
    try:
        sent = [build_sent_prompt(context, v, args.motif) for v in (1, 2, 3)]
        check_prompt_safety(sent)
        if not key:
            raise Blocked(f"환경변수 {KEY_ENV}가 설정되지 않음 (이미지를 로컬에서 대체 생성하지 않음)")
        clear_stale_scoring(paths)
        variants: list[dict[str, Any]] = []
        for i, (img_path, prompt_path, score_path) in enumerate(zip(paths.images, paths.prompts, paths.scores), 1):
            print(f"[generate] v{i} seed={seeds[i-1]} model={model}")
            raw, retries = request_image(
                url, key, build_request_body(model, sent[i - 1], args.size, seeds[i - 1]), timeout=args.timeout_seconds
            )
            png, fmt, converted = to_png_bytes(raw)
            tmp = img_path.with_suffix(".png.tmp")
            tmp.write_bytes(png)
            tmp.replace(img_path)
            variants.append(
                {
                    "variant": i,
                    "prompt_file": rel(prompt_path),
                    "image_file": rel(img_path),
                    "score_file": rel(score_path),
                    "seed": seeds[i - 1],
                    "sent_prompt": sent[i - 1],
                    "sent_prompt_chars": len(sent[i - 1]),
                    "response_format": fmt,
                    "converted_to_png": converted,
                    "bytes": len(png),
                    "retries": retries,
                }
            )
        manifest = base_manifest(paths, model, "images_generated")
        manifest.update(
            {
                "endpoint": GENERATIONS_PATH,
                "size": args.size,
                "base_seed": base_seed,
                "variants": variants,
                "generated_at": _now(),
            }
        )
        hits = prohibited_image_generation_hits(manifest)
        if hits:
            raise Blocked("manifest에 금지 provenance 단어 포함: " + "; ".join(hits[:3]))
        write_json(paths.manifest, manifest)
    except Blocked as exc:
        write_blocked(paths, model, str(exc), stage="generate")
        return 2
    print(f"[OK] images_generated: {', '.join(rel(p) for p in paths.images)}")
    print(f"  manifest: {rel(paths.manifest)}")
    print("  다음: PNG 3장을 직접 열어 채점 → score.json/image-review.txt/selected-image.json 작성 → --finalize")
    return 0


# --------------------------------------------------------------------------- finalize
def finalize_problems(paths: StagePaths) -> tuple[list[str], dict[str, Any] | None, dict[str, Any] | None]:
    problems: list[str] = []
    manifest: dict[str, Any] | None = None
    selected: dict[str, Any] | None = None

    if not paths.manifest.is_file():
        return [f"{rel(paths.manifest)} 없음: 먼저 생성 단계를 실행"], None, None
    try:
        manifest = read_json(paths.manifest)
    except Exception as exc:
        return [f"{rel(paths.manifest)} JSON 오류: {exc}"], None, None
    if not isinstance(manifest, dict):
        return [f"{rel(paths.manifest)} object 아님"], None, None
    ok_status = manifest.get("status") in ("images_generated", "complete") or (
        manifest.get("status") == "blocked" and manifest.get("blocked_stage") == "finalize"
    )
    if not ok_status:
        problems.append(f"manifest status가 finalize 가능 상태가 아님: {manifest.get('status')!r} ({manifest.get('blocked_reason') or ''})")
    if manifest.get("generation_method") != GENERATION_METHOD:
        problems.append(f"manifest generation_method는 {GENERATION_METHOD} 여야 함")

    for p in (*paths.prompts, *paths.images):
        if not p.is_file():
            problems.append(f"{rel(p)} 없음")
        elif p in paths.images and not p.read_bytes().startswith(PNG_SIG):
            problems.append(f"{rel(p)} PNG 시그니처 아님")

    for i, p in enumerate(paths.scores, 1):
        if not p.is_file():
            problems.append(f"{rel(p)} 없음")
            continue
        try:
            data = read_json(p)
        except Exception as exc:
            problems.append(f"{rel(p)} JSON 오류: {exc}")
            continue
        if not isinstance(data, dict):
            problems.append(f"{rel(p)} object 아님")
        elif not isinstance(data.get("total"), (int, float)):
            problems.append(f"{rel(p)} 숫자 `total` 필요")

    if not paths.review.is_file() or not paths.review.read_text(encoding="utf-8").strip():
        problems.append(f"{rel(paths.review)} 없음/비어 있음")

    if not paths.selected.is_file():
        problems.append(f"{rel(paths.selected)} 없음")
        return problems, manifest, None
    try:
        selected = read_json(paths.selected)
    except Exception as exc:
        return [*problems, f"{rel(paths.selected)} JSON 오류: {exc}"], manifest, None
    if not isinstance(selected, dict):
        return [*problems, f"{rel(paths.selected)} object 아님"], manifest, None
    if str(selected.get("slug") or paths.slug) != paths.slug:
        problems.append(f"selected-image slug 불일치: {selected.get('slug')!r}")
    cand = selected.get("selected_candidate")
    if cand not in (1, 2, 3):
        problems.append("selected-image `selected_candidate`는 1~3 정수여야 함")
    if not str(selected.get("reason") or "").strip():
        problems.append("selected-image `reason` 필요")
    chosen, _ = selected_image_path(paths.slug)
    if chosen is None or not chosen.is_file():
        problems.append("selected-image 경로가 실제 파일로 해석되지 않음")
    elif chosen.suffix.lower() != ".png":
        problems.append("선택 이미지는 PNG여야 함")
    elif cand in (1, 2, 3) and chosen.resolve() != paths.images[cand - 1].resolve():
        problems.append(f"selected-image 경로가 selected_candidate({cand})의 PNG와 다름")
    hits = prohibited_image_generation_hits(selected)
    if hits:
        problems.append("selected-image에 금지 provenance 단어: " + "; ".join(hits[:3]))
    return problems, manifest, selected


def cmd_finalize(args: argparse.Namespace, paths: StagePaths) -> int:
    model = args.model
    problems, manifest, selected = finalize_problems(paths)
    if manifest and manifest.get("model"):
        model = str(manifest["model"])
    if problems or manifest is None or selected is None:
        carry = {k: manifest[k] for k in ("variants", "size", "base_seed", "endpoint", "generated_at") if manifest and k in manifest}
        write_blocked(paths, model, "finalize 검증 실패: " + "; ".join(problems[:12]), stage="finalize", extra=carry)
        return 2

    gen_with = generated_with(model)
    if not str(selected.get("generated_with") or "").strip():
        selected["generated_with"] = gen_with
        write_json(paths.selected, selected)
    final = {k: v for k, v in manifest.items() if k not in ("blocked_reason", "blocked_stage")}
    final.update(
        {
            "status": "complete",
            "generation_method": GENERATION_METHOD,
            "generated_with": gen_with,
            "selected_candidate": selected["selected_candidate"],
            "selected_image": selected.get("image_path") or selected.get("selected_image"),
            "review_file": rel(paths.review),
            "finalized_at": _now(),
            "updated_at": _now(),
        }
    )
    hits = prohibited_image_generation_hits(final)
    if hits:
        write_blocked(paths, model, "manifest에 금지 provenance 단어 포함: " + "; ".join(hits[:3]), stage="finalize")
        return 2
    write_json(paths.manifest, final)
    chosen, _ = selected_image_path(paths.slug)
    print(f"[PASS] stock-image complete: {rel(chosen) if chosen else rel(paths.selected)}")
    print(f"  manifest: {rel(paths.manifest)}")
    return 0


# --------------------------------------------------------------------------- CLI
def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("slug")
    ap.add_argument("--model", default=os.environ.get(MODEL_ENV) or DEFAULT_MODEL)
    ap.add_argument("--size", default=DEFAULT_SIZE, help="WIDTHxHEIGHT (예: 1536x1024, 1024x1024)")
    ap.add_argument("--seed", type=int, default=None, help="후보 seed 기준값(재시도 시 변경). 기본은 slug 해시")
    ap.add_argument("--motif", default=None, help="리포트 주제를 압축한 영어 시각 묘사 1~2문장(권장)")
    ap.add_argument("--base-url", default=DEFAULT_BASE_URL, help=argparse.SUPPRESS)
    ap.add_argument("--timeout-seconds", type=int, default=180)
    ap.add_argument("--dry-run", action="store_true", help="전송 프롬프트/요청 형태만 출력(키 마스킹, 파일 쓰기 없음)")
    ap.add_argument("--finalize", action="store_true", help="채점·선택 파일 검증 후 manifest를 complete로 전환")
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    paths = paths_for(args.slug)
    if args.finalize:
        return cmd_finalize(args, paths)
    require_inputs(paths)
    return cmd_generate(args, paths)


if __name__ == "__main__":
    raise SystemExit(main())
