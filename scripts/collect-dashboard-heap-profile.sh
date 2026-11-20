#!/usr/bin/env bash

set -euo pipefail

if [[ $# -lt 4 || $# -gt 5 ]]; then
  echo "usage: $0 KUBECONFIG NAMESPACE POD OUTPUT_PREFIX [CONTAINER]" >&2
  exit 2
fi

kubeconfig=$1
namespace=$2
pod=$3
output_prefix=$4
container=${5:-manager}
endpoint='http://127.0.0.1:6060/debug/pprof/heap'
pprof_bin=${PPROF_BIN:-pprof}

oc --kubeconfig "$kubeconfig" exec -n "$namespace" "$pod" -c "$container" -- \
  curl -fsS "${endpoint}?gc=1" > "${output_prefix}-heap.pb.gz"
oc --kubeconfig "$kubeconfig" exec -n "$namespace" "$pod" -c "$container" -- \
  curl -fsS "${endpoint}?gc=1&debug=1" > "${output_prefix}-heap.txt"

"$pprof_bin" -sample_index=inuse_space -top -nodecount=100 \
  "${output_prefix}-heap.pb.gz" > "${output_prefix}-inuse-space.txt"
"$pprof_bin" -sample_index=inuse_objects -top -nodecount=100 \
  "${output_prefix}-heap.pb.gz" > "${output_prefix}-inuse-objects.txt"
"$pprof_bin" -sample_index=alloc_space -top -nodecount=100 \
  "${output_prefix}-heap.pb.gz" > "${output_prefix}-alloc-space.txt"
"$pprof_bin" -sample_index=alloc_objects -top -nodecount=100 \
  "${output_prefix}-heap.pb.gz" > "${output_prefix}-alloc-objects.txt"

echo "Collected heap profile from ${pod}:"
ls -lh "${output_prefix}"-heap.pb.gz "${output_prefix}"-heap.txt \
  "${output_prefix}"-inuse-space.txt "${output_prefix}"-inuse-objects.txt \
  "${output_prefix}"-alloc-space.txt "${output_prefix}"-alloc-objects.txt
