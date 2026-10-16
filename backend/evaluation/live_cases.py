"""Authored live regression cases, not a statistically representative benchmark."""


def turn(message, **expected):
    return {"message": message, "expected": expected}


CASES = [
    {"id": "normal", "turns": [turn("帮我转到 PY-SUN-PM，原因是工作时间调整", draft="PY-SUN-PM", applications=0), turn("{confirm}", applications=1)]},
    {"id": "conflict", "turns": [turn("帮我转到周日班，不想补钱，老师最好不变", slots={"max_fee_cents": 0}, candidates=["PY-SUN-PM"]), turn("下午不行，只能晚上", slots={"max_fee_cents": 0, "periods": ["晚上"]}, candidates=[]), turn("最多补两百元也可以", slots={"max_fee_cents": 20000}, candidates=["PY-SUN-EVE"])]},
    {"id": "free", "turns": [turn("我是否符合免费转班条件？", assessment="unknown", applications=0), turn("PY-SUN-PM", assessment="eligible"), turn("PY-SUN-EVE", assessment="ineligible")]},
    {"id": "change", "turns": [turn("帮我转到 PY-SUN-PM", draft="PY-SUN-PM"), turn("改成 PY-SUN-EVE，最多补200元，帮我办理", draft="PY-SUN-EVE"), turn("{first_confirm}", applications=0), turn("{confirm}", applications=1)]},
    {"id": "duplicate", "turns": [turn("帮我转到 PY-SUN-PM", draft="PY-SUN-PM"), turn("{confirm}", applications=1), turn("{confirm}", applications=1)]},
    {"id": "policy", "turns": [turn("转班有什么规定？", tools=["search_knowledge_base"], applications=0)]},
    {"id": "catalog", "turns": [turn("有哪些课程可以报名？请查询课程目录", tools=["list_courses"], applications=0)]},
    {"id": "remaining", "turns": [turn("我还剩多少课时？", tools=["get_enrollment"], applications=0)]},
    {"id": "quote", "turns": [turn("转到 PY-SUN-EVE 需要补多少钱？请核算", tools=["check_transfer"], applications=0)]},
    {"id": "no_enrollment", "user": "missing_student", "turns": [turn("帮我转到 PY-SUN-PM", no_draft=True, applications=0)]},
    {"id": "no_seats", "turns": [turn("帮我转到 PY-SUN-AM", no_draft=True, applications=0)]},
    {"id": "different_course", "turns": [turn("帮我转到 DA-SUN-PM", no_draft=True, applications=0)]},
    {"id": "soft_teacher", "turns": [turn("帮我转班，老师最好不变，不想补钱", candidates=["PY-SUN-PM"])]},
    {"id": "hard_teacher", "turns": [turn("帮我转班，老师不能变，不想补钱", candidates=[])]},
    {"id": "clear_fee", "turns": [turn("帮我转到周日晚上，不想补钱", candidates=[]), turn("费用不限", absent=["max_fee_cents"], candidates=["PY-SUN-EVE"])]},
    {"id": "clear_time", "turns": [turn("帮我转到周日晚上，不想补钱", candidates=[]), turn("时间不限", absent=["days", "periods"], candidates=["PY-SUN-PM"])]},
    {"id": "clear_teacher", "turns": [turn("帮我转班，老师不能变，不想补钱", candidates=[]), turn("老师不限", absent=["same_teacher"], candidates=["PY-SUN-PM"])]},
    {"id": "ambiguous_fee", "turns": [turn("帮我转班，不想补钱", slots={"max_fee_cents": 0}), turn("不想补钱，但最多补两百元", slots={"max_fee_cents": 0}, ambiguous=True)]},
    {"id": "correct_time", "turns": [turn("帮我转到周日晚上，最多补200元", candidates=["PY-SUN-EVE"]), turn("改成下午", slots={"periods": ["下午"]}, candidates=["PY-SUN-PM"])]},
    {"id": "reject_afternoon", "turns": [turn("帮我转到周日，最多补200元", applications=0), turn("下午不行", slots={"excluded_periods": ["下午"]}, candidates=["PY-SUN-EVE"])]},
    {"id": "cancel", "turns": [turn("帮我转到 PY-SUN-PM", draft="PY-SUN-PM"), turn("取消办理", applications=0), turn("{first_confirm}", applications=0)]},
    {"id": "vague_confirmation", "turns": [turn("帮我转到 PY-SUN-PM", draft="PY-SUN-PM"), turn("可以", applications=0)]},
    {"id": "status", "turns": [turn("帮我转到 PY-SUN-PM", draft="PY-SUN-PM"), turn("{confirm}", applications=1), turn("我上次申请怎么样了？", tools=["get_application_status"], applications=1)]},
    {"id": "free_no_draft", "turns": [turn("我转到 PY-SUN-PM 是否符合免费转班条件？", assessment="eligible", no_draft=True, applications=0)]},
    {"id": "expensive_not_free", "turns": [turn("我转到 PY-SUN-EVE 是否符合免费转班条件？", assessment="ineligible", no_draft=True)]},
    {"id": "unknown_target", "turns": [turn("帮我转到 PY-UNKNOWN-PM", no_draft=True, applications=0)]},
    {"id": "colloquial", "turns": [turn("我周六上不了课了，想换到周日，不想再掏钱", slots={"max_fee_cents": 0, "days": ["周日"]}, applications=0)]},
    {"id": "budget_words", "turns": [turn("帮我转到周日晚上，最多补两百元", slots={"max_fee_cents": 20000}, candidates=["PY-SUN-EVE"])]},
    {"id": "handoff", "turns": [turn("我要转人工处理", applications=0, agent="escalation")]},
    {"id": "no_history_application", "turns": [turn("帮我查一下之前提交的申请", tools=["get_application_status"], applications=0)]},
]
