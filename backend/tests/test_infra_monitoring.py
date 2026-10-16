"""infra/ definitions are gcloud-importable: Cloud Monitoring alert policies (AlertPolicy resources for
`gcloud alpha monitoring policies create --policy-from-file`), the log-based metric (LogMetric for
`gcloud logging metrics create --config-from-file`) and the Cloud Scheduler job. Without GCP credentials the API
cannot be asked, so these checks parse every file and hold its fields to the REST resource schema: field names,
enum values, duration syntax and the filters that tie the files to the code."""

import json
import re
from pathlib import Path

import pytest
import yaml

from app.providers.railradar_client import QUOTA_EXHAUSTED_EVENT

REPO = Path(__file__).resolve().parents[2]
MONITORING = REPO / "infra" / "monitoring"
POLICIES = sorted(MONITORING.glob("alert-*.yaml"))
LOG_METRIC = MONITORING / "log-metric-railradar-quota-exhausted.yaml"
DEPLOY = REPO / ".github" / "workflows" / "deploy.yml"

# monitoring.googleapis.com/v3 AlertPolicy, MetricThreshold and Aggregation fields and enums.
POLICY_FIELDS = {"displayName", "documentation", "userLabels", "conditions", "combiner", "enabled",
                 "notificationChannels", "alertStrategy", "severity"}
CONDITION_TYPES = {"conditionThreshold", "conditionAbsent", "conditionMatchedLog", "conditionMonitoringQueryLanguage",
                   "conditionPrometheusQueryLanguage", "conditionSql"}
THRESHOLD_FIELDS = {"filter", "aggregations", "denominatorFilter", "denominatorAggregations", "forecastOptions",
                    "comparison", "thresholdValue", "duration", "trigger", "evaluationMissingData"}
AGGREGATION_FIELDS = {"alignmentPeriod", "perSeriesAligner", "crossSeriesReducer", "groupByFields"}
COMPARISONS = {"COMPARISON_GT", "COMPARISON_GE", "COMPARISON_LT", "COMPARISON_LE", "COMPARISON_EQ", "COMPARISON_NE"}
ALIGNERS = {"ALIGN_NONE", "ALIGN_DELTA", "ALIGN_RATE", "ALIGN_INTERPOLATE", "ALIGN_NEXT_OLDER", "ALIGN_MIN",
            "ALIGN_MAX", "ALIGN_MEAN", "ALIGN_COUNT", "ALIGN_SUM", "ALIGN_STDDEV", "ALIGN_COUNT_TRUE",
            "ALIGN_COUNT_FALSE", "ALIGN_FRACTION_TRUE", "ALIGN_PERCENTILE_99", "ALIGN_PERCENTILE_95",
            "ALIGN_PERCENTILE_50", "ALIGN_PERCENTILE_05", "ALIGN_PERCENT_CHANGE"}
REDUCERS = {"REDUCE_NONE", "REDUCE_MEAN", "REDUCE_MIN", "REDUCE_MAX", "REDUCE_SUM", "REDUCE_STDDEV", "REDUCE_COUNT",
            "REDUCE_COUNT_TRUE", "REDUCE_COUNT_FALSE", "REDUCE_FRACTION_TRUE", "REDUCE_PERCENTILE_99",
            "REDUCE_PERCENTILE_95", "REDUCE_PERCENTILE_50", "REDUCE_PERCENTILE_05"}
SEVERITIES = {"CRITICAL", "ERROR", "WARNING"}
DURATION = re.compile(r"^\d+s$")
METRIC_TYPE = re.compile(r'metric\.type="([^"]+)"')


def load(path: Path) -> dict:
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(doc, dict), f"{path.name} is not a mapping"
    json.dumps(doc)  # gcloud also takes JSON: the document must survive the round trip
    return doc


def backend_service_default() -> str:
    match = re.search(r"BACKEND_SERVICE: \$\{\{ vars\.BACKEND_SERVICE \|\| '([^']+)' \}\}", DEPLOY.read_text())
    assert match, "deploy.yml no longer defines the BACKEND_SERVICE default"
    return match.group(1)


def check_filter(text: str) -> list[str]:
    assert text.count('"') % 2 == 0, f"unbalanced quotes in {text!r}"
    assert text.count("(") == text.count(")")
    types = METRIC_TYPE.findall(text)
    assert len(types) == 1, f"a filter names exactly one metric type: {text!r}"
    assert re.search(r'resource\.type="[a-z_]+"', text)
    return types


def check_aggregations(aggs: list) -> None:
    assert isinstance(aggs, list) and aggs
    for agg in aggs:
        assert set(agg) <= AGGREGATION_FIELDS, set(agg) - AGGREGATION_FIELDS
        assert DURATION.match(agg["alignmentPeriod"]) and int(agg["alignmentPeriod"][:-1]) >= 60
        assert agg["perSeriesAligner"] in ALIGNERS
        assert agg.get("crossSeriesReducer", "REDUCE_NONE") in REDUCERS


def test_the_four_required_policies_exist():
    names = {p.name for p in POLICIES}
    assert names == {"alert-backend-5xx-rate.yaml", "alert-backend-p95-latency.yaml", "alert-redis-memory.yaml",
                     "alert-railradar-quota-exhausted.yaml"}


@pytest.mark.parametrize("path", POLICIES, ids=lambda p: p.name)
def test_alert_policy_matches_the_alert_policy_resource(path):
    doc = load(path)
    assert set(doc) <= POLICY_FIELDS, set(doc) - POLICY_FIELDS
    assert doc["displayName"] and doc["combiner"] in {"AND", "OR", "AND_WITH_MATCHING_RESOURCE"}
    assert doc["severity"] in SEVERITIES
    assert doc["documentation"]["mimeType"] == "text/markdown" and "docs/RUNBOOK.md" in doc["documentation"]["content"]
    assert DURATION.match(doc["alertStrategy"]["autoClose"])
    assert doc["conditions"]
    for condition in doc["conditions"]:
        kinds = set(condition) & CONDITION_TYPES
        assert condition["displayName"] and kinds == {"conditionThreshold"}, kinds
        threshold = condition["conditionThreshold"]
        assert set(threshold) <= THRESHOLD_FIELDS, set(threshold) - THRESHOLD_FIELDS
        check_filter(threshold["filter"])
        check_aggregations(threshold["aggregations"])
        if "denominatorFilter" in threshold:
            check_filter(threshold["denominatorFilter"])
            check_aggregations(threshold["denominatorAggregations"])
        assert threshold["comparison"] in COMPARISONS
        assert isinstance(threshold["thresholdValue"], (int, float))
        assert DURATION.match(threshold["duration"])
        assert threshold["trigger"]["count"] >= 1


def test_backend_policies_watch_the_deployed_service_and_the_right_metrics():
    service = backend_service_default()
    by_name = {p.name: load(p)["conditions"][0]["conditionThreshold"] for p in POLICIES}
    five_xx = by_name["alert-backend-5xx-rate.yaml"]
    assert check_filter(five_xx["filter"]) == ["run.googleapis.com/request_count"]
    assert 'metric.labels.response_code_class="5xx"' in five_xx["filter"]
    assert "response_code_class" not in five_xx["denominatorFilter"]  # ratio of 5xx to all requests
    latency = by_name["alert-backend-p95-latency.yaml"]
    assert check_filter(latency["filter"]) == ["run.googleapis.com/request_latencies"]
    assert latency["aggregations"][0]["crossSeriesReducer"] == "REDUCE_PERCENTILE_95"
    for cond in (five_xx, latency):
        assert f'resource.labels.service_name="{service}"' in cond["filter"]
    redis = by_name["alert-redis-memory.yaml"]
    assert check_filter(redis["filter"]) == ["redis.googleapis.com/stats/memory/usage_ratio"]
    assert 0 < redis["thresholdValue"] < 1


def test_quota_metric_counts_the_log_line_the_backend_writes_and_the_alert_reads_it():
    metric = load(LOG_METRIC)
    assert set(metric) <= {"name", "description", "filter", "metricDescriptor", "labelExtractors", "valueExtractor",
                           "bucketOptions", "disabled", "bucketName"}
    assert re.fullmatch(r"[A-Za-z0-9_./-]+", metric["name"])
    assert f'jsonPayload.event="{QUOTA_EXHAUSTED_EVENT}"' in metric["filter"]
    assert f'resource.labels.service_name="{backend_service_default()}"' in metric["filter"]
    descriptor = metric["metricDescriptor"]
    assert descriptor["metricKind"] == "DELTA" and descriptor["valueType"] == "INT64"
    assert {label["key"] for label in descriptor["labels"]} == set(metric["labelExtractors"])
    assert all(re.fullmatch(r"EXTRACT\(jsonPayload\.[a-z_]+\)", v) for v in metric["labelExtractors"].values())

    alert = load(MONITORING / "alert-railradar-quota-exhausted.yaml")["conditions"][0]["conditionThreshold"]
    assert check_filter(alert["filter"]) == [f"logging.googleapis.com/user/{metric['name']}"]


def test_scheduler_job_definition_parses_and_targets_the_collector():
    job = load(REPO / "infra" / "scheduler" / "collect-observations.yaml")
    assert job["httpTarget"]["httpMethod"] == "POST" and job["httpTarget"]["uri"].endswith("/internal/collect")
    assert job["httpTarget"]["oidcToken"]["audience"] and DURATION.match(job["attemptDeadline"])
