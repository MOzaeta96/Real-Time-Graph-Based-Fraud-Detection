import hashlib
import json
import joblib
import numpy as np
import os
import redis
import time
import uuid

from collections import Counter as CollCounter
from datetime import datetime, timezone
from fastapi import FastAPI, HTTPException, Request, Response, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST
from typing import Optional, Any, Dict, List


# Config
REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_DB = int(os.getenv("REDIS_DB", "0"))
KEY_PREFIX = os.getenv("KEY_PREFIX", "user")

MODEL_VERSION = os.getenv("MODEL_VERSION", "baseline_rules_v1")

# Multi-model routing
ACTIVE_MODEL = os.getenv("ACTIVE_MODEL", "champion")  # champion|challenger|auto
CHAMPION_PCT = int(os.getenv("CHAMPION_PCT", "90"))   # 0..100
BASE_MODELS_DIR = os.getenv("BASE_MODELS_DIR", "/models")

# Shadow evaluation
SHADOW_EVAL = os.getenv("SHADOW_EVAL", "1").lower() in ("1", "true", "yes", "y")
SHADOW_STREAM = os.getenv("SHADOW_STREAM", "shadow_events")
SHADOW_STREAM_MAXLEN = int(os.getenv("SHADOW_STREAM_MAXLEN", "200000"))

# Dynamic routing config (stored in Redis so we can change routing without restart)
ROUTING_KEY = os.getenv("ROUTING_KEY", "routing:config")

DEFAULT_ACTIVE_MODEL = os.getenv("ACTIVE_MODEL", "auto")  # champion|challenger|auto
DEFAULT_CHAMPION_PCT = int(os.getenv("CHAMPION_PCT", "90"))

# Default fallback threshold if metrics missing
DEFAULT_DECISION_THRESHOLD = float(os.getenv("DECISION_THRESHOLD", "0.5"))

MODEL_REGISTRY = {
    "champion": {
        "model": None,
        "features": None,
        "metrics": None,
        "thresholds": {},
        "default_thr": DEFAULT_DECISION_THRESHOLD,
    },
    "challenger": {
        "model": None,
        "features": None,
        "metrics": None,
        "thresholds": {},
        "default_thr": DEFAULT_DECISION_THRESHOLD,
    },
}

# Prometheus metrics
REQUESTS = Counter(
    "inference_requests_total",
    "Total inference requests",
    ["endpoint", "status_code", "policy", "active_model"],
)

LATENCY = Histogram(
    "inference_latency_ms",
    "Inference latency in milliseconds",
    ["endpoint", "policy", "active_model"],
    buckets=(1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 2000),
)

FRAUD_DECISIONS = Counter(
    "fraud_decisions_total",
    "Total fraud decisions",
    ["endpoint", "policy", "active_model", "decision"],
)

LAST_MODEL_LOADED = Gauge(
    "model_loaded",
    "1 if model is loaded, else 0",
    ["variant"],
)

SHADOW_PREDICTIONS = Counter(
    "shadow_predictions_total",
    "Shadow predictions computed (not used for decisions)",
    ["endpoint", "policy", "prod_model", "shadow_model"],
)

SHADOW_LATENCY = Histogram(
    "shadow_latency_ms",
    "Shadow inference latency in milliseconds",
    ["endpoint", "policy", "prod_model", "shadow_model"],
    buckets=(1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 2000),
)

PREDICTION_COUNT = Counter(
    "fraud_predictions_total",
    "Total fraud predictions",
    ["model_variant"],
)

FRAUD_PREDICTIONS = Counter(
    "fraud_positive_predictions_total",
    "Fraud positive predictions",
    ["model_variant"],
)

PREDICTION_SCORE = Histogram(
    "fraud_prediction_score",
    "Prediction probability distribution",
    ["model_variant"],
    buckets=[0.01, 0.05, 0.1, 0.2, 0.4, 0.6, 0.8, 0.9, 0.95, 0.99],
)

RELOAD_COUNT = Counter(
    "model_reload_total",
    "Total model reload attempts",
    ["status"],
)


# App + clients
app = FastAPI(title="Fraud Scoring API", version="0.4.0")
r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB, decode_responses=True)


# Logging
def log_event(event: str, **fields):
    payload = {
        "ts_utc": datetime.now(timezone.utc).isoformat(),
        "event": event,
        **fields,
    }
    print(json.dumps(payload, default=str), flush=True)


# Schemas
class ScoreRequest(BaseModel):
    user_id: str = Field(..., examples=["u_1"])
    amount: Optional[float] = Field(None, examples=[120.50])
    country: Optional[str] = Field(None, examples=["US"])


class TransactionEvent(BaseModel):
    transaction_id: str = Field(..., examples=["abc123"])
    timestamp: Optional[str] = Field(None, description="Event time (ISO8601) if available")
    user_id: str = Field(..., examples=["u_1"])
    merchant_id: Optional[str] = Field(None, examples=["m_10"])
    device_id: Optional[str] = Field(None, examples=["d_42"])
    amount: float = Field(..., examples=[120.50])
    country: str = Field(..., examples=["US"])


class RoutingConfigRequest(BaseModel):
    active_model_mode: str = Field(..., pattern="^(champion|challenger|auto)$")
    champion_pct: int = Field(..., ge=0, le=100)


# Explainability helper
def predict_with_contribs(model, x_row: np.ndarray, feature_names: list[str]):
    """
    Returns:
      prob: float
      contribs: dict[str, float]  # SHAP-style contributions per feature (raw score space)
      bias: float                 # bias term (raw score space)
    """
    booster = model.booster_
    contrib = booster.predict(x_row, pred_contrib=True)  # (1, n_features+1)
    contrib = contrib[0]
    bias = float(contrib[-1])
    per_feat = {feature_names[i]: float(contrib[i]) for i in range(len(feature_names))}
    prob = float(model.predict_proba(x_row)[:, 1][0])
    return prob, per_feat, bias


def emit_shadow_event(payload: dict) -> None:
    """
    Writes one event to a Redis Stream for offline evaluation.
    Uses approximate trimming to avoid unbounded growth.
    """
    try:
        flat = {}
        for k, v in payload.items():
            if v is None:
                continue
            if isinstance(v, (str, int, float)):
                flat[k] = v
            else:
                flat[k] = json.dumps(v, default=str)

        r.xadd(
            SHADOW_STREAM,
            flat,
            maxlen=SHADOW_STREAM_MAXLEN,
            approximate=True,
        )
    except Exception as e:
        log_event("shadow_stream_write_error", error=str(e))


# Routing config helpers
def stable_bucket_0_99(s: str) -> int:
    h = hashlib.sha256(s.encode("utf-8")).hexdigest()
    return int(h[:8], 16) % 100


def get_routing_config() -> dict:
    raw = r.get(ROUTING_KEY)
    if not raw:
        return {
            "active_model_mode": DEFAULT_ACTIVE_MODEL,
            "champion_pct": DEFAULT_CHAMPION_PCT,
        }

    try:
        cfg = json.loads(raw)
        return {
            "active_model_mode": cfg.get("active_model_mode", DEFAULT_ACTIVE_MODEL),
            "champion_pct": int(cfg.get("champion_pct", DEFAULT_CHAMPION_PCT)),
        }
    except Exception:
        return {
            "active_model_mode": DEFAULT_ACTIVE_MODEL,
            "champion_pct": DEFAULT_CHAMPION_PCT,
        }


def set_routing_config(active_model_mode: str, champion_pct: int) -> None:
    payload = {
        "active_model_mode": active_model_mode,
        "champion_pct": int(champion_pct),
    }
    r.set(ROUTING_KEY, json.dumps(payload))


def resolve_variant(user_id: str) -> str:
    cfg = get_routing_config()
    mode = cfg["active_model_mode"]
    pct = int(cfg["champion_pct"])

    if mode in ("champion", "challenger"):
        return mode

    b = stable_bucket_0_99(user_id)
    return "champion" if b < pct else "challenger"


def other_variant(v: str) -> str:
    return "challenger" if v == "champion" else "champion"


# Shadow gate helper
def _shadow_gate_eval(
    n: int,
    max_mismatch_rate: float,
    max_shadow_latency_p99_ms: float,
    max_abs_delta_score_p99: float,
):
    summary = shadow_summary(n=n)

    mismatch_rate = float(summary.get("decision_mismatch_rate", 0.0) or 0.0)
    p99_latency = float((summary.get("shadow_latency_ms_stats", {}) or {}).get("p99", 0.0) or 0.0)
    p99_abs_delta = float((summary.get("delta_score_stats", {}) or {}).get("p99", 0.0) or 0.0)

    checks = {
        "mismatch_rate": {
            "value": mismatch_rate,
            "limit": max_mismatch_rate,
            "ok": mismatch_rate <= max_mismatch_rate,
        },
        "shadow_latency_p99_ms": {
            "value": p99_latency,
            "limit": max_shadow_latency_p99_ms,
            "ok": p99_latency <= max_shadow_latency_p99_ms,
        },
        "abs_delta_score_p99": {
            "value": p99_abs_delta,
            "limit": max_abs_delta_score_p99,
            "ok": p99_abs_delta <= max_abs_delta_score_p99,
        },
    }

    passed = all(v["ok"] for v in checks.values())
    return {
        "pass": passed,
        "checks": checks,
        **summary,
    }


# Model loading
def _model_version_for_variant(variant: str) -> str:
    entry = MODEL_REGISTRY.get(variant, {})
    metrics = entry.get("metrics") or {}
    return metrics.get("model_version") or MODEL_VERSION


def load_one_model(variant: str) -> None:
    """
    Load model artifacts from:
      /models/<variant>/{model.joblib, feature_list.json, metrics.json}
    into MODEL_REGISTRY[variant]
    """
    model_dir = os.path.join(BASE_MODELS_DIR, variant)
    model_path = os.path.join(model_dir, "model.joblib")
    feature_list_path = os.path.join(model_dir, "feature_list.json")
    metrics_path = os.path.join(model_dir, "metrics.json")

    thresholds = {"f1": None, "recall95": None, "precision20": None}
    default_thr = DEFAULT_DECISION_THRESHOLD

    try:
        model = None
        features = None
        metrics = None

        if os.path.exists(model_path) and os.path.exists(feature_list_path):
            model = joblib.load(model_path)
            with open(feature_list_path, "r", encoding="utf-8") as f:
                features = json.load(f)
            log_event("model_loaded", variant=variant, model_path=model_path, n_features=len(features))
        else:
            log_event(
                "model_missing",
                variant=variant,
                model_path=model_path,
                feature_list_path=feature_list_path,
            )

        if os.path.exists(metrics_path):
            with open(metrics_path, "r", encoding="utf-8") as f:
                metrics = json.load(f)

            thr_f1 = (metrics or {}).get("best_threshold_by_f1", {}).get("thr")
            thr_r = (metrics or {}).get("threshold_by_recall_target", {}).get("thr")
            thr_p = (metrics or {}).get("threshold_by_precision_target", {}).get("thr")

            thresholds["f1"] = float(thr_f1) if thr_f1 is not None else None
            thresholds["recall95"] = float(thr_r) if thr_r is not None else None
            thresholds["precision20"] = float(thr_p) if thr_p is not None else None

            if thresholds["f1"] is not None:
                default_thr = float(thresholds["f1"])

            log_event(
                "metrics_loaded",
                variant=variant,
                metrics_path=metrics_path,
                thresholds=thresholds,
                default_thr=default_thr,
                model_version=metrics.get("model_version"),
            )
        else:
            log_event("metrics_missing", variant=variant, metrics_path=metrics_path)

        MODEL_REGISTRY[variant]["model"] = model
        MODEL_REGISTRY[variant]["features"] = features
        MODEL_REGISTRY[variant]["metrics"] = metrics
        MODEL_REGISTRY[variant]["thresholds"] = thresholds
        MODEL_REGISTRY[variant]["default_thr"] = default_thr

        LAST_MODEL_LOADED.labels(variant=variant).set(1 if model is not None else 0)

    except Exception as e:
        MODEL_REGISTRY[variant]["model"] = None
        MODEL_REGISTRY[variant]["features"] = None
        MODEL_REGISTRY[variant]["metrics"] = None
        MODEL_REGISTRY[variant]["thresholds"] = {"f1": None, "recall95": None, "precision20": None}
        MODEL_REGISTRY[variant]["default_thr"] = DEFAULT_DECISION_THRESHOLD
        LAST_MODEL_LOADED.labels(variant=variant).set(0)
        log_event("model_load_error", variant=variant, error=str(e))


def reload_all_models() -> dict:
    started = datetime.now(timezone.utc).isoformat()
    try:
        load_one_model("champion")
        load_one_model("challenger")
        RELOAD_COUNT.labels(status="success").inc()

        return {
            "status": "ok",
            "reloaded_at_utc": started,
            "champion_loaded": MODEL_REGISTRY["champion"]["model"] is not None,
            "challenger_loaded": MODEL_REGISTRY["challenger"]["model"] is not None,
            "champion_model_version": _model_version_for_variant("champion"),
            "challenger_model_version": _model_version_for_variant("challenger"),
        }
    except Exception as e:
        RELOAD_COUNT.labels(status="error").inc()
        log_event("reload_models_error", error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to reload models: {e}")


@app.on_event("startup")
def on_startup():
    load_one_model("champion")
    load_one_model("challenger")


# Middleware
@app.middleware("http")
async def add_request_context(request: Request, call_next):
    request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
    request.state.request_id = request_id
    t0 = time.time()
    try:
        response = await call_next(request)
        latency_ms = round((time.time() - t0) * 1000, 2)
        log_event(
            "http_request",
            request_id=request_id,
            method=request.method,
            path=str(request.url.path),
            status_code=response.status_code,
            latency_ms=latency_ms,
        )
        response.headers["x-request-id"] = request_id
        response.headers["x-latency-ms"] = str(latency_ms)
        return response
    except Exception as e:
        latency_ms = round((time.time() - t0) * 1000, 2)
        log_event(
            "http_request_error",
            request_id=request_id,
            method=request.method,
            path=str(request.url.path),
            latency_ms=latency_ms,
            error=str(e),
        )
        raise


# Baseline scoring
def baseline_score(features: dict, amount: Optional[float], country: Optional[str]) -> float:
    score = 0.02

    txn_count = int(features.get("txn_count", 0) or 0)
    distinct_devices = int(features.get("distinct_devices", 0) or 0)
    fraud_rate = float(features.get("fraud_rate", 0.0) or 0.0)
    avg_amt = float(features.get("avg_amount", 0.0) or 0.0)

    if txn_count >= 5:
        score += 0.10
    if distinct_devices >= 3:
        score += 0.15
    if fraud_rate > 0:
        score += min(0.50, fraud_rate * 5)

    if amount is not None:
        if avg_amt > 0 and amount > 5 * avg_amt:
            score += 0.20
        elif amount > 200:
            score += 0.10

    if country is not None and country not in {"US", "CA", "UK"}:
        score += 0.10

    return max(0.0, min(0.99, score))


# Feature fetch
def get_user_features(user_id: str) -> dict:
    key = f"{KEY_PREFIX}:{user_id}:features"
    raw = r.get(key)
    if raw is None:
        raise HTTPException(status_code=404, detail=f"No online features found for user_id={user_id}")
    return json.loads(raw)


# Core scoring helper
def score_with_variant(
    variant: str,
    user_features: dict,
    amount: Optional[float],
    country: Optional[str],
    policy: str,
) -> dict:
    entry = MODEL_REGISTRY.get(variant, {})
    model = entry.get("model")
    model_features = entry.get("features")
    thresholds = entry.get("thresholds") or {}
    default_thr = float(entry.get("default_thr") or DEFAULT_DECISION_THRESHOLD)
    metrics = entry.get("metrics") or {}

    thr = thresholds.get(policy) or default_thr

    model_prob = None
    top_contribs = None
    bias = None

    if model is not None and model_features is not None:
        x = np.array([[float(user_features.get(f, 0.0) or 0.0) for f in model_features]], dtype=float)
        model_prob, contribs, bias = predict_with_contribs(model, x, model_features)
        s = float(model_prob)
        top = sorted(contribs.items(), key=lambda kv: abs(kv[1]), reverse=True)[:3]
        top_contribs = [{"feature": k, "contribution": float(v)} for k, v in top]
    else:
        s = float(baseline_score(user_features, amount, country))

    decision = int(s >= float(thr))

    return {
        "variant": variant,
        "model_version": metrics.get("model_version") or MODEL_VERSION,
        "score": s,
        "threshold": float(thr),
        "decision": int(decision),
        "model_probability": float(model_prob) if model_prob is not None else None,
        "top_feature_contribs": top_contribs,
        "bias": bias,
        "model_loaded": model is not None and model_features is not None,
    }


def _to_float(x):
    try:
        return float(x)
    except Exception:
        return None


def _to_int(x):
    try:
        return int(x)
    except Exception:
        return None


# Endpoints
@app.get("/health")
def health():
    try:
        r.ping()
        redis_ok = True
    except Exception:
        redis_ok = False

    champ_loaded = MODEL_REGISTRY["champion"]["model"] is not None
    chall_loaded = MODEL_REGISTRY["challenger"]["model"] is not None
    cfg = get_routing_config()

    return {
        "status": "ok",
        "redis_ok": redis_ok,
        "ts": datetime.now(timezone.utc).isoformat(),
        "model_version": MODEL_VERSION,
        "active_model_mode": cfg["active_model_mode"],
        "champion_pct": cfg["champion_pct"],
        "shadow_eval": SHADOW_EVAL,
        "champion_loaded": champ_loaded,
        "challenger_loaded": chall_loaded,
        "champion_model_version": _model_version_for_variant("champion"),
        "challenger_model_version": _model_version_for_variant("challenger"),
    }


@app.post("/score")
def score(
    req: ScoreRequest,
    request: Request,
    policy: str = Query("f1", pattern="^(f1|recall95|precision20)$"),
):
    t0 = time.time()
    user_feats = get_user_features(req.user_id)

    audit_id = request.state.request_id
    bucket = stable_bucket_0_99(req.user_id)
    prod_variant = resolve_variant(req.user_id)

    prod = score_with_variant(
        variant=prod_variant,
        user_features=user_feats,
        amount=req.amount,
        country=req.country,
        policy=policy,
    )

    PREDICTION_COUNT.labels(model_variant=prod_variant).inc()
    PREDICTION_SCORE.labels(model_variant=prod_variant).observe(float(prod["score"]))
    if int(prod["decision"]) == 1:
        FRAUD_PREDICTIONS.labels(model_variant=prod_variant).inc()

    shadow = None
    if SHADOW_EVAL:
        sh_variant = other_variant(prod_variant)
        if (
            MODEL_REGISTRY.get(sh_variant, {}).get("model") is not None
            and MODEL_REGISTRY.get(sh_variant, {}).get("features") is not None
        ):
            t_shadow0 = time.time()
            shadow = score_with_variant(
                variant=sh_variant,
                user_features=user_feats,
                amount=req.amount,
                country=req.country,
                policy=policy,
            )
            shadow_latency_ms = round((time.time() - t_shadow0) * 1000, 2)

            emit_shadow_event(
                {
                    "ts_utc": datetime.now(timezone.utc).isoformat(),
                    "endpoint": "/score",
                    "audit_id": audit_id,
                    "user_id": req.user_id,
                    "feature_date": user_feats.get("feature_date"),
                    "policy": policy,
                    "bucket": bucket,
                    "prod_model": prod_variant,
                    "shadow_model": sh_variant,
                    "prod_model_version": prod["model_version"],
                    "shadow_model_version": shadow["model_version"],
                    "prod_score": float(prod["score"]),
                    "prod_thr": float(prod["threshold"]),
                    "prod_decision": int(prod["decision"]),
                    "shadow_score": float(shadow["score"]),
                    "shadow_thr": float(shadow["threshold"]),
                    "shadow_decision": int(shadow["decision"]),
                    "delta_score": float(shadow["score"]) - float(prod["score"]),
                    "delta_decision": int(shadow["decision"]) - int(prod["decision"]),
                    "shadow_latency_ms": float(shadow_latency_ms),
                    "shadow_model_loaded": int(shadow.get("model_loaded", False)),
                }
            )

            SHADOW_PREDICTIONS.labels(
                endpoint="/score",
                policy=policy,
                prod_model=prod_variant,
                shadow_model=sh_variant,
            ).inc()
            SHADOW_LATENCY.labels(
                endpoint="/score",
                policy=policy,
                prod_model=prod_variant,
                shadow_model=sh_variant,
            ).observe(shadow_latency_ms)

            log_event(
                "shadow_score_user",
                audit_id=audit_id,
                user_id=req.user_id,
                feature_date=user_feats.get("feature_date"),
                prod_model=prod_variant,
                prod_model_version=prod["model_version"],
                prod_score=float(prod["score"]),
                prod_threshold=float(prod["threshold"]),
                prod_decision=int(prod["decision"]),
                shadow_model=sh_variant,
                shadow_model_version=shadow["model_version"],
                shadow_score=float(shadow["score"]),
                shadow_threshold=float(shadow["threshold"]),
                shadow_decision=int(shadow["decision"]),
                shadow_latency_ms=shadow_latency_ms,
            )

    latency_ms = round((time.time() - t0) * 1000, 2)

    REQUESTS.labels(endpoint="/score", status_code="200", policy=policy, active_model=prod_variant).inc()
    LATENCY.labels(endpoint="/score", policy=policy, active_model=prod_variant).observe(latency_ms)
    FRAUD_DECISIONS.labels(
        endpoint="/score",
        policy=policy,
        active_model=prod_variant,
        decision=str(prod["decision"]),
    ).inc()

    log_event(
        "score_user",
        audit_id=audit_id,
        user_id=req.user_id,
        feature_date=user_feats.get("feature_date"),
        model_version=prod["model_version"],
        policy_used=policy,
        threshold_used=float(prod["threshold"]),
        fraud_probability=float(prod["score"]),
        fraud_decision=int(prod["decision"]),
        active_model=prod_variant,
        bucket=bucket,
        latency_ms=latency_ms,
    )

    resp = {
        "audit_id": audit_id,
        "user_id": req.user_id,
        "fraud_probability": round(float(prod["score"]), 6),
        "feature_date": user_feats.get("feature_date"),
        "model_probability": round(float(prod["model_probability"]), 6) if prod["model_probability"] is not None else None,
        "model_version": prod["model_version"],
        "policy_used": policy,
        "threshold_used": float(prod["threshold"]),
        "fraud_decision": int(prod["decision"]),
        "latency_ms": latency_ms,
        "active_model": prod_variant,
        "bucket": bucket,
        "top_feature_contribs": prod["top_feature_contribs"],
        "bias": prod["bias"],
        "shadow_eval": bool(SHADOW_EVAL),
        "shadow": (
            {
                "model": shadow["variant"],
                "model_version": shadow["model_version"],
                "fraud_probability": round(float(shadow["score"]), 6),
                "model_probability": round(float(shadow["model_probability"]), 6)
                if shadow["model_probability"] is not None
                else None,
                "threshold_used": float(shadow["threshold"]),
                "fraud_decision": int(shadow["decision"]),
            }
            if shadow is not None
            else None
        ),
    }

    response = JSONResponse(content=resp)
    response.headers["x-model-version"] = prod["model_version"]
    response.headers["x-active-model"] = prod_variant
    response.headers["x-bucket"] = str(bucket)
    response.headers["x-policy-used"] = policy
    response.headers["x-threshold-used"] = str(prod["threshold"])
    if shadow is not None:
        response.headers["x-shadow-model"] = shadow["variant"]
        response.headers["x-shadow-model-version"] = shadow["model_version"]
    return response


@app.post("/score/transaction")
def score_transaction(
    evt: TransactionEvent,
    request: Request,
    policy: str = Query("f1", pattern="^(f1|recall95|precision20)$"),
):
    t0 = time.time()
    user_feats = get_user_features(evt.user_id)

    audit_id = request.state.request_id
    bucket = stable_bucket_0_99(evt.user_id)
    prod_variant = resolve_variant(evt.user_id)

    prod = score_with_variant(
        variant=prod_variant,
        user_features=user_feats,
        amount=evt.amount,
        country=evt.country,
        policy=policy,
    )

    PREDICTION_COUNT.labels(model_variant=prod_variant).inc()
    PREDICTION_SCORE.labels(model_variant=prod_variant).observe(float(prod["score"]))
    if int(prod["decision"]) == 1:
        FRAUD_PREDICTIONS.labels(model_variant=prod_variant).inc()

    shadow = None
    if SHADOW_EVAL:
        sh_variant = other_variant(prod_variant)
        if (
            MODEL_REGISTRY.get(sh_variant, {}).get("model") is not None
            and MODEL_REGISTRY.get(sh_variant, {}).get("features") is not None
        ):
            t_shadow0 = time.time()
            shadow = score_with_variant(
                variant=sh_variant,
                user_features=user_feats,
                amount=evt.amount,
                country=evt.country,
                policy=policy,
            )
            shadow_latency_ms = round((time.time() - t_shadow0) * 1000, 2)

            emit_shadow_event(
                {
                    "ts_utc": datetime.now(timezone.utc).isoformat(),
                    "endpoint": "/score/transaction",
                    "audit_id": audit_id,
                    "transaction_id": evt.transaction_id,
                    "user_id": evt.user_id,
                    "feature_date": user_feats.get("feature_date"),
                    "policy": policy,
                    "bucket": bucket,
                    "prod_model": prod_variant,
                    "shadow_model": sh_variant,
                    "prod_model_version": prod["model_version"],
                    "shadow_model_version": shadow["model_version"],
                    "prod_score": float(prod["score"]),
                    "prod_thr": float(prod["threshold"]),
                    "prod_decision": int(prod["decision"]),
                    "shadow_score": float(shadow["score"]),
                    "shadow_thr": float(shadow["threshold"]),
                    "shadow_decision": int(shadow["decision"]),
                    "delta_score": float(shadow["score"]) - float(prod["score"]),
                    "delta_decision": int(shadow["decision"]) - int(prod["decision"]),
                    "shadow_latency_ms": float(shadow_latency_ms),
                    "shadow_model_loaded": int(shadow.get("model_loaded", False)),
                }
            )

            SHADOW_PREDICTIONS.labels(
                endpoint="/score/transaction",
                policy=policy,
                prod_model=prod_variant,
                shadow_model=sh_variant,
            ).inc()
            SHADOW_LATENCY.labels(
                endpoint="/score/transaction",
                policy=policy,
                prod_model=prod_variant,
                shadow_model=sh_variant,
            ).observe(shadow_latency_ms)

            log_event(
                "shadow_score_transaction",
                audit_id=audit_id,
                transaction_id=evt.transaction_id,
                user_id=evt.user_id,
                feature_date=user_feats.get("feature_date"),
                prod_model=prod_variant,
                prod_model_version=prod["model_version"],
                prod_score=float(prod["score"]),
                prod_threshold=float(prod["threshold"]),
                prod_decision=int(prod["decision"]),
                shadow_model=sh_variant,
                shadow_model_version=shadow["model_version"],
                shadow_score=float(shadow["score"]),
                shadow_threshold=float(shadow["threshold"]),
                shadow_decision=int(shadow["decision"]),
                shadow_latency_ms=shadow_latency_ms,
            )

    latency_ms = round((time.time() - t0) * 1000, 2)

    REQUESTS.labels(endpoint="/score/transaction", status_code="200", policy=policy, active_model=prod_variant).inc()
    LATENCY.labels(endpoint="/score/transaction", policy=policy, active_model=prod_variant).observe(latency_ms)
    FRAUD_DECISIONS.labels(
        endpoint="/score/transaction",
        policy=policy,
        active_model=prod_variant,
        decision=str(prod["decision"]),
    ).inc()

    log_event(
        "score_transaction",
        audit_id=audit_id,
        transaction_id=evt.transaction_id,
        user_id=evt.user_id,
        amount=float(evt.amount),
        country=evt.country,
        feature_date=user_feats.get("feature_date"),
        model_version=prod["model_version"],
        policy_used=policy,
        threshold_used=float(prod["threshold"]),
        fraud_probability=float(prod["score"]),
        fraud_decision=int(prod["decision"]),
        active_model=prod_variant,
        bucket=bucket,
        latency_ms=latency_ms,
    )

    resp = {
        "audit_id": audit_id,
        "transaction_id": evt.transaction_id,
        "user_id": evt.user_id,
        "fraud_probability": round(float(prod["score"]), 6),
        "model_probability": round(float(prod["model_probability"]), 6) if prod["model_probability"] is not None else None,
        "feature_date": user_feats.get("feature_date"),
        "model_version": prod["model_version"],
        "policy_used": policy,
        "threshold_used": float(prod["threshold"]),
        "fraud_decision": int(prod["decision"]),
        "latency_ms": latency_ms,
        "active_model": prod_variant,
        "bucket": bucket,
        "top_feature_contribs": prod["top_feature_contribs"],
        "bias": prod["bias"],
        "shadow_eval": bool(SHADOW_EVAL),
        "shadow": (
            {
                "model": shadow["variant"],
                "model_version": shadow["model_version"],
                "fraud_probability": round(float(shadow["score"]), 6),
                "model_probability": round(float(shadow["model_probability"]), 6)
                if shadow["model_probability"] is not None
                else None,
                "threshold_used": float(shadow["threshold"]),
                "fraud_decision": int(shadow["decision"]),
            }
            if shadow is not None
            else None
        ),
    }

    response = JSONResponse(content=resp)
    response.headers["x-model-version"] = prod["model_version"]
    response.headers["x-active-model"] = prod_variant
    response.headers["x-bucket"] = str(bucket)
    response.headers["x-policy-used"] = policy
    response.headers["x-threshold-used"] = str(prod["threshold"])
    if shadow is not None:
        response.headers["x-shadow-model"] = shadow["variant"]
        response.headers["x-shadow-model-version"] = shadow["model_version"]
    return response


@app.get("/shadow/summary")
def shadow_summary(n: int = Query(200, ge=1, le=5000)):
    """
    Summarize the last N shadow events from Redis stream `shadow_events`.
    """
    try:
        items = r.xrevrange(SHADOW_STREAM, max="+", min="-", count=n)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read Redis stream: {e}")

    if not items:
        return {
            "stream": SHADOW_STREAM,
            "n_requested": n,
            "n_returned": 0,
            "note": "No shadow events found.",
        }

    prod_counts = CollCounter()
    shadow_counts = CollCounter()
    policy_counts = CollCounter()

    mismatches = 0
    total = 0

    delta_scores: List[float] = []
    shadow_latency: List[float] = []

    for _id, fields in items:
        total += 1
        prod_counts[fields.get("prod_model")] += 1
        shadow_counts[fields.get("shadow_model")] += 1
        policy_counts[fields.get("policy")] += 1

        dd = _to_int(fields.get("delta_decision"))
        if dd == 1:
            mismatches += 1

        ds = _to_float(fields.get("delta_score"))
        if ds is not None:
            delta_scores.append(ds)

        sl = _to_float(fields.get("shadow_latency_ms"))
        if sl is not None:
            shadow_latency.append(sl)

    def stats(vals: List[float]) -> Dict[str, Any]:
        if not vals:
            return {"count": 0}
        vals_sorted = sorted(vals)

        def pct(p):
            i = int(round((p / 100.0) * (len(vals_sorted) - 1)))
            return vals_sorted[max(0, min(len(vals_sorted) - 1, i))]

        return {
            "count": len(vals_sorted),
            "min": vals_sorted[0],
            "p50": pct(50),
            "p90": pct(90),
            "p99": pct(99),
            "max": vals_sorted[-1],
            "mean": sum(vals_sorted) / len(vals_sorted),
        }

    return {
        "stream": SHADOW_STREAM,
        "n_requested": n,
        "n_returned": total,
        "prod_model_counts": dict(prod_counts),
        "shadow_model_counts": dict(shadow_counts),
        "policy_counts": dict(policy_counts),
        "decision_mismatches": mismatches,
        "decision_mismatch_rate": (mismatches / total) if total else 0.0,
        "delta_score_stats": stats(delta_scores),
        "shadow_latency_ms_stats": stats(shadow_latency),
        "ts_utc": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/shadow/gate")
def shadow_gate(
    n: int = Query(200, ge=1, le=5000),
    max_mismatch_rate: float = Query(0.01, ge=0.0, le=1.0),
    max_shadow_latency_p99_ms: float = Query(50.0, ge=0.0),
    max_abs_delta_score_p99: float = Query(0.05, ge=0.0),
):
    return _shadow_gate_eval(
        n=n,
        max_mismatch_rate=max_mismatch_rate,
        max_shadow_latency_p99_ms=max_shadow_latency_p99_ms,
        max_abs_delta_score_p99=max_abs_delta_score_p99,
    )


@app.post("/shadow/promote")
def shadow_promote(
    n: int = Query(2000, ge=50, le=5000),
    step: int = Query(20, ge=1, le=90),
    min_events: int = Query(200, ge=50, le=5000),
):
    cfg = get_routing_config()
    current_pct = int(cfg["champion_pct"])

    gate = _shadow_gate_eval(
        n=n,
        max_mismatch_rate=0.01,
        max_shadow_latency_p99_ms=50.0,
        max_abs_delta_score_p99=0.05,
    )

    if gate.get("n_returned", 0) < min_events:
        raise HTTPException(status_code=400, detail="Not enough shadow events.")

    if not gate.get("pass", False):
        return {
            "recommendation": "HOLD",
            "reason": "Gate failed.",
            "current_champion_pct": current_pct,
            "suggested_champion_pct": current_pct,
            "gate": gate,
        }

    new_pct = max(0, current_pct - int(step))

    return {
        "recommendation": "RAMP",
        "reason": "Gate passed; reduce CHAMPION_PCT to shift more traffic to challenger.",
        "current_champion_pct": current_pct,
        "suggested_champion_pct": int(new_pct),
        "note": "Apply by updating routing config and/or reloading inference-api if needed.",
        "gate": gate,
    }


@app.get("/model")
def model_info():
    cfg = get_routing_config()

    def summarize(v: str):
        e = MODEL_REGISTRY[v]
        metrics = e["metrics"] or {}
        features = e["features"] or []
        return {
            "loaded": e["model"] is not None,
            "features_loaded": e["features"] is not None,
            "feature_count": len(features),
            "feature_list": features,
            "metrics_loaded": e["metrics"] is not None,
            "model_version": metrics.get("model_version") or MODEL_VERSION,
            "thresholds": e["thresholds"],
            "default_thr": float(e["default_thr"]),
            "paths": {
                "model": os.path.join(BASE_MODELS_DIR, v, "model.joblib"),
                "feature_list": os.path.join(BASE_MODELS_DIR, v, "feature_list.json"),
                "metrics": os.path.join(BASE_MODELS_DIR, v, "metrics.json"),
            },
        }

    return {
        "active_model_mode": cfg["active_model_mode"],
        "champion_pct": cfg["champion_pct"],
        "shadow_eval": SHADOW_EVAL,
        "champion": summarize("champion"),
        "challenger": summarize("challenger"),
    }


@app.get("/model/status")
def model_status():
    cfg = get_routing_config()

    def summarize(v: str):
        entry = MODEL_REGISTRY[v]
        metrics = entry.get("metrics") or {}
        features = entry.get("features") or []
        return {
            "loaded": entry.get("model") is not None,
            "model_version": metrics.get("model_version") or MODEL_VERSION,
            "feature_count": len(features),
            "default_threshold": float(entry.get("default_thr") or DEFAULT_DECISION_THRESHOLD),
            "thresholds": entry.get("thresholds") or {},
        }

    return {
        "ts_utc": datetime.now(timezone.utc).isoformat(),
        "routing": cfg,
        "shadow_eval": SHADOW_EVAL,
        "champion": summarize("champion"),
        "challenger": summarize("challenger"),
    }


@app.post("/reload-models")
def reload_models():
    return reload_all_models()


@app.get("/routing")
def routing():
    return get_routing_config()


@app.post("/routing")
def update_routing(cfg: RoutingConfigRequest):
    set_routing_config(cfg.active_model_mode, cfg.champion_pct)
    log_event(
        "routing_updated",
        active_model_mode=cfg.active_model_mode,
        champion_pct=cfg.champion_pct,
    )
    return get_routing_config()


@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
