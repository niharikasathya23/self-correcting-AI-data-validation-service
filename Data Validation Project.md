

<a id="top"></a>

# EXPLANATION

## Table of Contents

- [Opening (30–40 seconds)](#opening)
- [Results (≈50–60 seconds)](#results)
- [Tradeoffs (≈60–70 seconds)](#tradeoffs)
- [Learnings (≈50–60 seconds)](#learnings)
- [Follow Ups](#follow-ups)
- [Correctness, Validation, and Semantics](#correctness-validation-and-semantics)
  - [Why not just use OpenAI function calling or structured outputs?](#why-not-just-use-openai-function-calling-or-structured-outputs)
  - [correctness if the LLM is probabilistic?](#how-do-you-guarantee-correctness-if-the-llm-is-probabilistic)
  - [ weakness of this system?](#whats-the-biggest-weakness-of-this-system)
  - [system fail silently?](#where-can-this-system-fail-silently)
  - [ handle hallucinated fields?](#how-do-you-handle-hallucinated-fields)
  - [Why Pydantic?](#why-pydantic)
  - [Why LanGraph?](#why-langraph)
  - [validation logic has a bug?](#what-if-validation-logic-has-a-bug)
  - [support multiple schemas or document types?](#how-would-you-support-multiple-schemas-or-document-types)
  - [Why not just fine-tune a model?](#why-not-just-fine-tune-a-model)
- [Queue, Reliability, and Failure Recovery](#queue-reliability-and-failure-recovery)
  - [ DB commit succeeds but enqueue fails?](#what-if-the-db-commit-succeeds-but-enqueue-fails)
  - [Dual-Write Problem?](#what-is-the-dual-write-problem)
  - [Worker Crashes mid-job?](#worker-crashes-mid-job)
  - [Failed Jobs?](#failed-jobs)
  - [handle partial failures?](#15-how-do-you-handle-partial-failures)
  - [if Redis goes down?](#16-what-happens-if-redis-goes-down)
  - [if DB goes down?](#17-what-happens-if-db-goes-down)
- [API and Client Interaction](#api-and-client-interaction)
  - [REST vs gRPC?](#why-rest-instead-of-grpc)
  - [polling vs WebSockets?](#why-polling-instead-of-websockets)
  - [When would you switch to WebSockets?](#when-would-you-switch-to-websockets)
- [LLM Layer, Cost, and Throughput](#llm-layer-cost-and-throughput)
  - [semaphore for concurrency?](#why-semaphore-for-concurrency)
  - [handle LLM timeouts?](#how-do-you-handle-llm-timeouts)
  - [model quality drops suddenly?](#what-happens-if-model-quality-drops-suddenly)
  - [ scaling bottleneck and how to improve?](#what-is-the-scaling-bottle-neck-and-how-to-improve)
- [Rate Limiting and Distributed Controls](#rate-limiting-and-distributed-controls)
  - [Why Redis-backed rate limiting and retry budgets?](#why-redis-backed-rate-limiting-and-retry-budgets)
  - [avoid race conditions in rate limiting?](#how-do-you-avoid-race-conditions-in-rate-limiting)
- [Data Layer, Persistence, and Concurrency](#data-layer-persistence-and-concurrency)
  - [Why store every attempt?](#why-store-every-attempt)
  - [ DB goes down mid-processing?](#what-if-db-goes-down-mid-processing)
  - [Why async SQLAlchemy?](#why-async-sqlalchemy)
  - [prevent race conditions on job updates?](#how-do-you-prevent-race-conditions-on-job-updatesisolation-read-commited)
  - [How do you handle concurrent updates?](#how-do-you-handle-concurrent-updates)
- [Platform Choice and Queueing](#platform-choice-and-queueing)
  - [Why Redis vs kafka?](#why-redis)
  - [handle worker autoscaling?](#how-do-you-handle-worker-autoscaling)
- [Scaling and Capacity](#scaling-and-capacity)
  - [Scaling Questions](#scaling-questions)
  - [If this had 10x traffic, what would you change?](#19-if-this-had-10x-traffic-what-would-you-change)
- [Observability and Monitoring](#observability-and-monitoring)
  - [Observability & Monitoring follow-ups](#-10-observability--monitoring)
- [Priority Lists for Interview Prep](#priority-lists-for-interview-prep)
  - [Most Critical Follow-Ups (Top 12 You Must Master)](#-most-critical-follow-ups-top-12-you-must-master)
   - [Tier 1 — Highest Probability (You MUST be ready)](#-tier-1--highest-probability-you-must-be-ready)
  - [Tier 4 — Distributed Systems Follow Ups](#-tier-4--distributed-systems-follow-ups)
- [Behavioral Follow Ups (Do Not Ignore)](#behavioral-follow-ups-do-not-ignore)
  - [What trade-offs did you make?](#21-what-trade-offs-did-you-make)
  - [What Improvements would you make?](#what-improvemnts-would-you-make)
  - [What mistake did you make?](#22-what-mistake-did-you-make)
  - [Rebuild Differently](#rebuild-differently)
  - [What was the hardest design decision?](#23-what-was-the-hardest-design-decision)
  - [Why are you proud of this?](#24-why-are-you-proud-of-this)

---

[⬆ Back to Top](#top)

<a id="opening"></a>

### **INTRO**

At Virufy, I work on an AI-powered healthcare screening platform.
On the backend, I build FastAPI services that handle large audio uploads, process and validate data, and manage state in PostgreSQL.

I also deploy services on AWS using Docker, Lambda, and ECS, and help resolve production issues.

Recently, I integrated GenAI to automate triage, which helped reduce manual review.


“Earlier, during my Master’s at CU Boulder, I built Bilateral Segmentation and Disparity Refinement (BSDR),real-time dense
spatial perception in low-SWaP robots, achieving 11 FPS and improving occlusions and object recognition through

interactive React and Flask dashboards that visualized live perception outputs and system health to help teams debug and tune models in real time

Before that, at Rakuten, I worked on a order management B2B platform, building customer-facing UI features using TypeScript and Angular collaborating closely with product and QA. and iterating quickly in a production environment.

Across these experiences, a few principles guide how I work. I care a lot about ownership and integrity in building systems, focusing on solving real customer problems, and to continuously learning new technologies as systems evolve.

I’m excited about Intuit’s mission of powering prosperity and building products like TurboTax and QuickBooks that help millions of people make better financial decisions. This role also aligns well with my experience building backend services and AI-driven systems, and I’m excited about applying those skills to large-scale platforms that have real user impact.

### **Opening (30–40 seconds)**


The project is a self-correcting AI data validation service that converts unstructured healthcare input into validated, schema-safe structured data using an LLM with deterministic guardrails.

In systems like Virufy, upstream data such as patient symptoms and clinician notes is unstructured, while downstream systems like triage engines and training loops, need deterministic fields. That mismatch was the core problem I wanted to solve.

---

[⬆ Back to Top](#top)

<a id="why-not-just-an-llm"></a>

### **🔹 Why This Needed More Than “Just an LLM” (45 seconds)**

LLMs are very good at interpreting natural language and mapping it into structured JSON. But they’re probabilistic. Even with strong prompts, they can miss required fields, return malformed JSON, or produce logically inconsistent values.

In healthcare, we can’t rely on raw model output. I designed an orchestration layer around the model that enforces deterministic validation and controlled retries.

---
[⬆ Back to Top](#top)
<a id="high-level-architecture"></a>

### **🔹 High-Level Architecture (1.5 minutes)**

When a request comes in, it first hits a FastAPI layer. The request passes through API key authentication and distributed rate limiting using redis so that limits are enforced globally across instances, not per-process.

I also implemented idempotency and content-based deduplication so repeated requests don’t trigger duplicate LLM calls.

Once validated, we create a Job record in the database. Instead of pushing directly to Redis, we use a transactional outbox pattern where the Job and an OutboxEvent are written in the same database transaction, and a dispatcher publishes the job to Redis. This avoids the dual-write problem.

Workers pull jobs from Redis and execute the pipeline. We use Redis LMOVE semantics to atomically move jobs from pending to processing. If a worker crashes, a reaper process re-queues stale jobs. That gives us crash recovery and at-least-once delivery, while idempotency ensures effectively-once behavior.

---

[⬆ Back to Top](#top)

<a id="core-orchestration-logic"></a>

### **🔹 Core Orchestration Logic (2 minutes)**

The processing pipeline is modeled as a  Lanagraph state machine:  
 Extract → Validate → Correct (if needed) → Finalize.

In the Extract state, we build a schema-aware prompt and call the LLM. The model returns structured JSON, which we parse — but we don’t assume it’s correct.

In the Validate state, we deterministically validate the parsed JSON using Pydantic schemas and domain rules. That includes required field checks, numeric ranges, and cross-field consistency. 

If validation fails, we don’t immediately fail the job. Instead, we enter a correction state. We construct a new prompt that includes the original input, the model’s previous output, and structured validation errors. The model is asked to fix only the incorrect fields.

This self-correction loop significantly improves accuracy while maintaining deterministic guarantees.

---

[⬆ Back to Top](#top)

<a id="reliability-and-cost-guardrails"></a>

### **🔹 Reliability & Cost Guardrails (1 minute)**

Because retries increase latency and cost, I added guardrails. Each job has a retry cap, and there’s also a distributed retry budget enforced via Redis. That acts as a circuit breaker — if model quality degrades system-wide, we prevent runaway token usage.

I also support optional fallback models for correction attempts — using a cheaper model after the first extraction to balance quality and cost.

---

[⬆ Back to Top](#top)

<a id="observability-and-auditability"></a>

### **🔹 Observability & Auditability (40–50 seconds)**

Every LLM attempt is stored in an audit table, including the prompt, response, validation results, tokens, and latency. This gives full traceability and replay capability.

The API returns 202 Accepted with a job_id because processing is asynchronous, and clients poll for results.

We also track metrics like token usage, retry rate, validation failures, and latency. I built an offline evaluation harness to measure pass@1 and pass@k on labeled samples to evaluate prompt and model changes.

<a id="results"></a>

### 🔹 Results (≈50–60 seconds)

In offline evaluation on labeled samples, first-pass schema validity was about 86%, which increased to ~98.5% with the correction loop.

At the field level, accuracy reached ~99.5% 

The correction loop averaged 0.22 retries per job, keeping token usage efficient, while idempotency and content-hash deduplication reduced duplicate LLM calls.

End-to-end latency averaged ~5.1 seconds per job.

Most importantly, downstream systems only consumed validated structured data, preventing malformed outputs from propagating into analytics or clinical workflows.


---

[⬆ Back to Top](#top)

<a id="tradeoffs"></a>

### 🔹 Tradeoffs (≈60–70 seconds)

There were important tradeoffs.

First, accuracy versus latency and cost. 

I implemented a self-correction loop where the LLM output is validated against strict schemas and retried if validation fails. This improves structured data reliability, but it increases latency and token usage. To control that, I added bounded retries, retry budgets, and fallback models so worst-case cost remains predictable.

Second, reliability versus system complexity. I

Instead of pushing jobs directly to Redis, I used a transactional outbox pattern. This ensures the job is never lost if a failure occurs between the database write and queue enqueue, though it adds extra components like a dispatcher.

Third, API simplicity versus client complexity.

I chose an asynchronous job-based API with polling. This keeps the backend resilient for long-running LLM workflows, but clients must poll for results.

---

[⬆ Back to Top](#top)

<a id="learnings"></a>

### 🔹 Learnings (≈50–60 seconds)

The biggest learning was that LLM systems must be treated as unreliable external dependencies — similar to distributed services.

Early on, I realized that prompt quality alone isn’t enough. Deterministic validation and circuit breakers are essential.

I also learned that cost controls is a reliability dimension must be built into the architecture from day one. But without retry caps and global budgets, token usage can grow quickly during degradation scenarios.

Finally, observability changed everything. Metrics like retry rates and tokens per job allowed me to iterate based on data instead of intuition.

<a id="follow-ups"></a>

# Follow Ups

<a id="correctness-validation-and-semantics"></a>

## Correctness, Validation, and Semantics

### Why not just use OpenAI function calling or structured outputs?

Function calling guarantees that the output conforms to a declared JSON structure. It helps ensure the response is well-formed and matches the expected field layout.

However, it does not ensure that the values themselves are logically correct.

For example, a response can include all required fields but still contain incorrect or inconsistent data. A numeric field may satisfy type constraints yet violate domain expectations. 

Function calling addresses structural validity. My validation layer enforces domain integrity.

In healthcare workflows, downstream systems depend on data that is not just well-structured, but trustworthy. Deterministic validation ensures the output satisfies business rules before it is consumed.
[⬆ Back to Top](#top)
### How do you guarantee correctness if the LLM is probabilistic?”

I don’t guarantee that the LLM is correct.  
 I guarantee that only validated data leaves the system.

The model generates a candidate structured output, but that output is always passed through deterministic validation before being accepted. We enforce schema rules, required fields, numeric constraints, and cross-field consistency checks.

If validation fails, the system either corrects the output through a structured retry loop or marks the job as failed. Downstream systems never consume raw model output.

So the correctness guarantee doesn’t come from the model — it comes from the validation boundary around it.
[⬆ Back to Top](#top)
### “What’s the biggest weakness of this system?”

The biggest weakness is that correctness is bounded by the validation rules we define.

The system guarantees that outputs satisfy structural and business constraints we explicitly encode. But if a domain rule is missing or incomplete, the model can produce semantically incorrect data that still passes validation.

In other words, validation coverage is finite. As business logic grows more complex — for example, multi-currency handling, edge-case medical inputs, or evolving domain requirements — the validation layer must evolve with it.

A second weakness is latency. Correction loops improve accuracy but increase response time and token usage. That’s a deliberate tradeoff, but it limits real-time use cases.

So the system is strong on safety and reliability, but it requires ongoing rule maintenance and monitoring to remain correct over time.

### “Where can this system fail silently?”

There are a few places where silent failures could occur if we’re not careful.

First is **validation coverage gaps**. The system guarantees that outputs satisfy the rules we encode, but if a business rule is missing or incomplete, the model could produce logically incorrect data that still passes validation. That would silently propagate incorrect structured data downstream.

Second is **model drift or quality degradation**. If the model starts producing worse outputs but still passes validation, the system might not immediately detect it. That’s why monitoring metrics like pass@1 rate and validation error distribution is important.

Third is **schema evolution issues**. If the schema changes but older jobs or clients still use the previous version, mismatches could cause incorrect interpretation of fields without immediately failing.

Fourth is **queue recovery edge cases**. If the reaper logic incorrectly requeues a job that actually finished but didn’t update status yet, the job could run twice. Application-level idempotency protects the final result, but it could still waste compute.l
[⬆ Back to Top](#top)
### How do you handle hallucinated fields?

Schema validation – Model output must match a predefined schema (e.g., using Pydantic). Invalid or unexpected fields are rejected.

Deterministic validation – Business rules check types, ranges, and required fields to detect incorrect values.

Correction loop – If validation fails, the model receives the errors and is asked to regenerate only the invalid parts.

Retry limits – A retry budget prevents infinite correction attempts.

Fallback handling – If corrections keep failing, the system flags the job or sends it for manual review

[⬆ Back to Top](#top)

### Why Pydantic?

Pydantic provides **strong typed schema validation with minimal boilerplate** and integrates naturally with Python and FastAPI.

It automatically enforces:

* type validation

* required fields

* value constraints

* structured error messages

Those structured errors are especially useful because they can be passed back to the model in the **correction loop** to guide fixes.

So Pydantic gives both **strict validation and machine-readable error feedback**.

## **Why LanGraph?**

LangGraph is a framework for building state-machine-based workflows around LLM applications. Instead of writing a linear chain of calls, it lets you define nodes representing steps in the pipeline and edges that control how the system transitions between them.

In my system, the workflow naturally fits that model: we extract structured data, validate it, and if validation fails we enter a correction step before finalizing the result. That kind of conditional looping is much easier to represent as a state machine than with nested retry logic.

f I implemented this with regular Python code, it would quickly turn into nested retry loops and complex conditional logic, which becomes harder to maintain and reason about as the pipeline grows.

I chose LangGraph because it keeps the orchestration explicit and modular, which makes the pipeline easier to extend and debug.

Compared to heavier orchestration tools like Airflow or Temporal, LangGraph is lightweight and designed specifically for LLM-driven application workflows rather than large data pipelines.


[⬆ Back to Top](#top)

### What if validation logic has a bug?

validation logic has a bug, the system could either reject correct outputs or accept incorrect ones.

To reduce that risk, there are a few safeguards.

First, the validation layer is **covered by unit tests**, especially for domain rules and edge cases.

Second, we maintain **evaluation datasets** that run through the pipeline periodically. If validation behavior changes unexpectedly, metrics like pass rate or failure distribution will surface it.

Third, because every attempt is logged — including validation errors and model responses — we can quickly diagnose whether failures are caused by model behavior or validator logic.

So while validator bugs are possible, testing, evaluation harnesses &  observability,help detect them quickly.

Schema correctness is tested through unit tests for validation rules, edge-case tests, and evaluation datasets with labeled inputs to verify the pipeline produces valid outputs.

### “How would you support multiple schemas or document types?”

The system is designed to be **schema-driven**, so supporting multiple document types mainly requires adding new schemas and prompt templates rather than redesigning the architecture.

Each schema is defined in the **data\_schemas layer using Pydantic models**, which describe the expected fields, types, and validation rules. When a request comes in, the client specifies the **schema type** (for example, respiratory assessment, invoice, or survey).

The pipeline then loads the corresponding schema and generates a **schema-aware prompt** dynamically. That prompt instructs the LLM to extract data according to that specific schema.

During validation, the same schema is used to deterministically check the output and enforce business rules.

Because the orchestration logic — extract → validate → correct → finalize — is schema-agnostic, the system can support new document types simply by:

1. Adding a new Pydantic schema

2. Adding domain validation rules

3. Creating the associated prompt template

This makes the system **extensible without changing the pipeline itself**.
[⬆ Back to Top](#top)
### “Why not just fine-tune a model?”

Fine-tuning can improve extraction quality, but it doesn’t eliminate the need for deterministic validation.

Even a fine-tuned model can still produce:

* malformed outputs

* logically inconsistent values

* domain rule violations

So validation remains necessary regardless of model training.

Additionally, fine-tuning introduces **data collection, labeling, retraining pipelines, and model version management**, which increases operational complexity.

My design treats the LLM as a probabilistic component and enforces correctness through deterministic validation, which works across models and providers.

That said, fine-tuning could be used later to **improve first-pass accuracy and reduce correction loops**, but it would complement this architecture rather than replace it.

[⬆ Back to Top](#top)

<a id="queue-reliability-and-failure-recovery"></a>

## Queue, Reliability, and Failure Recovery

### “What if the DB commit succeeds but enqueue fails?”

**Answer**

This is exactly the failure the **transactional outbox pattern** is designed to solve.

Instead of writing the job to the database and pushing to Redis in two separate steps, the API writes both the **Job record and an OutboxEvent record in the same database transaction**.

If the transaction commits, both records exist in the database. The enqueue operation is then performed by a separate **outbox dispatcher** process that continuously scans the outbox table and pushes jobs to Redis.

So even if the Redis enqueue fails temporarily — for example due to network issues — the outbox record still exists in the database. The dispatcher will retry until the job is successfully pushed to the queue.

This guarantees that **a committed job will eventually be enqueued**.

[⬆ Back to Top](#top)

### What is the Dual-Write Problem?

The **dual-write problem** happens when a system tries to write to **two different systems separately** (for example a database and a queue), and one write succeeds while the other fails.

### Worker Crashes mid-job?

If a worker crashes mid-job, the system assumes at-least-once execution and relies on recovery mechanisms to avoid data loss.

When a worker picks up a job, it uses Redis `LMOVE` to atomically move the job from the **pending** list to a **processing** list. So even if the worker crashes during execution, the job is not lost — it remains in the processing list.

A reaper process periodically scans the processing list for stale jobs. If a job has exceeded a timeout or has no active heartbeat, it gets moved back to pending so another worker can retry it.

At the queue level, this gives us at-least-once delivery.

At the application level, we enforce idempotency. The job has a unique ID in the database, and final writes are guarded by job status. So even if the job executes twice, we don’t duplicate the final result. ( Before writing the structured output, the pipeline checks the job’s status. If the job is already marked `COMPLETED`, we do not overwrite it. That prevents duplicate final writes.)

So a crash causes a retry — not data loss — and downstream systems still only see validated output.

[⬆ Back to Top](#top)

**BLPOP simply removes a job from the queue and gives it to the worker. If the worker crashes after popping but before completing the job, that job is lost because it’s no longer in Redis.**

**LMOVE, on the other hand, atomically moves the job from a “pending” list to a “processing” list in a single operation.** That means the job always exists in Redis — it’s either pending or being processed. If the worker crashes mid-execution, the job remains in the processing list and a reaper can move it back to pending for retry.

### Failed Jobs?

Failed jobs are captured through a **dead-letter mechanism**. When a job exceeds its retry limit, times out, or encounters a non-recoverable error, it is marked with a `FAILED` status in the database and its job ID is stored in a **dead-letter queue (DLQ)**.

To replay a failed job, the system exposes an operational endpoint or internal tool that retrieves the failed job record, resets its status to `PENDING`, and pushes the job ID back into the queue for reprocessing.

Because every job stores the **original input and the full attempt history**, we can replay it deterministically with the same data or after making improvements, such as updating prompts or validation rules.
[⬆ Back to Top](#top)
### **15️⃣ “How do you handle partial failures?”**

* Job status transitions

* Dead-letter queue

* Replay endpoint

* Idempotent reprocessing

### **16️⃣ “What happens if Redis goes down?”**

* API can still accept jobs

* Outbox table buffers events

* Dispatcher resumes when Redis back

For rate limiting and retry budgets, the system can fall back to local in-memory limits, which reduces protection slightly but keeps the system operational

### **17️⃣ “What happens if DB goes down?”**

The database is the source of truth in this system, so if it becomes unavailable, the system prioritizes safety over continued processing.

First, the API layer will fail fast when it cannot create new job records. That prevents requests from entering the system in an inconsistent state.

No partial Enqueue

For workers that are already processing jobs, any attempt to write attempts, status updates, or results will fail. In that case, the worker will retry the database write with backoff. If the database remains unavailable, the job will eventually be retried later through the queue.

Because the queue uses pending and processing lists, jobs are not lost even if workers crash while waiting for the database. The reaper process can requeue stale jobs once the system recovers.

After LLM call but before DB write: we may “waste” that LLM call, but we still preserve correctness because downstream only reads from DB. When DB recovers, job is retried.

Once the database comes back online, the system resumes normal operation and workers continue processing jobs from the queue.

<a id="api-and-client-interaction"></a>

## API and Client Interaction

### “Why REST instead of gRPC?”

I chose REST primarily for interoperability and simplicity. This service is intended to be consumed by a variety of clients — web apps, internal tools, and potentially third-party systems — and REST over HTTP is universally supported.

Since the API mainly handles job submission and result retrieval, the performance benefits of gRPC weren’t critical. The payload sizes are small and the interaction pattern is request–response.

gRPC would make more sense if we had **high-frequency internal service-to-service communication** or needed **streaming responses**. But for an external-facing API where ease of integration matters, REST is the more practical choice.
[⬆ Back to Top](#top)
### “Why polling instead of WebSockets?”

I chose polling mainly because the workflow is job-based and completion times are unpredictable. The client submits a request, receives a `job_id`, and checks the status periodically. Polling keeps the API stateless and easy to scale behind load balancers without maintaining long-lived connections.

WebSockets would require managing persistent connections, handling reconnections, and coordinating state across multiple API instances. For workloads where completion events are relatively infrequent, that added complexity usually isn’t justified.

Polling also works well with simple backoff strategies so clients don’t overwhelm the API.
[⬆ Back to Top](#top)
### “When would you switch to WebSockets?”

I would switch if **real-time responsiveness becomes important** or if **clients need immediate push notifications** when jobs complete.

For example:

* If job completion latency must be **sub-second**

* If the UI needs **live updates or progress streaming**

* If polling traffic becomes inefficient at scale

* If jobs produce **incremental streaming outputs**

In those cases, WebSockets or server-sent events would reduce unnecessary polling traffic and provide better real-time UX.

<a id="llm-layer-cost-and-throughput"></a>

## LLM Layer, Cost, and Throughput

### Why semaphore for concurrency?

A semaphore limits how many operations can run concurrently. I use it to cap the number of simultaneous LLM calls so we don’t exceed provider rate limits or overwhelm the external API.
[⬆ Back to Top](#top)
### How do you handle LLM timeouts?

###  “What happens if model quality drops suddenly?”

If model quality drops, the first signal we would see is an increase in **validation failures and retry rates**, because the deterministic validator sits between the model and downstream systems.

Since we track metrics like **retry count, pass@1 rate, and validation error frequency**, we can detect quality degradation quickly.

Once detected, there are a few mitigation steps:

First, the **global retry budget acts as a circuit breaker**. If the model starts producing many invalid outputs, the system prevents runaway correction loops and fails jobs gracefully instead of burning unlimited tokens.

Second, we can **switch to a fallback model or provider** through the provider abstraction layer.

Third, we can **roll back prompt versions**, since prompts are versioned and evaluated offline through the evaluation harness.

[⬆ Back to Top](#top)

### What is the scaling bottle neck and how to improve?

The main scaling bottleneck is the LLM inference layer because model calls are slow, expensive, and rate-limited by the provider. So my strategy is to **reduce the number of model calls and control concurrency** rather than just adding more workers.

First, I reduce unnecessary calls through **idempotency and content-hash deduplication**. If the same input arrives again, the system returns the existing result instead of calling the model again.

Second, I **improve first-pass accuracy** to avoid correction loops. Better prompts and schema hints reduce retries, which directly reduces both latency and token usage.

Third, I implement **concurrency control using a semaphore** so workers don’t exceed provider rate limits or overload the model API.

Fourth, I use **model tiering**. The first extraction may use a higher-quality model, but correction attempts can use a cheaper or faster fallback model.

Finally, I scale horizontally at the worker layer while respecting provider limits, and if throughput requirements grow significantly, we could add **multi-provider routing or self-hosted models** to distribute inference loa

Latency fast
  
**Scale data layer:** move to Postgres, add indexes, tune pool sizes; use read replicas for result polling if needed.

<a id="rate-limiting-and-distributed-controls"></a>

## Rate Limiting and Distributed Controls

### Why Redis-backed rate limiting and retry budgets?”

I used **Redis-backed rate limiting and retry budgets** because the system can run across **multiple API and worker instances**, so limits need to be enforced **globally**, not per process.

If rate limits were stored in memory, each instance would track its own counters. That would allow clients to bypass limits simply by hitting different servers. By storing counters in Redis, every instance reads and updates the **same shared state**, so limits are enforced consistently across the whole deployment.

Redis is also a good fit because it supports **atomic operations with very low latency**, which makes it ideal for implementing distributed counters and token-bucket style rate limiting.

The same idea applies to the **retry budget**. Correction loops can generate additional LLM calls, so we maintain a global retry budget in Redis to prevent runaway token usage if model quality degrades. This acts like a **distributed circuit breaker** across all workers.

* What rate limiting algorithm are you using?

**Fixed Window**

* Count requests in a fixed time window (e.g., 100 requests per minute).

* Simple to implement using Redis counters \+ TTL.

* **Problem:** bursts at window boundaries (e.g., 100 at 12:00:59 and 100 at 12:01:00).

**Sliding Window**

* Tracks requests over a moving time window.

* More accurate because it smooths boundary bursts.

* **Tradeoff:** more expensive to compute (often uses timestamps or sorted sets).

**Token Bucket**

* Requests consume tokens from a bucket that refills at a steady rate.

* Allows **short bursts** while maintaining an average rate.

* Commonly used for APIs because it balances flexibility and protection.

  Fixed window is simplest but bursty, sliding window is most precise but heavier, and token bucket allows controlled bursts while maintaining a steady rate

### How do you avoid race conditions in rate limiting?

Race conditions are avoided by using **Redis atomic operations**.

For example, when a request arrives, the system performs an atomic increment on the counter associated with the API key and checks whether the value exceeds the allowed limit. Because the increment and read are handled atomically by Redis, concurrent requests cannot bypass the limit.

[⬆ Back to Top](#top)

<a id="data-layer-persistence-and-concurrency"></a>

## Data Layer, Persistence, and Concurrency

### Why store every attempt?

**Auditability:** we can reconstruct exactly what the model saw and returned (prompt, raw output, parsed JSON, validation errors).

**Debuggability:** quickly tell if failures come from prompt/model drift vs validator bugs.

**Replay \+ iteration:** after improving prompts/rules, we can replay failed jobs and compare attempts.

**Metrics:** tokens/latency per attempt helps cost \+ performance tuning.

[⬆ Back to Top](#top)

### What if DB goes down mid-processing?

**During status/attempt writes:** worker can’t persist progress → it should **fail the job gracefully** and retry later. In practice, we implement:

* DB write retries with backoff

* if DB remains down → stop taking new jobs (fail fast) \+ keep jobs in “processing/pending” to retry once DB returns

  **After LLM call but before DB write:** we may “waste” that LLM call, but we still preserve correctness because downstream only reads from DB. When DB recovers, job is retried.  
  Key point: **DB is the source of truth**, so if DB is unavailable we prefer to **pause/slow processing** rather than return partial results.

### Why async SQLAlchemy?

For persistence, the system uses PostgreSQL with SQLAlchemy’s async ORM. I chose a relational database because the system has well-defined entities like jobs, attempts, and outbox events, and those relationships benefit from structured schemas, constraints, and transactional guarantees.

The job lifecycle — including statuses like pending, extracting, validating, and completed — is naturally modeled with relational tables. Using SQL also lets us enforce data integrity and support the transactional outbox pattern, which requires atomic writes between the job record and the enqueue event.

I used SQLAlchemy’s async engine so database operations wouldn’t block the event loop. Since the API and workers handle many concurrent requests, asynchronous DB access allows the system to process multiple jobs simultaneously without tying up threads during network I/O.

So the combination of PostgreSQL and async SQLAlchemy gave us strong consistency guarantees, structured data modeling, and high concurrency support for the pipeline.

If they ask “Why not NoSQL?”

Because the data model is structured and transactional — jobs, attempts, and outbox events have clear relationships. SQL makes those constraints and joins easier, and it supports atomic transactions which are important for reliability patterns like the transactional outbox.

### How do you prevent race conditions on job updates?isolation-Read commited

Use **atomic queue handoff** (pending \-\> processing) so one worker owns a job at a time.

* Use **idempotency key \+ input dedup** to avoid duplicate job creation/processing.  
  * Use **transactional outbox** to avoid DB/queue dual-write inconsistency.  
  * Use **reaper recovery** for worker crashes (stale processing jobs get re-queued).  
  * Check **terminal states** (cancel/timeout/completed) in pipeline flow.
* **What more you could do**  
  * Add **optimistic locking** on Job rows (version column, compare-and-swap updates).  
  * Add **conditional status transitions** (only allow legal transitions; reject stale updates).  
  * Add **DB row locking** (SELECT ... FOR UPDATE) in critical update paths (Postgres mode).

### How do you handle concurrent updates?

Main strategy: **design so concurrency doesn’t happen**, and guard the edges.

* Prevent two workers from owning the same job via queue semantics (pending → processing).

* If it still happens (requeue/reaper edge case), then:

  * final write is protected by **idempotent finalization** (only finalize if not already COMPLETED)

  * attempts are **append-only**, so duplicates don’t corrupt state

  * use **atomic/conditional DB updates** or `FOR UPDATE` to ensure only one worker transitions to COMPLETED.

[⬆ Back to Top](#top)

<a id="platform-choice-and-queueing"></a>

## Platform Choice and Queueing

### Why Redis?”

I chose Redis mainly because it provides **fast, simple, in-memory data structures that work well for building lightweight distributed queues**.

In this system the queue only needs to handle **job IDs and state transitions**, so Redis lists are sufficient and extremely fast. Using Redis also allows multiple workers to pull jobs concurrently with very low latency.

[⬆ Back to Top](#top)

[⬆ Back to Top](#top)

Another reason is **reliable queue semantics**. Redis supports operations like `LMOVE`, which atomically moves jobs from a *pending* list to a *processing* list. That makes it possible to implement crash recovery — if a worker fails mid-job, the job can be re-queued safely.

Redis also fits well operationally because it already supports **distributed coordination patterns** such as rate limiting, retry budgets, and counters, which I’m also using in the system.

Finally, the system doesn’t require the heavier guarantees of systems like Kafka. The workload is task execution rather than event streaming, so Redis gives a simpler operational model with very good performance.

Processing directly in threads, like FastAPI BackgroundTasks, works for small setups but doesn’t scale well. The work runs inside the API process, so if the server crashes or restarts, in-flight jobs can be lost, and job throughput becomes tied to API instances.

Celery is a solid distributed task framework, but it introduces extra operational overhead with its own worker system, broker setup, and retry semantics. Since the pipeline already handles orchestration, retries, and validation, Celery would add complexity without much benefit.

Kafka is optimized for high-throughput event streaming and durable logs. Our workload is task execution with short-lived jobs, so Kafka would add unnecessary infrastructure complexity compared to a simpler Redis queue.

### How do you handle worker autoscaling?

Worker autoscaling is based on queue backlog and latency metrics. When the pending queue grows, we add more worker instances; when it shrinks, we scale down. Since workers are stateless, horizontal scaling is straightforward, though we still enforce concurrency limits to respect LLM provider rate limits.

[⬆ Back to Top](#top)

<a id="scaling-and-capacity"></a>

## Scaling and Capacity

### Scaling Questions

These are almost guaranteed:

How many users can this handle?

How do you handle LLM rate limits?

Would you batch LLM calls?

How would you isolate tenants?

### **19️⃣ “If this had 10x traffic, what would you change?”**

* Replace polling with webhooks

* Add read replicas

* Separate metrics service

* Dedicated rate-limit cluster

* Batch LLM calls

<a id="observability-and-monitoring"></a>

## Observability and Monitoring

### 🔥 🔟 Observability & Monitoring

Since you have metrics:

* What metrics matter most?

* How do you detect prompt regression?

* How do you track token cost?

* How do you alert on anomaly?

* How do you measure success rate?

* How do you detect model drift?

* What dashboards would you build?

They are testing:

Production readiness and maturity.

[⬆ Back to Top](#top)

<a id="priority-lists-for-interview-prep"></a>

### 🔥 Tier 1 — Highest Probability (You MUST be ready)

### **7️⃣ “Why asynchronous processing?”**

* LLM latency unpredictable

* Avoid request timeouts

* Decouple ingestion from execution

* Better throughput control

### **9️⃣ “How do you prevent cost blowups?”**

* Retry caps

* Distributed retry budget

* Fallback models

* Idempotency

* Global rate limiting

### **🔟 “How do you version schemas?”**

* Versioned Pydantic models

* Versioned API endpoints

* Backward compatibility handling

### **13️⃣ “How do you measure model quality?”**

* Pass@1

* Pass@k

* Validation failure rate

* Retry rate

* Token usage trends

[⬆ Back to Top](#top)

<a id="behavioral-follow-ups-do-not-ignore"></a>

## Behavioral Follow Ups (Do Not Ignore)

Intuit loves this part.

### **21️⃣ “What trade-offs did you make?”**

* Polling over WebSockets

* At-least-once over exactly-once

* Schema-first validation vs flexible parsing

* Retry caps vs higher recall

<a id="what-improvemnts-would-you-make"></a>

### **What Improvemnts would you make**

1) Improve extraction quality

Schema-specific prompt tuning & few-shot examples for the weakest schemas (invoices, edge-case notes).
Model selection per schema (e.g., stronger model for invoices, cheaper for simpler forms).
Add lightweight pre/post-processing (OCR cleanup, currency/date normalization) to reduce “silly” validation failures.

2) Smarter correction loop
Make corrections field-targeted: only re-generate failing fields instead of the whole object.
Use adaptive retry policies: fewer retries for low-value jobs, more for high-value/priority ones.
Learn from history: mine the audit table to auto-generate better correction hints for recurring error patterns.

6) Evaluation & monitoring
Automate nightly evals on a fixed benchmark set and track pass@k over time (CI for prompts/models).
Add alerting on:
spike in retry-rate,
drop in pass@1/pass@3,
surge in token usage per job.
Build a small UI to diff attempts (before/after correction) for rapid debugging.

3) Stronger consistency & concurrency control

Add optimistic locking on Job rows (version column) to guard against concurrent updates.
Tighten state transition rules (only allow legal PENDING → RUNNING → COMPLETED/FAILED transitions).
Optionally bump isolation level to REPEATABLE READ for critical updates in Postgres.

4) Better scalability & multi-tenant controls.

Add simple sharding strategy for workers (e.g., by tenant or schema type) to avoid noisy-neighbor effects.

Run a proper load test suite (k6/Locust) and auto-generate capacity reports (X jobs/min at p95 < Y sec).

5) Product & UX layer

Turn the Streamlit dashboard into a multi-tenant admin console: job search, replay, DLQ inspection, per-tenant metrics.

Add webhook / SSE callbacks as an alternative to polling for higher-end integrations.

Provide a schema registry + versioning story so clients can evolve schemas safely.
[⬆ Back to Top](#top)
### **22️⃣ “What mistake did you make?”**

* Initial naive queue without atomic move
The biggest mistake I made early on was treating the DB write and the Redis enqueue as two separate steps. My first version wrote the job to the database and then pushed the job ID to Redis. In a failure test I realized there was a window where the DB commit could succeed but the enqueue could fail, leaving a job “accepted” but never processed.

Fixing that forced me to redesign around the transactional outbox + dispatcher + reliable queue pattern. It added complexity, but it completely removed that lost‑job class of bugs and taught me to treat cross‑system writes (DB + queue) as a first‑class design problem, not an implementation detail.

* No global retry cap

* Too strict validation early

I also made validation too strict too early. The first version of the validator encoded lots of tight rules and formatting expectations. That gave strong guarantees, but in practice it caused many “good enough” outputs to fail, especially for edge‑case invoices and noisy text. The correction loop kept firing on minor issues, which hurt latency and made overall pass rates look worse than they needed to be.

I fixed this by prioritizing critical invariants first (schema correctness, math consistency, key fields), and relaxing or normalizing cosmetic issues (for example, currency symbols, minor whitespace, some optional fields). I also added better normalization before validation. That balance kept the strong guarantees where they matter, while reducing unnecessary retries and improving pass@1 and latency.

<a id="rebuild-differently"></a>

### **Rebuild Differently**

Start with a “validation contract” first, then prompts.
I’d design schema + business rules + normalization up front (including what’s a hard failure vs warning), and only then design prompts around that contract. In this version, I iterated prompts and validators in parallel, which caused avoidable churn and “too‑strict too‑early” validation.

Bake in global controls and tenancy from day one.
I added the global retry budget and per‑API‑key limits later, after seeing cost‑spike risks. If I rebuilt, I’d design multi‑tenant controls (per‑tenant limits, priorities, cost budgets) and a global circuit breaker as first‑class primitives instead of retrofits.

Design for observability and evaluation as core features.
The audit log and eval harness came after the core pipeline. Next time I’d treat:

nightly evals on a fixed benchmark set,
pass@k dashboards, and
alerts on retry‑rate / token‑usage spikes
as part of the MVP. That makes every later prompt/model change safer and more data‑driven.

### **23️⃣ “What was the hardest design decision?”**

The hardest design decision was how strict to make validation, and how aggressively to retry with self‑correction.

On one side, I could have kept validation relatively light and accepted “mostly correct” JSON from the LLM. That would have meant lower latency, fewer LLM calls, and a much simpler architecture: no correction loop, no retry budgets, no global circuit breaker. But it also meant that subtle inconsistencies—like invoice math errors or out‑of‑range clinical values—would slip through and corrupt downstream systems.

On the other side was the design I chose: schema‑first, business‑rule‑strict validation plus a correction loop, backed by per‑key and global retry budgets. That raised latency by ~15–25% and increased implementation complexity (extra states, budgets, metrics), but it gave me a property I cared a lot about: downstream systems only ever see data that passes deterministic checks. I decided that in a healthcare/financial-style workflow, that guarantee was worth the extra complexity and cost, and then I used retry caps, budgets, and a fallback model to keep the worst‑case behavior bounded.

### **24️⃣ “Why are you proud of this?”**

I’m particularly proud of this project because it wasn’t something assigned to me — it came from a problem I noticed while working with LLM outputs on messy healthcare data. When we tried to extract structured information, the model would sometimes return outputs that looked valid syntactically but were actually incomplete or logically inconsistent. That created real issues because downstream systems depend on deterministic structured data.

Instead of just trying to improve prompts, I realized the system needed guardrails around the model. So I took the initiative to design a pipeline where the model’s output is deterministically validated, and if something is wrong, the system feeds structured validation errors back to the model to correct only the problematic fields.

Over time, I expanded the system with reliability features like idempotency, retry limits, and evaluation tooling so we could measure accuracy and control cost. What I’m proud of is that it started from observing a practical pain point and evolved into a complete engineering solution that made the AI pipeline much more reliable and production-ready.
[⬆ Back to Top](#top)

# Technologies Used in the Flow (Updated)

* API layer: FastAPI (async, job-style APIs)  
* Orchestration: LangGraph state machine (EXTRACT → VALIDATE → CORRECT loop)  
* LLM layer: Provider abstraction over OpenAI / Gemini, with concurrency semaphore and fallback models  
* Validation: Pydantic v2 schemas \+ custom business-rule validators (e.g., invoice math)  
* DB: SQLAlchemy async (SQLite locally, Postgres via config)  
* Queue & dispatch:  
  * Mode A: FastAPI BackgroundTasks (no Redis)  
  * Mode B: Redis-based workers **with transactional outbox \+ reliable queue**  
* Distributed controls: Redis-backed **rate limiting**, **per-API-key \+ global retry budget**, and **degradation detection** (retry-rate spikes)  
* Frontend: Streamlit dashboard/UX for running jobs  
* Eval: Async evaluation harness with pass@k and field-level accuracy, driven against labeled samples

---

[⬆ Back to Top](#top)

**Full System Flow (What Happens Internally – Updated)**

1. **Request enters the API layer**  
   * POST /api/v1/process receives raw\_text \+ schema\_name and optional X-Idempotency-Key.  
2. **Authentication \+ rate limiting**  
   * API key (X-API-Key) is validated.  
   * Per-key rate limit is enforced (Redis-backed sliding window with in-memory fallback).  
3. **Idempotency check**  
   * If an existing job already uses this idempotency key, that job is returned immediately (no new processing).  
4. **Deduplication via input hash**  
   * A deterministic hash of (schema\_name, raw\_text) is computed.  
   * If a completed job exists for this hash, that job is returned instantly (skips LLM and saves cost).  
5. **Job creation in the DB**  
   * A new Job row is inserted with status PENDING, plus:  
     * api\_key\_id (hashed API key) for per-tenant tracking.  
     * Initial counters: retry\_count \= 0, total\_tokens \= 0, total\_latency\_ms \= 0\.  
6. **Enqueueing / dispatch (two modes, with outbox in Redis mode)**  
   * **If Redis queue is disabled (simple mode):**  
     * FastAPI BackgroundTasks runs the pipeline in-process for this job.  
   * **If Redis queue is enabled (distributed mode):**  
     * The API **does not** push directly to Redis.  
     * It writes a **transactional outbox event** in the same DB transaction as the Job.  
       * Event says “enqueue this job ID”.  
     * A separate **outbox dispatcher** process consumes these events and pushes job IDs onto the Redis queue using a **reliable enqueue** function (dedup-aware).  
7. **Reliable Redis queue semantics (distributed mode)**  
   * Workers use an **LMOVE / BRPOPLPUSH-style pattern**:  
     * Atomically move a job ID from a pending list to a processing list.  
     * Mark it active and record a start timestamp.  
   * When the worker finishes, it **acknowledges** the job, removing it from processing and the active set; successful ones are marked as completed in a results hash.  
   * A separate **reaper** periodically scans processing and **moves stale jobs back to** pending if they’ve been stuck too long (e.g., worker crashed mid-job).  
8. **Pipeline start**  
   * The orchestrator loads the Job from the DB, records a “job start” metric (for degradation tracking), and constructs the initial LangGraph state:  
     * job\_id, raw\_text, schema\_name, api\_key\_id, attempt\_number \= 0, etc.  
   * Job status is set to EXTRACTING.  
9. **Node 1 – EXTRACT**  
   * Builds an extraction prompt from the raw text and target schema.  
   * Calls the LLM through the unified client with concurrency limiting.  
   * Strips JSON fences / formatting, parses to JSON, and returns a parsed document into the pipeline state.  
   * Tokens \+ latency are recorded in metrics.  
10. **Node 2 – VALIDATE**  
    * Runs JSON through Pydantic schemas and business-rule validators:  
      * Type correctness (dates, numbers, enums, etc.).  
      * Domain rules (e.g., each line-item total, subtotal vs total, discounts/taxes).  
    * If all checks pass:  
      * State is marked is\_valid \= True.  
    * If checks fail:  
      * Collects fine-grained field-path errors and produces a human-readable summary.  
11. **If valid (happy path)**  
    * The graph reaches FINALIZE:  
      * Job status transitions to COMPLETED.  
      * structured\_output is persisted as JSON.  
      * validation\_status is set (e.g., VALID).  
      * Aggregate metrics (retry\_count, total\_tokens, total\_latency\_ms) are updated.  
12. **If invalid (self-correction loop)**  
    * Validation errors are converted into precise messages (“path: error”) and stored in state.  
    * The pipeline transitions to the CORRECT node.  
13. **Node 3 – CORRECT (with budgets \+ degradation controls)**  
    * Records a “retry attempt” for degradation tracking.  
    * **Retry budgets checked before calling the LLM:**  
      * Per-API-key budget: protects tenants from noisy neighbors (each key has its own hourly retry allowance).  
      * Global budget: circuit breaker for the whole system (e.g., in case of provider outage or model degradation).  
    * If **per-key or global budget is exhausted**, the pipeline:  
      * Skips the LLM call.  
      * Forces exit from the retry loop.  
      * Marks the job failed with a clear error (budget exhausted).  
    * If budgets allow:  
      * Builds a correction prompt including:  
        * Original raw text,  
        * Previous JSON output,  
        * Validation errors as structured hints.  
      * **Degradation detection:**  
        * The system tracks jobs\_in\_window and retries\_in\_window over a moving time window.  
        * If retry\_rate (retries / jobs) exceeds a configured threshold, the system enters a “degraded” state.  
      * **Model selection:**  
        * If degradation is detected *or* “use fallback for retries” is configured, it routes correction calls to a fallback (cheaper/more stable) model.  
      * Calls the LLM again, records tokens, latency, and increments retry metrics.  
14. **Looping behavior**  
    * After CORRECT, the graph returns to VALIDATE with the new JSON.  
    * The EXTRACT → VALIDATE → CORRECT loop continues until:  
      * The document becomes valid, or  
      * Max retries is reached, or  
      * Retry budgets (per-key or global) are exhausted, or  
      * The job is canceled or times out.  
15. **Attempt-level audit trail**  
    * Every extraction/correction pass is stored as an Attempt row:  
      * Prompt, raw LLM output, parsed JSON, validation errors, is\_valid, tokens used, latency, timestamp.  
    * This forms a full correction log that can be surfaced to the client.  
16. **Final job state**  
    * Terminal statuses:  
      * COMPLETED with validated structured output.  
      * FAILED with error\_message and last known state.  
      * TIMEOUT if job exceeded its configured duration (cleanup run can mark stale PENDING/RUNNING jobs).  
      * CANCELLED if a client explicitly canceled.  
17. **Client result retrieval (with backoff hints)**  
    * Client calls GET /api/v1/result/{job\_id}. Response contains:  
      * status and validation\_status  
      * structured\_output (or None if not completed / failed)  
      * correction\_log (all attempts, ordered)  
      * retry\_count, total\_tokens, total\_latency\_ms  
      * retry\_after\_seconds: suggestion for how long to wait before polling again  
      * is\_terminal: whether the job is in a final state  
    * Clients can implement smarter polling based on retry\_after\_seconds instead of hammering the API.

---

[⬆ Back to Top](#top)
