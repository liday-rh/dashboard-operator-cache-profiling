#!/usr/bin/env bash

set -euo pipefail

if [[ $# -ne 5 ]]; then
  echo "usage: $0 KUBECONFIG OUTPUT_TSV SAMPLE_COUNT INTERVAL_SECONDS EXPECTED_IMAGE" >&2
  exit 2
fi

kubeconfig=$1
output=$2
sample_count=$3
interval_seconds=$4
expected_image=$5
namespace=redhat-ods-applications

pod=$(oc --kubeconfig "$kubeconfig" get pods -n "$namespace" -o json |
  jq -r '[.items[] | select(.metadata.name | startswith("dashboard-operator-")) | select(.status.phase == "Running") | .metadata.name] | if length == 1 then .[0] else error("expected exactly one running dashboard-operator pod") end')
pod_uid=$(oc --kubeconfig "$kubeconfig" get pod "$pod" -n "$namespace" -o jsonpath='{.metadata.uid}')
image=$(oc --kubeconfig "$kubeconfig" get pod "$pod" -n "$namespace" -o jsonpath='{.spec.containers[0].image}')

if [[ "$image" != "$expected_image" ]]; then
  echo "unexpected operator image: $image" >&2
  exit 1
fi

printf 'timestamp\tworking_set\trestarts\tlast_reason\tprocess_rss_bytes\theap_alloc_bytes\theap_inuse_bytes\theap_objects\tgo_sys_bytes\tcpu_seconds\tdashboard_reconciles\n' > "$output"

for ((sample = 1; sample <= sample_count; sample++)); do
  current_uid=$(oc --kubeconfig "$kubeconfig" get pod "$pod" -n "$namespace" -o jsonpath='{.metadata.uid}')
  if [[ "$current_uid" != "$pod_uid" ]]; then
    echo "dashboard-operator pod identity changed during benchmark" >&2
    exit 1
  fi

  timestamp=$(date -u '+%Y-%m-%dT%H:%M:%SZ')
  working_set=$(oc --kubeconfig "$kubeconfig" adm top pod "$pod" -n "$namespace" --containers --no-headers | awk 'NR == 1 {print $4}')
  status=$(oc --kubeconfig "$kubeconfig" get pod "$pod" -n "$namespace" -o json)
  restarts=$(printf '%s' "$status" | jq -r '.status.containerStatuses[0].restartCount')
  last_reason=$(printf '%s' "$status" | jq -r '.status.containerStatuses[0].lastState.terminated.reason // "none"')
  metrics=$(oc --kubeconfig "$kubeconfig" exec -n "$namespace" "$pod" -- sh -c 'curl -ks https://127.0.0.1:8443/metrics')

  process_rss=$(printf '%s\n' "$metrics" | awk '$1 == "process_resident_memory_bytes" {print $2}')
  heap_alloc=$(printf '%s\n' "$metrics" | awk '$1 == "go_memstats_heap_alloc_bytes" {print $2}')
  heap_inuse=$(printf '%s\n' "$metrics" | awk '$1 == "go_memstats_heap_inuse_bytes" {print $2}')
  heap_objects=$(printf '%s\n' "$metrics" | awk '$1 == "go_memstats_heap_objects" {print $2}')
  go_sys=$(printf '%s\n' "$metrics" | awk '$1 == "go_memstats_sys_bytes" {print $2}')
  cpu_seconds=$(printf '%s\n' "$metrics" | awk '$1 == "process_cpu_seconds_total" {print $2}')
  dashboard_reconciles=$(printf '%s\n' "$metrics" | awk '$1 ~ /^controller_runtime_reconcile_total\{controller="dashboard",/ {sum += $2} END {print sum + 0}')

  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
    "$timestamp" "$working_set" "$restarts" "$last_reason" "$process_rss" \
    "$heap_alloc" "$heap_inuse" "$heap_objects" "$go_sys" "$cpu_seconds" \
    "$dashboard_reconciles" >> "$output"

  echo "sample $sample/$sample_count: working_set=$working_set restarts=$restarts rss=$process_rss heap_alloc=$heap_alloc reconciles=$dashboard_reconciles"

  if (( sample < sample_count )); then
    sleep "$interval_seconds"
  fi
done
