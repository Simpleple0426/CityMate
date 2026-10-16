"""Role-specific tools; identities are taken from Request, never model arguments."""
from agents.tools import make_tool


def education_tools(store, role):
    def tool(name, description, properties, handler, required=()):
        return make_tool(name, description, properties, handler, list(required))

    catalog = tool("list_courses", "查询演示课程与班级；金额为分。可按课程、日期、时段和基础筛选。", {
        "day": {"type": "string"}, "period": {"type": "string"},
        "course": {"type": "string"}, "foundation": {"type": "integer"},
    }, lambda req, args: store.catalog(**args))
    enrollment = tool("get_enrollment", "查询当前学员演示报名和剩余课时，不接受其他人的身份。", {},
                      lambda req, args: store.enrollment(req.user_id))
    quote = tool("check_transfer", "确定性校验目标班级和费用差额；不提交、不扣款。", {
        "target_id": {"type": "string"},
    }, lambda req, args: store.quote(req.user_id, args["target_id"]), ("target_id",))
    draft = tool("prepare_transfer", "生成持久化转班草稿。仅在用户选定目标班级后调用；不提交申请。完整展示草稿和确认口令。", {
        "target_id": {"type": "string"}, "reason": {"type": "string"},
    }, lambda req, args: store.prepare(req.user_id, req.conv_id, args["target_id"], args["reason"]),
        ("target_id", "reason"))
    status = tool("get_application_status", "查询当前学员演示转班申请；待审核不等于转班完成。", {},
                  lambda req, args: store.applications(req.user_id))
    advice = tool('advise_transfer', '按当前会话持久化要求筛选转班方案，返回硬性条件、偏好、政策依据、无解原因和追问。不会放宽条件或提交。', {},
                  lambda req, args: store.advise_transfer(req.user_id, req.conv_id))
    assessment = tool('assess_free_transfer', '先检索当前课程适用的免费转班政策，再按条款查询当前学员事实，返回逐条证据；没有目标班级时返回缺失事实。', {
        'target_id': {'type': 'string'},
    }, lambda req, args: store.assess_free_transfer(req.user_id, req.conv_id, args.get('target_id')))
    scopes = {
        "course_consultation": [catalog],
        "course_planning": [catalog, enrollment, quote, advice],
        "academic_service": [catalog, enrollment, quote, draft, status, advice, assessment],
        "fees_entitlements": [enrollment, quote, assessment, advice],
    }
    return {spec.name: spec for spec in scopes[role]}
