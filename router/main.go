// Switchyard router: an OpenAI-compatible streaming proxy in front of vLLM replicas.
//
// It picks a replica per request (round-robin, least-loaded or prefix-aware), streams the
// response straight through with a flush per chunk, and reports every decision in
// response headers, a JSONL log and /metrics. Standard library only.
package main

import (
	"flag"
	"log"
	"net/http"
	"strings"

	"switchyard/router/metrics"
	"switchyard/router/policies"
)

func main() {
	cfg := policies.DefaultConfig()
	listen := flag.String("listen", "127.0.0.1:8080", "address to listen on (localhost only)")
	backends := flag.String("backends", "", "comma-separated replica URLs; replica i is the i-th")
	policy := flag.String("policy", policies.PrefixAware, "round-robin | least-loaded | prefix-aware")
	decisionLog := flag.String("decision-log", "", "append routing decisions to this JSONL file")
	flag.IntVar(&cfg.ChunkSize, "chunk-size", cfg.ChunkSize, "bytes of prompt text per hashed chunk")
	flag.IntVar(&cfg.MaxChunks, "max-chunks", cfg.MaxChunks, "hash at most this many chunks per request")
	flag.IntVar(&cfg.TableChunks, "table-chunks", cfg.TableChunks, "prefix hashes remembered per replica")
	flag.Float64Var(&cfg.LoadFactor, "load-factor", cfg.LoadFactor, "overloaded above this x fair share")
	flag.IntVar(&cfg.MinBound, "min-bound", cfg.MinBound, "never call a replica overloaded below this")
	flag.Parse()

	if !policies.ValidPolicy(*policy) {
		log.Fatalf("unknown policy %q", *policy)
	}
	var urls []string
	for _, u := range strings.Split(*backends, ",") {
		if u = strings.TrimSpace(u); u != "" {
			urls = append(urls, strings.TrimRight(u, "/"))
		}
	}

	s := &server{
		router:  policies.NewRouter(len(urls), *policy, cfg),
		metrics: metrics.New(),
		urls:    map[int]string{},
		client:  newUpstreamClient(),
	}
	for i, u := range urls {
		s.urls[i] = u
	}
	if *decisionLog != "" {
		closeLog, err := s.openDecisionLog(*decisionLog)
		if err != nil {
			log.Fatal(err)
		}
		defer closeLog()
	}

	log.Printf("switchyard router on %s, policy %s, %d replicas", *listen, *policy, len(urls))
	log.Fatal(http.ListenAndServe(*listen, s.handler()))
}
