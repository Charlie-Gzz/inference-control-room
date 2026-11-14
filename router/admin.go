package main

import (
	"encoding/json"
	"net/http"
	"strings"

	"switchyard/router/policies"
)

// Admin endpoints. The router listens on localhost only, so these are never public.
//
//	POST /admin/replicas  {"replicas": [{"id": 0, "url": "http://127.0.0.1:8001"}]}  set live replicas
//	POST /admin/policy    {"policy": "prefix-aware"}                                 switch policy
//	POST /admin/reset                                                                forget all prefixes
//	GET  /admin/state                                                                policy, live, outstanding
func (s *server) registerAdmin(mux *http.ServeMux) {
	mux.HandleFunc("POST /admin/replicas", s.adminReplicas)
	mux.HandleFunc("POST /admin/policy", s.adminPolicy)
	mux.HandleFunc("POST /admin/reset", func(w http.ResponseWriter, _ *http.Request) {
		s.router.Reset()
		s.flushLog()
		w.WriteHeader(http.StatusNoContent)
	})
	mux.HandleFunc("GET /admin/state", func(w http.ResponseWriter, _ *http.Request) {
		s.flushLog()
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(s.router.Snapshot())
	})
}

// adminReplicas sets which replicas are live. The autoscaler calls it only after a new
// replica passes its health check, so the router never sends to one that is not ready.
func (s *server) adminReplicas(w http.ResponseWriter, r *http.Request) {
	var req struct {
		Replicas []struct {
			ID  int    `json:"id"`
			URL string `json:"url"`
		} `json:"replicas"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		http.Error(w, "bad JSON", http.StatusBadRequest)
		return
	}
	live := make([]int, 0, len(req.Replicas))
	s.mu.Lock()
	for _, rep := range req.Replicas {
		s.urls[rep.ID] = strings.TrimRight(rep.URL, "/")
		live = append(live, rep.ID)
	}
	s.mu.Unlock()
	s.router.SetLive(live)
	w.WriteHeader(http.StatusNoContent)
}

func (s *server) adminPolicy(w http.ResponseWriter, r *http.Request) {
	var req struct {
		Policy string `json:"policy"`
	}
	if json.NewDecoder(r.Body).Decode(&req) != nil || !policies.ValidPolicy(req.Policy) {
		http.Error(w, "unknown policy", http.StatusBadRequest)
		return
	}
	s.router.SetPolicy(req.Policy)
	w.WriteHeader(http.StatusNoContent)
}
