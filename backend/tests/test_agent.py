"""Agent orchestration regressions; scripted model responses are not LLM evaluation."""

import asyncio
import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from openai.types.chat import ChatCompletionMessage

from citymate.assistant import Assistant
from citymate.knowledge import Knowledge


class ScriptedModel:
    """Exercises real orchestration/tools using explicitly synthetic model decisions."""

    def __init__(self, *messages):
        self.messages = iter(messages)
        self.requests = []
        self.chat = SimpleNamespace(completions=self)

    async def create(self, **kwargs):
        self.requests.append(kwargs)
        message = next(self.messages)
        if isinstance(message, Exception):
            raise message
        return SimpleNamespace(
            choices=[SimpleNamespace(message=message)],
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        )

    async def close(self):
        pass


def answer(text="已根据工具结果回答。"):
    return ChatCompletionMessage(role="assistant", content=text)


def calls(*items):
    return ChatCompletionMessage(
        role="assistant",
        tool_calls=[
            {
                "id": f"call_{i}",
                "type": "function",
                "function": {
                    "name": name,
                    "arguments": args if isinstance(args, str) else json.dumps(args),
                },
            }
            for i, (name, args) in enumerate(items)
        ],
    )


def scripted(platform, *messages):
    assistant = Assistant(platform, Knowledge())
    assistant.client = ScriptedModel(*messages)
    return assistant


def test_booking_followup_preserves_role(platform):
    assistant = Assistant(platform, Knowledge())

    async def scenario():
        first = await assistant.chat("u0", "我想预约青岚攀岩")
        second = await assistant.chat("u0", "明天下午六点，2个人", first["conv_id"])
        assert second["agent"] == "booking"

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "name,args,message",
    [
        ("my_orders", {"user_id": "u1"}, "查我的订单"),
        ("claim", {"voucher_id": "v1"}, "抢购优惠券"),
        ("confirm_appointment", {"draft_id": "a" * 32}, "预约"),
        ("my_orders", {}, "推荐咖啡店"),
        ("search_shops", {"budget": -1}, "推荐商户"),
        ("search_shops", {"longitude": 121.4}, "推荐商户"),
        ("search_shops", '{"budget":', "推荐商户"),
        ("prepare_appointment", {"shop_id": "s3", "slot": "明天", "party_size": 2}, "预约"),
        (
            "prepare_appointment",
            {"shop_id": "s3", "slot": "2030-01-01 18:00", "party_size": 21},
            "预约",
        ),
        (
            "prepare_appointment",
            {"shop_id": "s3", "slot": "2030-01-01 18:00", "party_size": 2, "user_id": "u1"},
            "预约",
        ),
    ],
)
def test_invalid_or_unauthorized_tool_has_no_side_effects(platform, name, args, message):
    assistant = scripted(platform, calls((name, args)), answer())
    result = asyncio.run(assistant.chat("u0", message))
    assert "error" in result["tools"][0]["result"]
    assert platform.appointments() == []
    assert platform.r.xlen(platform.key("orders")) == 0


def test_booking_tool_chain_only_creates_draft_and_reports_usage(platform):
    slot = platform.slots("s3")[0]["label"]
    assistant = scripted(
        platform,
        calls(("available_slots", {"shop_id": "s3"})),
        calls(("prepare_appointment", {"shop_id": "s3", "slot": slot, "party_size": 2})),
        answer("请确认预约草稿"),
    )
    result = asyncio.run(assistant.chat("u0", f"预约s3，{slot}，2人"))
    draft = platform.appointments("u0")[0]
    assert draft["status"] == "draft" and draft["party_size"] == 2
    assert platform.slots("s3")[0]["seats"] == 12
    assert result["model_calls"] == 2  # The receipt no longer needs another model response.
    assert result["usage_complete"]
    assert result["token_usage"]["total_tokens"] == 30  # Synthetic usage, not real cost.
    assert result["tools"][1]["arguments"]["slot"] == slot
    assert "当前本地日期时间" in assistant.client.requests[0]["messages"][0]["content"]


def test_confirm_owned_draft_is_idempotent_and_foreign_draft_rejected(platform):
    slot = platform.slots("s3")[0]["label"]
    draft = platform.draft_appointment("u0", "s3", slot, 2)
    assistant = Assistant(platform, Knowledge())

    async def scenario():
        with pytest.raises(HTTPException) as exc:
            await assistant.chat("u1", "确认预约 " + draft["id"])
        assert exc.value.status_code == 404
        for _ in range(2):
            result = await assistant.chat("u0", "确认预约 " + draft["id"])
            assert result["tools"][0]["result"]["status"] == "pending_review"
            assert result["model_calls"] == 0
        assert platform.slots("s3")[0]["seats"] == 12

    asyncio.run(scenario())


def test_tool_outage_is_sanitized_and_model_can_explain(platform, monkeypatch):
    def unavailable(**kwargs):
        raise RuntimeError("SECRET INTERNAL ERROR")

    monkeypatch.setattr(platform, "shops", unavailable)
    assistant = scripted(platform, calls(("search_shops", {})), answer("查询暂不可用"))
    result = asyncio.run(assistant.chat("u0", "推荐商户"))
    assert result["tools"][0]["result"] == {"error": "工具参数无效或暂不可用"}
    assert "SECRET" not in json.dumps(result)
    tool_messages = assistant.client.requests[-1]["messages"]
    assert any(m["role"] == "tool" and "error" in m["content"] for m in tool_messages)


def test_model_failure_releases_lock_and_http_returns_503(client, platform):
    from .conftest import login

    client.app.state.assistant.client = ScriptedModel(RuntimeError("provider unavailable"))
    response = client.post(
        "/chat", headers=login(client), json={"message": "推荐商户", "conv_id": "failure-check"}
    )
    assert response.status_code == 503
    assert "provider unavailable" not in response.text
    assert not list(platform.r.scan_iter(platform.key("lock:chat:*") + "failure-check"))


def test_round_limit_and_per_round_tool_limit(platform):
    batch = calls(*[("search_shops", {}) for _ in range(9)])
    assistant = scripted(platform, batch, batch, batch, batch)
    result = asyncio.run(assistant.chat("u0", "推荐商户"))
    assert result["model_calls"] == 4
    assert len(result["tools"]) == 36
    assert (
        sum("error" in t["result"] for t in result["tools"] if isinstance(t["result"], dict)) == 4
    )
    assert "暂不可用" in result["response"]


def test_successful_tool_loop_stops_at_round_limit(platform):
    batch = calls(("search_shops", {}))
    assistant = scripted(platform, batch, batch, batch, batch)
    result = asyncio.run(assistant.chat("u0", "推荐商户"))
    assert result["model_calls"] == 4
    assert len(result["tools"]) == 4
    assert "上限" in result["response"]


def test_memory_is_bounded_preferences_can_clear_and_expire(platform):
    assistant = Assistant(platform, Knowledge())

    async def scenario():
        first = await assistant.chat("u0", "推荐预算50元的咖啡")
        conv = first["conv_id"]
        for _ in range(13):
            await assistant.chat("u0", "再看看", conv)
        result = await assistant.chat("u0", "不限预算，不限类别", conv)
        key = platform.key(f"chat:u0:{conv}")
        assert result["preferences"] == {}
        assert platform.r.llen(key) == 24
        assert 0 < platform.r.ttl(key + ":role") <= 86400
        assert 0 < platform.r.ttl(key) <= 86400

    asyncio.run(scenario())


def test_repeated_tool_failure_has_actionable_fallback(platform, monkeypatch):
    def unavailable(**kwargs):
        raise RuntimeError("unavailable")

    monkeypatch.setattr(platform, "shops", unavailable)
    batch = calls(("search_shops", {}))
    assistant = scripted(platform, batch, batch, batch, batch)
    result = asyncio.run(assistant.chat("u0", "推荐咖啡店"))
    assert "暂不可用" in result["response"]
    assert "页面" in result["response"]
    assert "轮次" not in result["response"]
    prompt = assistant.client.requests[0]["messages"][0]["content"]
    assert "不是普通商户查询的必填项" in prompt


@pytest.mark.parametrize(
    "message,force_search",
    [
        ("推荐咖啡店", True),
        ("推荐离我最近的咖啡店", False),
        ("推荐我附近的咖啡店", False),
        ("预约咖啡店", False),
    ],
)
def test_tool_choice_only_for_supported_category_search(platform, message, force_search):
    assistant = scripted(platform, answer())
    result = asyncio.run(assistant.chat("u0", message))
    if "附近" in message or "最近" in message:
        assert result["response_kind"] == "capability_notice"
        assert assistant.client.requests == []
        return
    choice = assistant.client.requests[0]["tool_choice"]
    if force_search:
        assert choice == {"type": "function", "function": {"name": "search_shops"}}
    else:
        assert choice == "auto"


def test_same_conversation_rejects_overlapping_turn(platform):
    assistant = Assistant(platform, Knowledge())

    async def scenario():
        lock = platform.r.lock(platform.key("lock:chat:u0:busy"), timeout=30, thread_local=False)
        assert lock.acquire(blocking=False)
        try:
            with pytest.raises(HTTPException) as exc:
                await assistant.chat("u0", "你好", "busy")
            assert exc.value.status_code == 409
        finally:
            lock.release()
        assert (await assistant.chat("u0", "你好", "busy"))["response"]

    asyncio.run(scenario())


def test_draft_receipt_uses_database_values_and_stops_before_hallucinated_policy(platform):
    slot = platform.slots("s3")[0]["label"]
    assistant = scripted(
        platform,
        calls(("prepare_appointment", {"shop_id": "s3", "slot": slot, "party_size": 2})),
        answer("预约已成功，取消必须提前24小时，确认预约 s3"),
    )
    result = asyncio.run(assistant.chat("u0", f"预约s3，{slot}，2人"))
    draft = platform.appointments("u0")[0]
    assert result["model_calls"] == 1
    assert f"确认预约 {draft['id']}" in result["response"]
    assert slot in result["response"] and "2 人" in result["response"]
    assert "待审核" in result["response"] and "尚未提交" in result["response"]
    assert "24小时" not in result["response"]
    assert "确认预约 s3" not in result["response"]
    assert draft["status"] == "draft"
    history = platform.r.lrange(platform.key(f"chat:u0:{result['conv_id']}"), 0, -1)
    assert json.loads(history[-1])["content"] == result["response"]


@pytest.mark.parametrize("status", ["processing", "ready", "cancelled", "rejected", "unknown"])
def test_order_receipt_explains_real_status_without_model_claims(platform, status):
    from citymate.models import Order

    with platform.db.begin() as db:
        db.add(Order(id="mine", user_id="u0", voucher_id="v1", status=status, price_cents=1234))
        db.add(Order(id="foreign", user_id="u1", voucher_id="v1", status="ready", price_cents=999))
    assistant = scripted(platform, calls(("my_orders", {})), answer("预约成功，现在立刻取消即可"))
    result = asyncio.run(assistant.chat("u0", "查我的订单，能取消吗"))
    assert result["model_calls"] == 1
    assert "mine" in result["response"] and "foreign" not in result["response"]
    assert status in result["response"] and "12.34" in result["response"]
    assert "优惠券订单" in result["response"] and "预约" not in result["response"]
    if status == "processing":
        assert "等待" in result["response"] and "不能取消" in result["response"]
    elif status == "unknown":
        assert "不能判断" in result["response"]
    assert platform.orders("u0")[0]["status"] == status


def test_order_failure_cannot_turn_into_fake_success(platform, monkeypatch):
    def unavailable(*args):
        raise RuntimeError("offline")

    monkeypatch.setattr(platform, "orders", unavailable)
    assistant = scripted(platform, calls(("my_orders", {})), answer("订单已取消并完成退款"))
    result = asyncio.run(assistant.chat("u0", "我的订单"))
    assert "无法确认" in result["response"]
    assert "已取消" not in result["response"] and "退款" not in result["response"]


def test_empty_orders_are_not_filled_with_model_inventions(platform):
    assistant = scripted(platform, calls(("my_orders", {})), answer("有一笔待支付订单"))
    result = asyncio.run(assistant.chat("u0", "查订单"))
    assert "暂无" in result["response"]
    assert result["model_calls"] == 1


@pytest.mark.parametrize(
    "message", ["推荐附近咖啡店", "定位后能推荐吗", "哪家店离我最近", "这家店多远"]
)
def test_location_capability_does_not_depend_on_model_promises(platform, message):
    assistant = scripted(platform, answer("允许定位后可以精准推荐最近的咖啡店"))
    result = asyncio.run(assistant.chat("u0", message))
    assert result["model_calls"] == 0 and result["tools"] == []
    assert "不支持" in result["response"] and "即使提供位置" in result["response"]
    assert "精准推荐" not in result["response"]


def test_recent_activity_is_not_mistaken_for_distance(platform):
    assistant = scripted(platform, answer("可以查看优惠页"))
    result = asyncio.run(assistant.chat("u0", "最近有什么优惠"))
    assert result["agent"] == "benefits" and result["model_calls"] == 1


def test_eval_checker_detects_wrong_arguments_missing_draft_and_leaks():
    from evals.run_agent import CANARY, check_turn

    result = {
        "tools": [{"tool": "search_shops", "arguments": {"budget": 100}, "result": []}],
        "response": CANARY,
        "agent": "discovery",
        "sources": [],
    }
    errors = check_turn(
        result, {"arguments": {"search_shops": {"budget": 10000}}, "draft": {"party_size": 2}}, []
    )
    assert set(errors) == {
        "wrong_arguments:search_shops",
        "draft_missing_or_wrong",
        "foreign_data_leaked",
    }


@pytest.mark.parametrize(
    "response,checks,expected",
    [
        (
            "取消请至少提前24小时操作",
            {"response_forbidden": ["提前24小时"]},
            "unsupported_response:提前24小时",
        ),
        (
            "允许使用定位功能，以便更精准推荐",
            {"response_forbidden": ["精准推荐"]},
            "unsupported_response:精准推荐",
        ),
        ("确认预约 s3", {"draft_receipt": True}, "draft_receipt_missing_or_wrong"),
    ],
)
def test_eval_checker_detects_observed_ungrounded_responses(response, checks, expected):
    from evals.run_agent import check_turn

    result = {
        "tools": [
            {
                "tool": "prepare_appointment",
                "result": {"id": "a" * 32, "slot": "2030-01-01 18:00", "party_size": 2},
            }
        ],
        "response": response,
        "agent": "booking",
        "sources": [],
    }
    assert expected in check_turn(result, checks, [])


def test_explicit_topic_switch_and_user_isolation(platform):
    assistant = Assistant(platform, Knowledge())

    async def scenario():
        first = await assistant.chat("u0", "查我的订单")
        same = await assistant.chat("u0", "这个状态是什么意思", first["conv_id"])
        assert same["agent"] == "orders"
        other = await assistant.chat("u1", "这个状态是什么意思", first["conv_id"])
        assert other["agent"] == "discovery"
        switched = await assistant.chat("u0", "推荐咖啡店", first["conv_id"])
        assert switched["agent"] == "discovery"

    asyncio.run(scenario())
