"""Run solve_case offline against saved MCP responses (zero audited calls).

Usage (from repo root): python data/replay.py L3B_CASE_001 L3B_CASE_004 ...
Outputs go to data/replay_out/; fails loudly if solve_case needs a tool that was never probed.
"""

import asyncio
import json
import sys
from pathlib import Path

from student_agent.contracts import Contracts
from student_agent.trace import TraceWriter
from student_agent.workflow import solve_case

SAMPLES, OUT = Path("data/mcp_samples"), Path("data/replay_out")


class ReplayGateway:
    async def call(self, tool_name: str, *, case_id: str, **arguments: str) -> dict:
        path = SAMPLES / case_id / f"{tool_name}.json"
        if not path.exists():
            # Treated like a failed call so older snapshots still replay after routing changes.
            raise RuntimeError(f"not probed yet: {case_id}/{tool_name} {arguments}")
        evidence = json.loads(path.read_text(encoding="utf-8"))
        if "error" in evidence:
            raise RuntimeError(evidence["error"])
        return evidence


async def main(case_ids: list[str]) -> None:
    contracts = Contracts(Path("contracts/schemas"))
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "trace.jsonl").unlink(missing_ok=True)
    trace = TraceWriter(OUT / "trace.jsonl", contracts)
    for case_id in case_ids:
        case = json.loads(Path(f"inputs/{case_id}.json").read_text(encoding="utf-8"))
        output = await solve_case(case, ReplayGateway(), trace)
        contracts.validate_output(output, case_id)
        (OUT / f"{case_id}.json").write_text(
            json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        a, p, s = output["assessment"], output["payment_analysis"], output["shipment_analysis"]
        refund = output["financial_resolution"]["recommended_refund_brl"]
        print(
            f"{case_id} claim={case['customer_request']['claims'][0]['topic']} -> "
            f"{a['primary_issue']} {a['secondary_issues']} | {a['case_status']} "
            f"{output['resolution_actions']} refund={refund} "
            f"| ship={s['verdict']} pay={p['verdict']} captured={p['captured_total_brl']} "
            f"| conflicts={len(output['data_conflicts'])} refs={len(output['evidence_refs'])}"
        )


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))
