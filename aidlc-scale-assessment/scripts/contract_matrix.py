#!/usr/bin/env python3
"""Contract 목록에서 수치를 계산한다. 손으로 세지 않는다.

문서의 요약 수치는 사람이 손으로 적은 값이라 **틀린 채로 여러 문서에 퍼진다.** 실제로
한 Workstream 의 관여 수가 9로 적혀 있었지만 실제 11이었고, "두 Workstream 공유 15개" 가 실제 14였다.
Contract 별 참여자 목록이 정본이고 나머지 수치는 전부 여기서 파생돼야 한다.

입력: Contract 목록 JSON

    [
      {"id": "C1", "title": "요청 진입 경계", "parties": ["004", "003"],
       "strength": "최상", "status": "gap"},
      {"id": "C2", "title": "요청 컨텍스트", "parties": ["004", "003", "001"],
       "strength": "상", "status": "ok"}
    ]

  status 는 con(충돌) / dup(중복) / gap(갭) / ok(정리됨) 넷 중 하나.
  policy 에 정책 문서 이름을 주면 참여자에서 제외하고 센다 — 정책 문서는 경계를
  주장하지 않으므로 Workstream 수치에 넣으면 부풀려진다.

사용법:
    python3 contract_matrix.py contracts.json
    python3 contract_matrix.py contracts.json --policy 000 000-attach
    python3 contract_matrix.py contracts.json --group 004,003 --group 001 --group 002

  --group 을 주면 그 묶음 배치에서 **경계를 넘는 Contract 수**를 센다. 배치 대안 표
  (파트 2 "배치를 바꿔도 남는 것")의 수치가 이것이다.

출력은 붙여 쓸 수 있는 마크다운 표다.
"""
import argparse
import itertools
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

STATUS_LABEL = {"con": "충돌", "dup": "중복", "gap": "갭", "ok": "정리됨"}

SECTION_RE = re.compile(r"^\s{0,3}(#{1,6})\s+(.+?)\s*#*\s*$")
# "1.3 전역 등록" · "9. 테스트·문서" 처럼 앞에 붙은 절 번호
SECNUM_RE = re.compile(r"^(\d+(?:\.\d+)*)[.)]?\s+(.*)$")
# 파일명 앞의 숫자 접두 — 05_연관_모듈… → 05
FILENUM_RE = re.compile(r"^(\d{1,2})[_\-. ]")

# 절 제목에 이 말이 있으면 경계가 있을 자리다. 인용되지 않은 절 중 이것에 걸리는 것만
# 보여준다 — 비율로 거르면 문서 대부분이 걸려 아무 정보가 없다(실측 7문서 중 6문서).
# 실제로 놓쳤던 두 절이 여기 걸린다: "1.3 전역 등록" · "9. 테스트·문서".
# 충돌의 근거가 **범위 제외를 말하는 문장**이면 그것은 충돌이 아니다. 제외 목록은 경계를
# 주장하지 않는다 — 한쪽이 "우리 것" 이라고 말한 것이 아니라 "안 만든다" 고 말한 것이다.
# 평가에서 이 실패가 **두 판 연속** 났고 같은 문서의 같은 절이었다. 지시는 이미 references 에
# 있으므로(*"제외 목록은 충돌의 한쪽이 될 수 없다"*) 기계가 짚는다.
EXCLUDE_QUOTE = re.compile(
    r"제외|미포함|범위\s*밖|범위에서\s*빠|구현하지\s*않|"
    r"won'?t|out\s*of\s*scope|not\s*in\s*scope|non-?goal", re.I)

# 근거가 입력 문서가 아니라 **이 산출물 자신**을 가리키는 것(it.17 신설).
# 실측 과녁 — it.15 `plandetail` C77 의 cites[2] 가 "이 문서 파트 4 #01" 이고, 그러면서
# 강도 최상 · Layer 1 · 충돌로 세어져 표지 판정이 쓰는 집계에 들어갔다. 채점자가
# **거짓 양성**으로 판정한 자리다. 계약 지점은 두 입력 문서가 합의해야 하는 자리이므로
# 산출물 자신은 경합의 당사자가 될 수 없다.
# 채택 검증: 그 파일에서 C77 1건 · it.13~it.16 산출물 다섯에서 0건(오탐 없음).
SELF_CITE = re.compile(
    r"이\s*문서\s*(의\s*)?(파트|부록|§|절)|본\s*문서\s*(의\s*)?(파트|부록|§|절)|"
    r"이\s*산출물|이\s*평가\s*문서|assessment\.html")

RISK_TITLE = re.compile(
    r"전역|공통|의존|제약|정책|테스트|검증|상태|세션|인증|권한|보안|성능|계약|규칙|"
    r"제외|범위|전환|마이그레이션|호환|플러그인|미확정|확인\s*필요|미정|갭|이력|"
    r"global|common|depend|constraint|polic|test|state|session|auth|migrat|compat")


def section_coverage(surfaces, roots, doc_aliases=()):
    """입력 문서의 절 목록과 cites 를 대조해 **인용되지 않은 절**을 찾는다.

    `--docs` 는 문서 단위라 문서가 Contract 를 몇 개 냈으면 경고가 뜨지 않는다. 그런데 절이
    아홉인 문서가 Contract 넷을 내고도 두 절을 통째로 놓친 적이 있다(전역 등록 패턴 · 테스트
    부재). 문서 단위로는 보이지 않는 누락이다.
    """
    hay = " ".join(str(c) for s in surfaces for c in s.get("cites", []))
    files = []
    for r in roots:
        p = Path(r)
        if p.is_dir():
            files += sorted(q for q in p.rglob("*.md") if q.is_file())
        elif p.is_file():
            files.append(p)
    out, skipped = [], []
    for f in files:
        m = FILENUM_RE.match(f.name)
        # 별칭 후보 — 파일명 숫자 접두 + --docs 로 준 별칭 중 이 파일명에 걸리는 것 +
        # 확장자를 뗀 파일명 자체. 접두가 없는 파일(requirements.md)이 전부 미인용으로
        # 잡히는 것을 막는다(실측에서 "인용된 절 0" 이 나왔다).
        names = [m.group(1)] if m else []
        stem = f.stem
        for group in doc_aliases:
            parts = [a for a in group.split("|") if a]
            if any(a.lower() in f.name.lower() or f.stem.lower() in a.lower()
                   for a in parts):
                names += parts
        names.append(stem)
        names = [n for n in dict.fromkeys(names) if len(n) >= 2]
        try:
            lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        secs, cited, headings = [], [], 0
        for line in lines:
            sm = SECTION_RE.match(line)
            if not sm:
                continue
            if len(sm.group(1)) > 1:
                headings += 1
            if len(sm.group(1)) == 1:   # h1 은 문서 제목이다. 절로 세지 않는다
                continue
            title = sm.group(2).strip()
            nm = SECNUM_RE.match(title)
            num, rest = (nm.group(1), nm.group(2)) if nm else ("", title)
            if not num:          # 번호 없는 소절은 대조 대상이 아니다
                continue
            secs.append((num, rest[:46]))
            # ① 문서 별칭 + 절 번호가 한 인용 안에 있는가 (예 "05 §1.3" · "REQ §3.2.1")
            hit = any(re.search(
                rf"{re.escape(n)}\s*[^,;]{{0,12}}§?\s*{re.escape(num)}(?![\d.])",
                hay, re.I) for n in names)
            # ② 절 제목의 고유 낱말(4자 이상)이 인용에 있는가
            if not hit:
                for tok in re.findall(r"[가-힣]{4,}|[A-Za-z][A-Za-z0-9]{4,}", rest):
                    if tok in hay:
                        hit = True
                        break
            cited.append(hit)
        if secs:
            out.append((f.name, secs, cited))
        else:
            # 절 제목에 번호가 없으면(`## 📂 데이터 계층 구조`) 이 문서는 대조에서 빠진다.
            # 조용히 빠지면 **읽은 것처럼 보인다** — 실측에서 5문서 중 1문서가 표에 아예
            # 나오지 않았고 그 문서의 절 20개를 사람이 손으로 대조해야 했다.
            skipped.append((f.name, headings))
    return out, skipped


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("surfaces")
    ap.add_argument("--policy", nargs="*", default=[],
                    help="정책 문서 이름. 참여자에서 제외하고 센다")
    ap.add_argument("--group", action="append", default=[],
                    help="쉼표로 묶은 배치 단위. 여러 번 줄 수 있다")
    ap.add_argument("--sections", nargs="*", default=[],
                    help="입력 문서 디렉터리. 각 문서의 절 목록과 cites 를 대조해 "
                         "인용되지 않은 절을 찾는다 — --docs 가 못 잡는 절 단위 누락용")
    ap.add_argument("--elements", nargs="*", default=[],
                    help="입력 문서 경로. 문서가 번호를 붙인 식별자 계열을 세어 "
                         "**대부분 인용했는데 소수만 빠진** 원소를 낸다(놓친 발견 축)")
    ap.add_argument("--docs", nargs="*", default=[],
                    help="입력 문서의 짧은 이름 전부. Contract 를 거의 못 낸 문서를 찾는다. "
                         "cites 에서 부르는 이름이 여러 가지면 "
                         "'05|RE05|RE §5' 처럼 | 로 별칭을 묶는다")
    ap.add_argument("--full", action="store_true",
                    help="접는 자리를 전량 펼친다(「원소 여럿을 인용한 Contract」 표). "
                         "접힌 목록을 못 알아채는 실패가 있었으므로 접을 때 남는 수를 찍는다")
    args = ap.parse_args()

    surfaces = json.load(open(args.surfaces, encoding="utf-8"))
    # it.19: 정본이 객체 형태(`{"contracts": [...], "counts": [...]}`)면 배열을 꺼낸다.
    # 옛 배열 형태도 그대로 받는다 — 과거 판 산출물이 그 형태다(한쪽만 받으면 회귀가 죽는다).
    if isinstance(surfaces, dict):
        surfaces = surfaces.get("contracts", [])
    policy = set(args.policy)

    # 참여자에서 정책 문서를 뺀 목록. 이 값이 모든 수치의 기준이 된다.
    for s in surfaces:
        s["_parties"] = sorted(set(s.get("parties", [])) - policy)

    total = len(surfaces)
    print(f"# Contract {total}개\n")

    # ── 상태 분포 ──────────────────────────────────────────────────────────
    tally = Counter(s.get("status", "?") for s in surfaces)
    print("## 상태 분포\n")
    print("| 상태 | 개수 | Contract |")
    print("|---|---|---|")
    for key in ("con", "dup", "gap", "ok"):
        ids = [s["id"] for s in surfaces if s.get("status") == key]
        print(f"| {STATUS_LABEL[key]} | {len(ids)} | {', '.join(ids) or '—'} |")
    unknown = [s["id"] for s in surfaces if s.get("status") not in STATUS_LABEL]
    if unknown:
        print(f"| **미분류** | {len(unknown)} | {', '.join(unknown)} |")
    checksum = sum(tally.get(k, 0) for k in STATUS_LABEL)
    print(f"\n합 {checksum} / 전체 {total}"
          + ("" if checksum == total else "  ← **어긋난다. 미분류를 채운다**"))

    # 갭의 하위 분류. 본문이 「고아 N · 규격 미정 M」을 인용하므로 여기서 세어 준다 —
    # 실측(it.15)에서 그 수를 본문에만 두어 기계가 대조할 대상이 없었고 논리 모순이 났다.
    gaps = [s for s in surfaces if s.get("status") == "gap"]
    if gaps:
        kinds = Counter(str(s.get("gap_kind") or "").strip() for s in gaps)
        blank = kinds.pop("", 0)
        print("\n### 갭의 하위 분류\n")
        if kinds:
            print("| 하위 | 개수 | Contract |")
            print("|---|---|---|")
            for k, label in (("orphan", "고아"), ("spec", "규격 미정")):
                ids = [s["id"] for s in gaps if str(s.get("gap_kind") or "").strip() == k]
                if ids:
                    print(f"| {label} | {len(ids)} | {', '.join(ids)} |")
            other = sorted(set(kinds) - {"orphan", "spec"})
            for k in other:
                ids = [s["id"] for s in gaps if str(s.get("gap_kind") or "").strip() == k]
                print(f"| **모르는 값 `{k}`** | {len(ids)} | {', '.join(ids)} |")
        if blank:
            print(f"\n**`gap_kind` 가 빈 갭 {blank}건** — 갭은 안에서 둘로 갈린다"
                  " (`orphan` 소유자를 배정하면 닫힌다 / `spec` 필드·값·규칙을 써야 닫힌다)."
                  " 본문이 그 수를 인용하므로 **정본에 적어야 대조된다**(SKILL.md 2단계).")

    # ── Workstream 별 관여 ────────────────────────────────────────────────────────
    involve = Counter()
    for s in surfaces:
        involve.update(s["_parties"])
    print("\n## Workstream 별 관여\n")
    print("| Workstream | 관여 | 비율 | 막대 width |")
    print("|---|---|---|---|")
    for party, count in involve.most_common():
        pct = count / total * 100
        print(f"| {party} | {count} / {total} | {pct:.0f}% | `width:{pct:.1f}%` |")
    if policy:
        print(f"\n정책 문서 제외: {', '.join(sorted(policy))}")

    # ── 쌍별 인접 행렬 ─────────────────────────────────────────────────────
    pairs = Counter()
    shared = defaultdict(list)
    for s in surfaces:
        for a, b in itertools.combinations(s["_parties"], 2):
            pairs[(a, b)] += 1
            shared[(a, b)].append(s["id"])
    order = [p for p, _ in involve.most_common()]
    print("\n## 쌍별 인접 행렬\n")
    print("|  | " + " | ".join(order) + " |")
    print("|---|" + "---|" * len(order))
    for a in order:
        cells = []
        for b in order:
            if a == b:
                cells.append("—")
            else:
                cells.append(str(pairs.get(tuple(sorted((a, b))), 0)))
        print(f"| **{a}** | " + " | ".join(cells) + " |")

    if pairs:
        (ta, tb), thickest = pairs.most_common(1)[0]
        print(f"\n가장 두꺼운 경계: **{ta} ↔ {tb} — {thickest}개** "
              f"({thickest / total * 100:.0f}%)")
        print(f"  공유 Contract: {', '.join(shared[(ta, tb)])}")
        print("  → 이 쌍은 대체로 한 덩어리로 다뤄야 한다. 역방향 의존이 있는지 확인한다")

    # ── 근거 인용(cites) 검증 ──────────────────────────────────────────────
    # 채점에서 네 산출물 전부가 같은 자리에서 감점됐다 — 충돌·중복에는 참여 문서를
    # 적고 갭·정리됨에는 적지 않았다. 그리고 인용 밀도가 미결 수에 못 미쳤다.
    # 두 실패의 뿌리가 같다: **Contract 마다 근거 원문이 기록되지 않는다.**
    #   con(충돌) 은 경합하는 양쪽이 필요하므로 2개 이상,
    #   dup·gap 은 그 자리를 보이는 1개 이상.
    MIN_CITES = {"con": 2, "dup": 1, "gap": 1, "ok": 1}
    missing, thin_cites = [], []
    for s in surfaces:
        cites = [c for c in s.get("cites", []) if str(c).strip()]
        s["_cites"] = cites
        need = MIN_CITES.get(s.get("status", ""), 1)
        if not cites:
            missing.append(s["id"])
        elif len(cites) < need:
            thin_cites.append((s["id"], s.get("status", "?"), len(cites), need))

    total_cites = sum(len(s["_cites"]) for s in surfaces)
    floor = sum(MIN_CITES.get(s.get("status", ""), 1) for s in surfaces)
    print("\n## 근거 인용\n")
    if missing and len(missing) == total:
        print("Contract 에 `cites` 가 하나도 없다. **원문 인용을 Contract 마다 적는다** —"
              " 충돌은 경합하는 양쪽, 갭은 빠진 자리를 보이는 문장이다.")
        print("형식: `\"cites\": [\"004 §4 — '컨텍스트 주입은 WS2의 Provider'\", \"001 축1 — ...\"]`")
    else:
        print(f"인용 {total_cites}개 / 하한 {floor}개"
              + ("" if total_cites >= floor else "  ← **미달**"))
        print("\n하한은 Contract 상태에서 나온다 — 충돌 2개(양쪽) · 중복·갭·정리됨 1개.")
        if missing:
            print(f"\n**`cites` 가 빈 Contract: {', '.join(missing)}** — 근거 없이 분류한 자리다")
        for sid, st, got, need in thin_cites:
            print(f"- `{sid}`({STATUS_LABEL.get(st, st)}) 인용 {got}개 < {need}개 필요")
        if not missing and not thin_cites:
            print("\nContract 전부가 상태별 하한을 넘는다.")

    # ── 원소 여럿을 인용한 Contract (it.26 신설 · ㊴) ──────────────────────
    # **세기만 한다. 어긋남이 아니다.** 판정(접었는가)은 사람이 하고 이 절은 그 모집단을 준다.
    #
    # 왜 스크립트가 세는가 — it.25 에 ㊲ 가 자기 보고로 이 수를 요구했더니 **세 런이 `0` 을
    # 적었고 채점자 실측은 16 · 92 · 120** 이었다(접은 자리도 0 이 아니었다). 그리고 **채점자
    # 넷의 값도 서로 갈렸다**(9 · 16 · 92 · 120) — 즉 **그 수의 정의가 어디에도 없었다.**
    # 확정 사실 *"정본에 자리가 없는 축은 기계가 못 지킨다"*(it.12)의 자기 보고 판이고,
    # 처방은 검사를 더 넣는 것이 아니라 **셀 수 있는 수를 사람이 세지 않게 하는 것**이다.
    #
    # 세는 기준 — 한 `cites` 문자열 안에서 **원문이 스스로 가른 표지**를 센다. 넷이다.
    #   ①표 행 이어붙임(`|` 로 이은 칸이 셋 이상) ②번호·기호 매김(`①`~`⑳` · `1.` · `- ` ·
    #   `#N`) ③서로 다른 ID 토큰(`FR-...` · `BC-017` 계열) ④**구분자로 이어 쓴 열거**
    #   (` / ` · ` · ` · `, `) — **원문 인용 부호 안에서만** 센다.
    # 셋 이상이면 「원소 여럿을 인용했다」로 세고 **어느 표지로 세었는지 함께 찍는다.**
    #
    # ④ 를 넣은 근거가 실측이다 — ①~③ 만으로는 `table-order` 가 **0** 이었고 그 집합의
    # 인용은 *"테이블 번호 및 비밀번호 설정 / 16시간 세션 생성 / 자동 로그인 활성화"* 처럼
    # **슬래시로 가른 형태**다. 확정 사실 *"과녁 하나로 채택 검증한 검사는 그 과녁의 표기에
    # 맞춰진다"*(it.17) → **표기가 다른 집합을 하나 더 대 보고 넓혔다.** 인용 부호 밖을
    # 세지 않는 것이 필수다 — 해설 문장의 쉼표가 전부 걸린다.
    ELEM_ID = re.compile(r"\b[A-Z][A-Z0-9]{1,9}(?:-[A-Z0-9]{1,9}){1,3}\b")
    ELEM_NUM = re.compile(r"[①-⑳]|(?<![0-9.])[0-9]{1,2}\.\s|(?:^|\s)[-*]\s|#[0-9]{1,3}\b")
    QSPAN = re.compile(r"[\"“]([^\"”]{8,})[\"”]")
    ELEM_SEP = re.compile(r"\s/\s|\s·\s|,\s")
    multi = []
    for s in surfaces:
        marks = {}
        for i, c in enumerate(s.get("_cites", [])):
            t = str(c)
            pipes = t.count("|")
            ids = {m.group(0) for m in ELEM_ID.finditer(t)}
            nums = len(ELEM_NUM.findall(t))
            seps = max((len(ELEM_SEP.findall(q)) + 1
                        for q in QSPAN.findall(t)), default=0)
            n = max(pipes - 1 if pipes >= 3 else 0, len(ids), nums,
                    seps if seps >= 3 else 0)
            if n >= 3:
                kind = ("표 행" if pipes >= 3 and (pipes - 1) == n
                        else "ID" if len(ids) == n
                        else "번호·불릿" if nums == n else "구분자 열거")
                marks[f"cites[{i}]"] = (n, kind)
        if marks:
            multi.append((s["id"], marks))
    print("\n## 원소 여럿을 인용한 Contract — **세기만 한다**\n")
    if not surfaces or not total_cites:
        print("⚠ `cites` 가 없어 **이 축은 꺼졌다.** 0 이 통과가 아니다.")
    else:
        print(f"**원소 셋 이상을 인용한 Contract {len(multi)}개** / 전체 {total}개."
              " 이 수를 자기 보고에 쓸 때 **이 줄을 그대로 붙인다**(㊱-b).")
        print("\n**이 절은 판정하지 않는다** — 여기 오른 Contract 마다"
              " *「원문이 스스로 가른 것을 하나로 접었는가」*를 손으로 갈라"
              " `eval_metadata.json` 에 적는다(㊲). **접지 않았으면 그것도 적는다.**")
        if multi:
            shown = multi if args.full else multi[:40]
            print("\n| Contract | 자리 | 원소 수 | 무엇으로 세었나 |")
            print("|---|---|---|---|")
            for sid, marks in shown:
                for where, (n, kind) in marks.items():
                    print(f"| `{sid}` | `{where}` | {n} | {kind} |")
            if len(shown) < len(multi):
                print(f"\n⚠ **판정하지 않은 {len(multi) - len(shown)}건이 남아 있다** —"
                      " 전량은 `--full` 로 본다")
        print("\n**이 절이 보는 표기는 넷이다** — 표 행 이어붙임 · 번호·기호 매김 ·"
              " ID 토큰 · 인용 부호 안의 구분자 열거(` / ` · ` · ` · `, `)."
              " **인용 부호 밖의 산문으로 이어 쓴 열거는 보지 않으므로 0 이"
              " 「접은 것이 없다」를 뜻하지 않는다.**")

    # ── 근거가 산출물 자신인가 (it.17 신설) ───────────────────────────────
    # 이것은 후보가 아니라 **어긋남**이다 — 범위 제외 문장과 달리 정당한 경우가 없다.
    self_cited = []
    for s in surfaces:
        for i, c in enumerate(s.get("_cites", [])):
            # **원문 인용 구간을 뺀다.** 원문이 스스로를 *"본 문서"* 라 부르는 자리가 있고,
            # 인용은 원문 그대로여야 한다 — 실측(it.17)에서 `C82` 의 `"… | 본 문서 §2"` 가
            # PUB 원문의 문구인데 거짓 양성으로 걸렸다. 확정 사실 *"인용 안을 빼지 않으면
            # 오탐 기계가 된다"* 를 이 검사에도 적용한다.
            outside = re.sub(r'"[^"]*"', " ", str(c))
            if SELF_CITE.search(outside):
                self_cited.append((s["id"], i, str(c)[:110]))
    if self_cited:
        print("\n### ⚠ 근거가 이 산출물 자신을 가리킨다 — 어긋남\n")
        print("| Contract | `cites` | 그 인용 |")
        print("|---|---|---|")
        for sid, i, cite in self_cited:
            print(f"| `{sid}` | `[{i}]` | {cite} |")
        print("\n**계약 지점은 두 입력 문서가 합의해야 하는 자리다.** 산출물 자신은 경합의"
              " 당사자가 될 수 없다 — 자기가 내린 배정을 근거로 자기 충돌을 세우면 그 Contract"
              " 가 강도·Layer·상태 집계에 들어가 **표지 판정을 부풀린다.**")
        print("\n둘 중 하나로 고친다 —")
        print("1. 그 경합이 **입력 문서 사이의 것**이면 그 두 문서의 문장으로 근거를 바꾼다")
        print("2. 산출물의 배정 선택이 만든 것이면 **Contract 가 아니다** — 확인 요청으로 올리고"
              " 대장에서 뺀다(집계가 함께 줄어드는지 확인한다)")

    # ── 충돌의 근거가 범위 제외 문장인가 ──────────────────────────────────
    suspect = []
    for s in surfaces:
        if s.get("status") != "con":
            continue
        for c in s.get("_cites", []):
            if EXCLUDE_QUOTE.search(str(c)):
                suspect.append((s["id"], str(c)[:96]))
                break
    if suspect:
        print("\n### 충돌인데 근거가 범위 제외 문장이다\n")
        print("| Contract | 그 인용 |")
        print("|---|---|")
        for sid, cite in suspect:
            print(f"| `{sid}` | {cite} |")
        print("\n**후보다. 전부 고칠 것이 아니다** — 평가 네 산출물에서 이 목록의 절반쯤은"
              " 차수 귀속을 다투는 정당한 충돌이었다(*\"1차에 Won't\"* ↔ *\"1차에 필요\"*).")
        print("\n**제외 목록은 충돌의 한쪽이 될 수 없다.** 한쪽이 소유를 주장한 것이 아니라"
              " 만들지 않겠다고 적은 것이다. 셋 중 하나로 고친다 —")
        print("1. 그 낱말이 **두 문서에서 다른 것을 가리키는** 것이면 상태는 **갭(정의 누락)**이다")
        print("2. 제외됐는데 다른 문서가 그것을 **필요로 하면** 갭이고, 확인 요청으로 올린다")
        print("3. 제외와 무관한 별개 경합이면 **그 인용을 빼고** 경합하는 양쪽만 남긴다")

    # ── 입력 문서별 기여 ───────────────────────────────────────────────────
    # 참여자 집계는 "Contract 에 등장한 것" 만 센다. 입력에 있는데 Contract 를 못 낸 문서는
    # 그 표에서 아예 보이지 않아 **얕게 읽은 것이 드러나지 않는다.** 기대 목록을
    # 받아 0~1건인 문서를 경고한다 — 채점에서 이 유형으로 3건을 놓친 적이 있다.
    if args.docs:
        # 한 문서를 cites 에서 여러 이름으로 부를 수 있다. '|' 로 묶은 별칭 중 하나라도
        # 걸리면 기여로 센다 — 실측에서 cites 가 "RE §5" 라고 적고 --docs 가 "RE03" 이어서
        # 0건으로 잡히는 거짓 경고가 났다.
        # **경계에서 끊어 센다.** 부분 문자열로 세면 짧은 이름이 다른 이름 안에 걸린다 —
        # 실측에서 `02` 가 `RE02 §…` 의 `02` 를 잡아 기여 28개(실제 9개)로 나왔다.
        # 앞뒤가 글자·숫자가 아닐 때만 인정한다.
        def hit(alias: str, hay: str) -> bool:
            return re.search(rf"(?<![0-9A-Za-z]){re.escape(alias)}(?![0-9A-Za-z])",
                             hay) is not None

        contrib = defaultdict(list)
        for s in surfaces:
            hay = " ".join(str(x) for x in
                           s["_cites"] + s.get("parties", []) + [s.get("title", "")])
            for name in args.docs:
                if any(a and hit(a, hay) for a in name.split("|")):
                    contrib[name].append(s["id"])
        print("\n## 입력 문서별 기여 Contract\n")
        print("| 문서 | Contract | 어디에 |")
        print("|---|---|---|")
        thin = []
        for name in args.docs:
            ids = contrib.get(name, [])
            if len(ids) < 2:
                thin.append(name)
            print(f"| {name} | {len(ids)}{'' if len(ids) >= 2 else '  ← **얕다**'} "
                  f"| {', '.join(ids) or '—'} |")
        if thin:
            print(f"\n**Contract 를 1개 이하로 낸 문서: {', '.join(thin)}**")
            print("차례로 가른다.")
            print("1. **`cites` 가 그 문서를 다른 이름으로 부르고 있지 않은가** — 이건 거짓"
                  " 경고다. `--docs '05|RE05|RE §5'` 처럼 별칭을 묶어 다시 돌린다")
            print("2. 정책·범례·인벤토리처럼 **경계를 주장하지 않는 문서**인가 — 그렇게 적고"
                  " 넘어가되 그 판단을 문서에 남긴다")
            print("3. 둘 다 아니면 **얕게 읽은 것이다.** 그 문서를 다시 열어 전수로 읽는다 —"
                  " 그 문서만 아는 사실이 Contract 가 되지 못했을 수 있다")
        else:
            print("\n입력 문서 전부가 Contract 2개 이상에 기여했다.")

    # ── 절 단위 대조 ───────────────────────────────────────────────────────
    if args.sections:
        cov, skipped = section_coverage(surfaces, args.sections, args.docs)
        print("\n## 절 단위 대조 — 인용되지 않은 절\n")
        if skipped:
            print("**아래 문서는 이 대조에서 빠졌다 — 이 스크립트가 절 번호를 읽는 방식"
                  "(`## 3.2 …`)에 맞지 않는다.** 절 단위 누락이 기계로 잡히지 않으므로"
                  " **직접 전수로 읽는다.**\n")
            for name, headings in skipped:
                print(f"- `{name}` — 제목 {headings}개. **이 도구가 센 번호 붙은 절 0개**")
            print("\n> **이것은 도구의 한계이고 문서의 사실이 아니다.** 한 산출물이 이 줄을"
                  " *\"번호 붙은 절이 0개인 문서\"* 로 본문에 옮겨 적었는데, 원문에는"
                  " `# 1.`~`# 15.` 최상위 절이 있었다. **경고 문구를 산출물에 인용하지"
                  " 않는다** — 직접 읽고 센 값을 적는다.\n")
        if not cov:
            print("읽을 `.md` 가 없다. PDF 는 이 대조에 들어오지 않는다 — 직접 확인한다.")
        else:
            print("| 문서 | 인용된 절 | 경계 신호가 있는 미인용 절 |")
            print("|---|---|---|")
            risky = []
            for name, secs, cited in cov:
                miss = [(n, t) for (n, t), c in zip(secs, cited) if not c]
                hot = [(n, t) for n, t in miss if RISK_TITLE.search(t)]
                if hot:
                    risky.append((name, hot))
                print(f"| `{name}` | {sum(cited)} / {len(secs)} | "
                      f"{len(hot) or '—'} |")
            if risky:
                print("\n**아래 절은 인용되지 않았고 제목에 경계 신호가 있다. 열어서 읽는다.**")
                print("비율이 아니라 제목으로 골랐다 — 모든 절이 Contract 를 낼 필요는 없고,"
                      " 목록·인벤토리·예시 절은 미인용이 정상이다.\n")
                for name, hot in risky:
                    print(f"**`{name}`**")
                    for n, t in hot[:10]:
                        print(f"- §{n} {t}")
                    if len(hot) > 10:
                        print(f"- … 그 밖 {len(hot) - 10}개")
                    print()
            else:
                print("\n경계 신호가 있는 미인용 절이 없다.")
            prefixes = [m.group(1) for m in
                        (FILENUM_RE.match(n) for n, _, _ in cov) if m]
            dup_prefix = [k for k, v in Counter(prefixes).items() if v > 1]
            if dup_prefix:
                print(f"**주의 — 파일명 접두가 겹친다({', '.join(dup_prefix)}).** 절 번호"
                      " 매칭이 문서를 섞어 셀 수 있다. 인용된 절 수를 그대로 믿지 않는다.")

    # ── 원소 단위 커버리지 ─────────────────────────────────────────────────
    # 실측(it.13): 놓친 발견 25건의 모양을 네 채점자가 같은 말로 보고했다 —
    # *"인용된 절 ↔ 원문 절의 차집합은 비어 있고 놓친 것은 전부 **인용된 절 안의 표 셀·불릿**"*.
    # 한 Contract 가 표의 첫 행이고 다른 Contract 들이 같은 표의 둘째·셋째 행에서 나온 자리가 결정적이다.
    # 위 `--sections` 는 절 단위라 「미인용 절 0건」을 내고 이것을 못 본다.
    #
    # 그래서 **문서가 스스로 번호를 붙인 식별자를 계열별로 세고, 대부분 인용됐는데 소수만 빠진
    # 계열**을 낸다 — *"나머지는 다 봤는데 이것만 빠졌다"* 가 실측의 모양이다.
    # 채택 전 검증: 한 집합의 놓친 발견 과녁 3건을 전부 검출하고 후보를 221 → 14 로 좁혔다.
    # 한계 셋을 함께 찍는다 — ①ID 체계가 없는 집합에서는 꺼진다(실측 넷 중 둘)
    # ②후보는 판정 대상이고 결함이 아니다 ③**인용된 ID 안의 하위 항목**은 못 잡는다.
    if args.elements:
        ID_RE = re.compile(r"\b([A-Z][A-Z0-9]{1,9}(?:[-_][A-Z0-9]{1,9})+)\b")
        cited_txt = " ".join(str(c) for s in surfaces for c in s.get("cites", []))
        fam: dict[str, list[set]] = {}
        docs = []
        for r in args.elements:
            p = Path(r)
            if p.is_dir():
                docs += sorted(q for q in p.rglob("*.md") if q.is_file())
            elif p.is_file():
                docs.append(p)
        for path in docs:
            try:
                text = path.read_text(encoding="utf-8")
            except OSError:
                continue
            for m in ID_RE.finditer(text):
                full = m.group(1)
                tail = re.split(r"[-_]", full)[-1]
                if not re.search(r"\d", tail):
                    continue                      # 마지막 조각에 숫자가 없으면 식별자가 아니다
                pre = re.sub(r"[-_][A-Z0-9]{1,9}$", "", full)
                if not pre:
                    continue
                slot = fam.setdefault(pre, [set(), set()])
                slot[0].add(full)
                if full not in cited_txt:
                    slot[1].add(full)
        print("\n## 원소 단위 커버리지 — 계열의 대부분을 인용했는데 빠진 것\n")
        hits = []
        for pre, (all_, miss) in sorted(fam.items()):
            if len(all_) < 4 or not miss:
                continue
            if len(miss) / len(all_) <= 0.34 and len(miss) <= 3:
                hits.append((pre, len(all_), sorted(miss)))
        if not fam:
            print("문서에서 식별자 계열을 찾지 못했다 — **이 축을 검사하지 못했다.**"
                  " 산문·표 위주 문서에서는 꺼진다. 그때는 번호 붙은 목록(완료 기준 · Must 표 ·"
                  " Q 목록)의 **원소마다 Contract ID 를 손으로 적어** 커버리지를 본다.")
        elif hits:
            print("| 계열 | 전체 | 빠진 것 |")
            print("|---|---|---|")
            for pre, n, miss in hits:
                print(f"| `{pre}` | {n} | {', '.join(f'`{x}`' for x in miss)} |")
            print(f"\n**후보 {sum(len(h[2]) for h in hits)}건. 결함이 아니라 판정 대상이다** —"
                  " 계열의 나머지를 다 인용하고 이것만 빼놓은 자리이므로, 하나씩 원문을 열어"
                  " Contract 가 되어야 하는지 본다. 실측에서 이 형태로 놓친 Contract 셋이 나왔다.")
        else:
            print(f"계열 {len(fam)}개를 셌고 「대부분 인용했는데 소수만 빠진」 계열이 없다.")
        print("\n**이 축이 보지 못하는 것** — 인용된 식별자 **안의** 하위 항목(표 셀 안의 열거"
              " 항목 하나 · 불릿 하나)은 계열 단위로 잡히지 않는다. 실측의 놓친 발견 하나가"
              " 그 모양이었다(미니 메뉴 세 항목 중 하나).")

    # ── 배치별 경계 통과 ───────────────────────────────────────────────────
    if args.group:
        groups = [set(g.split(",")) for g in args.group]
        owner = {}
        for i, g in enumerate(groups):
            for party in g:
                owner[party] = i
        crossing, internal = [], []
        for s in surfaces:
            homes = {owner.get(p, f"?{p}") for p in s["_parties"]}
            (crossing if len(homes) > 1 else internal).append(s["id"])
        print("\n## 이 배치에서 경계를 넘는 Contract\n")
        for i, g in enumerate(groups):
            print(f"- 묶음 {i + 1}: {', '.join(sorted(g))}")
        print(f"\n**경계 통과 {len(crossing)} / {total}** · 내부화 {len(internal)}")
        print(f"통과: {', '.join(crossing) or '—'}")
        print(f"내부: {', '.join(internal) or '—'}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
