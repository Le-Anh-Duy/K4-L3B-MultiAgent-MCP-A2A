"""Call a few MCP tools for one case and save raw responses to data/mcp_samples/<case_id>/.

Every call is audited against the team's efficiency budget for that case, so probe sparingly.
Usage (from repo root): python data/mcp_probe.py L3B_CASE_004 get_policy get_order ...
"""

import asyncio
import json
import sys
from pathlib import Path

from student_agent.config import Settings
from student_agent.contracts import Contracts
from student_agent.mcp_gateway import connect_gateway


async def main(case_id: str, tools: list[str]) -> None:
    case = json.loads(Path(f"inputs/{case_id}.json").read_text(encoding="utf-8"))
    args = {
        "get_policy": {"policy_version": case["policy_version"]},
        "get_customer_history": {"customer_unique_id": case["customer_unique_id_hint"]},
    }
    order_arg = {"order_id": case["customer_request"]["claimed_order_id"]}
    out = Path("data/mcp_samples") / case_id
    out.mkdir(parents=True, exist_ok=True)
    settings = Settings.load(Path("."))
    async with connect_gateway(
        settings.mcp_endpoint, settings.team_api_key, Contracts(Path("contracts/schemas"))
    ) as gateway:
        for tool in tools:
            try:
                result = await gateway.call(tool, case_id=case_id, **args.get(tool, order_arg))
            except Exception as exc:  # keep probing the remaining tools
                result = {"error": str(exc)}
            (out / f"{tool}.json").write_text(
                json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            print(tool, "ERROR: " + result["error"] if "error" in result else "OK")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1], sys.argv[2:]))
