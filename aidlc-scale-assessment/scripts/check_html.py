#!/usr/bin/env python3
"""자기완결 HTML 문서의 구조 점검. 표준 라이브러리만 쓴다.

사람이 눈으로 못 잡는 네 가지를 잡는다.

  1. 태그 균형 — 긴 표를 손으로 넣다 보면 </td> 하나가 빠지고, 브라우저는
     조용히 복구해 버려서 화면으로는 안 보인다. 인쇄에서만 레이아웃이 깨진다.
  2. 중복 id — 목차 링크가 첫 번째 것으로만 가고 나머지는 죽는다.
  3. 깨진 앵커 — 절을 지웠는데 목차 줄을 안 지우면 클릭이 아무 일도 안 한다.
  4. 폰트에 없는 글자 — Pretendard·Geist Mono 둘 다에 없는 글자는 PDF에서
     시스템 폰트를 끌어온다. 화면에서는 정상으로 보이므로 여기서 잡아야 한다.

사용법:
    python3 check_html.py <file.html> [<file2.html> ...]

종료 코드 0 = 통과, 1 = 문제 있음. CI 없이도 그냥 돌리면 된다.
"""
import collections
import json
import re
import sys
from pathlib import Path

# Pretendard·Geist Mono 어디에도 없어 시스템 폰트로 대체되는 글자.
# 실제로 PDF를 뽑아 pdffonts 로 확인해 모은 목록이다. 새로 발견하면 추가한다.
MISSING_GLYPHS = {
    "⇄": "⇄ (U+21C4) → ⇔ 로 바꾼다",
    "⇕": "⇕ (U+21D5) → ↕ 로 바꾼다",
    "▸": "▸ (U+25B8) → · 나 → 로 바꾼다",
    # 실측: 집합 연산 기호를 서술에 쓴 산출물의 PDF 가 Menlo 로 대체됐다. 이 검사는
    # 통과했고 to_pdf.py 의 폰트 이탈 경고만 잡았다 — 두 검사의 축을 맞춘다.
    "∪": "∪ (U+222A) → 「합집합」·「합친 고유 개수」로 풀어 쓴다",
    "∩": "∩ (U+2229) → 「교집합」·「양쪽에 다 있는 것」으로 풀어 쓴다",
    "⊆": "⊆ (U+2286) → 「포함된다」로 풀어 쓴다",
    "∖": "∖ (U+2216) → 「차집합」·「빼면 남는 것」으로 풀어 쓴다",
    # 실측(it.15): 두 런이 독립적으로 찾았다. `html-conventions.md` 가 이 글자를
    # **「있다(검증됨)」 목록에 잘못 올려 두었고** 실제로는 Pretendard 에 없어 PDF 가
    # `AppleSDGothicNeo` 를 끌어왔다. 한 런은 후보 14자를 단독 렌더로 하나씩 확인해
    # 이 글자만 걸러 냈다. `├`·`│` 는 실측에서 이탈하지 않았으므로 넣지 않는다.
    #
    # **그 「이탈하지 않았다」에는 조건이 빠져 있었다 — 자리가 갈린다.** 페이지별 폰트로
    # 다시 재니 `│`·`├`·`└` 셋 다 **`--sans` 에서 이탈하고**(`.SFNS-Regular` ·
    # `AppleSDGothicNeo-Regular`) **`--mono` 에서는 `GeistMono` 가 그린다** — Pretendard 에
    # 박스 드로잉이 없고 Geist Mono 에 있다. 그래서 ①`└` 를 여기 둔 것은 **sans 자리 기준**
    # 이고 ②`├`·`│` 가 이탈하지 않은 것은 그 산출물에서 **mono 자리였기 때문**이다
    # (`runs/iteration-2/qms` 는 `│` 를 쓰는데 폰트 전량이 예상 계열이다).
    # **이 검사는 글자 단위라 자리를 가리지 못한다** — mono 도해의 `└` 도 실패로 잡는다.
    # 자리를 보게 고치는 것은 검사 설계 변경이라 하지 않았고, 사실만 적어 둔다.
    "└": "└ (U+2514) → 트리는 `·` 나 들여쓰기로 그린다."
         " `├`·`│` 는 **mono 자리면** 안전하다(sans 에서는 셋 다 이탈한다)",
    # 실측(it.16): 원 안 라틴 글자(U+24D0~)가 인용에 들어와 PDF 가 대체 폰트를 끌어왔다.
    # **원 안 숫자(①~⑳, U+2460~2473)와 다른 대역이다** — 그쪽은 이탈하지 않았다.
    "ⓐ": "ⓐ (U+24D0) → 원 안 라틴은 폰트에 없다. `①`~`⑳` 이나 `(a)` 로 바꾼다",
    # 실측(it.19): 2차 반영으로 새로 들어온 `▾` 6자가 PDF 를 대체 폰트로 밀었고
    # **이 목록에 없어 그 축이 통과했다.** 런이 `to_pdf.py` 출력으로 스스로 찾았다.
    "▾": "▾ (U+25BE) → `▸` 와 같은 계열인데 이쪽은 폰트에 없다. `·`·`↓` 로 바꾼다",
}

# **목록을 뒤집는다 — 글자를 하나씩 더하는 방식은 네 판 연속 뚫렸다.**
# `∪`(it.10) · `└`(it.15) · `ⓐ`(it.16) · `▾`(it.19) 가 전부 「목록에 없어서」 통과했고,
# 넷 다 `to_pdf.py` 쪽에서 드러났다. 그래서 **폰트 이탈 0 으로 확인된 PDF 에 실제로 들어
# 있던 글자만 「확인됨」**으로 두고, 그 밖의 비-ASCII·비-한글 글자는 **경고**로 낸다
# (통과를 바꾸지 않는다 — 원문 인용에 들어온 기호를 실패로 세면 진짜가 묻힌다).
# 아래 목록은 it.15~it.19 산출물 10개의 전수 재고(30종)다.
VERIFIED_GLYPHS = set("·═─§—→「」↔…×★⇔↺−↑↓←↕↳")
# 실사용 판에서 매 판 경고가 난 넷. **골격에 심어 `--sans`·`--mono` 양쪽으로 단독 렌더해
# 이탈 0 을 확인했다** — 폰트 6종 전부 예상 계열이고 `pdftotext` 가 두 줄을 그대로 뽑았다
# (글자가 실제로 PDF 에 들어갔다는 뜻이다). 같은 렌더의 대조군 `⊕`·`▾` 는 `.SFNS-Regular`
# 이탈로 지목됐으므로 **검사가 꺼져서 나온 0 이 아니다.** `÷` 는 산식 표기(실측:
# `23÷0.116 = 198.3` · `44 ÷ 2`)이고 `▲` 는 원문 인용 안이라, 서술에 쓴 집합 연산 기호
# (위 `∪` 계열)와 달리 풀어 쓸 대상이 아니다. `≈`·`▼` 는 저장소 산출물에 0회이고
# 실사용 산출물에서 왔다.
VERIFIED_GLYPHS |= set("÷≈▲▼")
# **`±`·`△` 는 같은 렌더에서 깨끗했지만 올리지 않는다** — `iteration-10/woongjin` 의
# 「확인 안 된 글자 2종(`±`·`△`)」이 이 축의 **유일한 문서화된 양성 회귀 기준**이라,
# 올리면 0종이 되어 이 검사가 살아 있는지 확인할 자리가 없어진다.
# 같은 재고(경고 후보 40종 전수 렌더)에서 **양쪽 체인 모두 이탈**로 확인된 것은
# `⇢ ⏭ ⏮ ⏸ ⓘ ▦ ☐ ⚙ ⚪ ✕ ⬇` 다 — MISSING 후보이지만 실패를 늘리는 변경이라 여기서는
# 사실만 남긴다. `U+200B` 는 렌더 폭이 없어 이 방식으로 판정되지 않는다(다른 축이다).
# 원 안 숫자는 ①~⑩ 이 실측으로 확인됐고 **같은 대역의 ⑪~⑳ 도 확인됨으로 둔다** — 한 블록
# (U+2460~2473)이고 폰트 서브셋이 대역 단위다. [추론] 이라고 적어 둔다. `ⓐ` 계열(U+24D0~)은
# 실측으로 이탈했으므로 위 실패 목록에 있다.
VERIFIED_GLYPHS |= {chr(c) for c in range(0x2460, 0x2474)}

# 마크다운 강조가 문자 그대로 렌더되는 자리. 실측(it.15)에서 한 산출물의 본문 네 곳에
# `**` 가 그대로 찍혔고(PDF 로 확인) 이 검사는 통과했다 — 조립하는 쪽은 자기가 쓴
# 마크다운이라 못 알아본다. HTML 에서 강조는 `<b>`·`<strong>` 이다.
MD_EMPHASIS = re.compile(r"\*\*[^*\n]{1,60}\*\*")
VOID = {"meta", "link", "br", "hr", "img", "input", "col",
        "source", "area", "base", "wbr", "embed", "track", "param"}

# 머리글 행을 빼고 열 줄이 넘으면 한 페이지를 넘길 만큼 두껍다. 실측에서 빈 페이지를 만든
# 표는 14행이었고, 정상 통과해야 하는 골격 스텁 표는 전부 이보다 짧다.
LONG_TABLE_ROWS = 12

COMMENT = re.compile(r"<!--.*?-->", re.S)

# 골격 스텁 주석에만 나오는 문구. 본문(주석 밖)에서 발견되면 주석이 깨진 것이다.
# 실측에서 새어 나온 문장을 그대로 쓴다 — 새 스텁 주석을 넣으면 여기에도 한 조각 넣는다.
SKELETON_PHRASES = (
    "적지 않는다 --",
    "열 구성 —",
    "**미결 전량에 하나씩 배정한다.**",
    "공수(인일·인월)나",
    "표본으로 고르지 않는다.",
)


def check(path: str, extra_glyphs: set = frozenset()) -> list[str]:
    problems: list[str] = []
    try:
        text = open(path, encoding="utf-8").read()
    except OSError as exc:
        return [f"열 수 없다: {exc}"]

    # ── 1. 태그 균형 ───────────────────────────────────────────────────────
    stack: list[tuple[str, int]] = []
    for m in re.finditer(r"<(/?)([a-zA-Z][\w-]*)([^>]*?)(/?)>", text):
        closing, name, selfclose = m.group(1), m.group(2), m.group(4)
        name = name.lower()
        if name in VOID or selfclose == "/":
            continue
        line = text.count("\n", 0, m.start()) + 1
        if not closing:
            stack.append((name, line))
        elif not stack:
            problems.append(f"{line}행: 짝 없는 </{name}>")
        elif stack[-1][0] != name:
            open_name, open_line = stack[-1]
            problems.append(
                f"{line}행: </{name}> 가 닫으려는 것이 <{open_name}> ({open_line}행)"
            )
        else:
            stack.pop()
    for name, line in stack[:5]:
        problems.append(f"{line}행: <{name}> 가 닫히지 않았다")

    # ── 2. 중복 id ─────────────────────────────────────────────────────────
    ids = re.findall(r'\sid="([^"]+)"', text)
    for key, count in collections.Counter(ids).items():
        if count > 1:
            problems.append(f'id="{key}" 가 {count}번 나온다')

    # ── 3. 깨진 앵커 ───────────────────────────────────────────────────────
    for target in sorted(set(re.findall(r'href="#([^"]+)"', text)) - set(ids)):
        problems.append(f'href="#{target}" 의 대상이 없다')

    # ── 4. 폰트에 없는 글자 ────────────────────────────────────────────────
    for char, advice in MISSING_GLYPHS.items():
        if char in text:
            problems.append(f"폰트에 없는 글자 {advice}")
    # `to_pdf.py` 가 실측으로 지목한 글자를 **받아쓴다**(it.20 ④). 그쪽이
    # `<pdf>.glyph-misses.json` 을 남기고 이 검사가 그것을 실패로 승격한다 —
    # 「목록에 없어서 통과」를 네 판 반복하지 않기 위한 자리다.
    for char in extra_glyphs:
        if char in text and char not in MISSING_GLYPHS:
            problems.append(f"폰트에 없는 글자 {char} (U+{ord(char):04X})"
                            " — `to_pdf.py` 가 이 문서의 PDF 에서 실측으로 지목했다")
    hanja = {c for c in text if "一" <= c <= "鿿"}
    if hanja:
        problems.append(f"한자 {''.join(sorted(hanja))} — 폰트에 없다. 한글로 바꾼다")

    # 개별 목록은 매번 새 글자에 뚫린다. 실측(it.12)에서 `✅`(U+2705)가 인용에 들어와 PDF 가
    # AppleColorEmoji 를 끌어왔는데 이 검사는 통과했고 `to_pdf.py` 만 잡았다 → 범위로 넓힌다.
    #
    # 단 **넓게 잡으면 원문 인용을 거른다.** 처음 U+2600~U+27BF 를 통째로 걸었더니 어떤
    # 산출물의 인용 안 `★`(U+2605)가 걸렸는데, 그 집합 PDF 는 폰트 이탈이 0 이었다 —
    # Pretendard 가 커버하는 기호다. 인용은 원문 그대로여야 하므로 **컬러 이모지로 렌더되는
    # 대역과 알려진 개별 글자만** 잡고, 최종 판정은 `to_pdf.py` 의 폰트 이탈 검사에 맡긴다.
    KNOWN_EMOJI = {0x2705, 0x274C, 0x2714, 0x2716, 0x2757, 0x2B50, 0x26A0, 0x2B55,
                   0x2795, 0x2796, 0x27A1, 0x2764}
    emoji = {c for c in text
             if 0x1F000 <= ord(c) <= 0x1FAFF or ord(c) in (0xFE0F, 0x200D)
             or ord(c) in KNOWN_EMOJI}
    if emoji:
        codes = " ".join(f"{c}(U+{ord(c):04X})" for c in sorted(emoji))
        problems.append(f"이모지·딩뱃 {codes} — 폰트에 없어 PDF 가 다른 폰트를 끌어온다."
                        " 낱말로 바꾸거나 생략 표시로 줄인다")

    # 확인된 목록 밖의 글자 — **경고이고 통과를 바꾸지 않는다.** 0건이 안전을 뜻하지 않게
    # 하려면 「무엇을 확인했는가」를 말해야 한다(위 `VERIFIED_GLYPHS` 주석).
    unknown = {c for c in text
               if ord(c) >= 0x80 and not ("가" <= c <= "힣")
               and not ("ㄱ" <= c <= "ㆎ") and not ("一" <= c <= "鿿")
               and c not in VERIFIED_GLYPHS and c not in MISSING_GLYPHS
               and c not in emoji and not c.isspace()}
    if unknown:
        codes = " ".join(f"{c}(U+{ord(c):04X})" for c in sorted(unknown))
        problems.append(f"⚠ 폰트 확인이 안 된 글자 {len(unknown)}종: {codes}"
                        " — **목록에 있는 글자만 실패로 세므로 이것은 경고다.**"
                        " `to_pdf.py` 로 PDF 를 뽑아 폰트 이탈이 나는지 보고,"
                        " 이탈하지 않으면 `VERIFIED_GLYPHS` 에 올린다")

    # ── 4-b. 마크다운 강조가 본문에 그대로 찍힌 자리 ───────────────────────
    # `<style>`·`<script>`·주석을 지운 뒤 **태그 밖 텍스트**만 본다 — CSS 주석과 골격
    # 스텁 주석에는 `**` 가 정상으로 들어 있고 그것은 렌더되지 않는다.
    rendered = re.sub(r"<(style|script)[^>]*>.*?</\1>",
                      lambda m: "\n" * m.group(0).count("\n"), text, flags=re.S)
    rendered = COMMENT.sub(lambda m: "\n" * m.group(0).count("\n"), rendered)
    # **인용 안과 밖을 가른다.** 실측(it.15)에서 한 산출물의 `**` 23건이 **전부 원문 인용
    # 안**이었다 — 원문이 마크다운 파일이라 `**버전:**` 이 그 파일의 표기다. 마크다운 기호는
    # 서식이지 내용이 아니므로 `<b>` 로 바꾸는 것이 맞지만, 인용을 손대는 판단이 필요하므로
    # 경고로 둔다. **우리가 쓴 문장(인용 밖)의 `**` 는 명백한 오류라 어긋남으로 센다.**
    # 지울 때 **줄바꿈은 남긴다.** 공백으로 통째로 치환하면 이후 행 번호가 밀린다
    # (실측에서 그 버그로 보고 행이 7행씩 어긋났다).
    blank = lambda m: re.sub(r"[^\n]", " ", m.group(0))
    no_q_md = re.sub(r'<span class="q"[^>]*>.*?</span>', blank, rendered, flags=re.S)
    for i, (line, line_nq) in enumerate(zip(rendered.splitlines(),
                                            no_q_md.splitlines()), 1):
        bare, bare_nq = (re.sub(r"<[^>]+>", " ", x) for x in (line, line_nq))
        outside_q = MD_EMPHASIS.findall(bare_nq)
        for hit in outside_q:
            problems.append(f"{i}행 — 마크다운 강조가 그대로 찍혔다: {hit[:44]}"
                            " → `<b>` 로 바꾼다")
        n_in = len(MD_EMPHASIS.findall(bare)) - len(outside_q)
        if n_in > 0:
            problems.append(f"⚠ {i}행 — 원문 인용 안에 마크다운 `**` 가 {n_in}건 있다."
                            " PDF 에 그대로 찍힌다 — 뜻은 그대로 두고 `<b>` 로 바꾼다")

    # ── 4-c. 옛 낱말이 남은 자리 ───────────────────────────────────────────
    # 어휘를 Contract·Layer·Workstream 으로 고정한 뒤(it.14 이후) 실측에서 한 산출물이
    # 같은 대상을 두 이름으로 불렀다 — 「Layer 3단 + 사전 준비 층」처럼 한 문장에 둘이
    # 함께 있는 자리까지 있었다. **스크립트가 양쪽 낱말을 다 받게 만들어도 본문은 섞인다.**
    #
    # **원문 인용(`.q`) 안은 세지 않는다.** 고객 문서가 「데이터 계층 구조」라고 적은 것을
    # 우리가 바꿔 쓸 수는 없다. 인용을 지우지 않으면 이 검사는 오탐 기계가 된다.
    no_q = re.sub(r'<span class="q"[^>]*>.*?</span>', blank, rendered, flags=re.S)
    for i, line in enumerate(no_q.splitlines(), 1):
        bare = re.sub(r"<[^>]+>", " ", line)
        # 파일·스크립트 옛 이름은 뜻이 하나뿐이라 어긋남으로 센다
        for old_name, new_name in (("surfaces.json", "contracts.json"),
                                   ("surface_matrix", "contract_matrix")):
            if old_name in bare:
                problems.append(f"{i}행 — 옛 파일 이름 `{old_name}` → `{new_name}`")
        # 옛 라벨은 문자열이 길어 중의성이 없다
        for lab, new_lab in (("종이로 닫힌다", "받아올 것 없음"), ("종이로 된다", "받아올 것 없음"),
                             ("실물 대기", "실물 필요"), ("회신 대기", "회신 필요")):
            if lab in bare:
                problems.append(f"{i}행 — 옛 라벨 「{lab}」 → 「{new_lab}」")
        # 낱말 축은 **경고**다. 「계층」·「위층」처럼 다른 뜻인 복합어가 있어 통과를 막지 않는다.
        for w, new_w in (("표면", "Contract"), ("층", "Layer"), ("갈래", "Workstream")):
            # it.19: 조사가 붙은 자리를 받는다 — `(?![가-힣])` 하나로는 *"두 번째 갈래가"*
            # (it.18 실측)를 놓쳤고 **경고도 안 떴다.** 조사 한 글자까지만 허용한다 —
            # 두 글자 조사(에서·으로)까지 열면 「층계」 계열 복합어 오탐이 커진다.
            for m in re.finditer(
                    rf"(?<![가-힣0-9]){w}(?:[가이은는을를도의와과만로에](?![가-힣]))?(?![가-힣])",
                    bare):
                pre = bare[max(0, m.start() - 1):m.start()]
                if w == "층" and pre in ("계", "위", "래", "상", "하", "최", "고", "저"):
                    continue
                problems.append(f"⚠ {i}행 — 옛 낱말 「{w}」 가 남았다(→ {new_w})"
                                f": …{bare[max(0, m.start()-24):m.start()+20].strip()}…")

    # ── 5. 골격 주석이 본문에 새어 나온 자리 ───────────────────────────────
    # 실측: 골격 스텁 주석을 편집하다 여는 `<!--` 가 지워져 지시문이 **고객 문서 본문에
    # 그대로 렌더링**됐다(마크다운 `**` 까지). 화면에서도 보이지만 조립하는 쪽은 자기가 쓴
    # 문장 사이에 섞여 있어 못 알아본다. `-->` 는 태그 균형 검사에 걸리지 않는다.
    # 여러 줄 주석을 통째로 지운 뒤 남은 기호만 본다 — 줄 단위로 보면 정상 주석의
    # 중간 줄이 전부 걸린다.
    outside = COMMENT.sub(lambda m: "\n" * m.group(0).count("\n"), text)
    for m in re.finditer(r"<!--|-->", outside):
        line = outside[:m.start()].count("\n") + 1
        frag = outside.splitlines()[line - 1].strip()[:60] if line - 1 < len(
            outside.splitlines()) else ""
        problems.append(f"{line}행 — 주석 기호가 짝 없이 남았다: {frag}")
    if any("짝 없이" in p for p in problems):
        problems.append("골격 주석의 여는 `<!--` 가 지워지면 지시문이 본문에 찍힌다."
                        " 그 블록을 지우거나 주석을 온전히 복구한다")

    # 여는 기호까지 함께 지워진 경우 위 검사가 못 잡는다. 골격 문구를 직접 찾는다.
    for mark in SKELETON_PHRASES:
        if mark in outside:
            problems.append(f"골격 지시문이 본문에 있다: \"{mark}\" — 그 문단을 지운다")

    # ── 6. 긴 표에 .tw.split 이 없다 ────────────────────────────────────────
    # 기본값 table{page-break-inside:avoid} 때문에 행이 많은 표는 통째로 다음 페이지로
    # 밀리고 앞 페이지가 절반 이상 빈다. 실측에서 두 산출물의 PDF 가 같은 자리(p34)에
    # 100자 내외인 페이지를 만들었고, 둘 다 14행 표가 밀린 것이었다. 규칙과 안내는
    # html-conventions.md ③ 에 이미 있었는데 지시로는 안 걸렸다 → 기계 검사로 만든다.
    for m in re.finditer(r"<table\b.*?</table>", text, re.S):
        rows = len(re.findall(r"<tr\b", m.group(0)))
        if rows < LONG_TABLE_ROWS:
            continue
        head = text[:m.start()]
        # 이 표를 감싸는 가장 가까운 여는 div 의 class 를 본다
        wrappers = re.findall(r'<div[^>]*class="([^"]*)"[^>]*>', head)
        if wrappers and "split" in wrappers[-1]:
            continue
        line = head.count("\n") + 1
        # 통과 여부는 바꾸지 않는다 — 긴 표 전부가 페이지 경계에 걸리는 것은 아니다.
        # 실측에서 여덟 자리가 걸렸고 실제로 빈 페이지를 만든 것은 하나였다. 실패로 세면
        # 주석 누출 같은 진짜 결함이 목록에 묻힌다.
        problems.append(
            f"⚠ {line}행 — {rows}행 표에 `.tw.split` 이 없다."
            " 인쇄에서 통째로 밀리면 앞 페이지가 빈다(`<div class=\"tw split\">`)")

    # ── 7. 본문이 쓴 class·CSS 변수가 `<style>` 에 정의돼 있는가 ─────────────
    # **이 축은 it.22 까지 한 번도 검사된 적이 없다.** 세 채점자가 독립적으로 같은 것을
    # 지목했고 결함 여섯 축 어디에도 들어가지 않았다 — 한 산출물에서 CSS 에 없는 class
    # **54곳** · 미정의 `var()` **17곳**이 나와 막대(`.bt-track` 6곳)·인접 행렬 히트맵·
    # 표지 파트 카드 여섯이 **렌더되지 않았다.** `check_numbers.py` 는 그 막대를
    # *"값·분모·width 가 정본과 같다"* 로 통과시켰다(`width:` 문자열만 봤다).
    #
    # **「검사를 더 넣는 계열」과 갈린다.** `on_exit_v2` 가 닫은 것은 *"겨냥한 유형은 매번
    # 사라지는데 총합이 줄지 않는" 계열이고, 이 축은 **한 번도 검사된 적이 없으며 실패의
    # 결과가 「다른 형태로 옮김」이 아니라 「그 자리가 안 보임」**이다.
    #
    # 실패가 아니라 **어긋남**으로 센다 — 렌더가 안 되는 것은 통과시킬 수 없다.
    # 다만 **집합마다 갈렸다**(한 산출물은 0 이었다) → 골격 결함이 아니라 런의 이탈이다.
    style_src = "\n".join(m.group(1) for m in re.finditer(r"<style[^>]*>(.*?)</style>", text, re.S))
    if style_src:
        # 선언된 class. `.a.b` · `.a > .b` · `.a, .b` 전부에서 토큰을 뽑는다.
        declared = set(re.findall(r"\.([A-Za-z][\w-]*)", style_src))
        # 선언된 CSS 변수(`--x:` 형태만 — `var(--x)` 는 사용이다).
        declared_var = set(re.findall(r"(--[\w-]+)\s*:", style_src))
        # 주석 안의 class 이름은 설명이다(골격이 이름을 백틱·속성으로 적는다) — 빼지 않으면
        # 오탐 기계가 된다. **줄바꿈은 보존한다** — 공백으로 통째로 치환하면 이후 행 번호가
        # 전부 밀린다(it.18 에 실제로 그 버그가 나 보고 행이 7행씩 어긋났다).
        head_len = text.find("</style>") + 8 if "</style>" in text else 0
        body = text[head_len:]
        offset = text.count("\n", 0, head_len)
        body_wo = COMMENT.sub(lambda m: "\n" * m.group(0).count("\n"), body)
        used: dict[str, int] = {}
        for m in re.finditer(r'class="([^"]*)"', body_wo):
            line = offset + body_wo.count("\n", 0, m.start()) + 1
            for tok in m.group(1).split():
                if tok and tok not in declared:
                    used.setdefault(tok, line)
        for tok, line in sorted(used.items(), key=lambda kv: kv[1]):
            problems.append(
                f"{line}행 — class `{tok}` 가 `<style>` 에 없다."
                " 그 자리는 스타일 없이 렌더된다 — 골격의 이름을 쓴다")
        used_var: dict[str, int] = {}
        for m in re.finditer(r"var\((--[\w-]+)", body_wo):
            if m.group(1) not in declared_var:
                used_var.setdefault(m.group(1), offset + body_wo.count("\n", 0, m.start()) + 1)
        for tok, line in sorted(used_var.items(), key=lambda kv: kv[1]):
            problems.append(
                f"{line}행 — CSS 변수 `{tok}` 가 정의돼 있지 않다."
                " 그 속성은 무시된다 — `:root` 에 있는 이름을 쓴다")

    return problems


def main() -> int:
    argv = sys.argv[1:]
    extra = set()
    if "--glyph-report" in argv:
        i = argv.index("--glyph-report")
        report = argv[i + 1] if i + 1 < len(argv) else ""
        del argv[i:i + 2]
        try:
            extra = set(json.loads(Path(report).read_text(encoding="utf-8"))
                        .get("glyphs", []))
            print(f"· `to_pdf.py` 의 실측을 받아썼다 — 글자 {len(extra)}종"
                  f" ({' '.join(sorted(extra))})")
        except OSError as exc:
            print(f"✗ `--glyph-report` 를 읽지 못했다: {exc}")
            return 1
    paths = argv
    if not paths:
        print(__doc__)
        return 1
    failed = False
    for path in paths:
        found = check(path, extra)
        hard = [p for p in found if not p.startswith("⚠")]
        warn = [p for p in found if p.startswith("⚠")]
        if hard:
            failed = True
            print(f"✗ {path} — {len(hard)}건")
            for p in hard:
                print(f"    {p}")
        else:
            print(f"✓ {path} — 태그 균형 · id · 앵커 · 폰트 글자 모두 통과")
        if warn:
            print(f"  경고 {len(warn)}건 — 통과 여부는 바꾸지 않는다. 인쇄에서 확인한다")
            for p in warn:
                print(f"    {p}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
