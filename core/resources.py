"""기본 자료(resources 폴더)와 교사 업로드 파일 읽기, 예시 고르기"""

import io
import json
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree

from core.text_utils import similarity, strip_markdown

ROOT = Path(__file__).resolve().parent.parent
RES = ROOT / "resources"
UPLOAD_LIMIT = 10_000          # 업로드 파일 1개당 AI에 보내는 최대 글자 수
SUPPORTED = ["txt", "md", "pdf", "docx", "hwpx"]


# ── 파일 → 텍스트 ───────────────────────────────
def bytes_to_text(data: bytes, filename: str) -> str:
    ext = filename.rsplit(".", 1)[-1].lower()
    if ext in ("txt", "md"):
        for enc in ("utf-8-sig", "cp949", "euc-kr"):
            try:
                return data.decode(enc)
            except UnicodeDecodeError:
                continue
        return data.decode("utf-8", errors="ignore")
    if ext == "pdf":
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        pages = [(p.extract_text() or "") for p in reader.pages]
        return _clean_pdf("\n".join(pages))
    if ext == "docx":
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            xml = z.read("word/document.xml")
        root = ElementTree.fromstring(xml)
        ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
        paras = ["".join(t.text or "" for t in p.iter(ns + "t")) for p in root.iter(ns + "p")]
        return "\n".join(p for p in paras if p.strip())
    if ext == "hwpx":
        out = []
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            sections = sorted(n for n in z.namelist() if re.match(r"Contents/section\d+\.xml", n))
            for name in sections:
                root = ElementTree.fromstring(z.read(name))
                for p in root.iter():
                    if p.tag.endswith("}p"):
                        line = "".join(t.text or "" for t in p.iter() if t.tag.endswith("}t"))
                        if line.strip():
                            out.append(line)
        return "\n".join(out)
    if ext == "hwp":
        raise ValueError("구형 한글(.hwp) 파일은 읽을 수 없습니다. 한글에서 PDF나 HWPX로 저장한 뒤 올려 주세요.")
    raise ValueError(f"지원하지 않는 형식입니다: .{ext}")


def _clean_pdf(text: str) -> str:
    lines = []
    for l in text.splitlines():
        s = l.strip()
        if not s or re.fullmatch(r"-?\s*\d{1,3}\s*-?", s):   # 쪽 번호
            continue
        lines.append(s)
    return "\n".join(lines)


def read_resource(rel_path: str) -> str:
    p = RES / rel_path
    if not p.exists():
        return ""
    return bytes_to_text(p.read_bytes(), p.name)


def list_resources() -> list:
    """관리자 점검 화면용: (상대경로, 크기)"""
    return [(str(p.relative_to(RES)), p.stat().st_size)
            for p in sorted(RES.rglob("*")) if p.is_file()]


# ── 예시문 다루기 ───────────────────────────────
def split_examples(text: str) -> list:
    """'## 예시...' 머리로 나뉜 예시문을 문단 리스트로. 머리가 없으면 빈 줄 기준."""
    text = re.sub(r"(?m)^#(?!#).*$", "", text or "")          # '# 제목/설명' 줄 제거
    parts = re.split(r"(?m)^##[^\n]*$", text)
    if len(parts) == 1:
        parts = re.split(r"\n\s*\n", text)
    out = [strip_markdown(re.sub(r"\s+", " ", p)).strip() for p in parts]
    return [p for p in out if len(p) >= 30]


def pick_similar(candidates: list, query: str, k: int = 3) -> list:
    if not candidates:
        return []
    if not query.strip():
        return candidates[:k]
    ranked = sorted(candidates, key=lambda c: similarity(query, c), reverse=True)
    return ranked[:k]


def load_seteuk_library() -> list:
    p = RES / "neis" / "세특_참고예시.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else []


def pick_seteuk_examples(subject: str, level: str, query: str, k: int = 3) -> list:
    """과목명이 같거나 비슷한 2024 세특 예시를 우선 고름"""
    lib = load_seteuk_library()
    if not lib:
        return []
    subj = re.sub(r"\s+", "", subject or "")

    def score(item):
        s = re.sub(r"\s+", "", item["subject"])
        sc = 0.0
        if subj and (s == subj):
            sc += 3
        elif subj and (s in subj or subj in s):
            sc += 2
        elif subj:
            sc += similarity(subj, s)
        if level and item["level"].startswith(level[:2]):
            sc += 1
        if level == "고등" and item["level"] == "고등(전문교과)":
            sc += 0.5
        sc += similarity(query, item["text"]) * 2
        return sc

    ranked = sorted(lib, key=score, reverse=True)
    return [f"[{x['level']} · {x['subject']}] {x['text']}" for x in ranked[:k]]


# ── 에듀파인 예시문 (Case 구조) ──────────────────
def parse_cases(text: str) -> list:
    """'## Case1: ... '제출' ...' 블록을 [{id, desc, keywords, title, body}]로"""
    cases = []
    blocks = re.split(r"(?m)^(##\s*Case\s*\d+\s*:.*)$", text or "")
    for i in range(1, len(blocks), 2):
        header, body = blocks[i], blocks[i + 1]
        m = re.match(r"##\s*(Case\s*\d+)\s*:(.*)", header)
        lines = [l.rstrip() for l in body.strip("\n").splitlines()]
        while lines and not lines[0].strip():
            lines.pop(0)
        if not lines:
            continue
        title = lines[0].strip()
        rest = "\n".join(lines[1:]).strip("\n")
        cases.append({
            "id": m.group(1).replace(" ", ""),
            "desc": m.group(2).strip(),
            "keywords": re.findall(r"'([^']+)'", m.group(2)),
            "title": title,
            "body": rest,
        })
    return cases


def match_case(title: str, cases: list):
    """제목에 키워드가 있으면 그 Case, 없으면 예시 제목과 가장 비슷한 Case. (case, 방식) 반환"""
    if not cases:
        return None, ""
    for c in cases:
        if any(k and k in title for k in c["keywords"]):
            return c, "keyword"
    best = max(cases, key=lambda c: similarity(title, c["title"]))
    return best, "similar"


def limit_text(text: str, limit: int = UPLOAD_LIMIT):
    """(잘린 텍스트, 잘렸는지)"""
    if len(text) <= limit:
        return text, False
    return text[:limit], True
