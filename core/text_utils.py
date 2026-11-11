"""글자 수·바이트 계산, 실명 치환, 응답 정리 등 화면과 무관한 도우미 함수"""

import json
import re


# ── 나이스 분량 계산 ─────────────────────────────
def neis_bytes(text: str) -> int:
    """나이스 기준 바이트 (2024 기재요령): 한글 등 3, 영문·숫자·공백·기호 1, 엔터 1"""
    total = 0
    for ch in text.replace("\r\n", "\n"):
        total += 1 if ord(ch) < 128 else 3
    return total


def count_chars(text: str) -> int:
    """공백 포함 글자 수 (줄바꿈 제외)"""
    return len(text.replace("\r", "").replace("\n", ""))


def measure(text: str, unit: str) -> int:
    return neis_bytes(text) if unit == "bytes" else count_chars(text)


# ── 개인정보: 학생 이름 치환 ─────────────────────
def mask_name(text: str, name: str) -> str:
    """입력한 학생 이름을 '학생'으로 바꿈 (성을 뺀 호칭, 조사 포함)"""
    name = (name or "").strip()
    if not name or not text:
        return text
    text = text.replace(name, "학생")
    if len(name) == 3:  # 성을 빼고 부르는 경우 (예: 민준이가, 민준이는)
        particle = {"이가": "이", "이는": "은", "이를": "을", "이의": "의", "이와": "과", "이": ""}
        text = re.sub(re.escape(name[1:]) + r"(이가|이는|이를|이의|이와|이)?",
                      lambda m: "학생" + particle.get(m.group(1) or "", ""), text)
    for wrong, right in {"학생는": "학생은", "학생가": "학생이", "학생를": "학생을", "학생와": "학생과"}.items():
        text = text.replace(wrong, right)
    return text


# ── 모델 응답 정리 ──────────────────────────────
def extract_json(text: str) -> dict:
    """모델 응답에서 JSON 부분만 꺼내 파싱"""
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        raise ValueError("AI 응답에서 분석 결과(JSON)를 찾지 못했습니다. 다시 시도해 주세요.")
    return json.loads(m.group(0))


def strip_markdown(text: str) -> str:
    """**굵게**, # 제목, 따옴표로 감싼 답 등 서식 기호 제거"""
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text or "")
    text = re.sub(r"(?m)^#+\s*", "", text)
    text = text.replace("**", "").strip()
    if len(text) > 2 and text[0] in "\"'“" and text[-1] in "\"'”":
        text = text[1:-1].strip()
    return text


def one_paragraph(text: str) -> str:
    """줄바꿈을 없애고 하나의 문단으로"""
    return re.sub(r"\s*\n+\s*", " ", strip_markdown(text)).strip()


# ── 간단한 유사도 (예시 고르기용) ────────────────
def bigrams(text: str) -> set:
    t = re.sub(r"[^가-힣A-Za-z0-9]", "", text or "")
    return {t[i:i + 2] for i in range(len(t) - 1)}


def similarity(a: str, b: str) -> float:
    A, B = bigrams(a), bigrams(b)
    if not A or not B:
        return 0.0
    return 2 * len(A & B) / (len(A) + len(B))   # Dice 계수 (0~1)


# ── 생기부 문장 점검 (규칙 기반) ─────────────────
FORBIDDEN_HINTS = {
    r"TOEIC|TOEFL|TEPS|HSK|JLPT|토익|토플|텝스": "공인어학시험은 기재할 수 없습니다.",
    r"대학교|[가-힣]{2,}대학(?!생)": "특정 대학명은 기재할 수 없습니다.",
    r"수상|입상|금상|은상|동상|최우수상|우수상|장려상": "수상 실적은 '수상경력' 외 항목에 기재할 수 없습니다.",
    r"대회": "대회 참여 사실은 기재가 제한됩니다. 대회 명칭을 행사로 바꿔 쓰는 것도 금지입니다.",
    r"논문|학회": "논문·학회 관련 사항은 기재할 수 없습니다.",
    r"특허|실용신안|출원": "지식재산권 관련 사항은 기재할 수 없습니다.",
    r"장학": "장학생·장학금 관련 내용은 기재할 수 없습니다.",
    r"모의고사|학력평가": "모의고사·학력평가 성적은 기재할 수 없습니다.",
    r"방과후": "방과후학교 활동 내용은 기재하지 않습니다.",
    r"자격증|기능사|산업기사": "자격증 명칭·취득 사실은 '자격증 및 인증 취득상황' 외에 기재할 수 없습니다.",
    r"아버지|어머니|부모님|아빠|엄마": "부모의 사회·경제적 지위를 암시하는 내용이 없는지 확인하세요.",
    r"해외|어학연수": "해외 활동 실적은 기재할 수 없습니다.",
}


def check_record_text(text: str, student_name: str = "", endings: tuple = ()) -> list:
    """생성 결과에서 확인이 필요한 부분을 찾아 [(수준, 메시지)]로 돌려줌"""
    issues = []
    name = (student_name or "").strip()
    if name and (name in text or (len(name) == 3 and name[1:] in text)):
        issues.append(("error", "학생 이름이 들어 있습니다. 지워 주세요."))
    if "*" in text or "#" in text:
        issues.append(("warning", "별표(*)나 샵(#) 같은 서식 기호가 남아 있습니다."))
    if "\n" in text.strip():
        issues.append(("warning", "줄바꿈이 있습니다. 하나의 문단으로 입력하는 것이 원칙입니다."))
    for pattern, msg in FORBIDDEN_HINTS.items():
        found = re.search(pattern, text)
        if found:
            issues.append(("warning", f"'{found.group(0)}' — {msg}"))
    if endings:
        sentences = [s.strip() for s in re.split(r"(?<=[.])\s+", text.strip()) if s.strip()]
        odd = [s for s in sentences if not any(s.rstrip(".").endswith(e) for e in endings)]
        if odd:
            sample = odd[0] if len(odd[0]) <= 40 else "…" + odd[0][-40:]
            issues.append(("info", f"어미 규칙({', '.join(endings)})과 다른 문장이 {len(odd)}개 있습니다. 예: {sample}"))
    return issues
