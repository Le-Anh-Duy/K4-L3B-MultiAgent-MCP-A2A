"""Light EDA over the L3B case inputs. Run: python data/eda_inputs.py (from repo root)."""

import json
from collections import Counter
from pathlib import Path

cases = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(Path("inputs").glob("*.json"))]
print(f"cases: {len(cases)}")
print("field sets:", Counter(tuple(sorted(c)) for c in cases).most_common())
print("policy:", Counter(c["policy_version"] for c in cases))
print("opened_at:", min(c["opened_at"] for c in cases), "->", max(c["opened_at"] for c in cases))

first_topic = Counter(c["customer_request"]["claims"][0]["topic"] for c in cases)
other_topics = Counter(t["topic"] for c in cases for t in c["customer_request"]["claims"][1:])
print("claim[0] topics:", dict(first_topic))
print("claim[1:] topics:", dict(other_topics))
print("messages:", Counter(c["customer_request"]["message"] for c in cases).most_common())

shapes = Counter()
for c in cases:
    claimed, cands = c["customer_request"]["claimed_order_id"], c["candidate_order_ids"]
    shapes[
        (
            len(cands),
            cands.index(claimed) if claimed in cands else None,
            sum(x.startswith("candidate-") for x in cands),
            c["customer_unique_id_hint"] == "customer-" + claimed[-12:],
        )
    ] += 1
print("(n_candidates, claimed_pos, n_placeholder, hint==customer-<order[-12:]>):", dict(shapes))

print("\ncase -> claim[0] topic, message #")
msgs = {m: i for i, m in enumerate(dict.fromkeys(c["customer_request"]["message"] for c in cases))}
for c in cases:
    r = c["customer_request"]
    print(c["case_id"], c["opened_at"][:10], r["claims"][0]["topic"], msgs[r["message"]])
