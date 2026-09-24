"""Seeds background (non-recorded) data for `docs/assets/demo-light.gif`/`demo-dark.gif`
(TRK-82).

Run on the host with plain python3 (stdlib only, no deps) against the isolated
backend's REST API — see `README.md` in this folder for how that backend is
raised. Creates queue APP ("Checkout service") and nine background tasks spanning
backlog (3) / open (2) / in_progress (2) / waiting (1) / done (1), so the busiest
column already stands close to as tall as the task-page scene (~700px of 800) —
one card per column left the board mostly empty below the fold, and no amount of
cropping fixes that: the board's own column height is `100dvh`-driven regardless
of card count (`ui/src/pages/tasks/ui/tasks-board.tsx`). Titles are kept short
enough to stay one line: a column's own visible height (before it grows its own
scrollbar, `fold:overflow-y-auto`) is close to what three cards need, and one
long enough to wrap to two lines already pushed a four-card backlog into a
scroll of its own on a live check — measured, not calculated. The recording
itself (`demo-recording.spec.ts`) creates exactly ONE more task live, on camera.

    python3 seed-background.py <owner-token-file> <claude-token-file>
"""

import json
import os
import sys
import urllib.error
import urllib.request

BASE = os.environ.get("DEMO_API_URL", "http://localhost:8020")


def call(method: str, path: str, token: str, body: object = None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req) as resp:
            raw = resp.read()
            return resp.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        raw = e.read()
        print(f"HTTP {e.code} on {method} {path}: {raw.decode()}", file=sys.stderr)
        raise


def main() -> None:
    with open(sys.argv[1]) as f:
        owner = f.read().strip()
    with open(sys.argv[2]) as f:
        claude = f.read().strip()

    call(
        "POST",
        "/api/v1/queues",
        owner,
        {
            "key": "APP",
            "title": "Checkout service",
            "description": (
                "Backend that owns cart, pricing and payment webhooks for the online store."
            ),
        },
    )
    print("queue APP created")

    def create_task(**fields):
        _, resp = call("POST", "/api/v1/tasks", claude, fields)
        return resp["data"]["key"]

    def transition(key, to, reason=None):
        body = {"to": to}
        if reason is not None:
            body["reason"] = reason
        call("POST", f"/api/v1/tasks/{key}/transition", claude, body)

    def entry(key, actor_token, type, title, body="", payload=None):
        b = {"type": type, "title": title, "body": body}
        if payload is not None:
            b["payload"] = payload
        call("POST", f"/api/v1/tasks/{key}/entries", actor_token, b)

    # 1. backlog — three cards: the one that was already here, plus two short,
    # single-line ones (see the module docstring for why single-line and why
    # three, not four).
    create_task(
        queue="APP",
        title="Refund flow for partially captured orders",
        description=(
            "A partial capture followed by a refund leaves the order in `paid` "
            "instead of `partially_refunded`."
        ),
        goal="Partial refunds move the order to the right status",
        context=(
            "Capture and refund are separate webhooks; the order state machine "
            "only expects one capture per order today."
        ),
        constraints="No new order statuses — reuse the existing state machine",
        output="Refund handler recomputes status from captured/refunded totals",
        checks=[
            "A partial refund after a partial capture sets `partially_refunded`",
            "Existing refund tests still pass",
        ],
        priority="normal",
        assignee="claude",
    )
    print("APP-1 backlog created")

    create_task(
        queue="APP",
        title="Idle carts never expire",
        description="A cart left untouched for weeks still shows as active and holds stock.",
        goal="An idle cart releases its held stock",
        context="Stock is reserved on add-to-cart, released only on checkout or explicit removal",
        constraints="No change to the reservation model itself",
        output="A cart idle for 24h releases its reservation and is marked abandoned",
        checks=[
            "A cart untouched for 24h releases its stock reservation",
            "Returning to an abandoned cart re-reserves stock if still available",
        ],
        priority="low",
        assignee="claude",
    )
    print("APP-2 backlog created")

    create_task(
        queue="APP",
        title="Coupon codes can stack silently",
        description="Two different coupon codes both apply to the same order with no warning.",
        goal="At most one coupon code applies per order",
        context=(
            "Coupon application has no mutual-exclusion check against a coupon already on the order"
        ),
        constraints="Existing single-coupon orders must not change retroactively",
        output="A second coupon code is rejected with a clear reason, not silently stacked",
        checks=[
            "Applying a second coupon code is rejected, not stacked",
            "Removing the first coupon lets a new one apply",
        ],
        priority="normal",
        assignee="claude",
    )
    print("APP-3 backlog created")

    # 2. open — two cards.
    open_key = create_task(
        queue="APP",
        title="Rate-limit the public orders API",
        description="A single API key can list every order in the store with no throttling.",
        goal="Public order lookups are rate-limited per API key",
        context="Endpoint is `GET /orders`, currently unauthenticated rate-wise",
        constraints="Limit must not affect the internal checkout flow",
        output="429 with Retry-After once a key crosses the limit",
        checks=[
            "A key over the limit gets 429 with Retry-After",
            "Checkout flow traffic is exempt",
        ],
        priority="normal",
    )
    transition(open_key, "open")
    print(f"{open_key} open created")

    saved_cards_key = create_task(
        queue="APP",
        title="Saved cards outlive a reissue",
        description=(
            "A saved card keeps charging after the customer's bank reissues it with a new number."
        ),
        goal="A reissued card is re-verified before it charges again",
        context=(
            "Card tokens don't carry a reissue signal from the payment processor's webhooks yet"
        ),
        constraints="No extra step for customers whose card wasn't reissued",
        output="A reissue webhook flags the saved card for re-verification on next use",
        checks=[
            "A reissued card is re-verified before the next charge",
            "An untouched card keeps charging without extra friction",
        ],
        priority="normal",
        assignee="claude",
    )
    transition(saved_cards_key, "open")
    print(f"{saved_cards_key} open created")

    # 3. in_progress — two cards: the one with a decision/finding trail and a
    # live summary, plus a second, quieter one (no entries — it just sits there,
    # a neighbor `APP-11` will later join without stealing its own history).
    discount_key = create_task(
        queue="APP",
        title="A discount code can be applied twice",
        description=(
            "Submitting the checkout form twice quickly applies the same discount "
            "code twice before the first request commits."
        ),
        goal="A discount code applies at most once per order",
        context="Discount application isn't behind the order's optimistic lock yet",
        constraints="Fix must not add a second round trip to checkout",
        output="Discount application takes the order's version lock",
        checks=[
            "Two concurrent submits apply the discount once",
            "Existing checkout latency budget (p95 < 300ms) is not exceeded",
        ],
        priority="high",
        assignee="claude",
    )
    transition(discount_key, "open")
    transition(discount_key, "in_progress")
    entry(
        discount_key,
        claude,
        "finding",
        "Discount write happens before the order version check, not after",
        "The handler writes the discount row, then checks the order version — "
        "a second request racing in before the first commit passes the same check.",
    )
    entry(
        discount_key,
        claude,
        "decision",
        "Take the order's optimistic lock before writing the discount",
        "Move the version check ahead of the discount write and reject the "
        "second request with `discount_already_applied` instead of a generic 409.",
    )
    call(
        "POST",
        f"/api/v1/tasks/{discount_key}/entries",
        claude,
        {
            "type": "summary",
            "payload": {
                "done": "Lock moved ahead of the discount write, first pass green locally",
                "remaining": "Load test the concurrent-submit case",
                "blockers": "None",
                "next_step": "Run the p95 checkout benchmark",
            },
        },
    )
    print(f"{discount_key} in_progress created")

    inventory_key = create_task(
        queue="APP",
        title="Inventory checks stall checkout",
        description="A slow inventory lookup can hold the checkout form open for several seconds.",
        goal="Checkout never waits on a slow inventory check",
        context="The inventory service is called synchronously from the checkout request path",
        constraints="Checkout must still refuse to sell stock that's actually gone",
        output="Checkout uses a cached stock count with a short TTL instead of a live call",
        checks=[
            "Checkout completes without waiting on a live inventory call",
            "An item that sold out in the last few seconds is still caught before payment",
        ],
        priority="normal",
        assignee="claude",
    )
    transition(inventory_key, "open")
    transition(inventory_key, "in_progress")
    print(f"{inventory_key} in_progress created")

    # 4. waiting, with a blocking question to owner
    uuid_key = create_task(
        queue="APP",
        title="Migrate orders to UUID primary keys",
        description="Sequential order ids leak order volume to anyone who can count.",
        goal="Order ids reveal nothing about volume",
        context="`orders.id` is a bigint read by three services and the analytics export",
        constraints="No downtime longer than five minutes; keep old ids readable for a month",
        output="Orders keyed by UUIDv7, old ids kept in `legacy_id`",
        checks=[
            "Migration runs on a copy of production in under 5 minutes",
            "All three services pass their contract tests",
        ],
        priority="high",
        assignee="claude",
    )
    transition(uuid_key, "open")
    transition(uuid_key, "in_progress")
    entry(
        uuid_key,
        claude,
        "question",
        "Can we take a 5-minute write freeze on Sunday at 02:00 UTC?",
        "The backfill needs one exclusive lock at the end. Everything else runs online.",
        payload={"addressees": ["owner"], "blocking": True},
    )
    call(
        "POST",
        f"/api/v1/tasks/{uuid_key}/entries",
        claude,
        {
            "type": "summary",
            "payload": {
                "done": "Backfill script is ready and tested on a production copy (3 min 40 s)",
                "remaining": "Run it in the freeze window",
                "blockers": "Waiting for the owner on the freeze-window question",
                "next_step": "Once the window is confirmed, schedule the migration job",
            },
        },
    )
    transition(uuid_key, "waiting", reason="Blocked on owner: confirm the 5-minute freeze window")
    print(f"{uuid_key} waiting created")

    # 5. done, closed with two passed verdicts
    rounding_key = create_task(
        queue="APP",
        title="Cart totals ignore currency rounding",
        description=(
            "Multi-currency carts summed line items in float and rounded only at "
            "the very end, so totals could be off by a cent."
        ),
        goal="Cart totals are exact to the minor unit in every supported currency",
        context="Line items are stored in minor units already; only the cart summary used float",
        constraints="No change to the stored line-item amounts",
        output="Cart summary sums minor units as integers",
        checks=[
            "A 3-line JPY cart (no minor unit) totals exactly",
            "A 3-line EUR cart totals exactly to the cent",
        ],
        priority="normal",
        assignee="claude",
    )
    transition(rounding_key, "open")
    transition(rounding_key, "in_progress")
    entry(
        rounding_key,
        claude,
        "finding",
        "Only the summary step used float; line items were always integer minor units",
        "Every stored amount is already an integer minor unit; the summary step "
        "was the only place that cast to float before summing.",
    )
    entry(
        rounding_key,
        claude,
        "decision",
        "Sum minor units as integers, format for display last",
        "Formatting (and its rounding) happens once, on the final integer total, "
        "not on each intermediate line.",
    )
    call(
        "POST",
        f"/api/v1/tasks/{rounding_key}/close",
        claude,
        {
            "summary": {
                "done": "Cart summary sums minor units as integers end to end",
                "remaining": "None",
                "blockers": "None",
                "next_step": "No steps left, the task is closed",
                "unmeasured": "None — both supported currencies in the demo scenario "
                "(JPY, no minor unit, and EUR, with one) are covered by the two checks",
            },
            "verdicts": [
                {
                    "check_no": 1,
                    "outcome": "passed",
                    "evidence": "docker compose run --rm test "
                    "tests/test_cart_totals.py::test_jpy_cart — passed",
                },
                {
                    "check_no": 2,
                    "outcome": "passed",
                    "evidence": "docker compose run --rm test "
                    "tests/test_cart_totals.py::test_eur_cart — passed",
                },
            ],
            "entries": [],
        },
    )
    print(f"{rounding_key} done created")

    print("background seed complete")


if __name__ == "__main__":
    main()
