package main

import (
	"bufio"
	"bytes"
	"encoding/json"
	"io"
	"net/http"
	"os"
	"strconv"
	"strings"
	"sync"
	"time"

	"switchyard/router/metrics"
	"switchyard/router/policies"
)

type server struct {
	router  *policies.Router
	metrics *metrics.Registry
	client  *http.Client

	mu   sync.Mutex
	urls map[int]string // replica id -> base URL
	log  *bufio.Writer  // decision log, nil when disabled
}

// newUpstreamClient keeps connections to the replicas open and never buffers or compresses.
func newUpstreamClient() *http.Client {
	return &http.Client{Transport: &http.Transport{
		MaxIdleConns:        4096,
		MaxIdleConnsPerHost: 1024,
		IdleConnTimeout:     90 * time.Second,
		DisableCompression:  true,
	}}
}

func (s *server) handler() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("POST /v1/chat/completions", s.proxy)
	mux.HandleFunc("POST /v1/completions", s.proxy)
	mux.HandleFunc("GET /health", func(w http.ResponseWriter, _ *http.Request) { w.WriteHeader(http.StatusOK) })
	mux.HandleFunc("GET /metrics", func(w http.ResponseWriter, _ *http.Request) {
		s.metrics.Write(w, s.router.Snapshot().Outstanding)
	})
	s.registerAdmin(mux)
	return mux
}

// proxy routes one request and streams the replica's response back unbuffered.
func (s *server) proxy(w http.ResponseWriter, r *http.Request) {
	start := time.Now()
	body, err := io.ReadAll(http.MaxBytesReader(w, r.Body, 8<<20))
	if err != nil {
		http.Error(w, "cannot read request body", http.StatusBadRequest)
		return
	}
	var text []byte
	if s.router.NeedsText() { // only the prefix-aware policy parses the body
		text = policies.CanonicalText(body)
	}
	decision, policy, ok := s.router.Route(text)
	if !ok {
		http.Error(w, "no live replicas", http.StatusServiceUnavailable)
		return
	}
	defer s.router.Finish(decision.Replica)

	s.mu.Lock()
	base := s.urls[decision.Replica]
	s.mu.Unlock()
	upstream, err := http.NewRequestWithContext(r.Context(), http.MethodPost, base+r.URL.Path, bytes.NewReader(body))
	if err != nil {
		http.Error(w, err.Error(), http.StatusInternalServerError)
		return
	}
	upstream.Header.Set("Content-Type", "application/json")
	requestID := r.Header.Get("X-Request-Id")
	if requestID != "" {
		upstream.Header.Set("X-Request-Id", requestID)
	}

	overhead := time.Since(start) // body read + decision: what the router adds before forwarding
	s.metrics.Decision(policy, decision.Reason, overhead.Seconds())
	s.logDecision(requestID, policy, decision, overhead)

	resp, err := s.client.Do(upstream)
	if err != nil {
		s.metrics.Error()
		http.Error(w, "replica unreachable: "+err.Error(), http.StatusBadGateway)
		return
	}
	defer resp.Body.Close()

	h := w.Header()
	for _, name := range []string{"Content-Type", "Cache-Control"} {
		if v := resp.Header.Get(name); v != "" {
			h.Set(name, v)
		}
	}
	h.Set("X-Switchyard-Replica", strconv.Itoa(decision.Replica))
	h.Set("X-Switchyard-Policy", policy)
	h.Set("X-Switchyard-Reason", decision.Reason)
	h.Set("X-Switchyard-Matched", strconv.Itoa(decision.Matched))
	h.Set("X-Switchyard-Loads", joinInts(decision.Loads))
	h.Set("X-Switchyard-Overhead-Us", strconv.FormatInt(overhead.Microseconds(), 10))
	w.WriteHeader(resp.StatusCode)

	// Copy with a flush after every read, so each SSE chunk leaves as soon as it arrives.
	flusher := http.NewResponseController(w)
	buf := make([]byte, 32<<10)
	for {
		n, readErr := resp.Body.Read(buf)
		if n > 0 {
			if _, err := w.Write(buf[:n]); err != nil {
				return // client went away
			}
			flusher.Flush()
		}
		if readErr != nil {
			return
		}
	}
}

func joinInts(values []int) string {
	parts := make([]string, len(values))
	for i, v := range values {
		parts[i] = strconv.Itoa(v)
	}
	return strings.Join(parts, ",")
}

// openDecisionLog starts appending decisions to path. The returned func flushes and closes.
func (s *server) openDecisionLog(path string) (func(), error) {
	f, err := os.OpenFile(path, os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0o644)
	if err != nil {
		return nil, err
	}
	s.log = bufio.NewWriter(f)
	return func() { s.flushLog(); f.Close() }, nil
}

func (s *server) flushLog() {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.log != nil {
		s.log.Flush()
	}
}

func (s *server) logDecision(requestID, policy string, d policies.Decision, overhead time.Duration) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.log == nil {
		return
	}
	line, _ := json.Marshal(map[string]any{
		"ts":             float64(time.Now().UnixMicro()) / 1e6,
		"request_id":     requestID,
		"policy":         policy,
		"replica":        d.Replica,
		"reason":         d.Reason,
		"matched_chunks": d.Matched,
		"loads":          d.Loads,
		"overhead_us":    overhead.Microseconds(),
	})
	s.log.Write(line)
	s.log.WriteByte('\n')
}
