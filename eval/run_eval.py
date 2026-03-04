#!/usr/bin/env python3
"""
Evaluation harness for the Data Validation Agent.
Runs labeled test samples through the API and computes accuracy metrics.

Metrics computed:
- pass@1: Sample fully correct on first attempt (no retries)
- pass@3: Sample fully correct within 3 retries
- field_accuracy: Percentage of fields correctly extracted
- retry_rate: Average number of correction cycles per sample
"""

import asyncio
import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx


@dataclass
class EvalResult:
    """Result for a single test sample."""
    sample_id: str
    schema_name: str
    passed: bool
    retries_used: int
    field_results: dict[str, bool] = field(default_factory=dict)
    error: str | None = None
    latency_ms: float = 0.0


@dataclass 
class EvalSummary:
    """Aggregate evaluation metrics."""
    total_samples: int = 0
    passed_samples: int = 0
    pass_at_1: float = 0.0
    pass_at_3: float = 0.0
    field_accuracy: float = 0.0
    avg_retries: float = 0.0
    avg_latency_ms: float = 0.0
    
    # Field-level breakdown
    field_counts: dict[str, int] = field(default_factory=dict)
    field_correct: dict[str, int] = field(default_factory=dict)


def normalize_value(val: Any) -> Any:
    """Normalize values for comparison."""
    if val is None:
        return None
    if isinstance(val, str):
        return val.strip().lower()
    if isinstance(val, float):
        return round(val, 2)
    return val


def compare_field(expected: Any, actual: Any, tolerance: float = 0.01) -> bool:
    """Compare expected vs actual field value with tolerance for floats."""
    if expected is None:
        return True  # Skip None expected values
    
    exp_norm = normalize_value(expected)
    act_norm = normalize_value(actual)
    
    if exp_norm is None or act_norm is None:
        return exp_norm == act_norm
    
    # Float comparison with tolerance
    if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
        return abs(float(expected) - float(actual)) <= tolerance * max(abs(float(expected)), 1)
    
    # String comparison (case-insensitive, stripped)
    if isinstance(exp_norm, str) and isinstance(act_norm, str):
        return exp_norm == act_norm
    
    return exp_norm == act_norm


async def run_single_sample(
    client: httpx.AsyncClient,
    base_url: str,
    api_key: str,
    sample: dict
) -> EvalResult:
    """Run a single test sample through the API."""
    sample_id = sample["id"]
    schema_name = sample["schema_name"]
    raw_text = sample["raw_text"]
    expected = sample["expected"]
    
    start_time = time.time()
    result = EvalResult(sample_id=sample_id, schema_name=schema_name, passed=False, retries_used=0)
    
    try:
        # Submit job
        resp = await client.post(
            f"{base_url}/api/v1/process",
            json={"raw_text": raw_text, "schema_name": schema_name},
            headers={"X-API-Key": api_key},
            timeout=60.0
        )
        
        if resp.status_code != 202:
            result.error = f"Submit failed: {resp.status_code} - {resp.text}"
            return result
        
        job_id = resp.json()["job_id"]
        
        # Poll for completion
        max_polls = 30
        for _ in range(max_polls):
            await asyncio.sleep(1.0)
            
            status_resp = await client.get(
                f"{base_url}/api/v1/result/{job_id}",
                headers={"X-API-Key": api_key},
                timeout=30.0
            )
            
            if status_resp.status_code != 200:
                continue
            
            status_data = status_resp.json()
            job_status = status_data.get("status")
            
            if job_status == "COMPLETED":
                result.retries_used = status_data.get("retry_count", 0)
                extracted = status_data.get("structured_output", {}) or {}
                
                # Compare fields
                all_correct = True
                for field_name, expected_val in expected.items():
                    actual_val = extracted.get(field_name)
                    is_correct = compare_field(expected_val, actual_val)
                    result.field_results[field_name] = is_correct
                    if not is_correct:
                        all_correct = False
                
                result.passed = all_correct
                break
            
            elif job_status in ("FAILED", "TIMEOUT", "CANCELLED"):
                result.error = f"Job ended with status: {job_status}"
                break
        else:
            result.error = "Polling timeout"
        
    except Exception as e:
        result.error = str(e)
    
    result.latency_ms = (time.time() - start_time) * 1000
    return result


async def run_evaluation(
    samples_path: str,
    base_url: str = "http://localhost:8000",
    api_key: str = "test-key-123",
    concurrency: int = 3
) -> tuple[list[EvalResult], EvalSummary]:
    """Run evaluation on all samples."""
    
    # Load samples
    with open(samples_path) as f:
        samples = json.load(f)
    
    print(f"Loaded {len(samples)} test samples")
    print(f"Base URL: {base_url}")
    print("-" * 60)
    
    results: list[EvalResult] = []
    semaphore = asyncio.Semaphore(concurrency)
    
    async def run_with_semaphore(client: httpx.AsyncClient, sample: dict) -> EvalResult:
        async with semaphore:
            return await run_single_sample(client, base_url, api_key, sample)
    
    async with httpx.AsyncClient() as client:
        tasks = [run_with_semaphore(client, sample) for sample in samples]
        
        for coro in asyncio.as_completed(tasks):
            result = await coro
            results.append(result)
            
            status = "PASS" if result.passed else "FAIL"
            print(f"  [{status}] {result.sample_id} - retries: {result.retries_used}, latency: {result.latency_ms:.0f}ms")
            if result.error:
                print(f"         Error: {result.error}")
    
    # Compute summary
    summary = EvalSummary(total_samples=len(results))
    
    total_fields = 0
    correct_fields = 0
    total_retries = 0
    total_latency = 0.0
    pass_at_1_count = 0
    pass_at_3_count = 0
    
    for r in results:
        if r.passed:
            summary.passed_samples += 1
            if r.retries_used == 0:
                pass_at_1_count += 1
            if r.retries_used <= 3:
                pass_at_3_count += 1
        
        total_retries += r.retries_used
        total_latency += r.latency_ms
        
        for field_name, is_correct in r.field_results.items():
            total_fields += 1
            summary.field_counts[field_name] = summary.field_counts.get(field_name, 0) + 1
            if is_correct:
                correct_fields += 1
                summary.field_correct[field_name] = summary.field_correct.get(field_name, 0) + 1
    
    if summary.total_samples > 0:
        summary.pass_at_1 = pass_at_1_count / summary.total_samples
        summary.pass_at_3 = pass_at_3_count / summary.total_samples
        summary.avg_retries = total_retries / summary.total_samples
        summary.avg_latency_ms = total_latency / summary.total_samples
    
    if total_fields > 0:
        summary.field_accuracy = correct_fields / total_fields
    
    return results, summary


def print_summary(summary: EvalSummary, results: list[EvalResult]):
    """Print evaluation summary."""
    print("\n" + "=" * 60)
    print("EVALUATION SUMMARY")
    print("=" * 60)
    
    print(f"\nOverall Results:")
    print(f"  Total samples:    {summary.total_samples}")
    print(f"  Passed samples:   {summary.passed_samples}")
    print(f"  Pass rate:        {summary.passed_samples/max(summary.total_samples,1)*100:.1f}%")
    
    print(f"\nKey Metrics:")
    print(f"  pass@1:           {summary.pass_at_1*100:.1f}%")
    print(f"  pass@3:           {summary.pass_at_3*100:.1f}%")
    print(f"  Field accuracy:   {summary.field_accuracy*100:.1f}%")
    print(f"  Avg retries:      {summary.avg_retries:.2f}")
    print(f"  Avg latency:      {summary.avg_latency_ms:.0f}ms")
    
    print(f"\nField-level accuracy:")
    for field_name in sorted(summary.field_counts.keys()):
        count = summary.field_counts[field_name]
        correct = summary.field_correct.get(field_name, 0)
        pct = correct / count * 100 if count > 0 else 0
        print(f"  {field_name:20s}: {correct}/{count} ({pct:.0f}%)")
    
    # Show failures
    failures = [r for r in results if not r.passed]
    if failures:
        print(f"\nFailed samples ({len(failures)}):")
        for r in failures:
            print(f"  - {r.sample_id}: {r.error or 'Field mismatch'}")
            if r.field_results:
                wrong_fields = [f for f, ok in r.field_results.items() if not ok]
                if wrong_fields:
                    print(f"    Wrong fields: {', '.join(wrong_fields)}")
    
    print("\n" + "=" * 60)
    
    # Return exit code
    return 0 if summary.pass_at_3 >= 0.7 else 1


async def main():
    """Main entry point."""
    samples_path = Path(__file__).parent / "test_samples.json"
    
    # Parse CLI args
    base_url = "http://localhost:8000"
    api_key = "test-key-123"
    
    for arg in sys.argv[1:]:
        if arg.startswith("--url="):
            base_url = arg.split("=", 1)[1]
        elif arg.startswith("--key="):
            api_key = arg.split("=", 1)[1]
        elif arg.startswith("--samples="):
            samples_path = Path(arg.split("=", 1)[1])
    
    if not samples_path.exists():
        print(f"Error: Samples file not found: {samples_path}")
        sys.exit(1)
    
    print("=" * 60)
    print("DATA VALIDATION AGENT - EVALUATION HARNESS")
    print("=" * 60)
    
    results, summary = await run_evaluation(
        str(samples_path),
        base_url=base_url,
        api_key=api_key
    )
    
    exit_code = print_summary(summary, results)
    
    # Output JSON for CI integration
    output_path = Path(__file__).parent / "eval_results.json"
    with open(output_path, "w") as f:
        json.dump({
            "summary": {
                "total_samples": summary.total_samples,
                "passed_samples": summary.passed_samples,
                "pass_at_1": summary.pass_at_1,
                "pass_at_3": summary.pass_at_3,
                "field_accuracy": summary.field_accuracy,
                "avg_retries": summary.avg_retries,
                "avg_latency_ms": summary.avg_latency_ms
            },
            "results": [
                {
                    "sample_id": r.sample_id,
                    "schema_name": r.schema_name,
                    "passed": r.passed,
                    "retries_used": r.retries_used,
                    "field_results": r.field_results,
                    "error": r.error,
                    "latency_ms": r.latency_ms
                }
                for r in results
            ]
        }, f, indent=2)
    
    print(f"\nResults saved to: {output_path}")
    sys.exit(exit_code)


if __name__ == "__main__":
    asyncio.run(main())
