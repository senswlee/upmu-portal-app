"""나이스(생기부형) 작성 엔진: 자료 입력 → 분석 → 교사 피드백 → 최종 작성
작성기별 차이(입력 칸, 규칙, 분량, 예시 자료)는 writers/ 의 설정(dict)으로 받는다."""

import json

import streamlit as st

from core import ui
from core.llm import LLMError, call_llm
from core.resources import pick_seteuk_examples, pick_similar, read_resource, split_examples
from core.text_utils import (check_record_text, extract_json, mask_name, measure, neis_bytes,
                             one_paragraph)

PHASES = ["① 자료 입력", "② 분석 결과", "③ 교사 피드백", "④ 최종 작성"]
DEFAULTS = {"phase": 0, "inputs": {}, "student_name": "", "inputs_masked": "",
            "analysis": None, "keywords": [], "history": [], "final_text": ""}

COMMON_CONSTRAINTS = """- 구체성 확보: 의견은 구체적이고 근거를 포함하며, 모호한 표현은 피함.
- 긍정적 접근: 학생의 성장을 긍정적으로 평가하며, 향후 가능성을 강조함.
- 품격 있는 표현: 신뢰감을 줄 수 있는 품격 있는 문체를 사용함.
- 개인정보 보호: 학생의 실명 및 신상정보는 포함하지 않음."""

ANALYSIS_JSON = """반드시 아래 JSON 형식으로만 응답하세요.
{
  "strengths": ["관찰 근거가 드러나는 긍정적 특성·변화 문장", ...],
  "growth_points": ["부정적 특성이나 부족한 점을 성장 가능성으로 재구성한 문장 (없으면 빈 배열)", ...],
  "keywords": ["서술에 쓸 핵심 키워드", ...],
  "analysis": "위 내용을 종합한 3~4문장 분석"
}"""


# ── 프롬프트 조립 ───────────────────────────────
def target_rule(w: dict) -> str:
    if w["unit"] == "bytes":
        return (f"{w['target']}바이트 이내로 작성함. (나이스 기준: 한글 1자 3바이트, 영문·숫자·공백 1바이트) "
                f"한글 기준 공백 포함 약 {int(w['target'] / 3 * 0.92)}자 이내.")
    lo, hi = int(w["target"] * 0.85), int(w["target"] * 1.15)
    return f"글자 수는 공백 포함 {w['target']}자 내외({lo}~{hi}자)로 작성함."


def format_inputs(w: dict, values: dict) -> str:
    parts = []
    for f in w["inputs"]:
        v = (values.get(f["key"]) or "").strip()
        if v:
            parts.append(f"[{f['label'].split('(')[0].strip()}]\n{v}")
    return "\n\n".join(parts)


def analysis_system(w: dict, refs: dict) -> str:
    principles = "\n".join(f"{i}. {p}" for i, p in enumerate(w["analysis_principles"], 1))
    return (f"당신은 학교생활기록부 '{w['name']}' 작성을 돕는 경력 교사입니다.\n"
            f"교사가 입력한 자료를 분석합니다.\n\n[분석 원칙]\n{principles}\n\n"
            f"[공통 제약]\n{COMMON_CONSTRAINTS}\n\n[기재 유의사항]\n{refs['guides']}\n\n{ANALYSIS_JSON}")


def write_system(w: dict, refs: dict, query: str) -> str:
    rules = "\n".join(f"- {r}" for r in [target_rule(w)] + w["write_rules"])
    blocks = [f"당신은 학교생활기록부 '{w['name']}'을(를) 작성하는 경력 교사입니다.",
              f"[작성 지침]\n{rules}",
              f"[공통 제약]\n{COMMON_CONSTRAINTS}",
              f"[기재 유의사항]\n{refs['guides']}"]

    if not refs["replace"]:
        teacher = split_examples(refs["teacher_examples"])
        if teacher:
            blocks.append("[교사 예시문 — 어휘, 문장 길이, 어미, 톤앤매너를 가장 우선하여 따름. 문장을 그대로 베끼지 않음]\n"
                          + "\n\n".join(f"- {t}" for t in teacher))
        ref_list = reference_examples(w, query)
        if ref_list:
            blocks.append("[참고 예시 — 구성과 표현 방식만 참고하고, 내용과 문장은 베끼지 않음]\n"
                          + "\n\n".join(f"- {t}" for t in ref_list))
    if refs["uploads"]:
        blocks.append("[교사가 올린 자료 — 문체와 내용 방향에 최우선으로 반영함]\n" + ui.uploads_block(refs["uploads"]))
    blocks.append("결과 문단만 출력하고, 제목·설명·따옴표·서식 기호는 붙이지 마세요.")
    return "\n\n".join(blocks)


def reference_examples(w: dict, query: str) -> list:
    src = w["resources"].get("reference_file", "")
    if not src:
        return []
    if src.endswith(".json"):   # 세특 자료집: 과목명 기준
        s = st.session_state.get(f"__state_{w['id']}", {})
        vals = s.get("inputs", {})
        return pick_seteuk_examples(vals.get("subject", ""), vals.get("level", ""), query, k=3)
    return pick_similar(split_examples(read_resource(src)), query, k=2)


def build_write_input(s: dict) -> str:
    a = s["analysis"] or {}
    return (f"[교사가 입력한 자료]\n{s['inputs_masked']}\n\n"
            f"[긍정적 특성·변화]\n- " + "\n- ".join(a.get("strengths", []) or ["(없음)"]) + "\n\n"
            f"[성장 가능성]\n- " + "\n- ".join(a.get("growth_points", []) or ["(없음)"]) + "\n\n"
            f"[중심 키워드]\n{', '.join(s['keywords'])}\n\n"
            f"[종합 분석]\n{a.get('analysis', '')}")


# ── AI 호출 (체험 모드 포함) ─────────────────────
def run_analysis(w, s, refs, feedback=""):
    if ui.is_demo():
        return w["demo"]["analysis"]
    user = s["inputs_masked"]
    if s.get("analysis"):
        user += f"\n\n[기존 분석 결과]\n{json.dumps(s['analysis'], ensure_ascii=False, indent=2)}"
    if feedback:
        user += f"\n\n[교사 피드백 — 반드시 반영할 것]\n{feedback}"
    return extract_json(call_llm(st.session_state["cfg"], analysis_system(w, refs), user, json_mode=True))


def run_write(w, s, refs, extra=""):
    if ui.is_demo():
        return w["demo"]["text"]
    cfg = st.session_state["cfg"]
    query = s["inputs_masked"] + " " + " ".join(s["keywords"])
    system = write_system(w, refs, query)
    user = build_write_input(s) + (f"\n\n[추가 요청]\n{extra}" if extra else "")
    text = one_paragraph(call_llm(cfg, system, user))

    # 분량 자동 조정 (최대 2회)
    for _ in range(2):
        size, b = measure(text, w["unit"]), neis_bytes(text)
        too_long = (w["unit"] == "bytes" and size > w["target"]) or \
                   (w["unit"] == "chars" and size > w["target"] * 1.3) or b > w["max_bytes"]
        if not too_long:
            break
        goal = (f"{w['target'] - 60}바이트 이내" if w["unit"] == "bytes" else f"공백 포함 {w['target']}자 내외")
        text = one_paragraph(call_llm(cfg, system,
                                      f"아래 글이 분량을 초과합니다. 핵심 내용과 문체는 유지하고 {goal}로 줄여 문단만 출력하세요.\n\n{text}"))
    return text


# ── 화면 ───────────────────────────────────────
def render(w: dict):
    wid = w["id"]
    s = ui.wstate(wid, DEFAULTS)
    st.subheader(f"{w['icon']} {w['title']}")
    st.caption(w["caption"])
    refs = ui.reference_panel(wid, w["resources"])

    phase = s["phase"]
    st.progress((phase + 1) / len(PHASES),
                text=" → ".join(f"**{p}**" if i == phase else p for i, p in enumerate(PHASES)))

    def go(p):
        s["phase"] = p

    def reset():
        ui.reset_writer(wid, DEFAULTS)

    # ① 자료 입력
    if phase == 0:
        st.info(w["intro"])
        if w.get("notice"):
            st.warning(w["notice"])
        values = {}
        for f in w["inputs"]:
            k = ui.wkey(wid, f["key"])
            cur = s["inputs"].get(f["key"], f.get("default", ""))
            if f["kind"] == "area":
                values[f["key"]] = st.text_area(f["label"], value=cur, key=k, height=f.get("height", 160),
                                                placeholder=f.get("placeholder", ""), help=f.get("help"))
            elif f["kind"] == "select":
                opts = f["options"]
                values[f["key"]] = st.selectbox(f["label"], opts, key=k,
                                                index=opts.index(cur) if cur in opts else 0, help=f.get("help"))
            else:
                values[f["key"]] = st.text_input(f["label"], value=cur, key=k,
                                                 placeholder=f.get("placeholder", ""), help=f.get("help"))
        s["inputs"] = values
        if w.get("ask_name", True):
            s["student_name"] = st.text_input("학생 이름 (선택 · AI에 보내기 전에 '학생'으로 자동으로 바뀜)",
                                              value=s["student_name"], key=ui.wkey(wid, "student_name"))
        missing = [f["label"] for f in w["inputs"] if f.get("required") and not (values.get(f["key"]) or "").strip()]
        if st.button("자료 분석하기 →", type="primary", disabled=bool(missing)):
            masked = {k: mask_name(v, s["student_name"]) if isinstance(v, str) else v for k, v in values.items()}
            s["inputs_masked"] = format_inputs(w, masked)
            s["analysis"], s["history"] = None, []
            with st.spinner("자료를 분석하는 중..."):
                try:
                    result = run_analysis(w, s, refs)
                    s["analysis"], s["keywords"] = result, list(result.get("keywords", []))
                    go(1)
                    st.rerun()
                except (LLMError, ValueError) as e:
                    st.error(str(e))
        if missing:
            st.caption("필수 입력: " + ", ".join(m.split("(")[0].strip() for m in missing))

    # ② 분석 결과
    elif phase == 1:
        a = s["analysis"] or {}
        st.markdown("##### ② 자료 정리 및 분석 결과")
        st.markdown("**✅ 긍정적 특성·변화**")
        for x in a.get("strengths", []):
            st.markdown(f"- {x}")
        if a.get("growth_points"):
            st.markdown("**🌱 성장 가능성으로 재구성한 점**")
            for x in a["growth_points"]:
                st.markdown(f"- {x}")
        st.markdown("**📌 종합 분석**")
        st.write(a.get("analysis", ""))
        st.markdown("**🔑 서술에 쓸 키워드** (빼거나 직접 입력해 추가할 수 있습니다)")
        options = list(dict.fromkeys(list(a.get("keywords", [])) + s["keywords"]))
        s["keywords"] = st.multiselect("키워드", options=options, default=s["keywords"],
                                       accept_new_options=True, label_visibility="collapsed",
                                       key=ui.wkey(wid, f"kw_{len(s['history'])}"))
        c1, c2 = st.columns(2)
        c1.button("← 자료 수정", on_click=go, args=(0,), use_container_width=True, key=ui.wkey(wid, "b_back0"))
        c2.button("피드백 단계로 →", on_click=go, args=(2,), type="primary", use_container_width=True,
                  key=ui.wkey(wid, "b_to2"))

    # ③ 교사 피드백
    elif phase == 2:
        a = s["analysis"] or {}
        st.markdown("##### ③ 교사 피드백")
        with st.container(border=True):
            st.write(a.get("analysis", ""))
            st.caption("키워드: " + ", ".join(s["keywords"]))
        for i, fb in enumerate(s["history"], 1):
            st.caption(f"반영된 피드백 {i}: {fb}")
        st.info(w["feedback_info"])
        fb_key = ui.wkey(wid, f"feedback_{len(s['history'])}")
        feedback = st.text_area("수정하거나 추가할 내용", height=110, key=fb_key,
                                placeholder=w["feedback_placeholder"])
        c1, c2, c3 = st.columns(3)
        c1.button("← 분석 결과", on_click=go, args=(1,), use_container_width=True, key=ui.wkey(wid, "b_back1"))
        if c2.button("피드백 반영", use_container_width=True, disabled=not feedback.strip(), key=ui.wkey(wid, "b_fb")):
            fb_masked = mask_name(feedback, s["student_name"])
            with st.spinner("피드백을 반영하는 중..."):
                try:
                    result = run_analysis(w, s, refs, fb_masked)
                    s["analysis"] = result
                    s["keywords"] = list(dict.fromkeys(s["keywords"] + list(result.get("keywords", []))))
                    s["inputs_masked"] += f"\n\n[추가 자료]\n{fb_masked}"
                    s["history"].append(feedback)
                    go(1)
                    st.rerun()
                except (LLMError, ValueError) as e:
                    st.error(str(e))
        st.caption("추가할 내용이 없다면 다음 단계로 이동해도 될까요?")
        if c3.button("추가할 내용 없음 → 작성", type="primary", use_container_width=True, key=ui.wkey(wid, "b_write")):
            with st.spinner(f"{w['name']}을(를) 작성하는 중..."):
                try:
                    s["final_text"] = run_write(w, s, refs)
                    go(3)
                    st.rerun()
                except (LLMError, ValueError) as e:
                    st.error(str(e))

    # ④ 최종 작성
    elif phase == 3:
        st.markdown(f"##### ④ {w['name']}")
        text = st.text_area("결과 (직접 수정할 수 있습니다)", value=s["final_text"], height=240,
                            key=ui.wkey(wid, f"final_{hash(s['final_text'])}"))
        s["final_text"] = text
        ui.length_metrics(text, w["unit"], w["target"], w["max_bytes"], w["unit"] == "bytes")
        ui.show_issues(check_record_text(text, s["student_name"], tuple(w.get("endings", ()))))
        ui.copy_box(text, "오른쪽 위 복사 아이콘을 눌러 나이스에 붙여 넣으세요. AI 초안이므로 사실 여부를 꼭 확인해 주세요.")

        c1, c2, c3, c4 = st.columns(4)
        c1.button("← 피드백", on_click=go, args=(2,), use_container_width=True, key=ui.wkey(wid, "b_back2"))
        regen = c2.button("다시 생성", use_container_width=True, key=ui.wkey(wid, "b_regen"))
        shorter = c3.button("더 짧게", use_container_width=True, key=ui.wkey(wid, "b_short"))
        c4.button("새 학생", on_click=reset, type="primary", use_container_width=True, key=ui.wkey(wid, "b_new"))
        if regen or shorter:
            size = measure(text, w["unit"])
            extra = "" if regen else (f"이전 결과보다 약 20% 짧게, 약 {int(size * 0.8)}"
                                      f"{'바이트' if w['unit'] == 'bytes' else '자'}로 작성할 것.")
            with st.spinner("다시 작성하는 중..."):
                try:
                    s["final_text"] = run_write(w, s, refs, extra)
                    st.rerun()
                except (LLMError, ValueError) as e:
                    st.error(str(e))
