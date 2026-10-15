from prometheus_client import Counter, Gauge, Histogram

HTTP_REQUESTS = Counter(
    "payflow_http_requests_total",
    "HTTP requests by route template and status code",
    ["method", "route", "status"],
)
HTTP_LATENCY = Histogram(
    "payflow_http_request_duration_seconds",
    "HTTP request latency by route template",
    ["method", "route"],
)
TRANSFERS = Counter(
    "payflow_transfers_total", "Transfers by outcome", ["currency", "status"]
)
FRAUD_SIGNALS = Counter(
    "payflow_fraud_signals_total", "Fraud rules triggered on held transfers", ["signal"]
)
DEPOSITS = Counter(
    "payflow_deposits_total", "Deposits settled by the provider", ["currency", "status"]
)
EXCHANGES = Counter("payflow_exchanges_total", "Completed exchanges", ["pair"])
RATE_LIMITED = Counter(
    "payflow_rate_limited_total", "Requests rejected by rate limiting", ["scope"]
)
FX_RATE_CACHE = Counter(
    "payflow_fx_rate_cache_total", "Exchange rate cache lookups", ["result"]
)
OUTBOX_DELIVERIES = Counter(
    "payflow_outbox_deliveries_total",
    "Outbox delivery attempts by outcome",
    ["event_type", "outcome"],
)
RECONCILIATION_ISSUES = Gauge(
    "payflow_reconciliation_issues", "Issues found by the latest reconciliation"
)
RECONCILIATION_FINISHED_AT = Gauge(
    "payflow_reconciliation_finished_timestamp_seconds",
    "Unix time the latest reconciliation finished",
)
