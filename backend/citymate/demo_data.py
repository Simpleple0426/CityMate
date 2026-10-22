"""Additive, repeatable sample content for the local CityMate demonstration."""

import json
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select

from .models import User, Shop, Voucher, Note, Like, Follow, Checkin, Slot, Appointment, utcnow


# All businesses, addresses, people and experiences below are fictional.
SHOPS = [
    (
        "弄堂鲜面",
        "美食",
        3200,
        "一碗热汤面配现煎锅贴，适合工作日午餐和独自用餐。",
        "徐汇区桂林路 126 号",
        121.419,
        31.175,
        "07:00–20:30",
        "招牌汤面与小食组合",
        1990,
    ),
    (
        "山野食堂",
        "美食",
        6800,
        "时令蔬菜与谷物饭，提供清淡少油选项，适合轻食午餐。",
        "徐汇区永嘉路 215 号",
        121.454,
        31.211,
        "10:30–21:00",
        "季节轻食单人餐",
        3990,
    ),
    (
        "巷口炭火烧鸟",
        "美食",
        8800,
        "炭火串物与热汤小锅，适合两三位朋友晚间小聚。",
        "静安区延平路 86 号",
        121.438,
        31.234,
        "17:00–23:00",
        "双人串物分享套餐",
        9900,
    ),
    (
        "江岸小笼",
        "美食",
        4500,
        "手工小笼与清汤馄饨，提供早午餐和小份点心。",
        "黄浦区南昌路 58 号",
        121.471,
        31.218,
        "07:30–20:00",
        "小笼与馄饨双拼",
        2590,
    ),
    (
        "南风云南菜",
        "美食",
        11800,
        "菌菇汽锅与香草烤鱼，适合家庭聚餐，可提前备注忌口。",
        "长宁区愚园路 892 号",
        121.425,
        31.222,
        "11:00–22:00",
        "双人云南风味套餐",
        15800,
    ),
    (
        "番茄与罗勒",
        "美食",
        15800,
        "现烤披萨与手工意面，有适合纪念日的双人座位。",
        "徐汇区安福路 168 号",
        121.447,
        31.214,
        "11:30–22:00",
        "双人披萨意面套餐",
        19800,
    ),
    (
        "拾味家宴",
        "美食",
        19800,
        "本帮家常菜与多人分享菜，适合生日和小型家庭聚会。",
        "黄浦区复兴中路 505 号",
        121.468,
        31.216,
        "11:00–21:30",
        "四人家宴体验套餐",
        49800,
    ),
    (
        "一页书咖",
        "咖啡",
        3800,
        "书架与窗边长桌，适合独处阅读；安静区不建议通话。",
        "徐汇区湖南路 65 号",
        121.441,
        31.209,
        "09:00–21:00",
        "手冲咖啡与阅读小点",
        2590,
    ),
    (
        "屋顶日落咖啡",
        "咖啡",
        5800,
        "露台座位与落日色饮品，适合下午聊天，雨天使用室内座位。",
        "静安区陕西北路 228 号",
        121.453,
        31.230,
        "10:00–22:00",
        "双人咖啡甜点下午茶",
        6900,
    ),
    (
        "烘焙研究所",
        "咖啡",
        4800,
        "每日烘焙可颂与司康，可搭配浓缩咖啡或无咖啡因饮品。",
        "长宁区新华路 365 号",
        121.425,
        31.202,
        "08:00–20:00",
        "可颂与拿铁早餐组合",
        2990,
    ),
    (
        "星期六桌游社",
        "娱乐",
        6900,
        "合作推理与轻策略桌游，提供规则讲解，适合三到六人。",
        "静安区胶州路 318 号",
        121.443,
        31.232,
        "13:00–23:00",
        "桌游畅玩三小时",
        3900,
    ),
    (
        "泥好陶艺",
        "娱乐",
        16800,
        "零基础手捏陶杯体验，含工具和基础指导，烧制需另等制作周期。",
        "黄浦区绍兴路 36 号",
        121.465,
        31.211,
        "10:00–20:00",
        "手捏陶杯入门体验",
        9900,
    ),
    (
        "城市回声排练室",
        "娱乐",
        9800,
        "小型音乐体验空间，提供入门节奏课程，适合朋友共同参与。",
        "长宁区定西路 710 号",
        121.421,
        31.210,
        "12:00–22:00",
        "入门节奏体验课",
        5900,
    ),
    (
        "轻跃羽毛球馆",
        "运动",
        6500,
        "室内羽毛球场，适合下班后运动；请自备运动鞋。",
        "徐汇区漕溪北路 355 号",
        121.437,
        31.185,
        "09:00–22:00",
        "单人羽毛球体验场",
        3900,
    ),
    (
        "呼吸瑜伽空间",
        "运动",
        8900,
        "舒缓伸展与基础瑜伽，小班体验，可向老师说明身体状况。",
        "静安区新闸路 1050 号",
        121.454,
        31.239,
        "08:00–21:00",
        "基础伸展单次体验",
        4900,
    ),
    (
        "沿江骑行驿站",
        "运动",
        7800,
        "城市休闲骑行体验，提供头盔和路线说明，出发前检查天气。",
        "黄浦区龙华东路 888 号",
        121.483,
        31.198,
        "08:00–19:00",
        "休闲骑行两小时",
        4500,
    ),
]

AUTHORS = [
    ("小满的觅食地图", "偏爱热汤面与街角小馆，预算友好也能吃得开心。"),
    ("阿屿咖啡日记", "收集窗边座位、手冲香气和安静的周末。"),
    ("林间走走", "每周解锁一条城市散步路线，偶尔停下来吃甜点。"),
    ("米粒与锅气", "两个人的晚餐记录，喜欢分享适合朋友聚餐的地方。"),
    ("周末不宅", "桌游、陶艺、音乐，周末总要试一点新东西。"),
    ("慢跑的橙子", "下班运动一小时，运动后再认真吃饭。"),
    ("小鹿读书角", "书店和咖啡都喜欢，寻找可以慢慢坐着的地方。"),
    ("陈皮的饭搭子", "研究工作日午餐，希望每顿饭都不将就。"),
    ("晴天去骑车", "喜欢江边、微风和不用赶路的下午。"),
    ("手作练习生", "第一次也可以大胆尝试，记录不完美的小作品。"),
    ("露台观察员", "追日落也追甜品，天气好的时候就在外面坐坐。"),
    ("城市散步员", "用脚步认识街区，用小本子记录下一站。"),
]

NOTE_TITLES = [
    "32 元的热汤面，给工作日一点安慰",
    "午餐想清淡一点，我会选这份谷物饭",
    "下班后的三人小聚，烧鸟刚刚好",
    "不用赶时间的早午餐，从一笼小笼开始",
    "把云南风味放进周末双人餐",
    "纪念日不想太正式，披萨和意面也很好",
    "一家人围坐吃饭，比打卡更重要",
    "带一本书，在窗边待一个下午",
    "等日落的时候，咖啡可以慢慢喝",
    "早起十分钟，换一份可颂早餐",
    "桌游新手第一局，先从合作游戏开始",
    "第一次捏陶杯，不圆也很可爱",
    "和朋友一起打节拍，比想象中有趣",
    "下班换上运动鞋，打一小时羽毛球",
    "周末伸展课，让肩颈放松一下",
    "沿江骑两小时，给生活按一下慢放",
    "一个人吃饭也值得认真挑选",
    "预算 100 元以内的聚餐备选清单",
    "安静咖啡馆怎么选？先想好这次想做什么",
    "雨天约会也可以去做一个陶杯",
    "朋友聚会除了吃饭，还有桌游这一站",
    "运动入门不用着急，先找到喜欢的节奏",
    "周末下午茶，给自己留一个空白时段",
    "这周的城市小目标：去一个没去过的街角",
]


def seed_rich(platform):
    """Insert missing fixture rows only; never reset stock, profiles or user activity."""
    p = platform
    if not p.cfg.demo:
        raise RuntimeError("Sample content requires CITYMATE_DEMO=true")
    counts = {}
    now = utcnow()
    today = datetime.now(ZoneInfo(p.cfg.timezone)).date()
    with p.r.lock(p.key("lock:seed-rich"), timeout=120, blocking_timeout=2):
        with p.db.begin() as db:

            def add(model, identity, **values):
                if db.get(model, identity) is not None:
                    return False
                db.add(model(**values))
                counts[model.__tablename__] = counts.get(model.__tablename__, 0) + 1
                return True

            for i, (name, bio) in enumerate(AUTHORS, 1):
                user_id, phone = f"demo-rich-user-{i:02}", f"139100000{i:02}"
                collision = db.scalar(select(User).where(User.phone == phone))
                if collision and collision.id != user_id:
                    raise ValueError(
                        "A sample phone number is already in use; existing account was not changed"
                    )
                add(
                    User,
                    user_id,
                    id=user_id,
                    phone=phone,
                    nickname=name + "·模拟",
                    bio=bio + "（模拟用户，内容仅供功能体验）",
                    role="user",
                )
            db.flush()
            for i, row in enumerate(SHOPS, 1):
                name, category, price, description, address, lon, lat, hours, deal, deal_price = row
                shop_id, voucher_id = f"demo-shop-{i:02}", f"demo-voucher-{i:02}"
                add(
                    Shop,
                    shop_id,
                    id=shop_id,
                    name=name,
                    category=category,
                    description=description + "（虚构演示商户）",
                    address="上海市" + address + "（演示）",
                    longitude=lon,
                    latitude=lat,
                    price_cents=price,
                    hours=hours,
                )
                db.flush()
                add(
                    Voucher,
                    voucher_id,
                    id=voucher_id,
                    shop_id=shop_id,
                    title=deal,
                    rules="模拟优惠，仅用于体验；每人限领一张，不发生支付。到店时段需单独预约，以管理员审核为准。",
                    price_cents=deal_price,
                    stock=20 + (i % 4) * 10,
                    starts_at=now - timedelta(days=1),
                    ends_at=now + timedelta(days=45),
                )
            db.flush()

            shop_ids = [f"demo-shop-{i:02}" for i in range(1, 17)]
            # Also supplement the original four shops, without touching existing seats.
            shop_ids += [s for s in ("s1", "s2", "s3", "s4") if db.get(Shop, s)]
            for shop_id in shop_ids:
                for day in range(1, 8):
                    for hour in ("12:00", "15:00", "18:00"):
                        label = (today + timedelta(days=day)).isoformat() + " " + hour
                        add(Slot, (shop_id, label), shop_id=shop_id, label=label, seats=12)

            for i, title in enumerate(NOTE_TITLES, 1):
                shop_index = ((i - 1) % 16) + 1
                row = SHOPS[shop_index - 1]
                user_id, note_id = f"demo-rich-user-{(i - 1) % 12 + 1:02}", f"demo-note-{i:02}"
                body = (
                    f"这次的城市探索目的地是{row[0]}。{row[3]}\n\n"
                    f"计划预算：人均约 {row[2] // 100} 元。建议先查看营业时间和优惠规则，"
                    "需要到店体验时再选择预约人数与时段；优惠领取和预约是两个步骤。\n\n"
                    "我的小建议：和同行的人先说好预算与时间，比临时决定更从容。"
                    "\n\n【模拟探店手记】以上为虚构体验内容，用于演示发布、点赞与关注功能。"
                )
                if add(
                    Note,
                    note_id,
                    id=note_id,
                    user_id=user_id,
                    shop_id=f"demo-shop-{shop_index:02}",
                    title=title,
                    body=body,
                    images=json.dumps([]),
                    created_at=now - timedelta(hours=i * 5),
                ):
                    p.emit(db, "note", {"note_id": note_id})
            db.flush()

            for i in range(1, 13):
                user_id = f"demo-rich-user-{i:02}"
                for offset in (1, 2, 4):
                    target = f"demo-rich-user-{(i - 1 + offset) % 12 + 1:02}"
                    add(Follow, (user_id, target), user_id=user_id, target_id=target)
                for offset in range(3 + i):
                    day = (today - timedelta(days=offset)).isoformat()
                    add(Checkin, (user_id, day), user_id=user_id, day=day, points=10)

            for i in range(1, 25):
                note_id = f"demo-note-{i:02}"
                author = (i - 1) % 12 + 1
                for offset in range(1, 4 + i % 6):
                    user_id = f"demo-rich-user-{(author - 1 + offset) % 12 + 1:02}"
                    add(
                        Like,
                        (user_id, note_id),
                        user_id=user_id,
                        note_id=note_id,
                        created_at=now - timedelta(minutes=i * 10 - offset),
                    )

            db.flush()
            for i in range(1, 9):
                appointment_id, shop_id = f"demo-appointment-{i:02}", f"demo-shop-{i:02}"
                if db.get(Appointment, appointment_id):
                    continue
                label = (today + timedelta(days=(i - 1) % 7 + 1)).isoformat() + " 18:00"
                status = "pending_review" if i <= 4 else "approved" if i <= 6 else "rejected"
                size = 2 + i % 3
                if status == "approved":
                    slot = db.scalar(
                        select(Slot)
                        .where(Slot.shop_id == shop_id, Slot.label == label)
                        .with_for_update()
                    )
                    if slot.seats < size:
                        continue
                    slot.seats -= size
                add(
                    Appointment,
                    appointment_id,
                    id=appointment_id,
                    user_id=f"demo-rich-user-{i:02}",
                    shop_id=shop_id,
                    slot=label,
                    party_size=size,
                    status=status,
                    decision="模拟预约审核样例，仅供体验。",
                    created_at=now - timedelta(minutes=i * 15),
                )

        # Rebuild indexes from stored rows, preserving user edits and interactions.
        with p.db() as db:
            for shop_id in shop_ids:
                shop = db.get(Shop, shop_id)
                p.r.geoadd(p.key("geo"), [shop.longitude, shop.latitude, shop.id])
            for i in range(1, 25):
                note_id = f"demo-note-{i:02}"
                likes = db.scalars(select(Like).where(Like.note_id == note_id)).all()
                if likes:
                    p.r.zadd(
                        p.key("likes:" + note_id),
                        {
                            like.user_id: like.created_at.replace(tzinfo=timezone.utc).timestamp()
                            * 1000
                            for like in likes
                        },
                    )
        for i in range(1, 17):
            p.initialize_stock(f"demo-voucher-{i:02}")
        for i in range(1, 13):
            user_id = f"demo-rich-user-{i:02}"
            p._sync_follows(user_id)
            p.rebuild_feed(user_id)
            p.checkin_stats(user_id)
        p.dispatch()
    return counts
