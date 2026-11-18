<<<<<<< HEAD
from __future__ import annotations

import argparse
import asyncio
import importlib.metadata
import json
import os
import platform
import statistics
import sys
import time
from pathlib import Path
from typing import Any

import httpx2
import psutil
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

from linux_mcp_agent.benchmark import calculate_percentile, evaluate_tool_acceptance


def _tool_specs(log_alias: str | None, log_lines: int) -> list[tuple[str, dict[str, Any]]]:
    specs: list[tuple[str, dict[str, Any]]] = [
        ("get_system_metrics", {}),
        ("get_disk_usage", {}),
        ("list_processes", {"limit": 20, "sort_by": "cpu"}),
    ]
    if log_alias:
        specs.append(("read_allowed_log", {"alias": log_alias, "lines": log_lines}))
    return specs


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    token = os.getenv("MCP_BENCHMARK_ACCESS_TOKEN", "").strip()
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    log_alias = os.getenv("MCP_BENCHMARK_LOG_ALIAS", "").strip() or None
    tool_specs = _tool_specs(log_alias, args.log_lines)
    results: dict[str, Any] = {}

    timeout = httpx2.Timeout(30.0, read=300.0)
    async with (
        httpx2.AsyncClient(headers=headers, timeout=timeout) as http_client,
        streamable_http_client(args.url, http_client=http_client) as transport,
        Client(transport) as client,
    ):
        available = {tool.name for tool in (await client.list_tools()).tools}
        missing = [name for name, _ in tool_specs if name not in available]
        if missing:
            raise RuntimeError(f"Server does not expose required tools: {', '.join(missing)}")

        for tool_name, arguments in tool_specs:
            # One warm-up call is excluded from the measured sample set.
            warmup = await client.call_tool(tool_name, arguments)
            if warmup.is_error:
                raise RuntimeError(f"Warm-up call failed for {tool_name}")

            samples_ms: list[float] = []
            errors = 0
            error_types: dict[str, int] = {}
            for _ in range(args.iterations):
                started = time.perf_counter()
                try:
                    response = await client.call_tool(tool_name, arguments)
                    elapsed_ms = (time.perf_counter() - started) * 1000
                    if response.is_error:
                        errors += 1
                        error_types["McpToolError"] = error_types.get("McpToolError", 0) + 1
                    else:
                        samples_ms.append(elapsed_ms)
                except Exception as exc:  # Report only exception types; never dump response data.
                    errors += 1
                    error_name = type(exc).__name__
                    error_types[error_name] = error_types.get(error_name, 0) + 1

            acceptance = evaluate_tool_acceptance(
                samples_ms,
                errors=errors,
                requested_samples=args.iterations,
                minimum_successful_samples=args.minimum_successful_samples,
                minimum_success_rate_percent=args.minimum_success_rate_percent,
                p95_target_ms=args.p95_target_ms,
            )
            results[tool_name] = {
                "requestedSamples": args.iterations,
                "successfulSamples": len(samples_ms),
                "errors": errors,
                "errorTypes": error_types,
                "p50Ms": calculate_percentile(samples_ms, 0.50),
                "p95Ms": calculate_percentile(samples_ms, 0.95),
                "p99Ms": calculate_percentile(samples_ms, 0.99),
                "minMs": round(min(samples_ms), 3) if samples_ms else None,
                "maxMs": round(max(samples_ms), 3) if samples_ms else None,
                "meanMs": round(statistics.fmean(samples_ms), 3) if samples_ms else None,
                **acceptance,
            }

    required_tools = {
        "get_system_metrics",
        "get_disk_usage",
        "list_processes",
        "read_allowed_log",
    }
    unmeasured_tools = sorted(required_tools.difference(results))
    acceptance_passed = not unmeasured_tools and all(
        result["acceptancePassed"] for result in results.values()
    )

    return {
        "schemaVersion": 2,
        "measuredAtUtc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "endpoint": args.url,
        "authentication": "bearer" if token else "none",
        "iterationsPerTool": args.iterations,
        "acceptancePassed": acceptance_passed,
        "unmeasuredRequiredTools": unmeasured_tools,
        "acceptanceCriteria": {
            "minimumSuccessfulSamples": args.minimum_successful_samples,
            "minimumSuccessRatePercent": args.minimum_success_rate_percent,
            "p95TargetMs": args.p95_target_ms,
            "allFourToolsMeasured": not unmeasured_tools,
        },
        "host": {
            "os": platform.platform(),
            "kernel": platform.release(),
            "architecture": platform.machine(),
            "logicalCpuCores": psutil.cpu_count(logical=True),
            "memoryTotalBytes": psutil.virtual_memory().total,
            "python": sys.version,
            "mcpSdk": importlib.metadata.version("mcp"),
        },
        "tools": results,
        "notes": [
            "Times measure MCP request/response latency and exclude external LLM inference.",
            "The acceptance result requires all four tools to be measured.",
            "Use a valid bearer token for production-mode measurements.",
            "Supply MCP_BENCHMARK_LOG_ALIAS and a token with mcp.logs.read to include read_allowed_log.",
            "A tool fails acceptance when sample coverage, success rate or p95 latency is below its configured gate.",
            "The access token and tool output are never written to the report.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Measure MCP tool latency over Streamable HTTP.")
    parser.add_argument(
        "--url",
        default=os.getenv("MCP_BENCHMARK_URL", "http://127.0.0.1:3002/mcp"),
        help="MCP Streamable HTTP endpoint URL",
    )
    parser.add_argument("--iterations", type=int, default=50)
    parser.add_argument("--log-lines", type=int, default=20)
    parser.add_argument("--minimum-successful-samples", type=int, default=20)
    parser.add_argument("--minimum-success-rate-percent", type=float, default=100.0)
    parser.add_argument("--p95-target-ms", type=float, default=2000.0)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("reports/acceptance/benchmark-latest.json"),
    )
    args = parser.parse_args()
    if args.iterations < 1 or args.iterations > 10000:
        parser.error("--iterations must be between 1 and 10000")
    if not 1 <= args.minimum_successful_samples <= args.iterations:
        parser.error(
            "--minimum-successful-samples must be between 1 and --iterations"
        )
    if not 0 < args.minimum_success_rate_percent <= 100:
        parser.error("--minimum-success-rate-percent must be in (0, 100]")
    if args.p95_target_ms <= 0:
        parser.error("--p95-target-ms must be greater than 0")
    if args.log_lines < 1 or args.log_lines > 200:
        parser.error("--log-lines must be between 1 and 200")

    report = asyncio.run(_run(args))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    if not report["acceptancePassed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
=======
import asyncio
import time
import json
import os
import httpx
import numpy as np

LIVE_HOST = os.getenv("MCP_LIVE_HOST", "https://<IP_CHUA_CO>")
VALID_TOKEN = os.getenv("MCP_VALID_TOKEN", "<TOKEN_CHUA_CO>")
TOOLS_TO_TEST = ["read_log", "get_status", "list_services", "system_metrics"]
ITERATIONS = 50 # Số lần test mỗi tool

async def benchmark_tool(tool_name, client, headers):
    latencies = []
    success_count = 0
    error_count = 0
    
    for _ in range(ITERATIONS):
        start_time = time.perf_counter()
        res = await client.post(f"{LIVE_HOST}/mcp", headers=headers, json={"method": f"tools/{tool_name}"})
        end_time = time.perf_counter()
        
        latencies.append((end_time - start_time) * 1000) # milliseconds
        if res.status_code == 200:
            success_count += 1
        else:
            error_count += 1
            
    return {
        "tool": tool_name,
        "success": success_count,
        "errors": error_count,
        "p50_ms": round(np.percentile(latencies, 50), 2),
        "p95_ms": round(np.percentile(latencies, 95), 2),
        "p99_ms": round(np.percentile(latencies, 99), 2),
        "pass_target": np.percentile(latencies, 95) < 2000
    }

async def run_benchmark():
    headers = {"Authorization": f"Bearer {VALID_TOKEN}"}
    results = []
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
>>>>>>> 8fe752d (chore: save local changes before pulling team-handoff)
