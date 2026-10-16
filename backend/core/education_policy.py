"""Shared, conservative rules for the education entry router and offline fallback."""
import re

EDUCATION_INTENTS = {"course_consultation", "course_planning", "academic_service", "fees_entitlements"}


def is_free_assessment(message):
    return '免费' in message and any(w in message for w in ('我', '符合', '可以', '能否'))


def explicit_education_intent(message):
    text = message.strip()
    if re.fullmatch(r"确认提交\s+[a-f0-9]{12}", text) or text in ("取消办理", "取消转班", "取消申请草稿"):
        return "academic_service"
    if any(word in text for word in ("转人工", "找人工", "特殊处理", "我要投诉")):
        return "human_handoff"
    if is_free_assessment(text):
        return 'fees_entitlements'
    # Questions about procedures do not authorize or start an application.
    policy_question = any(w in text for w in ("规定", "政策", "规则", "条件", "流程", "如何申请", "怎么申请", "怎么办理"))
    action = any(w in text for w in ("帮我转", "帮我换", "我要转", "我想转", "想换", "申请转班", "帮我请假", "申请补课", "帮我办理"))
    negated = any(w in text for w in ("不要帮我", "不想转", "不转班", "先别提交", "不要提交"))
    if action and not negated and (not policy_question or "帮我" in text):
        return "academic_service"
    if any(w in text for w in ("申请进度", "申请状态", "上次申请", "申请怎么样", "我的报名", "我能转", "按我的情况", "提交申请", "申请转到")):
        return "academic_service"
    if any(w in text for w in ("多少钱", "补多少", "补差价", "补差额", "收费", "费用", "课时余额", "剩几", "还剩", "权益", "优惠", "订单", "退费", "发票", "扣款")):
        return "fees_entitlements"
    if policy_question or any(w in text for w in ("课程内容", "先修", "上课方式", "零基础能", "课程包含", "课程会讲", "Python课程会讲")):
        return "course_consultation"
    if any(w in text for w in ("推荐", "选课", "选什么", "选哪", "适合我", "只有周末", "筛选", "周日的班", "可选班级")):
        return "course_planning"
    return None


def is_task_continuation(message):
    """Only short selections/confirmations continue implicitly; explicit new topics win."""
    return bool(re.fullmatch(r"(?:周[一二三四五六日天])?(?:上午|下午|晚上)(?:的|班|班级)?[。！!]?|"
                             r"(?:改成|换成|还是)(?:周[一二三四五六日天])?(?:上午|下午|晚上)(?:的|班)?[。！!]?|"
                             r"(?:可以|好的|确认|提交|就这个|继续|不加钱|不要额外花钱)[。！!]?|"
                             r"(?:PY|DA)-[A-Z-]+", message.strip()))
