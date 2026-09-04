#!/usr/bin/env python3
"""헤드리스 Chrome 으로 PDF 를 뽑고 세 가지를 확인한다.

읽는 문서는 화면과 인쇄가 다르게 깨진다. 특히 이 셋이 문제가 된다.

  1. 폰트 임베드 — Pretendard·Geist Mono 외의 이름이 뜨면 어딘가에 그 폰트에
     없는 글자가 있다는 뜻이다. 고객 화면에서 글자 모양이 달라진다.
  2. 인쇄 공백 — 행이 많고 두꺼운 표는 `table{page-break-inside:avoid}` 때문에
     통째로 다음 페이지로 밀리면서 앞 페이지를 절반 이상 비운다. 화면에서는
     절대 안 보이고 PDF 로 뽑아 봐야 안다. 그 표의 래퍼에 `.tw.split` 을 붙여
     행 사이에서 갈리게 하면 해소된다.
  3. 페이지 수 — 고객 메일에 "A4 N페이지" 를 적을 때 필요하다.

사용법:
    python3 to_pdf.py <file.html> [-o out.pdf]

pdfinfo·pdffonts·pdftotext(poppler)가 있으면 함께 점검한다. 없으면 렌더까지만
하고 그 사실을 알린다 — 렌더 자체는 Chrome 만 있으면 된다.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys

CHROME_CANDIDATES = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "google-chrome",
    "chromium",
    "chromium-browser",
]
# 이 두 계열만 임베드돼야 정상이다. 문서가 다른 폰트를 쓰기로 했다면 여기를 바꾼다.
EXPECTED_FONTS = ("Pretendard", "GeistMono")
# 파트 구분자 페이지와 절 끝 페이지는 원래 글자가 적다. 그 아래로 내려가면
# 표가 통째로 밀린 흔적일 가능성이 크다.
THIN_PAGE_CHARS = 420


def find_chrome() -> str | None:
    for candidate in CHROME_CANDIDATES:
        if candidate.startswith("/"):
            if os.path.exists(candidate):
                return candidate
        elif shutil.which(candidate):
            return candidate
    return None


def run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True)


def page_families(pdf: str, page: int) -> set:
    lines = run(["pdffonts", "-f", str(page), "-l", str(page), pdf]).stdout.splitlines()[2:]
    return {l.split()[0].split("+")[-1] for l in lines if l.strip()}


def page_chars(pdf: str, page: int) -> set:
    txt = run(["pdftotext", "-f", str(page), "-l", str(page), pdf, "-"]).stdout
    return {c for c in txt
            if ord(c) >= 0x80 and not ("가" <= c <= "힣") and not c.isspace()}


def offending_glyphs(pdf: str, pages: int, bad_families: set) -> tuple[set, int, int]:
    """예상 밖 폰트를 쓴 **페이지**를 찾고, 그 페이지에만 있는 글자를 골라낸다.

    `pdffonts` 는 어느 글자가 대체됐는지 말해 주지 않는다. 그래서 페이지 단위로 좁힌 뒤
    **깨끗한 페이지의 글자 집합을 빼서** 후보를 만든다. 완전하지는 않지만(같은 페이지에
    처음 나온 글자가 둘이면 둘 다 후보다) **이름을 대는 것**이 목적이다 —
    `check_html.py` 의 목록에 없는 글자는 그 검사가 통과시키고, 그러면 아무도 찾지 못한다.
    네 판(∪·└·ⓐ·▾)에서 그 일이 반복됐다.
    """
    bad_pages, good_pages = [], []
    for p in range(1, pages + 1):
        fams = page_families(pdf, p)
        (bad_pages if fams & bad_families else good_pages).append(p)
    bad_chars, good_chars = set(), set()
    for p in bad_pages:
        bad_chars |= page_chars(pdf, p)
    for p in good_pages:
        good_chars |= page_chars(pdf, p)
    return bad_chars - good_chars, len(bad_pages), len(good_pages)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("html")
    ap.add_argument("-o", "--out")
    args = ap.parse_args()

    html = os.path.abspath(args.html)
    if not os.path.exists(html):
        print(f"✗ 없는 파일: {html}")
        return 1
    out = os.path.abspath(args.out or os.path.splitext(html)[0] + ".pdf")

    chrome = find_chrome()
    if not chrome:
        print("✗ Chrome/Chromium 을 찾을 수 없다. CHROME_CANDIDATES 에 경로를 추가한다")
        return 1

    # --virtual-time-budget 은 웹폰트가 CDN 에서 내려올 시간을 준다. 짧으면
    # 폰트가 적용되기 전에 인쇄돼 레이아웃이 다르게 나온다.
    render = run([
        chrome, "--headless", "--disable-gpu", "--no-pdf-header-footer",
        "--virtual-time-budget=45000", f"--print-to-pdf={out}", f"file://{html}",
    ])
    if not os.path.exists(out):
        print(f"✗ 렌더 실패\n{render.stderr[-2000:]}")
        return 1
    print(f"✓ {out} ({os.path.getsize(out) / 1_000_000:.1f}MB)")

    failed = False

    page_count = 0
    if shutil.which("pdfinfo"):
        info = run(["pdfinfo", out]).stdout
        pages = next((l.split()[-1] for l in info.splitlines()
                      if l.startswith("Pages:")), "?")
        page_count = int(pages) if pages.isdigit() else 0
        size = next((l.split(":", 1)[1].strip() for l in info.splitlines()
                     if l.startswith("Page size:")), "?")
        print(f"  페이지 {pages} · {size}")
    else:
        print("  (pdfinfo 없음 — 페이지 수 미확인)")

    if shutil.which("pdffonts"):
        lines = run(["pdffonts", out]).stdout.splitlines()[2:]
        families = sorted({l.split()[0].split("+")[-1] for l in lines if l.strip()})
        unexpected = [f for f in families
                      if not any(f.startswith(e) for e in EXPECTED_FONTS)]
        if unexpected:
            failed = True
            print(f"  ✗ 예상 밖 폰트: {', '.join(unexpected)}")
            # **이 자리에서 글자를 이름으로 댄다.** 옛 문구는 *"check_html.py 로 찾는다"*
            # 였는데, 그 검사는 **목록에 있는 글자만** 보므로 새 글자는 통과시킨다 —
            # 네 판(`∪` it.10 · `└` it.15 · `ⓐ` it.16 · `▾` it.19)에서 그 일이 났다.
            named = set()
            if page_count and shutil.which("pdftotext"):
                named, nb, ng = offending_glyphs(out, page_count, set(unexpected))
                print(f"     · 그 폰트를 쓴 페이지 {nb} / 깨끗한 페이지 {ng}")
            if named:
                codes = " ".join(f"{c}(U+{ord(c):04X})" for c in sorted(named))
                print(f"     ✗ **이탈 후보 글자: {codes}**")
                print("     → 이 글자를 본문에서 바꾸고, `check_html.py` 의"
                      " `MISSING_GLYPHS` 에 **자리째 올린다**(다음 판이 같은 글자에"
                      " 다시 뚫리지 않게 한다)")
                # 옆에 적어 둔다 — `check_html.py --glyph-report` 가 이것을 받아쓴다.
                side = os.path.splitext(out)[0] + ".glyph-misses.json"
                with open(side, "w", encoding="utf-8") as fh:
                    json.dump({"fonts": unexpected, "glyphs": sorted(named)},
                              fh, ensure_ascii=False, indent=1)
                    # `json.dump` 는 마지막 개행을 붙이지 않는다 — 그러면 `wc -l` 과
                    # `splitlines()` 가 한 줄 갈리고 **두 수가 다 맞다.** 실측에서
                    # 그것이 파생 수치 어긋남으로 잡혔다(it.24, 표본 둘). 규약으로
                    # 두면 쓰는 사람이 바뀔 때 새므로 **JSON 을 쓰는 코드 자리마다**
                    # 이 한 줄을 붙인다.
                    fh.write("\n")
                print(f"     · 받아쓸 파일: {side}"
                      " → `python3 check_html.py <html> --glyph-report <이 파일>`")
            else:
                print("     ⚠ **글자를 특정하지 못했다** — 페이지 단위 차집합이 비었다"
                      "(모든 페이지가 그 폰트를 쓰거나 poppler 가 없다)."
                      " 후보를 손으로 좁힌다: 비-ASCII·비-한글 글자를 하나씩 빼며 재렌더한다")
        else:
            print(f"  ✓ 폰트 {len(families)}종, 전부 예상 계열")
    else:
        print("  (pdffonts 없음 — 폰트 임베드 미확인)")

    if shutil.which("pdftotext"):
        text = run(["pdftotext", out, "-"]).stdout
        pages_text = [p.strip() for p in text.split("\f")][:-1]
        thin = [(i + 1, len(p), (p.splitlines() or [""])[0][:32])
                for i, p in enumerate(pages_text) if len(p) < THIN_PAGE_CHARS]
        if thin:
            print(f"  · 글자 적은 페이지 {len(thin)}곳 — 파트 구분자·절 끝이면 정상이다")
            for page, count, first in thin:
                print(f"      p{page}: {count}자 · \"{first}\"")
        else:
            print("  ✓ 글자 적은 페이지 없음")
        if not any("가" <= c <= "힣" for c in text):
            failed = True
            print("  ✗ 한글이 추출되지 않는다 — 고객이 검색할 수 없다")
    else:
        print("  (pdftotext 없음 — 인쇄 공백 미확인)")

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
