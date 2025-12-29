from __future__ import annotations

import os
from datetime import date, datetime
from typing import Any, Dict, List
from ml_guard import MLGuardClient 

import pandas as pd
import requests
import streamlit as st

BASE_URL = os.getenv("MLGUARD_BASE_URL", "http://localhost:8000")
API_KEY = os.getenv("MLGUARD_API_KEY", "demo-key")

client = MLGuardClient(base_url=BASE_URL, api_key=API_KEY)


def headers() -> Dict[str, str]:
    return {"X-API-Key": API_KEY} if API_KEY else {}


def get(path: str, params: Dict[str, Any] | None = None) -> Any:
    r = requests.get(f"{BASE_URL}{path}", params=params or {}, headers=headers(), timeout=10)
    r.raise_for_status()
    return r.json()


def post(path: str, params: Dict[str, Any] | None = None) -> Any:
    r = requests.post(f"{BASE_URL}{path}", params=params or {}, headers=headers(), timeout=30)
    r.raise_for_status()
    return r.json()


st.set_page_config(page_title="ML Guard Dashboard", layout="wide")
st.title("ML Guard — Minimal Dashboard")

with st.sidebar:
    st.subheader("Connection")
    st.text_input("Base URL", value=BASE_URL, key="base_url", disabled=True)
    st.text_input("API Key", value=API_KEY, key="api_key", type="password", disabled=True)

    st.divider()
    st.subheader("Selection")

    project_id = st.text_input("Project ID", value=os.getenv("MLGUARD_PROJECT_ID", ""))

    if project_id:
        try:
            models = get("/api/v1/discover/models", {"project_id": project_id}).get("items", [])
        except Exception as e:
            st.error(f"discover/models failed: {e}")
            models = []
    else:
        models = []

    model_options = [f"{m['model_id']}::{m['endpoint']}" for m in models] if models else []
    sel = st.selectbox("Model + endpoint", options=model_options, index=0 if model_options else None)

    model_id, endpoint = (sel.split("::", 1) if sel else ("", "predict"))

    if project_id and model_id:
        try:
            days = get(
                "/api/v1/discover/days",
                {"project_id": project_id, "model_id": model_id, "endpoint": endpoint},
            ).get("days", [])
        except Exception as e:
            st.error(f"discover/days failed: {e}")
            days = []
    else:
        days = []

    day_str = st.selectbox("Day (UTC date from events)", options=days, index=len(days) - 1 if days else None)
    st.caption("Note: discover/days returns UTC dates from events; metrics/drift compute can use tz separately.")


colA, colB, colC = st.columns(3)

with colA:
    st.subheader("Health")
    try:
        h = get("/api/v1/health")
        st.success(h)
    except Exception as e:
        st.error(f"Health failed: {e}")

with colB:
    st.subheader("Alerts (latest)")
    if project_id:
        try:
            alerts = get("/api/v1/alerts", {"project_id": project_id, "limit": 50}).get("items", [])
            if alerts:
                df = pd.DataFrame(alerts)
                st.dataframe(df[["created_at", "day", "rule", "severity", "value", "threshold", "model_id", "endpoint"]])
            else:
                st.info("No alerts found for this project.")
        except Exception as e:
            st.error(f"alerts failed: {e}")
    else:
        st.info("Enter a project_id to view alerts.")

with colC:
    st.subheader("Costs (daily, stored)")
    if project_id and day_str:
        try:
            costs = get("/api/v1/costs/daily", {"project_id": project_id, "day": day_str})
            rows = costs.get("rows", [])
            if rows:
                cdf = pd.DataFrame(rows).sort_values("amount", ascending=False)
                st.dataframe(cdf[["service", "amount", "unit", "created_at"]])
                st.metric("Total (sum rows)", float(cdf["amount"].sum()))
            else:
                st.info("No stored costs for that day. Run /costs/pull first (or let worker do it).")
        except Exception as e:
            st.warning(f"costs/daily failed: {e}")
    else:
        st.info("Select project + day to view costs.")


st.divider()
st.subheader("Metrics & Drift (stored daily rows)")

c1, c2 = st.columns(2)

with c1:
    st.markdown("### Metrics (GET /metrics/daily)")
    if project_id and model_id and day_str:
        try:
            m = get(
                "/api/v1/metrics/daily",
                {"project_id": project_id, "model_id": model_id, "endpoint": endpoint, "day": day_str},
            )
            if m:
                st.json(m)
                # Quick-friendly view
                st.metric("n_events", m.get("n_events", 0))
                st.metric("latency_p50_ms", m.get("latency_p50_ms"))
                st.metric("latency_p95_ms", m.get("latency_p95_ms"))
            else:
                st.info("No stored metrics row for that day. Run POST /metrics/compute or let worker compute it.")
        except Exception as e:
            st.error(f"metrics/daily failed: {e}")
    else:
        st.info("Select project/model/day to view metrics.")

with c2:
    st.markdown("### Drift (GET /drift/daily)")
    if project_id and model_id and day_str:
        try:
            d = get(
                "/api/v1/drift/daily",
                {"project_id": project_id, "model_id": model_id, "endpoint": endpoint, "day": day_str},
            )
            if d:
                st.json(d)
                psi = (d.get("psi") or {})
                if isinstance(psi, dict) and psi:
                    # Flatten PSI dict
                    flat = []
                    for feat, obj in psi.items():
                        if isinstance(obj, dict):
                            flat.append(
                                {
                                    "feature": feat,
                                    "psi": obj.get("psi"),
                                    "n": obj.get("n"),
                                    "type": obj.get("type"),
                                    "severity": obj.get("severity"),
                                }
                            )
                    st.dataframe(pd.DataFrame(flat).sort_values("psi", ascending=False))
            else:
                st.info("No stored drift row for that day. Run POST /drift/compute_all after baseline capture.")
        except Exception as e:
            st.error(f"drift/daily failed: {e}")
    else:
        st.info("Select project/model/day to view drift.")


st.divider()
st.subheader("Actions (compute / pull)")

a1, a2, a3 = st.columns(3)

with a1:
    if st.button("Compute metrics for selected day (POST /metrics/compute)", use_container_width=True, disabled=not (project_id and model_id and day_str)):
        try:
            out = post(
                "/api/v1/metrics/compute",
                {"project_id": project_id, "model_id": model_id, "endpoint": endpoint, "day": day_str, "tz": "UTC", "overwrite": "true"},
            )
            st.success("metrics/compute OK")
            st.json(out)
        except Exception as e:
            st.error(f"metrics/compute failed: {e}")

with a2:
    if st.button("Compute drift_all for selected day (POST /drift/compute_all)", use_container_width=True, disabled=not (project_id and model_id and day_str)):
        try:
            out = post(
                "/api/v1/drift/compute_all",
                {"project_id": project_id, "model_id": model_id, "endpoint": endpoint, "day": day_str, "tz": "UTC", "min_samples": 10, "overwrite": "true", "alert": "true", "threshold": 0.25},
            )
            st.success("drift/compute_all OK")
            st.json(out)
        except Exception as e:
            st.error(f"drift/compute_all failed: {e}")

with a3:
    if st.button("Pull costs for selected day (POST /costs/pull)", use_container_width=True, disabled=not (project_id and day_str)):
        try:
            out = post("/api/v1/costs/pull", {"project_id": project_id, "day": day_str, "overwrite": "true"})
            st.success("costs/pull OK")
            st.json(out)
        except Exception as e:
            st.error(f"costs/pull failed: {e}")
