package policies

import (
	"container/list"
	"math"
	"sort"
	"sync"
)

// Policy names.
const (
	RoundRobin  = "round-robin"
	LeastLoaded = "least-loaded"
	PrefixAware = "prefix-aware"
)

// ValidPolicy reports whether name is a known policy.
func ValidPolicy(name string) bool {
	return name == RoundRobin || name == LeastLoaded || name == PrefixAware
}

// Config holds the prefix-aware policy's knobs. Mirrors RouterConfig in policy.py.
type Config struct {
	ChunkSize   int     `json:"chunk_size"`   // bytes of prompt text per hashed chunk
	MaxChunks   int     `json:"max_chunks"`   // hash at most this many chunks per request
	TableChunks int     `json:"table_chunks"` // prefix hashes remembered per replica (LRU)
	LoadFactor  float64 `json:"load_factor"`  // overloaded above LoadFactor x fair share
	MinBound    int     `json:"min_bound"`    // ... but never below this many outstanding
}

// DefaultConfig is used when no flags are given.
func DefaultConfig() Config {
	return Config{ChunkSize: 256, MaxChunks: 128, TableChunks: 4096, LoadFactor: 1.5, MinBound: 4}
}

// Decision is one routing choice and why it was made.
type Decision struct {
	Replica int    `json:"replica"`
	Reason  string `json:"reason"` // round-robin | least-loaded | prefix-hit | prefix-overloaded | no-prefix
	Matched int    `json:"matched_chunks"`
	Loads   []int  `json:"loads"` // outstanding per live replica when the decision was made
}

// lru is a set of prefix hashes with least-recently-used eviction.
type lru struct {
	order *list.List // front = most recently used
	items map[uint64]*list.Element
}

func newLRU() *lru { return &lru{order: list.New(), items: map[uint64]*list.Element{}} }

func (l *lru) has(h uint64) bool { _, ok := l.items[h]; return ok }

func (l *lru) touch(h uint64) {
	if e, ok := l.items[h]; ok {
		l.order.MoveToFront(e)
		return
	}
	l.items[h] = l.order.PushFront(h)
}

func (l *lru) trim(capacity int) {
	for l.order.Len() > capacity {
		oldest := l.order.Back()
		delete(l.items, oldest.Value.(uint64))
		l.order.Remove(oldest)
	}
}

// Router is the routing state: live replicas, outstanding requests, prefix tables.
// All methods are safe for concurrent use.
type Router struct {
	mu          sync.Mutex
	cfg         Config
	policy      string
	live        []int
	outstanding map[int]int
	tables      map[int]*lru
	rrNext      int
}

// NewRouter creates a router with replicas 0..n-1 live.
func NewRouter(replicas int, policy string, cfg Config) *Router {
	r := &Router{cfg: cfg, policy: policy, outstanding: map[int]int{}, tables: map[int]*lru{}}
	live := make([]int, replicas)
	for i := range live {
		live[i] = i
	}
	r.SetLive(live)
	return r
}

// SetLive replaces the set of replicas that may receive requests.
// A replica that leaves the set loses its prefix table (its cache is gone).
func (r *Router) SetLive(live []int) {
	r.mu.Lock()
	defer r.mu.Unlock()
	r.live = append([]int(nil), live...)
	sort.Ints(r.live)
	isLive := map[int]bool{}
	for _, i := range r.live {
		isLive[i] = true
		if r.tables[i] == nil {
			r.tables[i] = newLRU()
		}
	}
	for i := range r.tables {
		if !isLive[i] {
			r.tables[i] = newLRU()
		}
	}
}

// SetPolicy switches the routing policy.
func (r *Router) SetPolicy(policy string) {
	r.mu.Lock()
	defer r.mu.Unlock()
	r.policy = policy
}

// Reset forgets every remembered prefix and restarts round-robin.
func (r *Router) Reset() {
	r.mu.Lock()
	defer r.mu.Unlock()
	for i := range r.tables {
		r.tables[i] = newLRU()
	}
	r.rrNext = 0
}

// State is a snapshot for the admin endpoint.
type State struct {
	Policy      string      `json:"policy"`
	Live        []int       `json:"live"`
	Outstanding map[int]int `json:"outstanding"`
	TableSizes  map[int]int `json:"table_sizes"`
}

// Snapshot returns the current state.
func (r *Router) Snapshot() State {
	r.mu.Lock()
	defer r.mu.Unlock()
	s := State{Policy: r.policy, Live: append([]int(nil), r.live...),
		Outstanding: map[int]int{}, TableSizes: map[int]int{}}
	for i, n := range r.outstanding {
		s.Outstanding[i] = n
	}
	for i, t := range r.tables {
		s.TableSizes[i] = t.order.Len()
	}
	return s
}

// NeedsText reports whether the current policy reads the prompt text.
func (r *Router) NeedsText() bool {
	r.mu.Lock()
	defer r.mu.Unlock()
	return r.policy == PrefixAware
}

// Route picks a replica and counts the request as outstanding.
// ok is false when no replica is live.
func (r *Router) Route(text []byte) (d Decision, policy string, ok bool) {
	r.mu.Lock()
	defer r.mu.Unlock()
	if len(r.live) == 0 {
		return Decision{}, r.policy, false
	}
	loads := make([]int, len(r.live))
	for k, i := range r.live {
		loads[k] = r.outstanding[i]
	}
	var hashes []uint64
	switch r.policy {
	case RoundRobin:
		d = Decision{Replica: r.live[r.rrNext%len(r.live)], Reason: "round-robin"}
		r.rrNext++
	case LeastLoaded:
		d = Decision{Replica: r.leastLoaded(), Reason: "least-loaded"}
	default:
		hashes = PrefixHashes(text, r.cfg.ChunkSize, r.cfg.MaxChunks)
		d = r.prefixAware(hashes)
	}
	d.Loads = loads
	r.outstanding[d.Replica]++
	if len(hashes) > 0 {
		r.remember(d.Replica, hashes)
	}
	return d, r.policy, true
}

// Finish marks one request on replica as done.
func (r *Router) Finish(replica int) {
	r.mu.Lock()
	defer r.mu.Unlock()
	if r.outstanding[replica] > 0 {
		r.outstanding[replica]--
	}
}

func (r *Router) leastLoaded() int {
	best := r.live[0]
	for _, i := range r.live[1:] {
		if r.outstanding[i] < r.outstanding[best] {
			best = i
		}
	}
	return best
}

// bound is the most outstanding requests a replica may have and still take a prefix hit.
func (r *Router) bound() int {
	total := 0
	for _, i := range r.live {
		total += r.outstanding[i]
	}
	fair := float64(total+1) / float64(len(r.live))
	b := int(math.Ceil(r.cfg.LoadFactor * fair))
	if b < r.cfg.MinBound {
		b = r.cfg.MinBound
	}
	return b
}

func (r *Router) match(replica int, hashes []uint64) int {
	table := r.tables[replica]
	n := 0
	for _, h := range hashes {
		if !table.has(h) {
			break
		}
		n++
	}
	return n
}

func (r *Router) prefixAware(hashes []uint64) Decision {
	matches := map[int]int{}
	best := 0
	for _, i := range r.live {
		matches[i] = r.match(i, hashes)
		if matches[i] > best {
			best = matches[i]
		}
	}
	if best == 0 {
		return Decision{Replica: r.leastLoaded(), Reason: "no-prefix"}
	}
	// Longest match first; ties go to the less loaded replica, then the lower index.
	ranked := append([]int(nil), r.live...)
	sort.SliceStable(ranked, func(a, b int) bool {
		x, y := ranked[a], ranked[b]
		if matches[x] != matches[y] {
			return matches[x] > matches[y]
		}
		if r.outstanding[x] != r.outstanding[y] {
			return r.outstanding[x] < r.outstanding[y]
		}
		return x < y
	})
	bound := r.bound()
	for _, i := range ranked {
		if matches[i] == 0 {
			break
		}
		if r.outstanding[i] <= bound {
			return Decision{Replica: i, Reason: "prefix-hit", Matched: matches[i]}
		}
	}
	return Decision{Replica: r.leastLoaded(), Reason: "prefix-overloaded", Matched: best}
}

// remember records that replica will now hold these prefixes.
// The longest prefix is touched first, so short (widely shared) prefixes are evicted last.
func (r *Router) remember(replica int, hashes []uint64) {
	table := r.tables[replica]
	for k := len(hashes) - 1; k >= 0; k-- {
		table.touch(hashes[k])
	}
	table.trim(r.cfg.TableChunks)
}
