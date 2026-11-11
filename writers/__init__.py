"""작성기 목록. 새 작성기는 설정 파일을 만들고 여기에 한 줄 추가하면 됩니다."""

from writers import changche_autonomy, changche_club, gian, haengbal, pumui, seteuk

WRITERS = {w.CONFIG["id"]: w.CONFIG for w in (haengbal, changche_autonomy, changche_club, seteuk, gian, pumui)}

# 업무포털 → 메뉴 이름 → 작성기 id (창체는 자율/동아리 하위 선택)
MENU = {
    "나이스": {"행발": "haengbal", "창체": ["changche_autonomy", "changche_club"], "세특": "seteuk"},
    "에듀파인": {"기안": "gian", "품의": "pumui"},
}
