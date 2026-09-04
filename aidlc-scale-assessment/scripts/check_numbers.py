#!/usr/bin/env python3
"""HTML 본문의 수치를 `contracts.json` 과 대조한다. 손으로 옮긴 값은 어긋난다.

`contract_matrix.py` 는 **맞는 값을 계산해 주지만** 그 값이 HTML 에 옮겨 적히는 과정에서
어긋난다. 평가 네 산출물 **전부**에서 이 유형이 나왔다.

    표지·파트1·파트3 은 표면 44 인데 파트4 의 "센 값" 카드만 43
    스크립트가 RE04 12 / RE05 11 을 냈는데 본문은 두 라벨을 맞바꿔 적었다
    스크립트가 000 = 4/34 를 냈는데 막대는 6/34 로 적혔다 — 도구 출력에서 이탈
    "나머지 5건(C7 · C10 · C22 · C27~C29 · C39)" — 괄호 안은 7개다
    갭 9건이 참여 문서 없이 ID 만 적혔다

원인은 하나다 — **표면을 늦게 추가하면 파생 수치 수십 곳을 손으로 다시 갱신해야 한다.**
지시로는 막히지 않는다(스킬 본문에 "수치는 한 곳에서 재계산한다" 가 이미 있다). 그래서
조립이 끝난 뒤 **기계가 대조한다.**

**그런데 이 스크립트는 한 번 거짓 안심을 줬다.** 만들 때 본 실패 다섯 건을 잡는 것을 확인하고
채택했는데, 다음 판 다섯 산출물 **전부에 "0건" 을 내는 동안 채점자들은 26곳을 찾았다.** 못 본
자리가 여섯이었다.

    "강도 중 인 표면 여덟"          한글 수사 — 라벨은 붙었으나 숫자가 아니다
    표 셀의 33 · 17 · 16            라벨이 없다(정본 34 · 18 · 18)
    "합이 88이다"                   서술 문장 안의 맨 숫자(정본 90)
    "9개(C18 · C40 · G6 · G7 …)"    `C` 밖의 ID 접두를 세지 않았다
    "표면 96"                       정본 101 — 차이 5 를 부분합으로 봤다
    카드 본문 · 도해 주석            표·막대만 보고 지나갔다

그래서 축을 넓혔고, **통과 신호의 뜻을 좁혔다** — 출력 끝에 무엇을 검사하지 **않았는지** 항상
찍는다. `0건` 은 *"이 축에서 못 찾았다"* 는 뜻이고 *"본문 수치가 맞다"* 는 뜻이 아니다.

사용법:
    python3 check_numbers.py assessment.html contracts.json
    python3 check_numbers.py assessment.html contracts.json --no-strength   # 강도 대조 끄기
    python3 check_numbers.py assessment.html contracts.json --no-bare       # 라벨 없는 숫자 끄기

나가는 값이 0 이면 **검사한 축에서** 어긋난 곳이 없다. 1 이면 있다.
"""
import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

TAG = re.compile(r"<[^>]+>")
BAR = re.compile(r'class="bar"')
BV = re.compile(r'class="bv"[^>]*>\s*([\d,]+)\s*/\s*([\d,]+)')
BL = re.compile(r'class="bl"[^>]*>(.*?)</div>', re.S)
WIDTH = re.compile(r"width:\s*([\d.]+)%")
CELL = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.S)

STATUS_LABEL = {"con": "충돌", "dup": "중복", "gap": "갭", "ok": "정리됨"}

CLOSES_LABEL = {"paper": "받아올 것 없음", "reply": "회신 필요", "artifact": "실물 필요"}

# 갭의 하위 분류. 실측(it.15)에서 한 산출물이 「고아 13 · 규격 미정 53」을 네 자리에서
# 말하는데 **정본에 그 축이 없어** 기계가 대조할 대상이 없었고, 그 축에서 논리 모순이 났다.
# 확정 사실 *"정본에 자리가 없는 축은 기계가 못 지킨다"* 와 같은 모양이다.
GAP_KIND_LABEL = {"orphan": ["고아"], "spec": ["규격 미정"]}

# 총계 성격 라벨은 부분합일 수 없다 → `--near` 를 적용하지 않고 전부 본다.
# *"표면 96"* 이 정본 101 일 때 차이가 5 라 near 밖으로 빠져나갔다.
TOTAL_LABELS = ("Contract", "표면", "계약 지점", "경계 지점", "인용", "하한")

# **정본 키 하나에 산출물이 쓰는 낱말을 전부 잇는다.** 골격이 `s31` 제목을
# *"계약 지점 N개의 상태"* 로 주므로 산출물은 그 낱말을 쓴다. `표면` 만 찾다가 한 집합의
# 어긋남 **7건을 전량** 놓쳤고 그 항목이 `fail` 로 내려갔다.
ALIAS = {
    # 정본 낱말은 `Contract` 다. 옛 낱말(표면·계약 지점)을 별칭으로 남기는 이유는 **과거
    # 산출물이 그 낱말로 적혀 있기** 때문이다 — 지우면 회귀 기준이 검사되지 않는다.
    "Contract": ("Contract 지점", "표면", "계약 지점", "경계 지점", "계약 표면",
                 "경계 표면", "기반 계약", "결정 기록"),
    "미결": ("미결 안건", "열려 있는 것", "미결 표면", "남은 것"),
    "인용": ("근거 인용", "원문 인용", "근거 원문"),
    # **「갭」의 하위 라벨(「고아」·「규격 미정」)은 별칭이 아니다** — 별칭으로 두면 골격이
    # 요구하는 표기 *"갭 45건 = 고아 1건 + 규격 미정 44건"* 을 그대로 오탐한다(it.22 시험 런
    # `_trial-table-order` 실측: 5자리, 본문이 옳고 검사가 틀렸다). 하위 라벨은 ⑤ `gap_kind`
    # 검사가 별도로 본다. 스윕 대조: `iteration-11/table-order` 어긋남 2→1(같은 오탐이 있었다)
    # · `iteration-6/plandetail` 회귀 기준 4 불변 · 나머지 산출물 전량 불변.
    "갭": (),
}

# 한글 수사. **수량사와 관형사형을 가른다** — 관형사형(`한`·`두`·`세`)은 흔한 글자라
# *"동시 상**한**(2)"* 처럼 엉뚱한 자리에 걸린다. 그래서 관형사형은 단위가 뒤에 올 때만 센다.
HANGUL_CARD = {
    "하나": 1, "둘": 2, "셋": 3, "넷": 4, "다섯": 5, "여섯": 6, "일곱": 7,
    "여덟": 8, "아홉": 9, "열": 10, "열하나": 11, "열둘": 12, "열셋": 13,
    "열넷": 14, "열다섯": 15, "열여섯": 16, "열일곱": 17, "열여덟": 18,
    "열아홉": 19, "스물": 20,
}
HANGUL_DET = {
    "한": 1, "두": 2, "세": 3, "네": 4, "열한": 11, "열두": 12, "열세": 13,
    "열네": 14, "스무": 20,
}
HANGUL_NUM = dict(HANGUL_CARD, **HANGUL_DET)
UNIT = r"(?:개|건|곳|장|벌|쌍|묶음)"
# 긴 것을 먼저 시도해야 *"열둘"* 이 *"열"* 로 잘리지 않는다.
CARD_ALT = "|".join(sorted(HANGUL_CARD, key=len, reverse=True))
DET_ALT = "|".join(sorted(HANGUL_DET, key=len, reverse=True))
# 수량사는 단위 없이 ID 목록이 바로 붙는 자리가 있다 — 실측이 *"표면 여덟(C10 · C11 …)"*
# 이었다. 공백만으로는 인정하지 않는다(*"세 번째"* 가 걸린다).
HANGUL_TAIL = rf"(?:{UNIT}|[(（]|이다|이고|이며|이라)"

# 부분합 서술의 표지. 총계 라벨 앞에 이것이 있으면 전체를 말하는 자리가 아니다 —
# *"경계 Contract 7"* · *"Layer 1 Contract 12"* 는 정당하다.
# **한국어와 영문을 함께 받는다.** 어휘를 Contract·Layer·Workstream 으로 올린 뒤에도 과거
# 산출물(층·갈래·표면)을 검사해야 하고, 한쪽만 받으면 그 축이 조용히 죽는다 — 골격이 쓰는
# 낱말과 스크립트 라벨이 어긋나 어긋남 7건을 전량 놓친 실패가 이 자리에서 났다.
PARTIAL_WORD = (r"(?:경계|층|Layer|단계|구간|갈래|Workstream|쌍|중|내|당|째"
                r"|그|남|미|추가|공유)")
PARTIAL_HINT = re.compile(PARTIAL_WORD + r"[가-힣]{0,3}\s*$")
# **이 창에 숫자를 허용하지 않는다 — 넓혔다가 과녁을 지우고 되돌린 자리다.** it.19 오탐 17행의
# 원인이 어휘 절(*"영문 토큰 뒤에 공백을 넣고 조사를 붙인다"*)과의 충돌이라 `Layer 2 의` 를
# 받게 넓혀 봤더니, `iteration-7/woongjin:806` 의 *"세는 것은 층 5 · 단계 3 · 표면 96"*
# (정본 101 — 이 스크립트가 이름째 보호하는 과녁)이 **「단계 3 · 」로 함께 지워졌다.**
# 한정어 낱말과 값이 표기상 구별되지 않는다(`Layer 2` 는 색인 · `단계 3` 은 개수). 그래서
# 창을 넓히는 대신 **정본으로 부분합을 재계산해 맞을 때만 뺀다**(아래 `AXIS_TOK`).
# it.17 확정 사실 *"오탐을 줄이는 손질이 과녁을 함께 지운다"* 의 표본이 하나 늘었다.
#
# 총계 라벨 앞의 **축 토큰**. `Layer 2 · 모듈 내부 규격 — Contract 66개` 처럼 한정어가 절
# 앞머리에 있고 사이에 낱말이 드는 자리를 잡는다. 번호를 요구해 *"충돌 39개"* 의 `3` 을 층으로
# 읽지 않고, `1층` 형태를 먼저 시도해 *"1층 33"* 을 「층 33」으로 잘못 읽지 않는다.
AXIS_TOK = re.compile(r"(?:(\d{1,2})\s*층|(?:Layer|층|Workstream|갈래)\s*(\d{1,2}))(?!\d)")
# 단계 낱말 → 정본 코드. `aidlc` 축의 교차 재계산에 쓴다.
STAGE_CODE = {"prep": "prep", "사전 준비": "prep", "ideation": "ideation",
              "inception": "inception", "construction": "construction"}
STAGE_TOK = re.compile("|".join(re.escape(w) for w in
                                sorted(STAGE_CODE, key=len, reverse=True)))
# 강도 낱말. **앞뒤에 한글이 붙으면 다른 낱말이다** — 「중복」·「그중」·「상한」·「이상」·
# 「하나」가 전부 걸린다. 실측 정본 분포는 상 912 · 중 622 · 최상 403 · 하 3 이다.
STRENGTH_TOK = re.compile(r"(?<![가-힣])(최상|상|중|하)(?![가-힣])")

# 단위가 붙은 숫자는 표면 수와 무관하다 — 라벨 없는 숫자를 훑을 때 걸러 낸다.
UNIT_AFTER = re.compile(r"^\s*(?:%|px|kb|mb|일|주|월|년|시간|분|초|명|원|행|자|배|페이지|p\b)")


def id_pattern(prefixes) -> re.Pattern:
    """표면 ID 정규식. 접두는 `contracts.json` 에서 실제로 쓰인 것을 모아 만든다.

    `C` 만 박아 두었더니 `G` 계열을 쓰는 산출물에서 *"9개(C18 · C40 · G6 …)"* 를 2개로
    셌다. 접두를 고정하지 않는다.
    """
    alt = "|".join(sorted((re.escape(p) for p in prefixes), key=len, reverse=True))
    return re.compile(rf"\b({alt})(\d{{1,3}})\b")


def strip_tags(line: str) -> str:
    return TAG.sub(" ", line).replace("&middot;", "·").replace("&nbsp;", " ")


def expand_ids(text: str, sid: re.Pattern, rng: re.Pattern) -> set:
    """괄호 안의 ID 를 센다. `C27~C29` 는 3개로 펼친다. 접두는 섞여 있어도 된다."""
    ids = set()
    for m in rng.finditer(text):
        pre, a, b = m.group(1), int(m.group(2)), int(m.group(3))
        if a <= b and b - a < 40:
            ids.update(f"{pre}{n}" for n in range(a, b + 1))
    ids.update(m.group(0) for m in sid.finditer(text))
    return ids


def hangul_scan(text_lines, table):
    """*"강도 최상 넷"* · *"작업 단위가 세 벌"* — 라벨에 한글 수사가 붙은 자리.

    채점자가 두 산출물에서 이 유형을 찾았고 스크립트는 *"강도 낱말이 붙은 수치: 없다"* 를
    냈다. 숫자만 보고 있었다.
    """
    out = []
    for label, want in table.items():
        pat = re.compile(
            rf"(?<![가-힣]){re.escape(label)}(?![가-힣])[^\d\n]{{0,12}}?"
            rf"(?:({CARD_ALT})\s*{HANGUL_TAIL}|({DET_ALT})\s*{UNIT})")
        for i, t in enumerate(text_lines, 1):
            for m in pat.finditer(t):
                word = m.group(1) or m.group(2)
                got = HANGUL_NUM[word]
                if got == want:
                    continue
                if PARTIAL_HINT.search(t[max(0, m.start() - 12):m.start()]):
                    continue
                out.append((label, want, got, word, i,
                            t.strip()[max(0, m.start() - 26):m.start() + 30].strip()))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("html")
    ap.add_argument("surfaces")
    ap.add_argument("--no-strength", action="store_true",
                    help="강도(최상·상) 대조를 끈다. 강도 낱말이 서술에 많이 쓰이면 끈다")
    ap.add_argument("--near", type=int, default=2,
                    help="정본과의 차이가 이 값 안일 때만 어긋남으로 본다(기본 2). "
                         "부분합은 대체로 정본과 멀고, 손으로 옮기다 나는 실패는 가깝다")
    ap.add_argument("--policy", nargs="*", default=[],
                    help="정책 문서 이름. `contract_matrix.py` 와 같은 값을 준다")
    ap.add_argument("--no-bare", action="store_true",
                    help="라벨 없는 숫자 훑기를 끈다. 후보가 많으면 끈다")
    ap.add_argument("--full", action="store_true",
                    help="목록을 접지 않고 전량 찍는다. 실측(it.17)에서 한 산출물이 60행짜리 "
                         "목록을 접힌 25행만 보고 「15건」으로 적어 8 Contract 가 판정되지 "
                         "않았다 — 접힌 목록이 남아 있으면 이것으로 다시 본다")
    ap.add_argument("--docs-root",
                    help="입력 문서 디렉터리. 주면 ⑤-d 출처 귀속 검증이 켜진다 — "
                         "근거가 지목한 문서에 그 식별자가 실재하는지 원문으로 본다")
    args = ap.parse_args()

    canon_doc = json.load(open(args.surfaces, encoding="utf-8"))
    # it.19: 정본이 객체 형태(`{"contracts": [...], "counts": [...]}`)면 둘을 가른다.
    # 옛 배열 형태도 그대로 받는다 — 과거 판 산출물이 그 형태이고, **한쪽만 받게 고치면
    # 회귀 기준이 조용히 통과한다**(CLAUDE.md 어휘 절의 같은 규칙).
    if isinstance(canon_doc, dict):
        surfaces = canon_doc.get("contracts", [])
        counts_reg = canon_doc.get("counts")
    else:
        surfaces, counts_reg = canon_doc, None
    lines = Path(args.html).read_text(encoding="utf-8").splitlines()
    text_lines = [strip_tags(x) for x in lines]

    # 표면 ID 의 접두를 `contracts.json` 에서 모은다 — `C` 로 고정하면 다른 계열을 놓친다.
    prefixes = set()
    for s in surfaces:
        m = re.match(r"([A-Za-z]{1,3})\d{1,3}$", str(s.get("id", "")).strip())
        if m:
            prefixes.add(m.group(1))
    if not prefixes:
        prefixes = {"C"}
    sid = id_pattern(prefixes)
    palt = "|".join(sorted((re.escape(p) for p in prefixes), key=len, reverse=True))
    rng = re.compile(rf"({palt})(\d{{1,3}})\s*[~\-–]\s*(?:{palt})?(\d{{1,3}})")
    # "5건(C7 · C10 · C27~C29)" — 앞의 개수와 괄호 안 ID 수가 맞는가
    paren = re.compile(r"(\d{1,3})\s*(?:건|개)\s*[(（]([^)）]{0,400})[)）]")

    policy = set(args.policy)
    tally = Counter(s.get("status", "?") for s in surfaces)
    strength = Counter(s.get("strength", "?") for s in surfaces)
    involve = Counter()
    for s in surfaces:
        involve.update(sorted(set(s.get("parties", [])) - policy))
    total = len(surfaces)
    undecided = sum(tally.get(k, 0) for k in ("con", "dup", "gap"))
    cites_total = sum(len([c for c in s.get("cites", []) if str(c).strip()])
                      for s in surfaces)
    floor = sum({"con": 2}.get(s.get("status", ""), 1) for s in surfaces)

    print("# 수치 대조 — `contracts.json` 이 정본이다\n")
    print(f"Contract **{total}** · 충돌 {tally.get('con', 0)} · 중복 {tally.get('dup', 0)}"
          f" · 갭 {tally.get('gap', 0)} · 정리됨 {tally.get('ok', 0)}"
          f" · 미결 {undecided} · 인용 {cites_total} / 하한 {floor}"
          f" · ID 접두 {'·'.join(sorted(prefixes))}\n")

    problems = 0
    CAP = 10 ** 6 if args.full else None

    # ── ① 표면 ID 집합 ────────────────────────────────────────────────────
    declared = []
    for s in surfaces:
        m = sid.match(str(s.get("id", "")).strip())
        declared.append(m.group(0) if m else None)
    dup_ids = [k for k, v in Counter(i for i in declared if i).items() if v > 1]
    in_html = set()
    for t in text_lines:
        in_html.update(m.group(0) for m in sid.finditer(t))
    known = set(i for i in declared if i)

    def id_key(x):
        m = sid.match(x)
        return (m.group(1), int(m.group(2))) if m else (x, 0)

    missing = sorted(known - in_html, key=id_key)
    unknown = sorted(in_html - known, key=id_key)

    print("## Contract ID\n")
    if dup_ids:
        print(f"- **`contracts.json` 에 중복 ID: {', '.join(sorted(dup_ids, key=id_key))}**")
        problems += 1
    if missing:
        print(f"- **HTML 에 없는 Contract: {', '.join(missing)}**"
              " — 분석에는 있고 본문에 안 실렸다")
        problems += 1
    if unknown:
        print(f"- **HTML 에만 있는 ID: {', '.join(unknown)}**"
              " — `contracts.json` 에 없다. 오타이거나 지운 표면의 잔재다")
        problems += 1
    if not (dup_ids or missing or unknown):
        print(f"ID {total}개가 양쪽에 그대로 있다.")

    # ── ② 라벨 붙은 수치 ──────────────────────────────────────────────────
    # "표면 44" · "충돌 15" 처럼 라벨과 붙은 숫자를 전부 뽑아 기대값과 맞춘다.
    expect = {
        "Contract": total,
        "충돌": tally.get("con", 0),
        "중복": tally.get("dup", 0),
        "갭": tally.get("gap", 0),
        "정리됨": tally.get("ok", 0),
        "미결": undecided,
        "인용": cites_total,
        "하한": floor,
    }
    # 별칭을 같은 값으로 펼친다. 긴 낱말이 먼저 매칭돼야 *"계약 지점 27"* 이 `지점` 이 아니라
    # 통째로 걸린다 — `scan` 이 `expect` 를 순회하므로 삽입 순서를 길이 역순으로 둔다.
    for key, names in ALIAS.items():
        if key in expect:
            for alt in sorted(names, key=len, reverse=True):
                expect[alt] = expect[key]
    soft = {}
    if not args.no_strength:
        soft["최상"] = strength.get("최상", 0)
        soft["상"] = strength.get("상", 0)
    print("\n## 라벨 붙은 수치\n")
    print(f"상태별 라벨은 정본에서 **±{args.near} 안**으로 어긋난 것만 본다 —"
          " *\"1층 표면 11개\"* 처럼 부분합은 정당하다. 그러나"
          f" **{' · '.join(TOTAL_LABELS)}** 는 총계라 부분합일 수 없으므로 **차이가 얼마든"
          " 전부 본다** — 정본 101 을 96 으로 적은 자리가 차이 5 로 빠져나간 적이 있다.\n")

    # 부분합으로 판정해 뺀 자리를 세어 찍는다. **손질할 때마다 ①과녁을 잡는가 ②오탐이 몇인가를
    # 함께 찍는다**(it.17 확정 사실) — 오탐만 보면 과녁이 사라진 것을 모른다.
    skipped_partial = []
    # Layer 별 정본 개수. **표기로 지우지 않고 이 표로 재계산해 맞을 때만 뺀다.**
    layer_total = Counter()
    for s in surfaces:
        lm = re.match(r"\s*(\d{1,2})", str(s.get("layer") or ""))
        if lm:
            layer_total[lm.group(1)] += 1

    def scan(table, near_only=True):
        out = []
        for label, want in table.items():
            exact = label in TOTAL_LABELS
            # *"표면 수(88)"* 처럼 라벨과 숫자 사이에 `수` 와 괄호가 끼는 자리가 있다.
            pat = re.compile(rf"(?<![가-힣A-Za-z]){re.escape(label)}(?![가-힣A-Za-z])"
                             rf"\s*수?\s*(?:이|가|은|는)?\s*"
                             rf"[(（]?\s*(\d[\d,]*)\s*(?:개|건|곳|장)?")
            for i, t in enumerate(text_lines, 1):
                for m in pat.finditer(t):
                    got = int(m.group(1).replace(",", ""))
                    if got == want:
                        continue
                    if not exact and near_only and abs(got - want) > args.near:
                        continue
                    # 총계 라벨을 near 없이 보는 대신, 부분합 표지가 앞에 있으면 뺀다 —
                    # *"경계 표면 7 · 이력 ↔ 뷰어"* 를 전부 어긋남으로 세면 진짜가 묻힌다.
                    if exact and abs(got - want) > args.near and PARTIAL_HINT.search(
                            t[max(0, m.start() - 12):m.start()]):
                        skipped_partial.append((i, "한정어", m.group(1)))
                        continue
                    # **열거가 그 수와 1:1 이면 자기정합한 부분합이다.** it.19 실측 —
                    # *"자동화 관련 Contract 7개(C54 · C55 … C136)"* 가 총계 141 과 대 보여
                    # 오탐이 됐다. 한정어(*"관련"*)를 낱말로 받는 것은 **그 표기에 맞추는 것**
                    # 이라(it.17 확정 사실) 표기와 무관한 축을 하나 더 댄다 — 괄호 안 ID 수를
                    # 센다. 열거가 수와 다르면 그것은 잡혀야 하므로 **같을 때만** 뺀다.
                    if exact and abs(got - want) > args.near:
                        # **절로 끊어 되돌아보고 정본으로 재계산한다.** 한정어가 절 앞머리에
                        # 있고 사이에 낱말이 드는 자리(*"Layer 1 · 전 모듈 공통 정본 —
                        # Contract 49개"*)는 글자 수 창으로 못 본다. 그러나 **축 토큰이
                        # 있다고 지우면 안 된다** — 그 판정은 정본 부분합이 그 수와 같을
                        # 때만 선다(위 `PARTIAL_HINT` 주석의 과녁이 그렇게 지워졌다).
                        pre = t[:m.start()]
                        cut = max(pre.rfind("."), pre.rfind("。"))
                        hit = None
                        for am in AXIS_TOK.finditer(pre[cut + 1:]):
                            n = am.group(1) or am.group(2)
                            if layer_total.get(n) == got:
                                hit = n
                                break
                        if hit:
                            skipped_partial.append((i, f"Layer {hit} 부분합", m.group(1)))
                            continue
                        tail = t[m.end():m.end() + 220]
                        par = re.match(r"\s*[(（]([^)）]*)[)）]", tail)
                        # `got` 가 0 이면 **빈 괄호가 0 개와 맞물려** 지워진다 — 실측에서
                        # *"관여 표면 0개 (독립 경계 주장 없음)"* 가 그렇게 사라졌다.
                        if got and par and len(expand_ids(par.group(1), sid, rng)) == got:
                            skipped_partial.append((i, "열거 자기정합", m.group(1)))
                            continue
                    frag = t.strip()[max(0, m.start() - 30):m.start() + 40].strip()
                    out.append((label, want, got, i, frag))
        # 차이가 작은 것부터 — 손으로 옮기다 나는 실패가 위에 온다
        return sorted(out, key=lambda r: abs(r[2] - r[1]))

    bad = scan(expect)
    if bad:
        print("| 라벨 | 정본 | 본문 | 차이 | 행 | 자리 |")
        print("|---|---|---|---|---|---|")
        for label, want, got, i, frag in bad[:(CAP or 40)]:
            print(f"| {label} | {want} | **{got}** | {got - want:+d} | {i} | {frag[:60]} |")
        if len(bad) > 40 and not args.full:
            print(f"\n⚠ **판정하지 않은 {len(bad) - 40}건이 남아 있다** — 위 40건만 찍었다. 전량은 `--full` 로 본다")
        print("\n**어긋난 자리를 정본으로 고친다.** 다만 라벨이 다른 뜻으로 쓰인 문장"
              "(예 *\"충돌 24건 중 12건\"*)도 걸린다 — 한 줄씩 눈으로 가른다.")
        problems += 1
    else:
        print("라벨 붙은 수치가 전부 정본과 같다.")
    if skipped_partial:
        kinds = Counter(k for _, k, _ in skipped_partial)
        print(f"\n부분합으로 판정해 뺀 자리 **{len(skipped_partial)}건** —"
              f" {' · '.join(f'{k} {v}' for k, v in kinds.items())}"
              f" (행 {' · '.join(str(x[0]) for x in skipped_partial[:12])}"
              f"{' …' if len(skipped_partial) > 12 else ''})."
              " **이 수가 갑자기 커지면 필터가 과녁을 함께 지운 것이다** — 자리를 눈으로 대 본다.")

    # ── ②-c 숫자가 라벨 앞에 붙은 형태 — *"58표면"* ─────────────────────────
    # 실측(it.13): 파생 수치 7건이 전부 이 스크립트 밖의 형태였고 한 채점자가 셋으로 갈랐다 —
    # **숫자 뒤 라벨**(*"58표면"*) · 정본 키가 아닌 라벨 · 이중 계상. 위 ② 는 `라벨 + 수` 만
    # 보므로 순서가 뒤집힌 자리를 지나간다.
    #
    # 처음 `\d+\s*라벨` 로 넓게 걸었더니 오탐이 지배했다 — *"02 충돌"*(문서명) · *"C23 미결"*(ID) ·
    # *"층 1 미결 15"*(다른 축의 수식). **숫자와 라벨이 붙어 있고 앞이 ID·문서명·다른 축이
    # 아닌 것**만 본다(검증: 과녁 1건 검출 · 다른 네 집합 오탐 0).
    print("\n## 숫자가 라벨 앞에 붙은 자리\n")
    rev = re.compile(r"(?<![A-Za-z0-9§\-])(\d{1,4})("
                     + "|".join(re.escape(k) for k in expect) + r")(?![가-힣])")
    rev_bad = []
    for i, t in enumerate(text_lines, 1):
        for m in rev.finditer(t):
            got, label = int(m.group(1)), m.group(2)
            want = expect.get(label)
            if want is None or got == want:
                continue
            pre = t[max(0, m.start() - 12):m.start()]
            if re.search(r"(층|Layer|단계|일차|묶음|배치)\s*\d?\s*$", pre):
                continue                      # 다른 축이 수식하는 자리
            rev_bad.append((i, label, want, got,
                            t.strip()[max(0, m.start() - 16):m.start() + 30].strip()))
    if rev_bad:
        print("| 행 | 라벨 | 정본 | 본문 | 자리 |")
        print("|---|---|---|---|---|")
        for i, label, want, got, frag in rev_bad[:20]:
            print(f"| {i} | {label} | {want} | **{got}** | {frag[:44]} |")
        print("\n**부분합이면 범위를 밝히고, 총계 자리면 정본 값으로 고친다.** 같은 문구가"
              " 여럿이면 한 번 판정해 전부 처리한다.")
        problems += 1
    else:
        print("숫자가 라벨 앞에 붙은 자리가 전부 정본과 같다(또는 없다).")

    # ── ②-b 라벨 + 한글 수사 ──────────────────────────────────────────────
    print("\n## 라벨에 한글 수사가 붙은 자리\n")
    hb = hangul_scan(text_lines, dict(expect, **{k: v for k, v in strength.items()
                                                if k in ("최상", "상", "중")}))
    if hb:
        print("| 라벨 | 정본 | 본문 | 낱말 | 행 | 자리 |")
        print("|---|---|---|---|---|---|")
        for label, want, got, word, i, frag in hb[:(CAP or 25)]:
            print(f"| {label} | {want} | **{got}** | {word} | {i} | {frag[:52]} |")
        print("\n**부분합 서술이면 그대로 두고, 전체를 말하는 자리면 고친다.** 숫자로 쓴 자리는"
              " 위 표가 보고 이 표는 *\"여덟\"* · *\"세 벌\"* 처럼 낱말로 쓴 자리를 본다.")
        problems += 1
    else:
        print("라벨에 붙은 한글 수사가 정본과 어긋나는 자리가 없다.")

    # 강도 낱말은 부분합 서술에 자주 쓰인다(*"충돌 17건 중 최상 10건"*). 어긋남으로 세지
    # 않고 목록만 낸다 — 평가에서 이 축의 참 판정과 거짓 판정이 반반이었다.
    if soft:
        rows = scan(soft)
        print("\n### 참고 — 강도 낱말이 붙은 수치 (부분합일 수 있다)\n")
        if rows:
            print("| 라벨 | 전체 | 본문 | 행 | 자리 |")
            print("|---|---|---|---|---|")
            for label, want, got, i, frag in rows[:20]:
                print(f"| {label} | {want} | {got} | {i} | {frag[:60]} |")
            print("\n부분합이면 그대로 두고, 전체를 말하는 자리면 고친다.")
        else:
            print("없다.")

    # ── ③ 괄호 안 ID 개수 ────────────────────────────────────────────────
    print("\n## \"N건(ID · ID …)\" 대조\n")
    status_of = {}
    for s, num in zip(surfaces, declared):
        if num:
            status_of[num] = s.get("status", "?")
    paren_bad, status_bad = [], []
    for i, t in enumerate(text_lines, 1):
        for m in paren.finditer(t):
            want = int(m.group(1))
            inner = m.group(2)
            if "+" in inner:      # *"16건(1층 12 + 순환에 걸린 C10 …)"* 는 합산 서술이다
                continue
            ids = expand_ids(inner, sid, rng)
            if not ids:
                continue
            if want != len(ids):
                paren_bad.append((i, want, len(ids), m.group(0)[:70]))
            # 상태 낱말을 붙여 센 목록에 다른 상태가 섞이는 실패가 있었다 —
            # *"충돌 12건"* 으로 센 목록에 갭 하나가 들어 있었다.
            before = t[max(0, m.start() - 40):m.start()]
            for key, word in STATUS_LABEL.items():
                if word in before:
                    odd = sorted(f"{n}({STATUS_LABEL.get(status_of[n], '?')})"
                                 for n in ids
                                 if n in status_of and status_of[n] != key)
                    if odd:
                        status_bad.append((i, word, ", ".join(odd), m.group(0)[:60]))
                    break
    if paren_bad:
        print("| 행 | 적힌 수 | 괄호 안 ID | 자리 |")
        print("|---|---|---|---|")
        for i, want, got, frag in paren_bad:
            print(f"| {i} | {want} | **{got}** | {frag} |")
        problems += 1
    else:
        print("괄호 안 ID 개수가 앞의 수와 전부 맞는다.")
    if status_bad:
        print("\n**상태 낱말과 목록이 어긋난다.**\n")
        print("| 행 | 적힌 상태 | 다른 상태인 ID | 자리 |")
        print("|---|---|---|---|")
        for i, word, odd, frag in status_bad[:20]:
            print(f"| {i} | {word} | **{odd}** | {frag} |")
        problems += 1

    # ── ④ 막대 라벨과 값 ─────────────────────────────────────────────────
    # 라벨을 맞바꿔 적는 실패가 있었다 — 값은 스크립트 것이고 이름만 뒤집혔다.
    print("\n## 막대 — 라벨과 값\n")
    bar_bad, bar_seen = [], 0
    for i, raw in enumerate(lines, 1):
        if not BAR.search(raw):
            continue
        # 막대는 한 줄로 쓰기도 하고 여러 줄로 쪼개 쓰기도 한다. 뒤 여섯 줄까지 묶어 본다.
        block = "\n".join(lines[i - 1:i + 6])
        bv, bl = BV.search(block), BL.search(block)
        if not (bv and bl):
            continue
        label = strip_tags(bl.group(1))
        got, denom = int(bv.group(1).replace(",", "")), int(bv.group(2).replace(",", ""))
        hits = [p for p in involve if p and p in label]
        if not hits:
            continue
        bar_seen += 1
        party = max(hits, key=len)
        want = involve[party]
        wm = WIDTH.search(block)
        want_w = want / total * 100 if total else 0
        if got != want or denom != total or (
                wm and abs(float(wm.group(1)) - want_w) > 0.6):
            bar_bad.append((i, label.strip()[:34], party, want, got, denom,
                            wm.group(1) if wm else "—", f"{want_w:.1f}"))
    if bar_bad:
        print("| 행 | 라벨 | 걸린 갈래 | 정본 | 본문 | 분모 | width | 정본 width |")
        print("|---|---|---|---|---|---|---|---|")
        for row in bar_bad:
            print(f"| {row[0]} | {row[1]} | {row[2]} | {row[3]} | **{row[4]}** |"
                  f" {row[5]} | {row[6]}% | {row[7]}% |")
        print("\n**라벨과 값이 맞는지 본다.** 값은 맞고 이름만 뒤바뀐 경우가 있었다.")
        problems += 1
    elif bar_seen:
        print(f"갈래 막대 {bar_seen}개의 값·분모·width 가 정본과 같다.")
    else:
        print("갈래 이름이 걸리는 막대가 없다 — `class=\"bar\"` 와 `bl`·`bv` 를 확인한다.")

    # ── ⑤ 표면마다 참여 문서가 본문에 있는가 ──────────────────────────────
    # 갭·정리됨의 참여 표기 누락이 네 판에 걸쳐 반복됐다. 카드에는 적고 표에는 잊는다.
    print("\n## 참여 문서 표기\n")
    where = defaultdict(list)
    for i, t in enumerate(text_lines):
        for m in sid.finditer(t):
            where[m.group(0)].append(i)
    no_party = []
    for s, num in zip(surfaces, declared):
        parties = [p for p in s.get("parties", []) if p]
        if num is None or not parties:
            continue
        # 참여를 갈래 코드로 적는 산출물도 있고 문서 라벨로 적는 산출물도 있다. `cites` 의
        # 앞머리(*"REQ §3.2.1"* 의 `REQ`)도 같은 자리를 가리키므로 함께 인정한다.
        tokens = set(parties)
        for c in s.get("cites", []):
            head = re.split(r"[\s§:·—]", str(c).strip(), maxsplit=1)[0]
            if len(head) >= 2:
                tokens.add(head)
        found = False
        for i in where.get(num, []):
            window = " ".join(text_lines[max(0, i - 1):i + 3])
            if any(p in window for p in tokens):
                found = True
                break
        if not found:
            no_party.append((s.get("id"), s.get("status", "?"), ", ".join(parties)))
    if no_party:
        print("**아래 Contract 는 ID 가 본문에 있으나 참여 문서가 그 근처에 없다.**")
        print("상태와 무관하게 참여를 적는다 — 갭·정리됨에서 빠지는 것이 가장 자주 나는 실패다.\n")
        print("| Contract | 상태 | 참여 (`contracts.json`) |")
        print("|---|---|---|")
        # **`sid`(ID 정규식)를 가리지 않는다.** 이 루프가 같은 이름을 쓰고 있었고, 아래
        # 카드 라벨 축이 옛 산출물(`aidlc` 없음)에서는 실행되지 않아 **숨어 있던 버그**다 —
        # ⑤ 가 `strength` 로 그 축을 켜자 옛 산출물 일곱에서 예외로 죽었다.
        for cid_, st, parties in no_party:
            print(f"| {cid_} | {STATUS_LABEL.get(st, st)} | {parties} |")
        problems += 1
    else:
        print("Contract 전부가 참여 문서와 함께 본문에 있다.")

    # ── ④-b "A N개 중 M개" — 앞의 N 이 정본과 맞는가 ──────────────────────
    # *"갭 48개 중 19개"* 처럼 부분합 서술로 보이면 위 라벨 검사가 통과시킨다. 그런데
    # **앞의 N 은 총계**이므로 정본과 맞아야 한다. 실측에서 그 자리 둘이 어긋났다.
    print("\n## \"A N개 중 M개\" — 앞의 수\n")
    OFN = re.compile(rf"(?<![가-힣])({'|'.join(re.escape(k) for k in expect)})"
                     rf"\s*수?\s*(\d{{1,4}})\s*(?:개|건|곳)?\s*중\s*(\d{{1,4}})")
    ofn_bad = []
    for i, t in enumerate(text_lines, 1):
        for m in OFN.finditer(t):
            label, whole, part = m.group(1), int(m.group(2)), int(m.group(3))
            want = expect.get(label)
            if want is None or whole == want:
                continue
            ofn_bad.append((i, label, want, whole, part,
                            t.strip()[max(0, m.start() - 20):m.start() + 44].strip()))
    if ofn_bad:
        print("| 행 | 라벨 | 정본 | 적힌 전체 | 부분 | 자리 |")
        print("|---|---|---|---|---|---|")
        for i, label, want, whole, part, frag in ofn_bad[:20]:
            print(f"| {i} | {label} | {want} | **{whole}** | {part} | {frag[:50]} |")
        print("\n**부분(중 M)은 정당해도 전체(N)는 정본과 같아야 한다.**")
        problems += 1
    else:
        print("`A N개 중 M개` 형 서술의 앞 수가 전부 정본과 같다.")

    # ── ④-c 층·단계별 개수 — *"층 3 의 15개"* ─────────────────────────────
    # 실측(it.11): 남은 전파 누락 10건이 **전부** 「표·정본은 재계산했고 그 수를 인용하는
    # 서술 문장을 안 따라간 것」이었고, 이 스크립트가 하나도 잡지 못했다. 원인은 라벨 패턴이
    # 아니라 **그 축의 정본이 없던 것**이다 — 다섯 집합 중 `layer` 를 `contracts.json` 에 둔
    # 것은 하나뿐이고 나머지는 작업 파일이나 본문에만 있었다. 정본에 자리가 있으면 기계적으로
    # 잡힌다(검증: 한 산출물의 *"층 3 의 15개"* ↔ 정본 18).
    print("\n## Layer·단계별 개수\n")
    layer_axes = []
    # `closes`(받아올 것)는 **이 축에 넣지 않는다 — 만들어 보고 기각했다.** 값이 층별
    # 부분합으로 쓰이는 것이 정상이어서(*"층 1 의 실물 6건"* ↔ 정본 8) 한 산출물에 거짓
    # 양성 11건 · 진성 0건이 나왔다. 앞의 층 한정어를 거르는 필터를 붙여도 *"결정권자가
    # 화요일에 없으면 회신 3건이 밀린다"* 처럼 한정어가 뒤에 오는 자리가 남는다 — 아래
    # "검사하지 않은 축" 의 **교차 부분합**과 같은 계열이다. 정합 검사(④-e)만 채택했다.
    for field, word in (("layer", "층"), ("aidlc", None), ("gap_kind", None)):
        vals = [s.get(field) for s in surfaces if s.get(field) not in (None, "")]
        if vals:
            layer_axes.append((field, word, Counter(str(v).strip() for v in vals)))
    if not layer_axes:
        print("`contracts.json` 에 `layer`·`aidlc` 가 없다 — **이 축을 검사하지 못했다.**"
              " 층과 단계 배정은 판정의 근거이고 서술 문장이 그 수를 인용한다."
              " 정본에 두면 이 검사가 켜진다(스키마: `layer` 는 층 번호나 층 이름,"
              " `aidlc` 는 `prep`·`ideation`·`inception`·`construction`," " `gap_kind` 는 갭에만 `orphan`·`spec`).")
        unchecked_extra = True
    else:
        unchecked_extra = False
        lay_bad = []
        # **이 절은 한 축만 말하는 자리를 본다.** 교차 부분합(*"Layer 1 의 ideation 10건"*)은
        # ⑩ⓐ 가 `cross` 로 재계산하므로 여기서 총계와 대 보면 **중복 오탐**이다 — it.19 실측에서
        # 이 절의 9행이 전부 그 계열이고 정본 교차로는 10·25·14·41·2·22 **전부 맞는 값**이었다.
        # 그 판까지 이 절에는 부분합 필터가 **아예 없었다**(「라벨 붙은 수치」에는 있었다) —
        # 오탐 17행의 절반이 여기서 났다.
        #
        # **다른 축의 토큰이 있다는 것만으로 지우지 않는다 — 정본 교차표가 그 수와 같아야 한다.**
        # 표기로 지우면 진성이 함께 사라진다(실측: `iteration-11/lotteon-6docs` 의 *"사전 준비
        # 29건"* ↔ 정본 10 이 「그리고」를 한정어로 읽는 필터에 지워졌다. 「그」로 시작하는
        # 접속사다). 교차로 재계산할 수 없는 자리(*"그중 Layer 3 의 2건(C46 · C68)"*)는
        # **괄호 안 열거가 그 수와 1:1 인가**로 판정한다 — 표기와 무관한 축이다.
        lay_skip = []
        cross_c = Counter()
        for s in surfaces:
            lm = re.match(r"\s*(\d{1,2})", str(s.get("layer") or ""))
            cross_c[(lm.group(1) if lm else "", str(s.get("aidlc") or "").strip())] += 1
        for field, word, cnt in layer_axes:
            for key, want in cnt.items():
                # 층은 **반드시 「층 N」 형태로만** 찾는다. 번호만 쓰면 *"충돌 39개"* 의 `3` 을
                # 층 3 으로 읽어 거짓 양성이 쏟아진다(실측에서 과녁 1건에 오탐 11건).
                # 단계(`aidlc`)는 `ideation`·`inception` 같은 낱말이라 그대로 쓴다.
                if word == "층":
                    m = re.match(r"(\d{1,2})", key)
                    # 어휘를 `Layer` 로 올렸어도 **과거 산출물은 「층 N」으로 적혀 있다.**
                    # 둘 다 만들어 어느 쪽이든 검사되게 한다.
                    keys = [f"Layer {m.group(1)}", f"층 {m.group(1)}"] if m else []
                elif field == "gap_kind":
                    # 갭 하위 분류. 정본은 소문자 코드이고 본문은 한국어 라벨을 쓴다.
                    keys = GAP_KIND_LABEL.get(key, [key])
                else:
                    keys = [key]
                for k in keys:
                    pat = re.compile(rf"{re.escape(k)}\s*(?:의|은|는|에)?\s*(\d{{1,4}})\s*(?:개|건|곳)")
                    for i, t in enumerate(text_lines, 1):
                        for mm in pat.finditer(t):
                            got = int(mm.group(1))
                            if got == want:
                                continue
                            # 교차 부분합은 ⑩ⓐ 로 넘긴다(위 주석) — **정본 교차표가 그 수와
                            # 같을 때만** 뺀다.
                            skip = ""
                            if field == "aidlc":
                                for am in AXIS_TOK.finditer(t):
                                    n = am.group(1) or am.group(2)
                                    if cross_c.get((n, key)) == got:
                                        skip = f"Layer {n} × {key}"
                                        break
                            elif field == "layer":
                                lnum = re.match(r"(\d{1,2})", key.split()[-1])
                                for sm in STAGE_TOK.finditer(t):
                                    st = STAGE_CODE[sm.group(0)]
                                    if lnum and cross_c.get((lnum.group(1), st)) == got:
                                        skip = f"{key} × {st}"
                                        break
                            if not skip:
                                par = re.match(r"\s*[(（]([^)）]*)[)）]",
                                               t[mm.end():mm.end() + 220])
                                if got and par and \
                                        len(expand_ids(par.group(1), sid, rng)) == got:
                                    skip = "열거 자기정합"
                            if skip:
                                lay_skip.append((i, k, want, got, skip))
                                continue
                            # `--near` 를 여기서는 쓰지 않는다. 층·단계별 개수는 부분합이
                            # 아니라 정본에서 정확히 세어지는 값이므로 차이가 커도 어긋남이다.
                            # 실측의 그 자리가 정본 18 ↔ 본문 15 로 차이 3 이었다.
                            lay_bad.append((i, k, want, got,
                                            t.strip()[max(0, mm.start() - 18):
                                                      mm.start() + 40].strip()))
        seen_lay = set()
        lay_bad = [x for x in lay_bad
                   if not (x[:4] in seen_lay or seen_lay.add(x[:4]))]
        if lay_bad:
            print("| 행 | 축 | 정본 | 본문 | 자리 |")
            print("|---|---|---|---|---|")
            for i, k, want, got, frag in lay_bad[:20]:
                print(f"| {i} | {k} | {want} | **{got}** | {frag[:48]} |")
            print("\n**정본의 Layer·단계 배정에서 센 값과 다르다.** 표를 고치고 서술 문장을"
                  " 안 고친 자리가 이 모양이다.")
            problems += 1
        else:
            axes = " · ".join(f"`{f}`" for f, _, _ in layer_axes)
            print(f"{axes} 로 센 Layer·단계별 개수가 본문 서술과 같다.")
        if lay_skip:
            seen_sk = set()
            sk = [x for x in lay_skip if not (x in seen_sk or seen_sk.add(x))]
            print(f"\n정본 교차표로 재계산해 **맞는 부분합이라 뺀 자리 {len(sk)}건** —"
                  f" {' · '.join(f'{x[0]} {x[4]}={x[3]}' for x in sk[:10])}"
                  f"{' …' if len(sk) > 10 else ''}."
                  " **그 형태는 「축을 어긴 서술」 ⓐ 가 본다.**"
                  " 이 수가 갑자기 커지면 필터가 과녁을 함께 지운 것이다.")

    # ── ④-d 축 라벨 혼용 — *"층 1 합의 25건"* 인데 25 는 단계 수 ─────────────
    # 실측(it.12): 정본에 `layer`·`aidlc` 를 두어 수치 대조는 닫혔는데, 세 채점자가 독립적으로
    # 같은 유형을 지적했다 — **수는 맞고 그 수에 붙은 축 라벨이 틀렸다.** 한 산출물의 부록
    # 트리가 `ideation/` 에 *"층 1 합의 25건"* 을 붙였고 정본 층 1 은 20, ideation 이 25 다.
    # 위 ④-c 는 「층 N」 바로 뒤 숫자만 보므로 사이에 낱말이 끼면 지나간다.
    # **다른 축의 값과 정확히 일치할 때만** 보고한다 — 그래서 오탐이 없다(검증: 과녁 2건 검출,
    # 오탐 0. 같은 검사의 다른 형태였던 「ID 열거의 축 일관성」은 오탐이 5/7 이라 채택하지 않고
    # 아래 "검사하지 않은 축" 에 남겼다).
    print("\n## 축 라벨 혼용 — Layer 자리에 단계 수, 단계 자리에 Layer 수\n")
    mix_bad = []
    if layer_axes:
        lay_cnt = next((c for f, _w, c in layer_axes if f == "layer"), None)
        stg_cnt = next((c for f, _w, c in layer_axes if f == "aidlc"), None)
        if lay_cnt and stg_cnt:
            # 층 이름이 "1 · 사전 준비" 처럼 길 수 있으므로 앞 번호로 정본을 찾는다
            by_num = {}
            for k, v in lay_cnt.items():
                mm = re.match(r"(\d{1,2})", k)
                if mm:
                    by_num[mm.group(1)] = v
            for i, t in enumerate(text_lines, 1):
                for m in re.finditer(r"(?:층|Layer)\s*(\d{1,2})[^0-9]{0,12}?"
                                     r"(\d{1,4})\s*(?:개|건|곳)", t):
                    key, got = m.group(1), int(m.group(2))
                    want = by_num.get(key)
                    if want is None or got == want:
                        continue
                    # **작은 수는 우연히 맞물린다.** `construction`(이월) 칸이 0~3 이라
                    # 실측에서 그 값 2 가 *"역방향 의존 2건"* · *"2개 — M1 + M3"* 에 걸려
                    # 오탐 2건이 났다. 이 검사는 「수는 맞고 라벨이 틀렸다」를 잡는 것이므로
                    # **다른 축의 값과 일치하는 것이 우연이 아닐 만큼 큰 수**만 본다.
                    alt = [k for k, v in stg_cnt.items() if v == got and v >= 4]
                    if alt:
                        mix_bad.append((i, key, want, got, alt[0],
                                        t.strip()[max(0, m.start() - 14):
                                                  m.start() + 40].strip()))
    if mix_bad:
        print("| 행 | 축 | 그 Layer 의 정본 | 본문 | 실은 이 값 | 자리 |")
        print("|---|---|---|---|---|---|")
        for i, key, want, got, alt, frag in mix_bad[:20]:
            print(f"| {i} | Layer {key} | {want} | **{got}** | 단계 `{alt}` | {frag[:44]} |")
        print("\n**Layer 라벨에 단계 수가 붙었다.** 수치는 맞고 라벨이 틀린 유형이라 수 대조로는"
              " 통과한다 — 라벨을 고치거나 그 층의 값으로 바꾼다.")
        problems += 1
    elif layer_axes:
        print("Layer 라벨에 붙은 수가 전부 그 Layer 의 정본 값이다.")
    else:
        print("`layer`·`aidlc` 가 없어 검사하지 못했다.")

    # ── ④-e 받아올 것 판정 ↔ 단계 배정 — *"실물이 필요한데 inception"* ────────
    # 실물(기존 소스·표본·실행 환경)은 워크숍 안에서 생기지 않는다. 그래서 `closes` 가
    # `artifact` 인 표면은 **전부 `prep`** 이어야 한다. 반대는 성립하지 않으므로 검사하지
    # 않는다 — 회신 필요는 결정할 사람이 구간에 있으면 `ideation` 이다(SKILL.md 5단계
    # 판정 순서). 이 두 축은 「미리 해 올 것」과 「AI-DLC 안에서 닫을 것」을 가르는 자리고,
    # 정본에 없으면 사전 준비 분량을 대조할 대상이 없다 — 실측에서 이 값을 본문에만 둔
    # 산출물이 같은 표면을 한 곳에서 실물 필요로, 파트 4 에서 *"외부 회신을 기다린다"* 로
    # 적었다. 받아올 것이 없는데 `prep` 인 것은 어긋남이 아니라 **근거를 요구하는 경고**다(선행
    # 때문에 내려간 자리이므로 그 ID 가 본문에 있어야 한다).
    print("\n## 받아올 것 ↔ AI-DLC 단계 배정\n")
    closes_missing = False
    with_closes = [s for s in surfaces if str(s.get("closes") or "").strip()]
    with_aidlc = [s for s in surfaces if str(s.get("aidlc") or "").strip()]
    if not with_closes or not with_aidlc:
        closes_missing = True
        lack = " · ".join(f"`{f}`" for f, have in
                          (("closes", with_closes), ("aidlc", with_aidlc)) if not have)
        print(f"`contracts.json` 에 {lack} 가 없다 — **이 축을 검사하지 못했다.**"
              " 사전 준비 분량(= `prep` 개수)이 기간 판정의 입력이므로 정본에 둔다"
              " (`closes` 는 `paper`·`reply`·`artifact`,"
              " `aidlc` 는 `prep`·`ideation`·`inception`·`construction`," " `gap_kind` 는 갭에만 `orphan`·`spec`).")
    else:
        blank = [str(s.get("id")) for s in surfaces
                 if not str(s.get("closes") or "").strip()
                 or not str(s.get("aidlc") or "").strip()]
        hard = [(str(s.get("id")), str(s.get("aidlc")).strip())
                for s in surfaces
                if str(s.get("closes") or "").strip() == "artifact"
                and str(s.get("aidlc") or "").strip() != "prep"]
        soft = [str(s.get("id")) for s in surfaces
                if str(s.get("closes") or "").strip() == "paper"
                and str(s.get("aidlc") or "").strip() == "prep"]
        if blank:
            print(f"- **두 축 중 하나가 빈 Contract: {', '.join(blank[:20])}**"
                  " — 미결 전량에 하나씩 배정한다")
            problems += 1
        if hard:
            print("| Contract | `closes` | `aidlc` | 왜 어긋남인가 |")
            print("|---|---|---|---|")
            for sid_, stage in hard[:20]:
                print(f"| `{sid_}` | {CLOSES_LABEL['artifact']} | **{stage}** |"
                      " 실물은 워크숍 안에서 생기지 않는다 → `prep` |")
            print("\n**실물이 필요한데 AI-DLC 안 단계로 배정됐다.** 배정은 「그 일의 성격」이"
                  " 아니라 「닫히기 위한 선행 조건」으로 정한다 — 설계할 일이어도 값이"
                  " 밖에서 와야 하면 `prep` 이다.")
            problems += 1
        if soft:
            print(f"\n⚠ 받아올 것이 없는데 `prep` 인 Contract: {', '.join(soft[:20])}"
                  " — 선행 표면 때문에 내려간 것이면 **그 표면 ID 가 근거로 본문에 있어야**"
                  " 한다. 근거가 없으면 사전 준비 분량이 부풀어 기간 판정이 실제보다 나쁘게"
                  " 나온다. **통과 여부는 바꾸지 않는다.**")
        carry = [str(s.get("id")) for s in surfaces
                 if str(s.get("aidlc") or "").strip() == "construction"]
        if carry:
            print(f"\n⚠ 이월(`construction`)로 내려간 Contract {len(carry)}건:"
                  f" {', '.join(carry[:20])} — 파트 4 #03 에 **되돌림 위험**이 적혀 있는지"
                  " 본다. 이 칸은 배정이 아니라 경고다(앞 단계가 이름만 정하고 필드를"
                  " 정하지 않은 자리). **통과 여부는 바꾸지 않는다.**")
        if not (blank or hard):
            prep = sum(1 for s in surfaces
                       if str(s.get("aidlc") or "").strip() == "prep")
            art = sum(1 for s in surfaces
                      if str(s.get("closes") or "").strip() == "artifact")
            print(f"실물 필요 {art}건이 전부 `prep` 이다 — 사전 준비 {prep}건"
                  f"({'같은 집합' if prep == art else f'실물 밖에서 {prep - art}건 더'}).")

    # ── ④-f 카드 라벨의 축 일관성 — *"C59 · C60 · 착수 전 회신"* ──────────────
    # 실측(it.15): 파생 수치 3건 중 **둘이 확인 카드의 `.cm` 라벨**이었다 — 카드가 담은 ID 중
    # 하나가 그 라벨의 축 값이 아니다(`C60` 은 `ideation` 인데 「착수 전」으로 묶였고, `C58` 은
    # `artifact` 인데 「회신」으로 묶였다). 수치는 맞고 **라벨이 틀린** 유형이라 수 대조로는
    # 통과한다.
    #
    # **자유 서술에는 걸지 않는다.** 같은 검사를 문장 단위로 두 번 만들어 두 번 기각했다
    # (오탐 6/7 — 순서 표현과 다른 항목의 ID 가 한 문장에 섞인다). 여기서는 **`.cm`·`.ct` 같은
    # 카드 요소 안**으로 범위를 좁힌다 — 그 안의 ID 는 그 카드가 말하는 대상뿐이다.
    print("\n## 카드 라벨의 축 일관성 — 라벨이 말한 칸과 그 카드의 ID\n")
    AXIS_WORDS = {
        "aidlc": {"사전 준비": "prep", "착수 전": "prep", "ideation": "ideation",
                  "inception": "inception", "construction": "construction", "이월": "construction"},
        "closes": {"받아올 것 없음": "paper", "회신 필요": "reply", "회신": "reply",
                   "실물 필요": "artifact", "실물": "artifact"},
    }
    card_bad = []
    by_id = {}
    have_axis = any(str(c.get("aidlc") or "").strip() for c in surfaces)
    strength_any = any(str(c.get("strength") or "").strip() for c in surfaces)
    if not have_axis and not strength_any:
        print("`contracts.json` 에 `aidlc`·`strength` 가 없어 **이 축이 꺼졌다** —"
              " 0건이 통과가 아니다.")
    else:
        if not have_axis:
            print("⚠ `aidlc` 가 없어 **단계·받아올 것 라벨은 검사하지 못했다** —"
                  " 강도 축만 봤다.")
        if not strength_any:
            print("⚠ `strength` 가 없어 **강도 라벨은 검사하지 못했다.**")
        by_id.update({str(c.get("id", "")).strip(): c for c in surfaces})
        raw = Path(args.html).read_text(encoding="utf-8")
        for m in re.finditer(r'<div class="(cm|ct)"[^>]*>(.*?)</div>', raw, re.S):
            inner = strip_tags(m.group(2))
            ids = [x.group(0) for x in sid.finditer(inner)]
            if len(ids) < 2:
                continue
            line = raw.count("\n", 0, m.start()) + 1
            # **강도 축**(it.20 신설). it.19 `plandetail` 파생 2건이 이 모양이다 —
            # 카드가 여러 Contract 를 **한 강도로 묶는** 형태이고(`:2564` C45 정본은 「상」인데
            # 카드는 「최상」 · `:2596` C109 정본은 「중」인데 카드는 「최상·상」이고 그 카드에
            # 「상」이 하나도 없다) `strength` 는 **정본 필드인데** 이 축이 상태·단계만 봤다.
            # 확정 사실 *"정본에 자리가 없는 축은 기계가 못 지킨다"* 의 변형 — **필드는 있고
            # 그 필드를 쓰는 서술 형태에 자리가 없었다.**
            #
            # **범위를 `.cm` 의 마지막 ID 뒤로 좁힌다.** 「상」·「중」·「하」는 산문에 흔한
            # 글자여서(*"39건 중"* · *"동시 상한"*) 카드 본문(`.ct`)이나 ID 앞을 보면 오탐
            # 기계가 된다. 카드 머리표는 `ID · ID · … · 라벨` 형식이라 라벨은 꼬리에 있다.
            if m.group(1) == "cm" and strength_any:
                tail = inner[inner.rfind(ids[-1]) + len(ids[-1]):]
                lab = {x.group(1) for x in STRENGTH_TOK.finditer(tail)}
                if lab:
                    got_s = {str(by_id[i].get("strength") or "").strip(): i
                             for i in ids if i in by_id
                             and str(by_id[i].get("strength") or "").strip()}
                    # **양방향으로 잰다**(확정 사실 *"한 방향으로만 거는 규칙은 반대쪽으로
                    # 넘친다"*). ⓐ 라벨에 없는 강도를 가진 ID · ⓑ 가진 ID 가 없는 라벨.
                    off = sorted(i for v, i in got_s.items() if v not in lab)
                    if off:
                        card_bad.append((line, "·".join(sorted(lab)), "strength",
                                         "·".join(sorted(lab)), off,
                                         " ".join(inner.split())[:44]))
                    empty = sorted(lab - set(got_s))
                    if empty and got_s:
                        card_bad.append((line, "·".join(sorted(lab)), "strength",
                                         f"「{'·'.join(empty)}」인 ID 가 없다", [],
                                         " ".join(inner.split())[:44]))
            for field, words in AXIS_WORDS.items():
                for word, want in words.items():
                    if word not in inner:
                        continue
                    off = [i for i in ids
                           if i in by_id and str(by_id[i].get(field) or "").strip()
                           and str(by_id[i].get(field)).strip() != want]
                    if off:
                        card_bad.append((line, word, field, want, off,
                                         " ".join(inner.split())[:44]))
                    break   # 한 축에 한 라벨만 본다 — 「회신」과 「회신 필요」가 겹친다
    if card_bad:
        print("| 행 | 카드 라벨 | 축 | 라벨이 뜻하는 값 | 어긋난 ID | 자리 |")
        print("|---|---|---|---|---|---|")
        for line, word, field, want, off, frag in card_bad[:20]:
            actual = ", ".join(f"{i}={by_id[i].get(field)}" for i in off) or "—"
            print(f"| {line} | 「{word}」 | `{field}` | `{want}` | **{actual}** | {frag} |")
        print("\n**카드 라벨이 말한 칸에 그 ID 가 없다.** 수치는 맞고 라벨이 틀린 유형이라"
              " 수 대조로는 통과한다 — 라벨을 고치거나 그 ID 를 다른 카드로 옮긴다."
              " **강도 축은 양방향이다** — 어긋난 ID 칸이 `—` 인 행은 *\"그 라벨을 가진 ID 가"
              " 카드에 없다\"* 는 뜻이므로 라벨을 지우는 쪽이 고치는 방향이다.")
        problems += 1
    elif have_axis or strength_any:
        print("카드 라벨이 말한 칸과 그 카드의 ID 가 전부 맞는다"
              f" — 강도 축 {'켜짐' if strength_any else '꺼짐'}.")

    # ── ④-g 「워크숍 안」 라벨 ↔ 단계 배정 (it.17 신설) ────────────────────
    # `aidlc == prep` 은 **앞 단계에서만 닫힌다**는 뜻이므로 「워크숍 안에서 답이 나온다」와
    # 양립하지 않는다. 확인 요청을 안/밖으로 가르는 자리가 그 배정을 어긴다.
    # 실측 과녁 — it.15 `plandetail:2964` 가 확인 요청 1·2·3 을 *"워크숍 안에서도 답이 나올
    # 수 있고"* 로 묶었고 그 카드들이 매단 `C70`·`C79`·`C93` 이 전부 `prep` 이다. 같은 산출물
    # 파트 4 #02 는 `prep` 22건을 *"착수 후에는 닫힐 수 없다"* 고 적는다 — 채점자가 **논리
    # 모순**으로 센 자리이고 이 검사가 셋을 정확히 낸다. 오탐: 다른 산출물 여섯에서 0건.
    #
    # **「안」 방향만 잰다.** 역방향(「밖」인데 `prep` 이 아니다)은 축이 다르다 — 「밖에서 와야
    # 한다」는 회신·실물을 받아 온다는 뜻(`closes`)이고 그 설계를 워크숍 안에서 하는 것과
    # 양립한다. 실측에서 역방향 5건이 나왔고 채점자는 하나도 결함으로 세지 않았다.
    # 판정을 양방향으로 만드는 원칙은 **같은 축의 두 끝**일 때만 적용된다.
    CARD_BLK = re.compile(r'<div class="card[^"]*">(.*?)</div>\s*</div>', re.S)
    CT_DIV = re.compile(r'<div class="ct">(.*?)</div>', re.S)
    CM_DIV = re.compile(r'<div class="cm">(.*?)</div>', re.S)
    whole = "\n".join(lines)
    numbered_cards = {}
    for m in CARD_BLK.finditer(whole):
        ct_, cm_ = CT_DIV.search(m.group(0)), CM_DIV.search(m.group(0))
        if not ct_ or not cm_:
            continue
        mnum = re.match(r"\s*(\d{1,2})\s*·", strip_tags(ct_.group(1)).strip())
        if mnum:
            # `sid` 는 그룹이 둘(`(C)(70)`)이라 `findall` 이 튜플을 낸다 — `group(0)` 를 쓴다.
            # 튜플을 그대로 쓰면 ID 가 하나도 안 맞아 이 축이 조용히 0건이 된다.
            numbered_cards[int(mnum.group(1))] = [
                m_.group(0) for m_ in sid.finditer(strip_tags(cm_.group(1)))]
    aidlc_of = {s.get("id"): s.get("aidlc") for s in surfaces}
    flat = re.sub(r"\s+", " ", strip_tags(whole))
    IN_WS = re.compile(r"([\d·,\s~\-–]{1,40})(?:은|는|이|가)?\s*워크숍\s*안")
    # **같은 문장까지만** 근거 ID 를 읽는다 — 창을 글자 수로 잡으면 뒷 문장의 ID 를 끌어와
    # 과녁이 조용히 사라진다(실측: 160자 창에서 과녁 3건이 0건이 됐다).
    SENT_END = re.compile(r"(?:다|음)\s*[.。]|[.。]\s")
    ws_bad = []
    for m in IN_WS.finditer(flat):
        span = m.group(1)
        picked = set()
        for mr in re.finditer(r"(\d{1,2})\s*[~\-–]\s*(\d{1,2})", span):
            a_, b_ = int(mr.group(1)), int(mr.group(2))
            if a_ <= b_ and b_ - a_ < 30:
                picked |= set(range(a_, b_ + 1))
        picked |= {int(x) for x in re.findall(r"(?<!\d)(\d{1,2})(?!\d)", span)}
        if not picked:
            continue
        rest = flat[m.end():m.end() + 400]
        e_ = SENT_END.search(rest)
        # 그 자리가 근거 ID 를 **스스로 밝혔으면** 그것만 본다. 카드 ID 전량을 보면 카드가
        # 여러 Contract 를 매단 자리에서 전부 걸린다(실측: 오탐 10/13).
        named = {m_.group(0) for m_ in sid.finditer(rest[:e_.start()] if e_ else rest)}
        for n_ in sorted(picked):
            ids_ = numbered_cards.get(n_, [])
            if named:
                ids_ = [c for c in ids_ if c in named]
            for cid_ in ids_:
                if aidlc_of.get(cid_) == "prep":
                    ws_bad.append((n_, cid_))
    if numbered_cards:
        print("\n## 「워크숍 안」 라벨 ↔ 단계 배정\n")
        if ws_bad:
            print("**「워크숍 안에서 답이 나온다」고 묶은 자리가 `prep` 인 Contract 를 매달고"
                  " 있다.** `prep` 은 앞 단계에서만 닫힌다는 뜻이므로 두 말이 양립하지 않는다.\n")
            print("| 확인 요청 | Contract | 정본 `aidlc` |")
            print("|---|---|---|")
            for n_, cid_ in ws_bad:
                print(f"| {n_} 번 | `{cid_}` | `prep` |")
            print("\n**둘 중 하나를 고친다** — 그 항목을 「밖에서 와야 한다」로 옮기거나,"
                  " 배정이 틀렸으면 정본 `aidlc` 를 고치고 그 수를 쓰는 자리를 함께 고친다.")
            problems += 1
        else:
            print(f"번호 붙은 확인 요청 {len(numbered_cards)}개의 안/밖 라벨이 배정과 맞는다.")
    else:
        print("\n## 「워크숍 안」 라벨 ↔ 단계 배정\n")
        print("⚠ **이 축은 꺼졌다 — 0건이 통과가 아니다.** 번호 붙은 확인 요청 카드"
              "(`<div class=\"ct\">N · …`)를 찾지 못해 「번호 → Contract」 대응을 만들 수 없다."
              " 안/밖을 가르는 서술이 있으면 **눈으로** 그 항목의 `aidlc` 를 대 본다 —"
              " `prep` 인 것이 「안」에 들어가 있으면 어긋남이다.")

    # ── ④-h 축을 어긴 서술 세 형태 (it.18 신설) ────────────────────────────
    # **네 판 연속 파생 수치 결함이 이 축이다** — 총계·부분합·차집합은 정본과 전수 일치하고
    # (it.17 실측: 도해 12수치 · Layer 관여 12칸 · 카드 24수치 · 인접 행렬 12칸 전부 일치)
    # **수를 쓰는 문장이 축을 어긴다.** it.16 은 자리 수를 줄여 봤고(절 20 → 18) 이 축은
    # 오히려 3 → 5 로 늘었다 → 자리 수가 아니라 서술 형태로 잡는다.
    #
    # 세 형태를 함께 본다. **과녁의 표기 하나에 맞추지 않기 위해서다** — it.17 의 ⑦ 이 과녁
    # 하나(파일 이름이 백틱 안)에 맞춰져 다음 판의 같은 유형(문장 단위)을 놓쳤다.
    #   ⓐ 라벨 → 수: *"Layer 3 inception 2건"* (정본 교차 4)
    #   ⓑ 수 → 라벨: *"3건 — Layer 3 전량"* (정본 9). **순서가 반대라 ⓐ 로는 안 걸린다**
    #   ⓒ 모집단 → 부분: *"회신 필요 30건 중 29건은 … ideation·inception"* (정본 20+7=27)
    print("\n## 축을 어긴 서술 — 교차 부분합 · 「전량」 · 라벨 열거\n")
    AX_LABEL = {}      # 본문 라벨 → (필드, 정본값, 그 값의 개수)
    for field, table in (("closes", CLOSES_LABEL), ("status", STATUS_LABEL),
                         ("aidlc", {"prep": "사전 준비", "ideation": "ideation",
                                    "inception": "inception",
                                    "construction": "construction"})):
        cnt = Counter(str(s.get(field) or "").strip() for s in surfaces)
        for val, label in table.items():
            if cnt.get(val):
                AX_LABEL[label] = (field, val, cnt[val])
    lay_cnt_all = Counter(str(s.get("layer")).strip() for s in surfaces
                          if str(s.get("layer") or "").strip())
    for key, n in lay_cnt_all.items():
        mnum = re.match(r"(\d{1,2})", key)
        if mnum:
            # 과거 산출물은 「층 N」으로 적혀 있다 — 한쪽만 받으면 그 축이 조용히 죽는다
            AX_LABEL[f"Layer {mnum.group(1)}"] = ("layer", key, n)
            AX_LABEL[f"층 {mnum.group(1)}"] = ("layer", key, n)
    STAGE_WORD = {"사전 준비": "prep", "착수 전": "prep", "ideation": "ideation",
                  "inception": "inception", "construction": "construction",
                  "이월": "construction"}
    cross = Counter((str(s.get("layer")).strip(), str(s.get("aidlc") or "").strip())
                    for s in surfaces)
    cl_cross = Counter((str(s.get("closes") or "").strip(),
                        str(s.get("aidlc") or "").strip()) for s in surfaces)
    # 모집단이 0 이면 「꺼졌다」를 찍는다 — 확정 사실 *"꺼질 때 스스로 밝히는 축은 0건이
    # 안전으로 읽히지 않는다"*. ⓒ 는 실측에서 16 산출물에 3자리뿐이라 특히 그렇다.
    pop_a = pop_b = pop_c = 0
    axis_bad = []
    QUAL = re.compile(r"(중|가운데|그중|나머지|안에서|밖|남[는은])")
    for i, t in enumerate(text_lines, 1):
        t = " ".join(t.split())
        # ⓐ 「Layer N … 단계낱말 … M건」. 창을 짧게 잡는다 — 뒷 문장을 끌어오면 과녁이 사라진다
        for word, stage in STAGE_WORD.items():
            for m in re.finditer(rf"(?:Layer|층)\s*(\d{{1,2}})[^0-9]{{0,20}}?"
                                 rf"{re.escape(word)}[^0-9]{{0,10}}?(\d{{1,3}})\s*(?:개|건)", t):
                key = next((k for k in cross if k[0].startswith(m.group(1))), None)
                if key is None:
                    continue
                pop_a += 1
                want = cross.get((key[0], stage), 0)
                got = int(m.group(2))
                frag = t[max(0, m.start() - 30):m.end() + 18]
                if got != want and not QUAL.search(frag):
                    axis_bad.append((i, "ⓐ 교차", f"Layer {m.group(1)} × {stage}",
                                     want, got, frag))
        # ⓑ 「라벨 전량 M건」 / 「M건 … 라벨 전량」 — **「전량」은 부분합일 수 없다**
        for label, (field, val, want) in AX_LABEL.items():
            for m in re.finditer(rf"{re.escape(label)}\s*(?:의\s*)?(?:전량|전부|모두)"
                                 rf"[^.。]{{0,25}}?(\d{{1,3}})\s*(?:개|건)", t):
                pop_b += 1
                if int(m.group(1)) != want:
                    axis_bad.append((i, "ⓑ 전량", f"{label}({field})", want,
                                     int(m.group(1)),
                                     t[max(0, m.start() - 25):m.end() + 12]))
            for m in re.finditer(rf"(\d{{1,3}})\s*(?:개|건)[^.。]{{0,25}}?"
                                 rf"{re.escape(label)}\s*(?:전량|전부|모두)", t):
                pop_b += 1
                if int(m.group(1)) != want:
                    axis_bad.append((i, "ⓑ 전량", f"{label}({field})", want,
                                     int(m.group(1)),
                                     t[max(0, m.start() - 25):m.end() + 12]))
    # ⓒ 는 문장이 행을 넘어가므로 본문 전체를 이어 붙여 본다. **절 경계까지만** 단계 낱말을
    # 읽는다 — 「… 이고 C30 하나만 착수 전이다」의 뒷절을 끌어오면 오탐이 된다(실측 2건).
    flat_all = " ".join(" ".join(x.split()) for x in text_lines)
    CLAUSE = re.compile(r"(?:이고|이며|지만|인데|이다|고,)")
    for m in re.finditer(r"([가-힣 ]{3,8}(?:없음|필요))\s*(\d{1,3})\s*건\s*중\s*"
                         r"(\d{1,3})\s*건[^.。]{0,80}", flat_all):
        label = m.group(1).strip()
        if label not in CLOSES_LABEL.values():
            continue
        val = next(k for k, v in CLOSES_LABEL.items() if v == label)
        seg = m.group(0)
        cut = CLAUSE.search(seg, seg.find("건 중") + 3)
        seg = seg[:cut.start()] if cut else seg
        stages = {STAGE_WORD[w] for w in STAGE_WORD if w in seg}
        if not stages:
            continue
        pop_c += 1
        want = sum(v for (c_, s_), v in cl_cross.items() if c_ == val and s_ in stages)
        got = int(m.group(3))
        if got != want:
            axis_bad.append((0, "ⓒ 라벨 열거",
                             f"{label} × {'·'.join(sorted(stages))}", want, got, seg[:90]))
    print(f"모집단 — ⓐ 교차 서술 {pop_a} · ⓑ「전량」 {pop_b} · ⓒ 라벨 열거 {pop_c}")
    for tag_, n_ in (("ⓐ", pop_a), ("ⓑ", pop_b), ("ⓒ", pop_c)):
        if not n_:
            print(f"⚠ **{tag_} 는 꺼졌다 — 0건이 통과가 아니다.** 그 형태의 서술이 없다."
                  " 축 라벨과 수가 한 문장에 있는 자리를 **눈으로** 대 본다")
    if axis_bad:
        print("\n| 행 | 형태 | 축 | 정본 | 본문 | 자리 |")
        print("|---|---|---|---|---|---|")
        for i, kind, ax, want, got, frag in axis_bad[:(CAP or 20)]:
            print(f"| {i or '—'} | {kind} | {ax} | {want} | **{got}** | {frag[:46]} |")
        if len(axis_bad) > 20 and not args.full:
            print(f"\n⚠ **판정하지 않은 {len(axis_bad) - 20}건이 남아 있다** — 위 20건만 찍었다. 전량은 `--full` 로 본다")
        print("\n**수는 정본에 있고 문장이 축을 어겼다.** 셋 다 수 대조로는 통과하는 유형이다 —"
              " ⓐ 는 **모집단 한정어**를 붙이고(*\"Layer 2 inception 15건 중 12건\"*),"
              " ⓑ 는 「전량」을 지우거나 그 축의 전체 수로 바꾸고,"
              " ⓒ 는 **빠진 칸을 라벨에 담는다**(*\"… ideation·inception 이고 이월 2건\"*).")
        problems += 1
    elif pop_a or pop_b or pop_c:
        print("교차 부분합 · 「전량」 주장 · 라벨 열거가 정본과 맞는다.")

    # ── ④-i 파트 3 #04 「판정」 열 ↔ 그 행 Contract 의 정본 (it.18 신설) ──────
    # **원인이 골격이었다.** `assets/assessment-base.html` 이 이 표를 *"판정은 셋이다 …
    # 축 정의는 §1 의 세 축 지도에 있고"* 로 주면서 「원문 항목」의 판정을 요구했다. 그래서
    # 한 산출물은 아홉 행을 정본에 맞추고 세 행을 원문 항목 기준으로 적었고(it.17 `qms`
    # :1797·:1845·:1852 — 채점자가 파생 수치로 셌다), 다른 산출물은 Contract 열을 「관련
    # Contract」로 써서 그 행 질문과 다른 Contract 를 매달았다. **한 라벨이 두 대상에 붙는
    # 중의성**이고, 골격에 ①Contract 열의 뜻 ②「가장 늦게 닫히는 것」을 못 박았다.
    #
    # **행에 Contract 가 여럿이면 가장 늦게 닫히는 것을 쓴다**(실물 > 회신 > 없음). 이 규칙이
    # 오탐을 실측으로 지웠다 — 규칙 없이 행 안 ID 를 전부 대조하면 한 산출물이 10행으로
    # 걸리는데(채점자는 그 축 0건) 규칙을 넣으면 3행이고 **과녁 셋은 그대로 걸린다.**
    print("\n## 파트 3 #04 「판정」 열 ↔ 그 행 Contract 의 정본\n")
    CLOSES_RANK = {"paper": 0, "reply": 1, "artifact": 2}
    LABEL_TO_CLOSES = {v: k for k, v in CLOSES_LABEL.items()}
    ID_ONLY = re.compile(r"^(?:C\d+[\s·,+]*)+$")
    by_id_all = {str(c.get("id", "")).strip(): c for c in surfaces}
    jd_pop, jd_bad = 0, []
    for m in re.finditer(r"<tr>(.*?)</tr>", whole, re.S):
        row = m.group(1)
        line = whole.count("\n", 0, m.start()) + 1
        cells = [" ".join(strip_tags(c.group(1)).split()) for c in CELL.finditer(row)]
        # ID 칸은 **ID 만 든 셀**이다. 근거 칸이 다른 Contract 를 언급하는 자리를 끌어오면
        # 오탐 기계가 된다(실측: 근거 칸까지 세면 한 산출물이 16행).
        ids = [x for c in cells if ID_ONLY.match(c) for x in re.findall(r"C\d+", c)]
        labels = [c for c in cells if c in LABEL_TO_CLOSES]
        if not ids or len(labels) != 1:
            continue
        vals = [str(by_id_all[i].get("closes") or "").strip() for i in ids
                if i in by_id_all and str(by_id_all[i].get("closes") or "").strip()]
        if not vals:
            continue
        jd_pop += 1
        want = max(vals, key=lambda v: CLOSES_RANK.get(v, 0))
        if LABEL_TO_CLOSES[labels[0]] != want:
            jd_bad.append((line, labels[0], want,
                           ", ".join(f"{i}={by_id_all[i].get('closes')}"
                                     for i in ids if i in by_id_all)))
    if not jd_pop:
        print("⚠ **이 축은 꺼졌다 — 0건이 통과가 아니다.** 판정 라벨 칸과 ID 칸이 같은 행에"
              " 있는 표를 찾지 못했다. 파트 3 #04 표가 **원문 항목 | 판정 | 근거 | Contract**"
              " 네 열인지 보고, 아니면 그 표의 판정을 **눈으로** 정본 `closes` 와 대 본다")
    elif jd_bad:
        print(f"모집단 {jd_pop}행 중 **{len(jd_bad)}행**이 어긋났다.\n")
        print("| 행 | 표의 판정 | 정본으로는 | 그 행의 Contract |")
        print("|---|---|---|---|")
        for line, label, want, detail in jd_bad[:(CAP or 20)]:
            print(f"| {line} | 「{label}」 | `{want}`({CLOSES_LABEL[want]}) | {detail} |")
        if len(jd_bad) > 20 and not args.full:
            print(f"\n⚠ **판정하지 않은 {len(jd_bad) - 20}건이 남아 있다** — 위 20건만 찍었다. 전량은 `--full` 로 본다")
        print("\n**이 열은 그 행 Contract 의 `closes` 정본을 쓴다.** 행에 여럿이면 가장 늦게"
              " 닫히는 것이다(실물 > 회신 > 없음). 라벨이 옳게 느껴지면 **정본 `closes` 가"
              " 틀린 것**이니 그쪽을 고치고 그 수를 쓰는 자리를 함께 고친다 — 표에서만 갈라"
              " 적으면 파트 4 #02 의 개수와 어긋난다.")
        problems += 1
    else:
        print(f"판정 라벨이 있는 {jd_pop}행이 전부 그 행 Contract 의 정본과 맞는다.")

    # ── ⑤-b 인접 쌍 — *"01 ↔ RE06 10개"* ─────────────────────────────────
    # 표면을 늦게 추가하면 쌍별 수가 전부 흔들린다. 한 산출물이 손으로 추가한 다섯 표면
    # **이전 값으로 19쌍이 굳었고** `matrix.md` 에는 옳은 값이 있었다. 도구가 옳고 본문이 틀렸다.
    print("\n## 인접 쌍 — 갈래 A ↔ B 의 개수\n")
    pair_want = Counter()
    for s in surfaces:
        ps = sorted(set(p for p in s.get("parties", []) if p) - policy)
        for i in range(len(ps)):
            for j in range(i + 1, len(ps)):
                pair_want[(ps[i], ps[j])] += 1
    known_party = set(involve)
    # it.19 사거리 수선 — it.18 실측: 정규식이 `A ↔ B 조사? N개` 뿐이라 본문 `↔` 개수 주장
    # **4자리 중 1자리만 해석**했다(「경계」 같은 개재 낱말이 목록에 없고 `건` 단위를 안 봤다).
    # 그리고 **모집단을 세지 않아** *"인접 쌍 1개가 정본과 같다"* 로 통과했다 — 놓친 자리
    # (*"경계 27개 전부"*, 정본 33)는 에디터가 손으로 찾았다. 확정 사실 *"커버리지를 세어
    # 대조하지 않으면 사거리가 조용히 줄어든다"* 의 다섯째 계열이라, 이제 `↔` 뒤에 개수가
    # 붙은 자리를 독립적으로 세어 해석 수와 대조한다.
    PAIR = re.compile(r"([A-Za-z0-9가-힣_·\-]{1,20})\s*↔\s*([A-Za-z0-9가-힣_·\-]{1,20})")
    # 실측으로 넓힌 자리 — `—` 구분자(*"01 ↔ RE03 — 34개"*)와 조사 「도」(*"02 ↔ RE03 도 2개"*)
    # 가 it.17 산출물에 있었다. 미해석으로 남기지 않고 창에 넣는다.
    ADJ_TAIL = re.compile(r"^\s*(?:의|와의|과의)?\s*(?:경계|쌍|접점|공유|Contract)?\s*"
                          r"(?:의|가|는|은|이|도|만)?\s*[—–\-]?\s*(\d{1,3})\s*(?:개|건)")
    adj_bad, adj_seen, adj_pop, adj_miss = [], 0, 0, []
    for i, t in enumerate(text_lines, 1):
        for m in PAIR.finditer(t):
            a, b = m.group(1).strip(), m.group(2).strip()
            if a not in known_party or b not in known_party:
                continue
            # 모집단: 쌍 바로 뒤 24자 안에 `N개`·`N건` 이 오는 자리
            if not re.search(r"\d{1,3}\s*(?:개|건)", t[m.end():m.end() + 24]):
                continue
            adj_pop += 1
            mt = ADJ_TAIL.match(t[m.end():])
            if not mt:
                adj_miss.append((i, f"{a} ↔ {b}",
                                 t[m.end():m.end() + 30].strip()))
                continue
            adj_seen += 1
            got = int(mt.group(1))
            want = pair_want.get(tuple(sorted((a, b))), 0)
            if got != want:
                adj_bad.append((i, f"{a} ↔ {b}", want, got))
    if adj_pop:
        print(f"본문의 `↔` 개수 주장 자리 **{adj_pop}** · 해석 **{adj_seen}**.\n")
    if adj_bad:
        print("| 행 | 쌍 | 정본 | 본문 |")
        print("|---|---|---|---|")
        for i, pair, want, got in adj_bad[:(CAP or 25)]:
            print(f"| {i} | {pair} | {want} | **{got}** |")
        print("\n**`contracts.json` 의 `parties` 로 다시 센 값이 정본이다.**"
              " `matrix.md` 에 옳은 값이 있는데 본문만 옛 값인 자리가 있었다.")
        problems += 1
    elif adj_seen and not adj_miss:
        print(f"서술형 인접 쌍 {adj_seen}개가 정본과 같다.")
    elif not adj_pop:
        print("`A ↔ B N개` 형태의 서술이 없다 — 표 안의 행렬은 이 축이 보지 못한다"
              "(아래 \"검사하지 않은 축\").")
    if adj_miss:
        # **「판정하지 않은 N건」 문구를 쓰지 않는다** — 그 문구는 접힌 목록에 예약돼 있고
        # `--full` 로 사라져야 한다(it.17 에 열두 자리를 통일했다). 이것은 접힘이 아니라
        # **형태 해석 실패**라 `--full` 로도 남는다. 두 신호를 섞으면 회귀 기준이 깨진다.
        print(f"\n⚠ **해석하지 못한 {len(adj_miss)}건** — `↔` 뒤에 개수가 오는데 형태를"
              " 해석하지 못했다(접힌 것이 아니라 창 밖이라 `--full` 로도 남는다)."
              " **그 자리는 손으로 `parties` 재계산과 대 본다** — 해석 실패 ≠ 맞는 값.")
        for i, pair, frag in adj_miss[:(CAP or 10)]:
            print(f"- `:{i}` {pair} … {frag}")

    # ── ⑭ 모집단 정본 — `counts` 등록 대조 (it.19 신설) ────────────────────
    # it.18 실측: 파생 수치 11건 중 6건이 **수를 세는 모집단이 문장마다 다른** 형태였다
    # (*"다섯이 M1 안"* ↔ 정본 `parties=[M1]` 은 넷 · *"그 14건으로 구간 3 을 줄인다"* ↔
    # 14 가 세 구간에 흩어짐). 「라벨 + 수」 형태 창(⑩)은 이 자리를 **구조적으로 못 본다** —
    # 표기를 늘려도 형태 안에서만 넓어진다. 그 계열은 기각됐다(`prescription_kill_rule`).
    # 처방은 창이 아니라 정본이다 — **정본 분포에 없는 수를 본문에 쓰려면 `counts` 에
    # 필터·ID 목록째 등록**하고(SKILL.md 2·7단계), 여기서 재계산해 대조한다.
    print("\n## 모집단 정본 — `counts` 등록 대조\n")
    CNT_SCALARS = ("status", "layer", "aidlc", "closes", "gap_kind", "strength")
    id_set = {str(s_.get("id", "")).strip() for s_ in surfaces}

    def cnt_members(flt):
        """필터를 정본에 적용해 ID 목록을 돌려준다. 모르는 키면 None(대조 불가)."""
        out = []
        for s_ in surfaces:
            hit = True
            for k, v in flt.items():
                if k == "parties":
                    hit = sorted(set(s_.get("parties", []))) == sorted(set(v))
                elif k == "parties_has":
                    need = v if isinstance(v, list) else [v]
                    hit = all(p in s_.get("parties", []) for p in need)
                elif k in CNT_SCALARS:
                    vals = v if isinstance(v, list) else [v]
                    hit = s_.get(k) in vals
                else:
                    return None
                if not hit:
                    break
            if hit:
                out.append(str(s_.get("id", "")).strip())
        return out

    if not counts_reg:
        # None(옛 배열 형태)과 [](등록 0건)을 가리지 않고 둘 다 꺼짐이다 — 등록이 없으면
        # 대조할 대상이 없다. 확정 사실 *"정본에 자리가 없는 축은 기계가 못 지킨다"*.
        print("⚠ **이 축은 꺼졌다 — 0건이 통과가 아니다.** 정본에 `counts` 등록이 없다"
              + ("(옛 배열 형태다)" if counts_reg is None else "(등록 0건)") + "."
              " 본문에 **정본 분포에 없는 수**(부분집합·교차·열거를 센 것)를 썼다면 그 문장마다"
              " 모집단(어느 필드의 어느 부분집합)을 손으로 댄다 — it.18 에서 이 형태가"
              " 파생 수치 6건이었다.")
    else:
        cnt_bad, cnt_enum, cnt_manual = [], [], []
        for e in counts_reg:
            label = str(e.get("label", "?"))[:40]
            val = e.get("value")
            flt, ids, items = e.get("filter"), e.get("ids"), e.get("items")
            uni = e.get("uniform")
            member = None
            if isinstance(flt, dict):
                member = cnt_members(flt)
                if member is None:
                    cnt_bad.append((label, val, "—",
                                    f"**필터에 모르는 키가 있다: {list(flt)}** — 재현할 수"
                                    " 없으므로 등록이 성립하지 않는다. 쓸 수 있는 키는"
                                    " status·layer·aidlc·closes·gap_kind·strength·"
                                    "parties·parties_has 다"))
                    continue
            # ids 는 실재하는 Contract 여야 한다
            if ids:
                ghost = [x for x in ids if str(x).strip() not in id_set]
                if ghost:
                    cnt_bad.append((label, val, "-",
                                    f"`ids` 에 정본에 없는 ID: {' · '.join(map(str, ghost))[:60]}"))
            # 값 ↔ 재계산
            if member is not None and isinstance(val, int) and val != len(member):
                cnt_bad.append((label, val, len(member),
                                f"필터 재계산과 다르다 — 실제: {' · '.join(member)[:80]}"))
            if member is None and ids and isinstance(val, int) and val != len(ids):
                cnt_bad.append((label, val, len(ids), "`ids` 개수와 다르다"))
            # ids ↔ 필터 — 열거와 필터를 함께 줬으면 **집합이 같아야** 한다.
            # 실측 과녁: *"이 여덟이 이월 4건과 사전 준비의 실체다"* — 여덟 ↔ 필터 12.
            if member is not None and ids:
                want_s, got_s = set(member), {str(x).strip() for x in ids}
                if want_s != got_s:
                    miss = " · ".join(sorted(want_s - got_s))[:60]
                    extra = " · ".join(sorted(got_s - want_s))[:60]
                    cnt_bad.append((label, len(got_s), len(want_s),
                                    (f"열거에 빠짐: {miss} " if miss else "")
                                    + (f"/ 열거에 넘침: {extra}" if extra else "")))
            # uniform — 본문이 「이 집합 전체가 이 축 값」이라고 주장할 때 등록한다.
            # 실측 과녁: *"그 14건으로 구간 3 을 줄인다"* — 14 의 layer 가 1×4·2×7·3×3.
            if isinstance(uni, dict):
                base = member if member is not None else \
                    [str(x).strip() for x in (ids or [])]
                by_id = {str(s_.get("id", "")).strip(): s_ for s_ in surfaces}
                for k, v in uni.items():
                    spread = Counter(str(by_id.get(x, {}).get(k)) for x in base)
                    if set(spread) - {str(v)}:
                        cnt_bad.append((label, f"{k}={v} 전체", dict(spread),
                                        "집합이 그 축 값을 공유하지 않는다 — 본문의"
                                        " 「전부/그 N건으로」 주장이 어긋난다"))
            # items — 정본 필드 밖의 열거(문서 유래). len 만 대조된다.
            if items is not None:
                if isinstance(val, int) and val != len(items):
                    cnt_bad.append((label, val, len(items), "`items` 개수와 다르다"))
                else:
                    cnt_enum.append(label)
            # **근거 필드를 하나 이상 붙이는 것이 필수다 — 「없음」은 어긋남이다**(it.20 ②).
            # it.19 실측: `plandetail` 등록 30 중 **7건이 근거 없이** 적혔고, 그중
            # `M1 ↔ M3 공유 = 68` 은 `parties_has: ["M1","M3"]` 로 재현하면 **정확히 68**
            # 이다 — **값은 맞고 검사가 확인할 수 없었다.** 같은 지시에 `qms` 는 「없음」 0 ·
            # `plandetail` 은 7 로 **두 해석이 나왔다.** 그래서 경고에서 어긋남으로 올린다.
            if flt is None and ids is None and items is None:
                cnt_bad.append((label, val, "—",
                                "**근거 필드가 없다** — 정본 필드로 재현되면 `filter`,"
                                " 문서 유래면 `items` 를 붙인다. `note` 만으로는 등록이"
                                " 아니다"))
        n_mech = len(counts_reg) - len(cnt_enum) - len(cnt_manual)
        print(f"등록 **{len(counts_reg)}** — 기계 대조 {n_mech} · 열거만 {len(cnt_enum)}"
              f" · 대조 불가 {len(cnt_manual)}.\n")
        if cnt_bad:
            print("| 등록 | 등록값 | 재계산 | 무엇이 다른가 |")
            print("|---|---|---|---|")
            for label, got, want, why in cnt_bad[:(CAP or 20)]:
                print(f"| {label} | **{got}** | {want} | {why} |")
            if len(cnt_bad) > 20 and not args.full:
                print(f"\n⚠ **판정하지 않은 {len(cnt_bad) - 20}건이 남아 있다** — 전량은 `--full` 로 본다")
            print("\n**등록이 틀렸으면 본문의 그 문장도 틀렸다** — 등록을 고치고 그 수를 쓰는"
                  " 자리를 grep 해서 함께 고친다. 값은 머리로 더하지 않고 **재계산 쪽**을 쓴다.")
            problems += 1
        else:
            print("등록 전부가 정본 재계산과 맞는다.")
        if cnt_enum:
            print(f"\n⚠ **열거만 대조한 등록 {len(cnt_enum)}건** — {' · '.join(cnt_enum)}."
                  " `items` 는 정본 필드 밖(문서 유래)이라 **개수만** 봤다. 원소가 그 라벨에"
                  " 맞는지(예: 컬럼 12 안에 필드가 아닌 것이 섞였는지)는 눈으로 본다.")
        if cnt_manual:
            print(f"\n⚠ **대조하지 못한 등록 {len(cnt_manual)}건** — 항목마다 본다:")
            for label, why in cnt_manual:
                print(f"- {label}: {why}")

    # ── ⑭-b 등록의 **사거리** — 본문이 센 자리를 세어 설명되는지 본다 (it.20 ②ⓒ)
    # it.19 실측: 정본에 자리를 만들었고 두 집합이 등록 37·30 을 채워 **어긋남 0** 인데
    # **등록되지 않은 문장은 이 축이 못 본다** — `qms` 22자리 · `plandetail` 55자리가 등록
    # 없이 쓰였고 그중 **파생 결함 3건**이 났다. 확정 사실 *"정본에 자리를 만드는 것과
    # 채우게 하는 것은 다르다"*.
    #
    # **이것은 판정이 아니라 커버리지다.** 형태로 창을 잡아 어긋남을 내는 계열은
    # `prescription_kill_rule` 로 닫혀 있으므로 **모집단을 세고 설명되지 않는 자리만 손에
    # 넘긴다**(it.17 확정 사실 *"모집단을 독립적으로 세어 처리한 수와 대조한다"*).
    # 통과를 바꾸지 않는다.
    print("\n## 등록의 사거리 — 본문이 센 자리 ↔ 정본 분포·등록\n")
    # 단위에 **문서 원소**(항목·컬럼·필드…)를 함께 넣는다 — 그것이 `items` 등록의 대상이고
    # it.19 확정 사실이 이름 붙인 형태다(*"필드 13개에 컬럼 12개" ↔ 필드 컬럼은 10*).
    # 실측으로 이 넷만 쓰면 모집단이 61 이고 여섯을 쓰면 101 인데, 늘어난 자리가 전부
    # *"정책 10항목 중 다섯"* 계열(등록해야 하는 자리)이었다.
    SUB_UNIT = r"(?:개|건|곳|항목|항|종|가지|벌|쌍|컬럼|필드|열|행)"
    SUBSET_PATS = (
        (rf"(\d{{1,3}})\s*{SUB_UNIT}\s*중", "N 중"),
        (rf"(?:그|이)\s+(\d{{1,3}})\s*{SUB_UNIT}", "그 N건"),
        (rf"나머지\s*(?:(\d{{1,3}})\s*{SUB_UNIT}?|({CARD_ALT}))", "나머지"),
        (rf"(?<![가-힣])({CARD_ALT})(?:이|가)\s", "수사 + 조사"),
        (rf"(?<![가-힣0-9])(\d{{1,3}})\s*(?:항목|항|종|가지|컬럼|필드)(?![가-힣])",
         "문서 원소"),
        (rf"(?<![가-힣])({CARD_ALT}|{DET_ALT})\s+[가-힣A-Za-z][가-힣A-Za-z ]{{0,18}}"
         rf"(?:전부|전량|모두)", "수사 + 전부"),
    )
    # 「설명된다」의 뜻 — 정본 총계·축별 개수·층×단계 교차 중 하나이거나 `counts` 등록값이다.
    # **값으로 맞추므로 우연히 설명되는 자리가 있다**(작은 수가 다른 축의 값과 맞물린다).
    # 그래서 남는 수가 0 이어도 통과가 아니다 — 아래 문구에 그것을 적는다.
    known_vals = {len(surfaces)}
    for f_ in ("status", "layer", "aidlc", "closes", "gap_kind", "strength"):
        known_vals |= set(Counter(str(x.get(f_) or "") for x in surfaces).values())
    known_vals |= set(cross_c.values()) if "cross_c" in dir() else set()
    known_vals |= {e.get("value") for e in (counts_reg or [])
                   if isinstance(e.get("value"), int)}
    pop_reg, unexplained = 0, []
    for i, t in enumerate(text_lines, 1):
        for pat, kind in SUBSET_PATS:
            for m in re.finditer(pat, t):
                g = [x for x in m.groups() if x]
                if not g:
                    continue
                v = int(g[0]) if g[0].isdigit() else HANGUL_NUM.get(g[0])
                pop_reg += 1
                if v is not None and v not in known_vals:
                    unexplained.append((i, kind, v,
                                        " ".join(t.split())[max(0, m.start() - 30):
                                                            m.start() + 40].strip()))
    print(f"모집단 **{pop_reg}자리** · 정본 분포나 등록으로 설명되는 것"
          f" {pop_reg - len(unexplained)} · **남는 것 {len(unexplained)}**"
          f" (등록 {len(counts_reg or [])}).")
    if counts_reg is None:
        # 옛 배열 형태에는 등록이 아예 없어 「남는 것」이 모집단의 절반을 넘는다 —
        # 목록을 쏟으면 정보가 아니다. 위 절과 같이 **꺼졌다**로 적는다.
        print("\n⚠ **이 축은 꺼졌다 — 정본이 옛 배열 형태라 등록이 없다.**"
              " 위 수는 참고값이고 자리 목록은 찍지 않는다.")
    elif unexplained:
        print("\n| 행 | 형태 | 값 | 자리 |")
        print("|---|---|---|---|")
        for i, kind, v, frag in unexplained[:(CAP or 25)]:
            print(f"| {i} | {kind} | {v} | {frag[:60]} |")
        if len(unexplained) > 25 and not args.full:
            # **문구를 예약과 맞춘다.** 「해석하지 못한 N건」은 인접 쌍(⑤-b)의 미해석에,
            # 「판정하지 않은 N건」은 **접힘**에 예약돼 있다. 이 목록은 접힌 것이고
            # `--full` 로 사라져야 하므로 뒤엣것을 쓴다 — 앞엣것을 쓰면 ⑤-b 의 회귀
            # 기준(it.18 `plandetail` 모집단 4 · 해석 4)이 이 절의 수와 섞인다.
            print(f"\n⚠ **판정하지 않은 {len(unexplained) - 25}건이 남아 있다**"
                  " — 위 25건만 찍었다. 전량은 `--full` 로 본다")
        print("\n⚠ **자리마다 `counts` 에 등록하거나, 정본 분포의 어느 값인지 적는다.**"
              " 이 목록은 어긋남이 아니라 **사거리**다 — 등록되지 않은 수는 위 대조가"
              " 보지 못한다.")
    else:
        print("\n남는 자리가 없다. **다만 값으로 맞추므로 0 이 통과가 아니다** —"
              " 작은 수는 다른 축의 값과 우연히 맞물린다.")

    # ── ⑤-c 정본 근거의 **식별자**가 본문에 있는가 ─────────────────────────
    # 정본은 고쳤고 HTML 이 안 받은 자리가 두 산출물에서 났고, 한 건은 **검토자 발견이 그대로
    # 되돌려졌다**(정본 cites 넷 중 하나가 본문에 없어 표면의 대상이 좁아졌다).
    # 인용 문장 전체로 대조하면 마크다운 표기 차이로 거의 다 걸린다 — **식별자만** 본다.
    # 코드 토큰·요건 ID 는 표기가 바뀌지 않으므로 없으면 진짜 누락이다.
    print("\n## 정본 근거의 식별자가 본문에 있는가\n")
    TOKEN = re.compile(r"`([A-Za-z_][\w.\-/]{5,40})`"          # 백틱 안의 코드
                       r"|\b([A-Z]{2,}[-_][A-Z0-9]{2,}(?:[-_][A-Z0-9]+)*)\b"  # FR-M5-04 계열
                       r"|\b([a-z][a-zA-Z]{4,}[A-Z][a-zA-Z]{2,})\b")          # camelCase
    body = " ".join(text_lines)
    tok_missing = []
    for s_ in surfaces:
        seen = set()
        for c in s_.get("cites", []):
            for m in TOKEN.finditer(str(c)):
                tok = next(g for g in m.groups() if g)
                if tok in seen or tok in body:
                    continue
                seen.add(tok)
                tok_missing.append((s_.get("id"), tok))
    if tok_missing:
        print("**아래 식별자가 `contracts.json` 의 근거에는 있고 본문에는 없다.**"
              " 정본만 고치고 HTML 을 안 고친 자리다 — 검토 반영에서 가장 자주 난다.\n")
        print("| Contract | 본문에 없는 식별자 |")
        print("|---|---|")
        for sid_, tok in tok_missing[:(CAP or 25)]:
            print(f"| {sid_} | `{tok}` |")
        if len(tok_missing) > 25 and not args.full:
            print(f"\n⚠ **판정하지 않은 {len(tok_missing) - 25}건이 남아 있다** — 위 25건만 찍었다. 전량은 `--full` 로 본다")
        print("\n**Contract 의 대상이 좁아졌는지 본다.** 근거에 있는 식별자가 본문에 없으면 그"
              " 표면이 원래 담던 것보다 적게 말하고 있다.")
        problems += 1
    else:
        print("정본 근거의 식별자가 전부 본문에서 확인된다.")

    # ── ⑤-d 근거의 출처 귀속 — 그 문서에 그 식별자가 있는가 (it.17 신설) ────
    # ⑤-c 는 「정본 → 본문」을 보고 이 축은 「정본 → **원문**」을 본다. 인용 자체는 정확한데
    # **어느 문서가 그렇게 적었는가**가 틀리는 자리가 있다.
    # 실측 과녁 — it.16 `plandetail` C103 의 note 가 *"PUB·RE05 가 기준 문서를
    # `02_기획전_파일_연관_분석.md` 로 부른다"* 고 적는데 그 이름은 PUB(03)에만 4회 있고
    # RE05 전문에 0회다. 채점자가 **인용 왜곡**으로 센 자리다.
    # 같은 검사가 그 판에서 두 건을 더 냈고(C6 `SB-PFM-SD-07000` 을 PPT 로 · C21
    # `TypeOneHalf`·`TypeThree` 를 RE05 로 귀속) 원문 대조 결과 **둘 다 진짜**다 —
    # 채점자도 놓친 자리다. 채택 검증: it.16 `qms` 0건(그 판 인용 결함 0과 일치) · 오탐 0.
    #
    # 약칭↔파일 매핑은 **산출물이 문서 표에 스스로 선언한 것**을 쓴다. 인자로 받지 않는
    # 이유는 런이 매핑을 틀리면 이 검사가 그대로 오탐 기계가 되기 때문이다.
    if args.docs_root:
        print("\n## 근거의 출처 귀속 — 그 문서에 그 식별자가 있는가\n")
        # 약칭 칸은 골격에 따라 `<b>` 이거나 `class="k"`·`class="m"` 다 — 한쪽만 받으면
        # 집합에 따라 조용히 0건이 된다(실측: `qms` 는 `class="k"` 라 매핑 0개였다).
        # **문자 클래스를 좁히면 사거리가 조용히 줄어든다.** 실측(it.17)에서 약칭이 `UI-M1`
        # 인 집합은 5개 중 2개만, `00`·`01`·`02`·`03` 을 쓰는 집합은 12개 중 7개만 해석됐다 —
        # 하이픈과 숫자 시작이 빠져 있었다. 산출물이 약칭을 자유롭게 정하므로 넓게 받고,
        # **아래에서 표의 행 수와 대조해** 그래도 못 읽은 행이 있으면 경고한다.
        FILE_EXT = r"\.(?:md|pdf|txt|csv)"
        ALIAS_ROW = re.compile(
            r"<td[^>]*>\s*(?:<b>)?([A-Za-z0-9][A-Za-z0-9_.\-가-힣]{0,14})(?:</b>)?\s*</td>\s*"
            r"<td[^>]*>\s*<code>([^<]+" + FILE_EXT + r")</code>")
        # 파일명을 담은 표 행의 수. 해석된 약칭 수와 어긋나면 **읽지 못한 행이 있다.**
        FILE_ROW = re.compile(r"<tr>(?:(?!</tr>).)*?<code>[^<]+" + FILE_EXT + r"</code>", re.S)
        BTICK = re.compile(r"`([^`]{4,80})`")
        # 부정 서술은 그 문서에 **없는 것이 요지**다 — 빼지 않으면 오탐 기계가 된다.
        NEG = re.compile(r"없|아니|0회|빠[졌지]|안\s|못\s|미[포함기]|누락|찾을 수|대신|"
                         r"반면|틀[렸리]|다르다|다른 이름|파일명")

        def nfc(s):
            import unicodedata
            return unicodedata.normalize("NFC", str(s))

        def qnorm(s):
            # 산출물이 인용 안에 넣은 이스케이프와 공백 폭을 지운다
            s = nfc(s).replace('\\"', '"').replace("\\'", "'")
            return re.sub(r"\s+", " ", s)

        amap = {}
        for m in ALIAS_ROW.finditer("\n".join(lines)):
            fn = nfc(m.group(2)).split("/")[-1]
            fn = fn.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
            amap.setdefault(m.group(1), fn)
        docs = {}
        for p in Path(args.docs_root).rglob("*.md"):
            docs[nfc(p.name)] = qnorm(p.read_text(encoding="utf-8", errors="replace"))
        solved = sum(1 for f in amap.values() if f in docs)
        # **문서 표는 파일명 행이 연속으로 붙어 있다.** 파일명은 뒤쪽 Contract 표에도 나오므로
        # 전부 세면 오탐이 된다(실측: 17행 중 12행만 문서 표였다). 간격으로 가른다 — 표 안은
        # 200자 안이고 표 밖으로 나가는 첫 점프가 3,580자였다.
        starts = [m.start() for m in FILE_ROW.finditer(whole)]
        rows = 0
        for k, st in enumerate(starts):
            if k and st - starts[k - 1] > 1000:
                break
            rows += 1
        print(f"문서 표의 약칭 {len(amap)}개 · 원문 {len(docs)}개 · **해석된 약칭 {solved}개**")
        # **행 수와 대조한다 — 이것이 근본 검사다.** 「파일을 못 찾은 약칭」은 *읽은* 약칭
        # 중에서만 세므로, 애초에 약칭 칸을 못 읽은 행은 그 경고에 걸리지 않는다. 실측(it.17)
        # 에서 두 집합 다 커버리지가 40%·58% 인데 **경고가 뜨지 않아 0건이 안전으로 읽혔다.**
        # 글자·패턴을 하나씩 더하는 방식은 `∪`·`└`·`ⓐ` 로 세 번 뚫렸다 — 세어서 대조한다.
        if rows > len(amap):
            print(f"\n⚠ **파일명을 담은 표 행이 {rows}개인데 약칭은 {len(amap)}개만 읽혔다** —"
                  f" {rows - len(amap)}행의 약칭 칸을 해석하지 못했다. **그 문서들은 이 축"
                  " 밖이고 0건이 통과가 아니다.** 약칭 칸이 `<td>약칭</td><td><code>파일명"
                  "</code></td>` 순서인지 본다")
        if amap and solved < len(amap):
            unresolved = sorted(a for a, f in amap.items() if f not in docs)
            print(f"\n⚠ 파일을 못 찾은 약칭: {', '.join(unresolved)}"
                  " — 그 약칭의 귀속은 **검사되지 않았다.** 문서 표의 파일명과 실제 파일명을"
                  " 맞추거나 `--docs-root` 를 고친다. **PDF 는 원문이 텍스트로 없으면 여기"
                  " 남는다** — 그 문서의 귀속은 눈으로 본다")
        if not amap:
            print("\n⚠ 문서 표에서 약칭↔파일명을 읽지 못했다 — **이 축은 꺼졌다.**"
                  " 0건이 통과가 아니다. 문서 표가 약칭 칸과 `<code>파일명</code>` 을"
                  " 나란히 두는지 본다")
        else:
            names = sorted(amap, key=len, reverse=True)
            # 숫자로만 된 약칭(`002`·`004`·`000A`)은 **하이픈·밑줄 옆에서도 끊는다** —
            # 그렇지 않으면 `REQ-ENTRY-004` 의 뒤 토막을 문서 약칭으로 읽어 그 뒤의
            # 식별자를 엉뚱한 문서에 귀속시킨다(it.24 실측: `C28` 의 `fetchPlanDetail`
            # 이 인용 앞머리 `002` 대신 `004` 로 잘렸다 — **런·에디터·채점자 셋이
            # 독립으로 같은 진단**을 냈다). 영문 약칭(`REQ`·`PUB`)에는 넓히지 않는다 —
            # `RE05`·`PUB-2` 처럼 하이픈을 낀 표기가 정상인 자리가 있다.
            NUMISH = re.compile(r"^[0-9]+[A-Za-z]?$")
            alts = []
            loose = [n for n in names if not NUMISH.match(n)]
            strict = [n for n in names if NUMISH.match(n)]
            if loose:
                alts.append(r"(?<![0-9A-Za-z])(?:"
                            + "|".join(re.escape(n) for n in loose)
                            + r")(?![0-9A-Za-z])")
            if strict:
                alts.append(r"(?<![0-9A-Za-z_\-])(?:"
                            + "|".join(re.escape(n) for n in strict)
                            + r")(?![0-9A-Za-z_\-])")
            NAME_RE = re.compile("(" + "|".join(alts) + ")")
            wrong = []
            for s_ in surfaces:
                blobs = [("note", s_.get("note") or "")]
                blobs += [(f"cites[{i}]", str(c))
                          for i, c in enumerate(s_.get("cites") or [])]
                for where, blob in blobs:
                    if not blob or NEG.search(blob):
                        continue
                    # 문서 이름이 나온 자리에서 잘라 **그 이름에만** 귀속시킨다.
                    # 곱집합으로 대조하면 한 인용이 여러 문서를 담는 자리에서 전부 걸린다
                    # (실측: 오탐 12/14 였다).
                    marks = [(m.start(), m.group(1)) for m in NAME_RE.finditer(blob)]
                    all_toks = [x.lower() for x in BTICK.findall(blob)]
                    for k, (pos, alias) in enumerate(marks):
                        end = marks[k + 1][0] if k + 1 < len(marks) else len(blob)
                        fn = amap.get(alias)
                        if not fn or fn not in docs:
                            continue
                        hay = docs[fn]
                        for tok in BTICK.findall(blob[pos:end]):
                            if tok.startswith("§"):
                                continue
                            t0 = qnorm(tok)
                            # 와일드카드는 접두로 찾는다 — `bg_coupon_el_*` ↔ `bg_coupon_el_230109`
                            if "*" in t0:
                                t0 = t0.split("*")[0]
                                if len(t0) < 4:
                                    continue
                            if t0 in hay:
                                continue
                            # 표기 차이를 **말하는** 문장은 한쪽에 없는 것이 요지다 —
                            # 같은 토큰의 대소문자 변형이 그 blob 에 둘이면 뺀다
                            if all_toks.count(tok.lower()) > 1:
                                continue
                            wrong.append((s_.get("id"), where, alias, fn, tok))
            if wrong:
                print("\n**아래 식별자가 그 근거가 지목한 문서에 없다.** 인용은 정확하고"
                      " **귀속이 틀린** 자리다 — 다른 문서에 있는지 확인하고 이름을 고친다.\n")
                print("| Contract | 자리 | 지목한 문서 | 없는 식별자 |")
                print("|---|---|---|---|")
                for sid_, where, alias, fn, tok in wrong[:(CAP or 25)]:
                    print(f"| {sid_} | `{where}` | {alias} (`{fn}`) | `{tok}` |")
                if len(wrong) > 25 and not args.full:
                    print(f"\n⚠ **판정하지 않은 {len(wrong) - 25}건이 남아 있다** — 위 25건만 찍었다. 전량은 `--full` 로 본다")
                print("\n**`grep` 으로 실제 자리를 찾아 이름을 고친다.** 귀속이 틀리면 그"
                      " Contract 가 「어느 문서와 합의해야 하는가」를 잘못 말한다 —"
                      " 참여 문서·Layer·확보 소스가 함께 어긋난다.")
                problems += 1
            elif solved:
                print("\n해석된 약칭의 근거가 전부 그 문서에서 확인된다.")

        # ── ⑤-e 절 수의 세는 기준 (it.18 신설) ─────────────────────────────
        # **라벨은 「절」인데 세는 기준이 「`## ` 로 시작하는 줄」이었다.** 실측(it.17): 한
        # 산출물이 *"최상위 절은 116개"* 로 적었고 그 값은 한 문서 §13 의 ```md 코드펜스 안에
        # 든 `## 1. 개요`~`## 5. 가정·제약` 다섯 줄을 절로 센 것이다(그 다섯은 변환 초안의
        # 본문이고 그 문서의 절이 아니다). 코드펜스를 빼면 111 이다. **이 값은 산출물이 「절
        # 단위로 전수 읽었다」고 주장하는 근거 수치**라 틀리면 그 주장이 흔들린다.
        # 검토자도 이 값을 「정본 파생 축 — 절 수 116/61」로 옳다고 확인해 주었다 →
        # *"검토자가 능동적 거짓 안심을 만든다"* 의 세 번째 표본이 될 자리다.
        # 채택 검증: 같은 판 다른 집합은 표지·요약·문서 표 5행·합계·부록이 **전수 일치**(0건).
        print("\n## 절 수의 세는 기준 — 코드펜스 밖 `## `\n")
        sec_top = sec_sub = 0
        per_doc = []
        for alias, fn in sorted(amap.items()):
            hit = next((p for p in Path(args.docs_root).rglob("*.md")
                        if nfc(p.name) == fn), None)
            if hit is None:
                continue
            t_, s_cnt, fence = 0, 0, False
            for ln in hit.read_text(encoding="utf-8", errors="replace").splitlines():
                if re.match(r"\s*```", ln):
                    fence = not fence
                    continue
                if fence:
                    continue
                if re.match(r"##\s", ln):
                    t_ += 1
                elif re.match(r"###\s", ln):
                    s_cnt += 1
            per_doc.append((alias, t_, s_cnt))
            sec_top += t_
            sec_sub += s_cnt
        skipped = [a for a, f in sorted(amap.items()) if f not in docs]
        if not per_doc:
            print("⚠ **이 축은 꺼졌다 — 0건이 통과가 아니다.** 문서 표에서 읽은 약칭에 대응하는"
                  " 마크다운 파일을 찾지 못했다")
        else:
            print("| 약칭 | 최상위(`## `) | 하위(`### `) |")
            print("|---|---|---|")
            for alias, t_, s_cnt in per_doc:
                print(f"| {alias} | {t_} | {s_cnt} |")
            print(f"| **합** | **{sec_top}** | **{sec_sub}** |")
            if skipped:
                print(f"\n⚠ 이 축 **밖**인 문서: {', '.join(skipped)} — PDF 등 마크다운이 아닌"
                      " 것은 세지 못한다. **그 문서의 절 수는 눈으로 세고, 합에 더한 값이면"
                      " 본문의 총계는 위 합보다 크다**(도구가 세지 못했다 ≠ 절이 없다)")
            # ① 문서 표의 **행별** 대조. 총계와 달리 이 축은 PDF 가 섞이지 않아 어긋남으로
            # 셀 수 있다. 실측 과녁이 바로 이 자리다 — 한 산출물의 `01` 행이 `19 / 35` 인데
            # 코드펜스 밖은 14 다.
            row_bad = []
            for alias, t_, _s in per_doc:
                fn = str(amap[alias])
                pat = re.compile(r"<tr>(?:(?!</tr>).)*?<code>[^<]*"
                                 + re.escape(fn) + r"</code>.*?</tr>", re.S)
                mrow = pat.search(whole)
                if not mrow:
                    continue
                nums = {int(x) for x in re.findall(r"(?<!\d)(\d{1,4})(?!\d)",
                                                   strip_tags(mrow.group(0)).replace(",", ""))}
                if t_ not in nums:
                    row_bad.append((whole.count("\n", 0, mrow.start()) + 1, alias, t_,
                                    ", ".join(str(n) for n in sorted(nums))[:40]))
            if row_bad:
                print("\n**문서 표의 행에 코드펜스 밖 실측값이 없다.**\n")
                print("| 행 | 약칭 | 코드펜스 밖 `## ` | 그 행의 수들 |")
                print("|---|---|---|---|")
                for line, alias, t_, nums in row_bad[:(CAP or 20)]:
                    print(f"| {line} | {alias} | **{t_}** | {nums} |")
                print("\n**절 수는 손으로 세지 않고 위 표에서 옮긴다.** 어긋나면 대개"
                      " **코드펜스 안의 `## `** 를 절로 센 것이다 — 그 줄들은 인용된 초안의"
                      " 본문이고 그 문서의 절이 아니다. 고칠 때 **표지·요약·부록의 같은 수를"
                      " 함께** 고친다.")
                problems += 1
            # ② 총계. **`skipped` 가 있으면 어긋남으로 세지 않는다** — 마크다운이 아닌 문서를
            # 못 세므로 「실측」이 총계가 아니다. 확정 사실 *"경고 문구는 사실로 옮겨진다"* 에
            # 걸리는 자리다(한 런이 *"번호 붙은 절 0개"* 를 본문에 적었다) → 뺄셈을 적어 준다.
            claims = []
            for i, t in enumerate(text_lines, 1):
                t = " ".join(t.split())
                for m in re.finditer(r"(최상위|하위)\s*절[^0-9]{0,6}(\d{1,3})", t):
                    claims.append((i, m.group(1), int(m.group(2)),
                                   t[max(0, m.start() - 24):m.end() + 12]))
                for m in re.finditer(r"최상위\s*(\d{1,3})\s*절", t):
                    claims.append((i, "최상위", int(m.group(1)),
                                   t[max(0, m.start() - 24):m.end() + 12]))
            off = [c for c in claims
                   if c[2] != (sec_top if c[1] == "최상위" else sec_sub)]
            if off and skipped:
                print(f"\n⚠ **총계 주장 {len(off)}자리가 위 합과 다르다 — 이 축 밖 문서"
                      f"({', '.join(skipped)})가 있어 어긋남으로 세지 않는다.**"
                      " 뺄셈을 손으로 맞춘다:\n")
                for i, ax, got, frag in off[:(CAP or 20)]:
                    base = sec_top if ax == "최상위" else sec_sub
                    print(f"- `:{i}` {ax} 절 **{got}** ↔ 마크다운 실측 {base}"
                          f" → 그 차 **{got - base}** 이 이 축 밖 문서의 값이어야 한다"
                          f" ({frag[:40]})")
                print("\n**도구가 세지 못했다 ≠ 절이 없다.** 위 합을 본문에 그대로 옮기지"
                      " 않는다 — 차가 이 축 밖 문서의 절 수와 맞는지 확인하고, 안 맞으면"
                      " **코드펜스 안의 `## `** 를 셌는지 본다")
            elif off:
                print("\n| 행 | 축 | 코드펜스 밖 실측 | 본문 | 자리 |")
                print("|---|---|---|---|---|")
                for i, ax, got, frag in off[:(CAP or 20)]:
                    print(f"| {i} | {ax} 절 |"
                          f" {sec_top if ax == '최상위' else sec_sub} | **{got}** | {frag[:44]} |")
                print("\n**절 수는 손으로 세지 않고 위 표에서 옮긴다.**"
                      " 어긋나면 대개 **코드펜스 안의 `## `** 를 절로 센 것이다.")
                problems += 1
            elif claims and not row_bad:
                print(f"\n본문의 절 수 주장 {len(claims)}자리가 코드펜스 밖 실측과 맞는다.")
            elif not claims:
                print("\n⚠ 본문에 「최상위/하위 절 N」 주장이 없다 — **이 축은 꺼졌다.**"
                      " 문서 표에 절 수를 적었는지 본다(SKILL.md 4단계는 갈라 적으라고 한다)")
            # it.19 수선: **경고는 말한 축만 고쳐진다** — it.18 실측에서 위 총계 경고가
            # 최상위 축에만 붙어, 런이 총계(111 = 102 + PDF 9)는 옳게 고치고 **같은 문장의
            # 하위 절 61 은 PDF 를 뺀 값**으로 남겨 두 수의 모집단이 갈렸다(파생 수치 1건).
            # 축이 둘이면 두 축에 같은 문장을 준다. 경고다 — 통과를 바꾸지 않는다.
            if skipped:
                same = [c for c in claims
                        if c[2] == (sec_top if c[1] == "최상위" else sec_sub)]
                for i, ax, got, frag in same[:(CAP or 20)]:
                    print(f"\n⚠ `:{i}` {ax} 절 **{got}** 이 **마크다운만의 합과 정확히"
                          f" 같다** — 이 축 밖 문서({', '.join(skipped)})의 절 수가"
                          " 더해졌는지 확인한다. 같은 문장의 다른 수가 그 문서를 더했으면"
                          " 이 수도 더한다 — **한 문장의 두 수는 모집단이 같아야 한다.**"
                          " 더하지 않기로 했으면 「마크다운 문서만」 한정어를 붙인다"
                          f" ({frag[:40]})")

    # ── ⑥ 라벨 없는 숫자 ─────────────────────────────────────────────────
    # 표 셀의 맨 숫자와 *"합이 88이다"* 는 라벨이 없어 위 축에 걸리지 않는다. 한 산출물이
    # 표면 62개 시절 값(33·17·16·8·6)을 쌍별 표에 남겼고 스크립트는 "0건" 을 냈다.
    bare = []
    if not args.no_bare:
        # 갈래별 관여 수는 넣지 않는다 — 값이 많아 거의 모든 숫자가 후보로 걸린다(실측
        # 106건). 늦게 추가한 표면이 어긋나게 만드는 것은 **총계와 상태별 개수**다.
        canon = defaultdict(list)
        for k, v in list(expect.items()) + list(strength.items()):
            if v:
                canon[v].append(str(k))
        for i, raw in enumerate(lines, 1):
            for m in CELL.finditer(raw):
                inner = strip_tags(m.group(1)).strip()
                if not re.fullmatch(r"\d{1,4}", inner):
                    continue
                got = int(inner)
                for v, labels in canon.items():
                    if got != v and abs(got - v) <= args.near:
                        bare.append((i, got, v, " / ".join(labels[:3]), "표 셀"))
        loose = re.compile(r"(?:합|총|모두|전체)\s*(?:이|가|은|는)?\s*(\d{1,3})")
        for i, t in enumerate(text_lines, 1):
            for m in loose.finditer(t):
                got = int(m.group(1))
                after = t[m.end():m.end() + 6]
                if UNIT_AFTER.match(after):
                    continue
                for v, labels in canon.items():
                    if got != v and abs(got - v) <= args.near:
                        bare.append((i, got, v, " / ".join(labels[:3]), "합계 서술"))

    print("\n## 라벨 없는 숫자 — 눈으로 가릴 후보\n")
    if args.no_bare:
        print("`--no-bare` 로 껐다.")
    elif bare:
        print(f"정본 값과 **±{args.near} 안**에서 다른 숫자다. **정당한 값이 많이 섞인다**"
              " — 표 셀은 다른 축의 수일 수 있다. 다만 표면을 늦게 추가했다면 여기부터 본다.\n")
        # **묶어 기각하면 샌다** — 실측(it.17): 런이 이 묶음을 *"전부 부분합이고 라벨에 한정어가
        # 있다"* 로 한 번에 기각했는데 그 안의 한 자리(*"Layer 3 inception 2건"*)에는 한정어가
        # 없었고 파생 수치 결함으로 남았다. it.13 의 `term_sweep` 도 같은 모양이었다 —
        # 묶어 기각한 18개 안에 **놓친 발견 세 건의 낱말**이 있었다.
        print(f"⚠ **이 묶음은 {len(set(bare))}건이고 묶어 기각하지 않는다** — 항목마다"
              " 「어느 축의 수인가」를 한 줄씩 적는다. *\"전부 부분합이다\"* 처럼 한 번에"
              " 기각하면 그 안의 예외가 그대로 남는다.\n")
        print("| 행 | 본문 | 정본 후보 | 그 값의 뜻 | 자리 |")
        print("|---|---|---|---|---|")
        # 차이가 작은 것부터 — 늦게 추가한 표면 때문에 어긋난 값이 위에 온다.
        # **정렬 키에 전체 항목을 넣는다**(it.19): `set` 순회는 판마다 달라서 동순위가 섞였고,
        # 접는 상한(40)과 겹치면 **판마다 다른 40건이 보인다** — 런이 판정한 목록과 에디터가
        # 다시 띄운 목록이 달라진다. 실측으로 커밋 판이 자기 재실행과 28줄 달랐다.
        for i, got, v, labels, kind in sorted(
                set(bare), key=lambda r: (abs(r[1] - r[2]), r[0], r[1], r[2],
                                          str(r[3]), str(r[4])))[:(CAP or 40)]:
            print(f"| {i} | **{got}** | {v} | {labels} | {kind} |")
        if len(set(bare)) > 40 and not args.full:
            print(f"\n⚠ **판정하지 않은 {len(set(bare)) - 40}건이 남아 있다** — 위 40건만 찍었다. 전량은 `--full` 로 본다")
    else:
        print("표 셀·합계 서술에 정본 근처의 다른 숫자가 없다.")

    # ── 마무리 — 통과 신호의 뜻을 좁힌다 ──────────────────────────────────
    # 이 스크립트가 다섯 산출물에 "0건" 을 내는 동안 채점자들은 26곳을 찾았다. 그때 런들은
    # 통과 신호를 받고 눈으로 다시 보지 않았다. 그래서 **검사하지 않은 축을 항상 찍는다.**
    unchecked = [
        "카드 본문·도해 주석 안의 수치 (*\"A 경계 통과 40\"* — 라벨이 표와 다르다)",
        "**표 안의 인접 행렬**(행·열 라벨이 붙은 격자). 서술형 `A ↔ B N개` 는 위에서 봤지만"
        " 격자 셀은 못 본다 — 한 산출물이 **19쌍을 옛 값으로 굳혔다**",
        "손으로 센 부분합 중 **정본 키가 아닌 라벨**을 쓴 것 (*\"종이 21\"* · *\"Must 13\"*)",
        "구간 배분·경계 통과처럼 `contracts.json` 에서 파생되지 않는 계산값",
        "ID 목록의 구성 (개수는 맞고 **다른 ID 가 섞인** 자리)",
        "서술의 논리 — 같은 사실을 두 곳에서 반대로 적은 것",
        "**ID 열거의 축 일관성** — *\"층 1 … (C1 · C62 · C67)\"* 에서 그 ID 들이 정말 같은 층인가."
        " 채점에서 이 축이 다섯 건을 냈고 자리가 일정하다 — **카드 · 부록 트리 · 층 도해**."
        " **기계로 두 번 만들어 두 번 기각했다**: 행 단위로 보면 문장 경계를 못 지켜"
        " (*\"C12·C52 는 층 1·2 뒤에 와야\"* 같은 순서 표현, *\"①…층 1 안에서 닫히고 ②이력 이동"
        "(C10·C25)\"* 처럼 다른 항목의 ID) 오탐이 6/7 이다. 표를 빼고 ID 2개 이상 창으로 좁혀도"
        " 그렇다 → **카드·목록·트리를 단위로 손으로 훑는다.** 각 카드의 라벨(*\"최상 · 층 1\"*)과"
        " 그 카드가 담은 ID 의 정본 층을 대 보는 일이다",
        "**`counts` 에 등록되지 않은 모집단 서술** — *\"다섯이 M1 안\"* 형태는 위"
        " 「모집단 정본」 절이 **등록된 것만** 대조하고, it.20 부터 「등록의 사거리」 절이"
        " **본문에서 센 자리를 세어 설명되지 않는 것을 나열한다.** 그 목록은 판정이 아니라"
        " 커버리지이고 **값으로 맞추므로 우연히 설명되는 자리가 있다** — 실측에서 파생 결함"
        " 두 자리(*\"나머지 여섯\"* · *\"세 API 요청 전부\"*)가 그 값(6·3)이 다른 축의 값과"
        " 맞물려 「설명됨」으로 빠졌다. `items` 계열(문서 유래 열거)은 **개수만** 본다."
        " 실측(it.18): 이 형태가 파생 수치 11건 중 6건이었다 → **정본 분포에 없는 수를 쓴"
        " 문장을 훑어 등록이 있는지 본다.** 그리고 기각 기록: **「라벨 + 수」 형태로 창을 잡는"
        " 검사 계열은 기각됐다**(`prescription_kill_rule`, it.18 — 겨냥 유형은 전부 없앴는데"
        " 그 축이 5 → 11). ⑩ 세 형태는 회귀 방지로만 남는다 — 이 계열로 새 검사를 만들지"
        " 않는다",
        "층·단계 교차 부분합 중 **한정어가 붙은 자리**(*\"Layer 2 inception 15건 중 12건\"*)."
        " 한정어 없는 자리는 it.18 부터 위에서 본다 — 한정어가 있으면 그 값이 정당한 부분합이라"
        " 대조할 수 없다. **한정어가 가리키는 모집단이 맞는지는 손으로 본다**",
        "**받아올 것(`closes`) 별 개수** — *\"실물 필요 8건\"* · *\"회신 3건\"* 같은 자리."
        " **만들어 보고 기각했다**: 이 값은 층별 부분합으로 쓰이는 것이 정상이라"
        " (*\"층 1 의 실물 6건\"* ↔ 정본 8) 한 산출물에 거짓 양성 11건 · 진성 0건이 나왔고,"
        " 앞의 층 한정어를 거르는 필터를 붙여도 한정어가 **뒤에 오는** 자리가 남는다"
        " → **파트 3 #04 의 세 묶음 수와 그것을 인용한 서술을 손으로 대 본다.**"
        " 정합(실물 필요 ↔ `prep`)은 위에서 봤다",
        "**충돌인데 `parties` 가 1개** — **만들어 보고 기각했다**(it.17): 한 산출물에 같은"
        " 모양이 **18건**인데 결함은 하나였다. `parties` 의 **단위가 집합마다 다르다** —"
        " 한쪽은 모듈(`M1`~`M5`)을, 다른 쪽은 문서를 적는다. `cites` 출처 종류로 바꿔도 9건 중"
        " 1건이다. **한 문서 안의 두 절이 부딪히는 것은 정당한 충돌**이라 이 축 자체가 서지"
        " 않는다 → **`contract_matrix.py` 의 「근거가 범위 제외 문장이다」 절을 읽는다.** 그"
        " 결함을 이미 이름으로 지목하고 있었고, 실패는 검사 부재가 아니라 **경고를 안 읽은"
        " 것**이었다",
        "**표 셀의 축 라벨** — **만들어 보고 기각했다**(it.17): 과녁(확보 소스 표 「계층」 열이"
        " *\"M3 → M5\"* 인데 정본 `layer` 는 2 하나)은 실재하는데 **그 열은 모듈 이름을 쓰고"
        " 정본은 숫자**라 맞대 볼 대상이 없다 → **표의 축 열은 눈으로 본다.** 값 하나에 화살표나"
        " 쉼표로 둘이 들어가 있으면 그 열이 단일 값 축인지 다시 본다."
        " **it.18 에서 한 열만 갈라 채택했다** — 파트 3 #04 의 판정 열은 셀 텍스트가 정본 표시"
        " 라벨과 정확히 같고 같은 행에 ID 칸이 있어 대조 대상이 서므로 위에서 본다. 나머지"
        " 열(계층·모듈 이름)은 여전히 이 목록에 남는다",
        # ── it.21 종료 처분(`on_exit_v2`) — 아래 넷은 「기계로 닫히지 않는 축」으로 확정됐다.
        # `stop_rule_v2` 가 it.20·it.21 두 판 연속 발동해 **기계 검사를 더 넣는 계열을 닫았다.**
        # 검사를 넣은 여섯 판의 결함 총합이 24 → 17 → 17 → 25 → 18 → 20 → 27 이고 **겨냥한
        # 유형은 매번 사라졌는데 총합이 줄지 않았다**(it.18·it.20·it.21 세 번 같은 결과).
        # 근거는 `runs/iteration-21/RESULT.md` §10-b. **이 넷으로 새 검사를 만들지 않는다.**
        "🔒 **기계로 닫히지 않는 축 ① 파생 수치 중 「정본에 모집단이 없는 수」**(it.21 확정)."
        " `counts` 정본화가 닫은 것은 **등록된 수**이고, 남은 것이 셋이다 — ⓐ산문이 바로 위"
        " 도해·표의 ID 를 **다시 세며 원소를 빠뜨리는 자리**(*\"열둘\"* ↔ 14 · *\"일곱\"* ↔ 6)."
        " 「N건(ID · ID …)」 형식이 아니라 위 괄호 대조가 **구조적으로 못 본다** ⓑ**원문 표의 행"
        " 수**와 자기 작업 표의 행 수 ⓒ**작업 파일·메타·정본 `note` 의 낡은 수**(한 산출물의"
        " 파생 6 중 5가 본문 밖이었다) → **골격이 「N건(ID…)」 형식을 강제하거나 그 모집단을"
        " 정본 스키마에 두는 것**이 남은 길이고, 그것은 검사가 아니다",
        "🔒 **기계로 닫히지 않는 축 ② 놓친 발견 중 「기각의 내용」**(it.21 확정). 형식을 세 층으로"
        " 정교화했고(묶어 기각 금지 → 원소마다 한 줄 → **몇 대 몇으로 같다**) **형식은 매번 100%"
        " 지켜지고 셈이 틀린다** — 실측에서 46행 전량이 형식을 지켰는데 표본 여덟 중 둘의 셈이"
        " 틀렸고 **놓친 발견 셋 중 둘이 그 두 줄 안에** 있었다. 잔여 일부는 **자기 보고가 덮었다고"
        " 적었으나 실물이 없는 자리**여서 검사할 대상이 문서에 없다 → **기각 목록은 손으로 표본을"
        " 뽑아 셈을 다시 센다.** 적는 형식을 더 정교하게 만들지 않는다",
        "🔒 **기계로 닫히지 않는 축 ③ 논리 모순**(it.21 확정). 일곱 판 평탄(5·3·3·3·3·4·4)이고"
        " 잔여가 **상태 전환의 서식 부속물·도해 라벨**이다. 다만 it.21 에 **같은 입력·같은 스킬의"
        " 한 런이 0 을 냈다** — 스킬의 한계가 아니라 **런의 분산**일 수 있다(그 판 두 런의 결함이"
        " 11 vs 15)",
        "🔒 **검사 밖의 축 — HTML 이스케이프 누출**(it.21 발견). 검토자 요구를 반영하며 이스케이프가"
        " 새어 **24자 / 9행**(11자는 `.q` 밖)이 렌더에 드러났다. `check_html.py` 와 이 스크립트"
        " 둘 다 이 축을 보지 않는다. **검사를 신설하지 않는다**(위 종료 처분) → 반영 뒤 렌더를"
        " 눈으로 본다",
    ]
    if closes_missing:
        unchecked.insert(0, "**받아올 것 ↔ 단계 배정의 정합** — `contracts.json` 에 `closes` 나"
                            " `aidlc` 가 없어 이번엔 껐다. **사전 준비 분량이 기간 판정의"
                            " 입력**이고, 이 축이 정본에 없으면 *\"미리 해 올 것\"* 과"
                            " *\"AI-DLC 안에서 닫을 것\"* 의 구분을 대조할 대상이 없다")
    if unchecked_extra:
        unchecked.insert(0, "**층·단계별 개수** — `contracts.json` 에 `layer`·`aidlc` 가 없어"
                            " 이번엔 껐다. 실측에서 남은 전파 누락이 **전부** 이 축이었다")
    print("\n---\n")
    print(f"**어긋난 묶음 {problems}개**"
          + (f" · 눈으로 가릴 후보 {len(set(bare))}건" if bare else "")
          + ".\n")
    print("**이 스크립트가 검사하지 않은 축이다 — 0건은 통과가 아니다.**\n")
    for u in unchecked:
        print(f"- {u}")
    print("\nContract 를 늦게 추가했다면 위 축을 **직접 훑는다.** 실측에서 이 스크립트가 다섯"
          " 산출물에 `0건` 을 내는 동안 채점자들이 **26곳**을 찾았고, 그 대부분이 위 목록이다.")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
