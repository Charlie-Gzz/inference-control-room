// Package metrics is a tiny Prometheus-style registry: labeled counters and one histogram.
package metrics

import (
	"fmt"
	"io"
	"sort"
	"sync"
)

// overheadBuckets are upper bounds in seconds for the router overhead histogram.
var overheadBuckets = []float64{0.00005, 0.0001, 0.0002, 0.0005, 0.001, 0.002, 0.005, 0.01, 0.05}

// Registry holds the router's metrics.
type Registry struct {
	mu        sync.Mutex
	decisions map[string]uint64 // key: policy + "\x00" + reason
	errors    uint64
	buckets   []uint64 // cumulative counts are computed when written
	sum       float64
	count     uint64
}

// New returns an empty registry.
func New() *Registry {
	return &Registry{decisions: map[string]uint64{}, buckets: make([]uint64, len(overheadBuckets)+1)}
}

// Decision counts one routing decision and its overhead in seconds.
func (r *Registry) Decision(policy, reason string, overheadSeconds float64) {
	r.mu.Lock()
	defer r.mu.Unlock()
	r.decisions[policy+"\x00"+reason]++
	i := sort.SearchFloat64s(overheadBuckets, overheadSeconds)
	r.buckets[i]++
	r.sum += overheadSeconds
	r.count++
}

// Error counts one failed upstream request.
func (r *Registry) Error() {
	r.mu.Lock()
	defer r.mu.Unlock()
	r.errors++
}

// Write renders the metrics in Prometheus text format.
// outstanding is the current number of in-flight requests per replica.
func (r *Registry) Write(w io.Writer, outstanding map[int]int) {
	r.mu.Lock()
	defer r.mu.Unlock()
	fmt.Fprintln(w, "# TYPE switchyard_decisions_total counter")
	keys := make([]string, 0, len(r.decisions))
	for k := range r.decisions {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	for _, k := range keys {
		var policy, reason string
		for i := range k {
			if k[i] == 0 {
				policy, reason = k[:i], k[i+1:]
			}
		}
		fmt.Fprintf(w, "switchyard_decisions_total{policy=%q,reason=%q} %d\n", policy, reason, r.decisions[k])
	}
	fmt.Fprintln(w, "# TYPE switchyard_upstream_errors_total counter")
	fmt.Fprintf(w, "switchyard_upstream_errors_total %d\n", r.errors)

	fmt.Fprintln(w, "# TYPE switchyard_overhead_seconds histogram")
	var cumulative uint64
	for i, le := range overheadBuckets {
		cumulative += r.buckets[i]
		fmt.Fprintf(w, "switchyard_overhead_seconds_bucket{le=\"%g\"} %d\n", le, cumulative)
	}
	fmt.Fprintf(w, "switchyard_overhead_seconds_bucket{le=\"+Inf\"} %d\n", r.count)
	fmt.Fprintf(w, "switchyard_overhead_seconds_sum %g\n", r.sum)
	fmt.Fprintf(w, "switchyard_overhead_seconds_count %d\n", r.count)

	fmt.Fprintln(w, "# TYPE switchyard_outstanding_requests gauge")
	replicas := make([]int, 0, len(outstanding))
	for i := range outstanding {
		replicas = append(replicas, i)
	}
	sort.Ints(replicas)
	for _, i := range replicas {
		fmt.Fprintf(w, "switchyard_outstanding_requests{replica=\"%d\"} %d\n", i, outstanding[i])
	}
}
