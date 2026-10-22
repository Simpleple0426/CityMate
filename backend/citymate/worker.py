"""At-least-once stream consumer. SQL transaction + outbox makes retries safe."""

import logging
import signal
import socket
import time
import uuid
from redis.exceptions import ResponseError
from .runtime import build

log = logging.getLogger(__name__)


class Worker:
    group = "order-workers"

    def __init__(self, platform, consumer=None):
        self.p = platform
        self.consumer = consumer or socket.gethostname() + "-" + uuid.uuid4().hex[:8]
        self.stream = platform.key("orders")
        self.running = True
        try:
            platform.r.xgroup_create(self.stream, self.group, id="0", mkstream=True)
        except ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    def process(self, records):
        count = 0
        for record_id, fields in records:
            try:
                if set(fields) != {"order_id", "user_id", "voucher_id"}:
                    # Malformed records are quarantined, not retried indefinitely.
                    self.p.r.xadd(
                        self.p.key("dead-orders"),
                        {"source_id": record_id, "reason": "invalid fields"},
                    )
                    self.p.r.xack(self.stream, self.group, record_id)
                    continue
                self.p.process_order(fields)
                # Crash here is safe: replay observes the committed order.
                self.p.r.xack(self.stream, self.group, record_id)
                count += 1
            except Exception:
                log.exception(
                    "Order processing failed; entry retained in pending list: %s", record_id
                )
        self.p.dispatch()
        return count

    def tick(self, block=1000, reclaim_ms=30000):
        # Reclaim abandoned consumers, then retry this consumer's own pending entries.
        reclaimed = self.p.r.xautoclaim(
            self.stream, self.group, self.consumer, reclaim_ms, "0-0", count=25
        )
        count = self.process(reclaimed[1])
        pending = self.p.r.xreadgroup(self.group, self.consumer, {self.stream: "0"}, count=25)
        for _, records in pending:
            count += self.process(records)
        messages = self.p.r.xreadgroup(
            self.group, self.consumer, {self.stream: ">"}, count=25, block=block
        )
        for _, records in messages:
            count += self.process(records)
        self.p.dispatch()
        self.p.r.set(self.p.key("worker-heartbeat"), str(time.time()), ex=15)
        return count

    def run(self):
        while self.running:
            try:
                self.tick()
            except Exception:
                log.exception("Worker unavailable; retrying")
            time.sleep(0.2)


def main():
    logging.basicConfig(level=logging.INFO)
    p, engine = build()
    worker = Worker(p)

    def stop(*_):
        worker.running = False

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    try:
        worker.run()
    finally:
        p.close()
        p.r.close()
        engine.dispose()


if __name__ == "__main__":
    main()
