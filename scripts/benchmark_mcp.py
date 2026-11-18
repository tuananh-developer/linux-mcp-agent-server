import asyncio
import json
import os
import time
from typing import Any

import httpx
import numpy as np

LIVE_HOST: str = os.getenv("MCP_LIVE_HOST", "https://<IP_CHUA_CO>")
VALID_TOKEN: str = os.getenv("MCP_VALID_TOKEN", "<TOKEN_CHUA_CO>")
TOOLS_TO_TEST: list[str] = ["read_log", "get_status", "list_services", "system_metrics"]
ITERATIONS: int = 50

async def benchmark_tool(tool_name: str, client: httpx.AsyncClient, headers: dict[str, str]) -> dict[str, Any]:
    latencies: list[float] = []
    success_count: int = 0
    error_count: int = 0
    
    for _ in range(ITERATIONS):
        start_time: float = time.perf_counter()
        res = await client.post(f"{LIVE_HOST}/mcp", headers=headers, json={"method": f"tools/{tool_name}"})
        end_time: float = time.perf_counter()
        
        latencies.append((end_time - start_time) * 1000.0) # milliseconds
        
        if res.status_code == 200:
            success_count += 1
        else:
            error_count += 1
            
    p50 = float(np.percentile(latencies, 50))
    p95 = float(np.percentile(latencies, 95))
    p99 = float(np.percentile(latencies, 99))
            
    return {
        "tool": tool_name,
        "success": success_count,
        "errors": error_count,
        "p50_ms": round(p50, 2),
        "p95_ms": round(p95, 2),
        "p99_ms": round(p99, 2),
        "pass_target": p95 < 2000.0
    }

async def run_benchmark() -> None:
    headers: dict[str, str] = {"Authorization": f"Bearer {VALID_TOKEN}"}
    results: list[dict[str, Any]] = []
    async with httpx.AsyncClient(verify=False) as client:
        for tool in TOOLS_TO_TEST:
            print(f"Benchmarking {tool}...")
            result = await benchmark_tool(tool, client, headers)
            results.append(result)
            
    with open("benchmark.json", "w") as f:
        json.dump(results, f, indent=4)
    print("Benchmark complete. Result saved to benchmark.json")

if __name__ == "__main__":
    asyncio.run(run_benchmark())