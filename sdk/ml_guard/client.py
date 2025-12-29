from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Dict, List, Optional, Union
import requests


Json = Dict[str, Any]


class MLGuardError(RuntimeError):
    pass


@dataclass(frozen=True)
class MLGuardClient:
    base_url: str
    api_key: Optional[str] = None
    timeout_s: float = 10.0

    # ---------------------------
    # Internals
    # ---------------------------
    def _url(self, path: str) -> str:
        return self.base_url.rstrip("/") + path

    def _headers(self) -> Dict[str, str]:
        h = {"Content-Type": "application/json"}
        if self.api_key:
            h["X-API-Key"] = self.api_key
        return h

    def _raise_for(self, r: requests.Response) -> None:
        if r.ok:
            return
        try:
            detail = r.json()
        except Exception:
            detail = r.text
        raise MLGuardError(f"HTTP {r.status_code}: {detail}")

    # ---------------------------
    # Health
    # ---------------------------
    def health(self) -> Json:
        r = requests.get(self._url("/api/v1/health"), timeout=self.timeout_s)
        self._raise_for(r)
        return r.json()

    # ---------------------------
    # Events
    # ---------------------------
    def ingest_event(
        self,
        *,
        project_id: str,
        model_id: str,
        endpoint: str,
        features: Dict[str, Any],
        timestamp: Optional[str] = None,
        latency_ms: Optional[int] = None,
        y_pred: Optional[int] = None,
        y_proba: Optional[float] = None,
    ) -> Json:
        payload: Json = {
            "project_id": project_id,
            "model_id": model_id,
            "endpoint": endpoint,
            "features": features,
        }
        if timestamp is not None:
            payload["timestamp"] = timestamp
        if latency_ms is not None:
            payload["latency_ms"] = latency_ms
        if y_pred is not None:
            payload["y_pred"] = y_pred
        if y_proba is not None:
            payload["y_proba"] = y_proba

        r = requests.post(
            self._url("/api/v1/events"),
            json=payload,
            headers=self._headers(),
            timeout=self.timeout_s,
        )
        self._raise_for(r)
        return r.json()

    def ingest_events(self, events: List[Json]) -> Json:
        r = requests.post(
            self._url("/api/v1/events"),
            json=events,
            headers=self._headers(),
            timeout=self.timeout_s,
        )
        self._raise_for(r)
        return r.json()

    # ---------------------------
    # Discover
    # ---------------------------
    def list_models(self, *, project_id: str) -> Json:
        r = requests.get(
            self._url("/api/v1/discover/models"),
            params={"project_id": project_id},
            headers=self._headers(),
            timeout=self.timeout_s,
        )
        self._raise_for(r)
        return r.json()

    def list_days(
        self,
        *,
        project_id: str,
        model_id: str,
        endpoint: str = "predict",
    ) -> Json:
        r = requests.get(
            self._url("/api/v1/discover/days"),
            params={
                "project_id": project_id,
                "model_id": model_id,
                "endpoint": endpoint,
            },
            headers=self._headers(),
            timeout=self.timeout_s,
        )
        self._raise_for(r)
        return r.json()

    # ---------------------------
    # Metrics
    # ---------------------------
    def compute_metrics(
        self,
        *,
        project_id: str,
        model_id: str,
        endpoint: str = "predict",
        day: Union[str, date],
        tz: str = "UTC",
        overwrite: bool = True,
    ) -> Json:
        day_s = day if isinstance(day, str) else day.isoformat()

        r = requests.post(
            self._url("/api/v1/metrics/compute"),
            params={
                "project_id": project_id,
                "model_id": model_id,
                "endpoint": endpoint,
                "day": day_s,
                "tz": tz,
                "overwrite": str(overwrite).lower(),
            },
            headers=self._headers(),
            timeout=self.timeout_s,
        )
        self._raise_for(r)
        return r.json()

    def read_metrics_daily(
        self,
        *,
        project_id: str,
        model_id: str,
        endpoint: str = "predict",
        day: Union[str, date],
    ) -> Json:
        day_s = day if isinstance(day, str) else day.isoformat()

        r = requests.get(
            self._url("/api/v1/metrics/daily"),
            params={
                "project_id": project_id,
                "model_id": model_id,
                "endpoint": endpoint,
                "day": day_s,
            },
            headers=self._headers(),
            timeout=self.timeout_s,
        )
        self._raise_for(r)
        return r.json()

    # ---------------------------
    # Drift / Baselines
    # ---------------------------
    def capture_baseline(
        self,
        *,
        project_id: str,
        model_id: str,
        endpoint: str = "predict",
        feature: str,
        tz: str = "UTC",
        overwrite: bool = True,
        start_ts: Optional[str] = None,
        end_ts: Optional[str] = None,
        start_day: Optional[Union[str, date]] = None,
        end_day: Optional[Union[str, date]] = None,
        n_bins: int = 10,
        top_k_categories: int = 50,
    ) -> Json:
        params: Json = {
            "project_id": project_id,
            "model_id": model_id,
            "endpoint": endpoint,
            "feature": feature,
            "tz": tz,
            "overwrite": str(overwrite).lower(),
            "n_bins": n_bins,
            "top_k_categories": top_k_categories,
        }
        if start_ts is not None:
            params["start_ts"] = start_ts
        if end_ts is not None:
            params["end_ts"] = end_ts
        if start_day is not None:
            params["start_day"] = start_day if isinstance(start_day, str) else start_day.isoformat()
        if end_day is not None:
            params["end_day"] = end_day if isinstance(end_day, str) else end_day.isoformat()

        r = requests.post(
            self._url("/api/v1/drift/baseline/capture"),
            params=params,
            headers=self._headers(),
            timeout=self.timeout_s,
        )
        self._raise_for(r)
        return r.json()

    def compute_drift_all(
        self,
        *,
        project_id: str,
        model_id: str,
        endpoint: str = "predict",
        day: Union[str, date],
        tz: str = "UTC",
        min_samples: int = 10,
        overwrite: bool = True,
        alert: bool = False,
        threshold: float = 0.25,
    ) -> Json:
        day_s = day if isinstance(day, str) else day.isoformat()

        r = requests.post(
            self._url("/api/v1/drift/compute_all"),
            params={
                "project_id": project_id,
                "model_id": model_id,
                "endpoint": endpoint,
                "day": day_s,
                "tz": tz,
                "min_samples": min_samples,
                "overwrite": str(overwrite).lower(),
                "alert": str(alert).lower(),
                "threshold": threshold,
            },
            headers=self._headers(),
            timeout=self.timeout_s,
        )
        self._raise_for(r)
        return r.json()

    def read_drift_daily(
        self,
        *,
        project_id: str,
        model_id: str,
        endpoint: str = "predict",
        day: Union[str, date],
    ) -> Json:
        day_s = day if isinstance(day, str) else day.isoformat()

        r = requests.get(
            self._url("/api/v1/drift/daily"),
            params={
                "project_id": project_id,
                "model_id": model_id,
                "endpoint": endpoint,
                "day": day_s,
            },
            headers=self._headers(),
            timeout=self.timeout_s,
        )
        self._raise_for(r)
        return r.json()

    # ---------------------------
    # Alerts
    # ---------------------------
    def list_alerts(
        self,
        *,
        project_id: Optional[str] = None,
        model_id: Optional[str] = None,
        endpoint: Optional[str] = None,
        rule: Optional[str] = None,
        limit: int = 50,
    ) -> Json:
        params: Json = {"limit": limit}
        if project_id:
            params["project_id"] = project_id
        if model_id:
            params["model_id"] = model_id
        if endpoint:
            params["endpoint"] = endpoint
        if rule:
            params["rule"] = rule

        r = requests.get(
            self._url("/api/v1/alerts"),
            params=params,
            headers=self._headers(),
            timeout=self.timeout_s,
        )
        self._raise_for(r)
        return r.json()

    # ---------------------------
    # Costs
    # ---------------------------
    def pull_costs(
        self,
        *,
        project_id: str,
        day: Union[str, date],
        overwrite: bool = True,
        metric: Optional[str] = None,
    ) -> Json:
        day_s = day if isinstance(day, str) else day.isoformat()
        params: Json = {
            "project_id": project_id,
            "day": day_s,
            "overwrite": str(overwrite).lower(),
        }
        if metric is not None:
            params["metric"] = metric

        r = requests.post(
            self._url("/api/v1/costs/pull"),
            params=params,
            headers=self._headers(),
            timeout=max(self.timeout_s, 30.0),
        )
        self._raise_for(r)
        return r.json()

    def read_costs_daily(self, *, project_id: str, day: Union[str, date]) -> Json:
        day_s = day if isinstance(day, str) else day.isoformat()

        r = requests.get(
            self._url("/api/v1/costs/daily"),
            params={"project_id": project_id, "day": day_s},
            headers=self._headers(),
            timeout=self.timeout_s,
        )
        self._raise_for(r)
        return r.json()
