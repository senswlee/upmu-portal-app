"""에듀파인(공문형) 작성 엔진: 제목 입력 → 예시 자동 선택 → 작성 → 확인·수정"""

import re

import streamlit as st

from core import ui
from core.llm import LLMError, call_llm
from core.resources import match_case, parse_cases, read_resource
from core.text_utils import strip_markdown

PHASES = ["① 제목 입력", "② 작성 결과 확인·수정"]
DEFAULTS = {"phase": 0, "title": "", "related": "", "details": "", "case_id": "", "result": "", "history": []}
RELATED_PLACEHOLDER = "○○고등학교-○○○○(○○○○. ○○. ○○.)"


def available_cases(w: dict, refs: dict):
    """기본 예시 Case + 교사가 올린 파일 속 Case. 반환 (cases, 일반 참고 텍스트)"""
    base = [] if refs["replace"] else parse_cases(refs["teacher_examples"])
    extra_text = []
    for name, text in refs["uploads"]:
        cs = parse_cases(text)
        if cs:
            for c in cs:
                c["id"] = f"내 예시·{c['id']}"
            base += cs
        else:
            extra_text.append((name, text))
    return base, extra_text


def system_prompt(w: dict, refs: dict, case: dict, extra_text: list) -> str:
    blocks = [
        f"당신은 학교 행정 업무에 능숙한 교사로, 에듀파인 '{w['name']}' 문서를 작성합니다.",
        "[작성 지침]\n"
        f"- 아래 [선택된 예시문]의 형식(항목 기호, 들여쓰기, 줄바꿈, 띄어쓰기, 문장 어미)을 정확히 따름.\n"
        f"- 입력한 제목에 맞게 본문 내용을 예시문을 참고하여 추론해서 작성함.\n"
        f"- 붙임은 반드시 포함하고, 제목에 맞게 첨부 문서명을 고쳐 씀. 마지막은 '끝.'으로 마침.\n"
        f"- 교사가 알려 주지 않은 일시, 장소, 인원, 금액 등은 지어내지 말고 '○○'로 비워 둠.\n"
        f"{w.get('extra_rule', '')}"
        "- 출력 형식: 첫 줄에 제목, 빈 줄, '1. 관련: ...', '2. 본문(세부 항목 가. 나. ...)', 빈 줄, '붙임 ...'. "
        "이 외의 설명은 출력하지 않음.",
        f"[작성요령]\n{refs['guides']}",
        f"[선택된 예시문 — {case['id']}]\n{case['title']}\n\n{case['body']}" if case else "",
    ]
    if extra_text:
        blocks.append("[교사가 올린 참고 자료]\n" + ui.uploads_block(extra_text))
    return "\n\n".join(b for b in blocks if b)


def user_prompt(s: dict) -> str:
    related = s["related"].strip() or RELATED_PLACEHOLDER
    text = f"[제목]\n{s['title']}\n\n[관련 (그대로 사용)]\n{related}"
    if s["details"].strip():
        text += f"\n\n[교사가 알려 준 세부 정보 — 반드시 반영]\n{s['details']}"
    return text


def postprocess(text: str, s: dict) -> str:
    """제목 줄과 '1. 관련:' 줄을 교사 입력대로 고정"""
    text = strip_markdown(text).strip()
    text = re.sub(r"(?m)^\s*(제목\s*[:：]\s*)", "", text)
    lines = text.splitlines()
    if lines and lines[0].strip() != s["title"].strip():
        if s["title"].strip() in lines[0] or len(lines[0]) < 60 and not lines[0].lstrip().startswith("1."):
            lines[0] = s["title"].strip()
        else:
            lines = [s["title"].strip(), ""] + lines
    related = s["related"].strip() or RELATED_PLACEHOLDER
    lines = [f"1. 관련: {related}" if re.match(r"^\s*1\.\s*관련\s*[:：]", l) else l for l in lines]
    return "\n".join(lines)


def demo_result(case: dict, s: dict) -> str:
    body = case["body"] if case else "1. 관련: \n2. (체험 모드 예시)"
    body = body.replace(case["title"], s["title"]) if case else body
    return postprocess(f"{s['title']}\n\n{body}", s)


def render(w: dict):
    wid = w["id"]
    s = ui.wstate(wid, DEFAULTS)
    st.subheader(f"{w['icon']} {w['title']}")
    st.caption(w["caption"])
    refs = ui.reference_panel(wid, w["resources"])
    cases, extra_text = available_cases(w, refs)

    phase = s["phase"]
    st.progress((phase + 1) / len(PHASES),
                text=" → ".join(f"**{p}**" if i == phase else p for i, p in enumerate(PHASES)))

    def go(p):
        s["phase"] = p

    def reset():
        ui.reset_writer(wid, DEFAULTS)

    case_by_id = {c["id"]: c for c in cases}

    if phase == 0:
        st.info(w["intro"])
        s["title"] = st.text_input(w["title_label"], value=s["title"], key=ui.wkey(wid, "title"),
                                   placeholder=w["title_placeholder"])
        case, how = (match_case(s["title"], cases) if s["title"].strip() else (None, ""))
        if cases:
            ids = [c["id"] for c in cases]
            auto_id = case["id"] if case else ids[0]
            labels = {c["id"]: f"{c['id']} — {c['title']}" for c in cases}
            if how == "keyword":
                st.success(f"제목의 단어로 **{labels[auto_id]}** 예시를 골랐습니다.")
            elif how == "similar":
                st.warning(f"일치하는 단어가 없어 가장 비슷한 **{labels[auto_id]}** 예시를 골랐습니다. 필요하면 바꾸세요.")
            # 자동 선택이 바뀌면 선택 상자도 따라가도록 key에 자동 선택값을 포함
            chosen = st.selectbox("참고할 예시문", ids, index=ids.index(auto_id), format_func=lambda i: labels[i],
                                  key=ui.wkey(wid, f"case_{auto_id}"))
            s["case_id"] = chosen
            with st.expander("선택한 예시문 보기"):
                c = case_by_id[chosen]
                st.text(f"{c['title']}\n\n{c['body']}")
        else:
            st.warning("사용할 예시문이 없습니다. 참고 자료에서 예시문 파일을 올리거나 '함께' 방식을 선택하세요.")

        s["related"] = st.text_input("관련 근거 (선택)", value=s["related"], key=ui.wkey(wid, "related"),
                                     placeholder="예: ○○고등학교-1234(2025. 3. 4.) · 비워 두면 형식만 표시",
                                     help="'1. 관련:' 줄에 그대로 들어갑니다.")
        s["details"] = st.text_area("세부 정보 (선택)", value=s["details"], key=ui.wkey(wid, "details"), height=110,
                                    placeholder=w["details_placeholder"],
                                    help="알려 준 정보만 사용하고, 나머지는 '○○'로 비워 둡니다.")
        if st.button("작성하기 →", type="primary", disabled=not s["title"].strip() or not cases,
                     key=ui.wkey(wid, "b_make")):
            case = case_by_id.get(s["case_id"])
            with st.spinner("문서를 작성하는 중..."):
                try:
                    if ui.is_demo():
                        s["result"] = demo_result(case, s)
                    else:
                        out = call_llm(st.session_state["cfg"], system_prompt(w, refs, case, extra_text), user_prompt(s))
                        s["result"] = postprocess(out, s)
                    s["history"] = []
                    go(1)
                    st.rerun()
                except LLMError as e:
                    st.error(str(e))

    elif phase == 1:
        case = case_by_id.get(s["case_id"])
        st.markdown(f"##### ② 작성된 {w['name']}")
        text = st.text_area("결과 (직접 수정할 수 있습니다)", value=s["result"], height=320,
                            key=ui.wkey(wid, f"result_{hash(s['result'])}"))
        s["result"] = text
        ui.copy_box(text, "오른쪽 위 복사 아이콘을 눌러 에듀파인 본문에 붙여 넣으세요. '○○' 부분은 직접 채워 주세요.")
        if "○○" in text:
            st.info("‘○○’로 비워 둔 부분이 있습니다. 실제 일시·장소·금액 등을 채워 주세요.")
        for i, h in enumerate(s["history"], 1):
            st.caption(f"반영된 수정 요청 {i}: {h}")

        st.markdown(f"작성된 {w['name']}를 확인해 주세요. 수정하거나 추가할 내용이 있으면 말씀해 주세요.")
        req_key = ui.wkey(wid, f"req_{len(s['history'])}")
        req = st.text_area("수정 요청", height=90, key=req_key, placeholder=w["revise_placeholder"])
        c1, c2, c3, c4 = st.columns(4)
        c1.button("← 제목 수정", on_click=go, args=(0,), use_container_width=True, key=ui.wkey(wid, "b_back"))
        apply = c2.button("수정 반영", use_container_width=True, disabled=not req.strip(), key=ui.wkey(wid, "b_apply"))
        regen = c3.button("다시 작성", use_container_width=True, key=ui.wkey(wid, "b_regen"))
        c4.button("새 문서", on_click=reset, type="primary", use_container_width=True, key=ui.wkey(wid, "b_new"))
        if apply or regen:
            with st.spinner("다시 작성하는 중..."):
                try:
                    if ui.is_demo():
                        s["result"] = demo_result(case, s)
                    else:
                        user = user_prompt(s)
                        if apply:
                            user += f"\n\n[현재 문서]\n{text}\n\n[수정 요청 — 반영하여 문서 전체를 다시 출력]\n{req}"
                        out = call_llm(st.session_state["cfg"], system_prompt(w, refs, case, extra_text), user)
                        s["result"] = postprocess(out, s)
                    if apply:
                        s["history"].append(req)
                    st.rerun()
                except LLMError as e:
                    st.error(str(e))
