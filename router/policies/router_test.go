package policies

import (
	"encoding/json"
	"fmt"
	"os"
	"reflect"
	"testing"
)

type vectorFile struct {
	Hashes []struct {
		Messages  json.RawMessage `json:"messages"`
		ChunkSize int             `json:"chunk_size"`
		MaxChunks int             `json:"max_chunks"`
		Expect    []string        `json:"expect"`
	} `json:"hashes"`
	Cases []struct {
		Name     string `json:"name"`
		Replicas int    `json:"replicas"`
		Policy   string `json:"policy"`
		Config   Config `json:"config"`
		Steps    []struct {
			Op      string `json:"op"`
			Content string `json:"content"`
			Replica int    `json:"replica"`
			Live    []int  `json:"live"`
			Expect  *struct {
				Replica int    `json:"replica"`
				Reason  string `json:"reason"`
				Matched int    `json:"matched"`
				Loads   []int  `json:"loads"`
			} `json:"expect"`
		} `json:"steps"`
	} `json:"cases"`
}

func loadVectors(t *testing.T) vectorFile {
	t.Helper()
	raw, err := os.ReadFile("../testdata/vectors.json")
	if err != nil {
		t.Fatal(err)
	}
	var v vectorFile
	if err := json.Unmarshal(raw, &v); err != nil {
		t.Fatal(err)
	}
	return v
}

func chatBody(content string) []byte {
	body, _ := json.Marshal(map[string]any{
		"model":    "llm",
		"messages": []map[string]string{{"role": "u", "content": content}},
	})
	return body
}

func TestHashVectors(t *testing.T) {
	for i, h := range loadVectors(t).Hashes {
		body := []byte(fmt.Sprintf(`{"messages": %s}`, h.Messages))
		got := PrefixHashes(CanonicalText(body), h.ChunkSize, h.MaxChunks)
		hex := make([]string, len(got))
		for k, x := range got {
			hex[k] = fmt.Sprintf("%016x", x)
		}
		if !reflect.DeepEqual(hex, h.Expect) {
			t.Errorf("hash vector %d: got %v, want %v", i, hex, h.Expect)
		}
	}
}

func TestRoutingVectors(t *testing.T) {
	for _, c := range loadVectors(t).Cases {
		t.Run(c.Name, func(t *testing.T) {
			r := NewRouter(c.Replicas, c.Policy, c.Config)
			for i, s := range c.Steps {
				switch s.Op {
				case "finish":
					r.Finish(s.Replica)
				case "set_live":
					r.SetLive(s.Live)
				case "reset":
					r.Reset()
				case "route":
					d, _, ok := r.Route(CanonicalText(chatBody(s.Content)))
					if !ok {
						t.Fatalf("step %d: no live replica", i)
					}
					e := s.Expect
					if d.Replica != e.Replica || d.Reason != e.Reason || d.Matched != e.Matched {
						t.Fatalf("step %d: got replica %d %s matched %d, want replica %d %s matched %d",
							i, d.Replica, d.Reason, d.Matched, e.Replica, e.Reason, e.Matched)
					}
					if e.Loads != nil && !reflect.DeepEqual(d.Loads, e.Loads) {
						t.Fatalf("step %d: loads %v, want %v", i, d.Loads, e.Loads)
					}
				default:
					t.Fatalf("step %d: unknown op %q", i, s.Op)
				}
			}
		})
	}
}

func TestNoLiveReplicas(t *testing.T) {
	r := NewRouter(2, LeastLoaded, DefaultConfig())
	r.SetLive(nil)
	if _, _, ok := r.Route(nil); ok {
		t.Fatal("routed with no live replicas")
	}
}

func TestMalformedBodyHasNoText(t *testing.T) {
	if text := CanonicalText([]byte("not json")); text != nil {
		t.Fatalf("expected nil, got %q", text)
	}
}
