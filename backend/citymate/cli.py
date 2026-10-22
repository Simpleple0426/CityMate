import argparse
from sqlalchemy import select
from .runtime import build
from .models import User, Note
from .service import fail


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["seed", "seed-rich", "promote"])
    parser.add_argument("--phone")
    args = parser.parse_args()
    p, engine = build()
    try:
        if args.command == "seed":
            p.seed()
            with p.db() as db:
                exists = db.scalar(select(Note.id).where(Note.user_id == "demo-author"))
            if not exists:
                p.create_note(
                    "demo-author",
                    {
                        "title": "周末，在城市里慢下来",
                        "body": "这是演示探店笔记。梧桐小馆适合聚餐，慢岛咖啡适合读书；出发前记得核对营业时间。",
                        "shop_id": "s1",
                        "images": [],
                    },
                )
            p.dispatch()
            print("Demo data ready; admin phone: 13900000000. Codes appear only in demo mode.")
        elif args.command == "seed-rich":
            import json
            from .demo_data import seed_rich

            print(json.dumps({"inserted": seed_rich(p)}, ensure_ascii=False))
        else:
            with p.db.begin() as db:
                user = db.scalar(select(User).where(User.phone == args.phone))
                if not user:
                    raise ValueError("User must exist before promotion")
                user.role = "admin"
            print("Role updated")
    finally:
        p.close()
        p.r.close()
        engine.dispose()


if __name__ == "__main__":
    main()
