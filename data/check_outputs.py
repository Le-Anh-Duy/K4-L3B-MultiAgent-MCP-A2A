"""Offline audit (zero MCP calls).

1. Routing audit: for every case, does _detect find the claim topic in an in-scope purchase?
   If not, solve_case falls back to the latest purchase, which may be the decoy.
2. Proxy scorer: cross-field consistency checks on an outputs directory.

Usage (from repo root): python data/check_outputs.py [outputs_dir]
"""

import json
import sys
from collections import Counter
from pathlib import Path

from student_agent.workflow import _bundles, _detect, _ts

SAMPLES = Path("data/mcp_samples")


def load(case_id: str, tool: str):
    path = SAMPLES / case_id / f"{tool}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8")).get("data")


def routing_audit(cases: list[dict]) -> None:
    print("== routing audit: where is the topic detected?")
    summary = Counter()
    for case in cases:
        cid, topic = case["case_id"], case["customer_request"]["claims"][0]["topic"]
        oid, opened = case["customer_request"]["claimed_order_id"], _ts(case["opened_at"])
        history = (load(cid, "get_customer_history") or {}).get("orders", [])
        payments = load(cid, "get_payment_timeline")
        refunds = [
            e
            for e in (load(cid, "get_refund_timeline") or {}).get("events", [])
            if _ts(e["event_at"]) <= opened
        ]
        bundles = _bundles(
            oid, history, load(cid, "get_order_items"), load(cid, "get_shipment_summary"), payments
        )
        found = []
        for b in bundles:
            in_scope = _ts(b["row"]["order_purchase_timestamp"]) <= opened
            issues = _detect(b, (payments or {}).get("payments", []), refunds)
            found.append((in_scope, issues))
        hit = [i for i, (scope, issues) in enumerate(found) if scope and topic in issues]
        status = "ok" if len(hit) == 1 else "AMBIGUOUS" if hit else "MISS"
        summary[(topic, status)] += 1
        if status != "ok" and topic != "unsupported_claim":
            print(f"  {cid} {topic:24s} {status}: {found}")
    for (topic, status), n in sorted(summary.items()):
        print(f"  {topic:24s} {status:10s} {n}")


def proxy_score(out_dir: Path, cases: dict[str, dict]) -> None:
    print(f"\n== proxy consistency checks on {out_dir}")
    problems = Counter()
    for path in sorted(out_dir.glob("*.json")):
        o = json.loads(path.read_text(encoding="utf-8"))
        rules = (load(o["case_id"], "get_policy") or {}).get("rules", {})
        issue, status = o["assessment"]["primary_issue"], o["assessment"]["case_status"]
        rule = rules.get(issue, {})
        refund = o["financial_resolution"]["recommended_refund_brl"]
        lines = o["financial_resolution"]["refund_lines"]
        parties = o["root_cause_analysis"]["responsible_parties"]
        checks = {
            "status != policy": status != rule.get("case_status"),
            "action != policy": o["resolution_actions"] != [rule.get("recommended_action")],
            "refund != sum(lines)": abs(refund - sum(x["amount_brl"] for x in lines)) > 0.01,
            "no_action but refund": status == "no_action" and refund > 0,
            "seller party without id": any(
                p["party_type"] == "seller" and not p["party_id"] for p in parties
            ),
            "seller party not in seller_ids": any(
                p["party_type"] == "seller"
                and p["party_id"] not in o["affected_entities"]["seller_ids"]
                for p in parties
            ),
            "late_seller but no late_seller_ids": issue == "late_delivery_seller"
            and not o["shipment_analysis"]["late_seller_ids"],
            "late_seller_ids on non-seller issue": issue != "late_delivery_seller"
            and bool(o["shipment_analysis"]["late_seller_ids"]),
            "refundable != captured - refunded": o["payment_analysis"]["captured_total_brl"]
            is not None
            and abs(
                o["payment_analysis"]["refundable_total_brl"]
                - max(
                    o["payment_analysis"]["captured_total_brl"]
                    - o["payment_analysis"]["refunded_total_brl"],
                    0,
                )
            )
            > 0.01,
            "refund > captured": refund > (o["payment_analysis"]["captured_total_brl"] or 0) + 0.01,
            "resolved order also rejected": bool(
                set(o["entity_resolution"]["resolved_order_ids"])
                & set(o["entity_resolution"]["rejected_candidates"])
            ),
            "claim ref not in evidence_refs": any(
                r not in o["evidence_refs"]
                for c in o.get("claim_assessments", [])
                for r in c["evidence_refs"]
            ),
            "duplicate actions": len(o["resolution_actions"]) != len(set(o["resolution_actions"])),
        }
        for name, failed in checks.items():
            if failed:
                problems[(name, issue)] += 1
    if not problems:
        print("  all checks passed")
    for (name, issue), n in sorted(problems.items()):
        print(f"  {n:3d}x {name:38s} [{issue}]")


if __name__ == "__main__":
    cases = [
        json.loads(p.read_text(encoding="utf-8")) for p in sorted(Path("inputs").glob("*.json"))
    ]
    routing_audit(cases)
    proxy_score(
        Path(sys.argv[1] if len(sys.argv) > 1 else "outputs"), {c["case_id"]: c for c in cases}
    )
