"""Streamlit UI for the Self-Correcting Data Validation Agent."""

from __future__ import annotations

import json
import time

import requests
import streamlit as st

# ── Configuration ────────────────────────────────────────────────────
API_BASE = "http://localhost:8000/api/v1"
POLL_INTERVAL = 2  # seconds


# ═══════════════════════════════════════════════════════════════════════
# Page setup
# ═══════════════════════════════════════════════════════════════════════

st.set_page_config(
    page_title="Data Validation Agent",
    page_icon="🔍",
    layout="wide",
)

st.title("🔍 Self-Correcting Data Validation Agent")
st.markdown(
    "Paste unstructured text (invoice, survey, form data) and let the AI "
    "extract structured JSON with automatic self-correction."
)


# ═══════════════════════════════════════════════════════════════════════
# State machine visualisation
# ═══════════════════════════════════════════════════════════════════════

def render_state_machine(current_status: str) -> None:
    """Render an inline state-machine diagram highlighting the active state."""
    states = ["PENDING", "EXTRACTING", "VALIDATING", "CORRECTING", "FINALIZING", "COMPLETED", "FAILED"]
    icons = {
        "PENDING": "⏳",
        "EXTRACTING": "🔄",
        "VALIDATING": "✅",
        "CORRECTING": "🔧",
        "FINALIZING": "📦",
        "COMPLETED": "✅",
        "FAILED": "❌",
    }

    cols = st.columns(len(states))
    for i, state in enumerate(states):
        with cols[i]:
            if state == current_status:
                st.markdown(
                    f"<div style='text-align:center; padding:8px; "
                    f"background:#4CAF50; color:white; border-radius:8px; "
                    f"font-weight:bold;'>"
                    f"{icons.get(state, '')} {state}</div>",
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(
                    f"<div style='text-align:center; padding:8px; "
                    f"background:#e0e0e0; border-radius:8px; color:#666;'>"
                    f"{icons.get(state, '')} {state}</div>",
                    unsafe_allow_html=True,
                )


# ═══════════════════════════════════════════════════════════════════════
# Sidebar – metrics
# ═══════════════════════════════════════════════════════════════════════

with st.sidebar:
    st.header("📊 Observability")
    if st.button("Refresh Metrics"):
        try:
            r = requests.get(f"{API_BASE}/metrics", timeout=5)
            if r.status_code == 200:
                st.json(r.json())
            else:
                st.error(f"API error: {r.status_code}")
        except requests.ConnectionError:
            st.error("Cannot connect to API. Is the server running?")

    st.markdown("---")
    st.markdown(
        "**API Base:** `http://localhost:8000`\n\n"
        "**Docs:** [Swagger UI](http://localhost:8000/docs)"
    )


# ═══════════════════════════════════════════════════════════════════════
# Input area
# ═══════════════════════════════════════════════════════════════════════

sample_invoice = """Invoice #INV-2026-0042
Date: 2026-02-28
Due: 2026-03-30

From: Acme Corp, 123 Innovation Dr, San Francisco CA 94107
To: Widget Inc, 456 Commerce St, New York NY 10001

Items:
1. Cloud Hosting (Annual) — 2 units @ $1,200.00 each = $2,400.00
2. Premium Support — 1 unit @ $500.00 = $500.00
3. Data Migration Service — 1 unit @ $350.00 = $350.00

Subtotal: $3,250.00
Tax (10%): $325.00
Total: $3,575.00

Payment terms: Net 30
Notes: Thank you for your business!"""

raw_text = st.text_area(
    "📝 Paste unstructured text here",
    value=sample_invoice,
    height=300,
)

# ── Schema selector (Optional Data Type Hint from diagram) ───────
schema_name = st.selectbox(
    "📋 Data Type Hint (optional)",
    options=["invoice", "survey"],
    index=0,
    help="Select the expected document type so the agent knows which schema to validate against.",
)

col1, col2 = st.columns([1, 4])
with col1:
    process_btn = st.button("🚀 Process", type="primary", use_container_width=True)


# ═══════════════════════════════════════════════════════════════════════
# Processing flow
# ═══════════════════════════════════════════════════════════════════════

if process_btn and raw_text.strip():
    with st.spinner("Submitting job..."):
        try:
            resp = requests.post(
                f"{API_BASE}/process",
                json={"raw_text": raw_text, "schema_name": schema_name},
                timeout=10,
            )
        except requests.ConnectionError:
            st.error("Cannot connect to API at localhost:8000. Start the server first.")
            st.stop()

        if resp.status_code not in (200, 202):
            st.error(f"API error {resp.status_code}: {resp.text}")
            st.stop()

        job = resp.json()
        job_id = job["job_id"]
        st.success(f"Job created: `{job_id}`")

    # ── Poll for result ──────────────────────────────────────────────
    status_placeholder = st.empty()
    state_placeholder = st.empty()
    step_counter_placeholder = st.empty()
    progress_bar = st.progress(0)

    terminal_states = {"COMPLETED", "FAILED"}
    result_data = None

    for tick in range(60):  # max 2 minutes
        try:
            r = requests.get(f"{API_BASE}/result/{job_id}", timeout=10)
            result_data = r.json()
        except Exception:
            time.sleep(POLL_INTERVAL)
            continue

        current = result_data.get("status", "PENDING")
        retry_count = result_data.get("retry_count", 0)
        status_placeholder.info(f"Status: **{current}** | Retries: {retry_count}")

        with state_placeholder.container():
            render_state_machine(current)

        # ── Step counter (matches diagram: "Step counter showing retry attempts") ──
        with step_counter_placeholder.container():
            sc1, sc2, sc3 = st.columns(3)
            sc1.metric("🔄 Current Step", current)
            sc2.metric("🔁 Retry Attempt", f"{retry_count} / {3}")
            sc3.metric("⏱️ Elapsed", f"{tick * POLL_INTERVAL}s")

        # Progress estimate
        phase_map = {"PENDING": 10, "EXTRACTING": 30, "VALIDATING": 50, "CORRECTING": 60, "FINALIZING": 80, "COMPLETED": 100, "FAILED": 100}
        progress_bar.progress(phase_map.get(current, 10))

        if current in terminal_states:
            break

        time.sleep(POLL_INTERVAL)

    progress_bar.empty()
    step_counter_placeholder.empty()

    # ── Display results ──────────────────────────────────────────────
    if result_data:
        st.markdown("---")

        status = result_data.get("status", "UNKNOWN")
        if status == "COMPLETED":
            st.success("✅ Extraction & validation succeeded!")
        else:
            st.error(f"❌ Job ended with status: {status}")
            if result_data.get("error_message"):
                st.warning(result_data["error_message"])

        # ── Before / After ───────────────────────────────────────────
        st.subheader("📄 Before / After")
        bcol, acol = st.columns(2)
        with bcol:
            st.markdown("**Raw Input**")
            st.code(raw_text, language="text")
        with acol:
            st.markdown("**Structured Output**")
            if result_data.get("structured_output"):
                st.json(result_data["structured_output"])
            else:
                st.info("No valid output produced.")

        # ── Summary metrics ──────────────────────────────────────────
        st.subheader("📊 Summary")
        mcol1, mcol2, mcol3, mcol4 = st.columns(4)
        mcol1.metric("Validation", result_data.get("validation_status", "—"))
        mcol2.metric("Retries", result_data.get("retry_count", 0))
        mcol3.metric("Tokens Used", result_data.get("total_tokens", 0))
        mcol4.metric("Latency (ms)", f"{result_data.get('total_latency_ms', 0):.0f}")

        # ── Correction iteration viewer ──────────────────────────────
        correction_log = result_data.get("correction_log", [])
        if correction_log:
            st.subheader("🔧 Correction Iterations")
            for attempt in correction_log:
                num = attempt["attempt_number"]
                valid = attempt["is_valid"]
                label = "✅ Valid" if valid else "❌ Invalid"
                with st.expander(f"Attempt {num} — {label} ({attempt.get('tokens_used', 0)} tokens, {attempt.get('latency_ms', 0):.0f}ms)"):
                    if attempt.get("parsed_json"):
                        st.json(attempt["parsed_json"])
                    if attempt.get("validation_errors"):
                        st.error(attempt["validation_errors"])

        # ── State machine final ──────────────────────────────────────
        st.subheader("🔀 Final State")
        render_state_machine(status)
