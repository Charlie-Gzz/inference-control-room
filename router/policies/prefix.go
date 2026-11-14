// Package policies holds the routing policies and the prefix hashing they share.
//
// The router has no tokenizer, so it hashes prompt text:
//  1. Canonical text: for every message, role + "\n" + content + "\n" (UTF-8).
//  2. Cut into fixed-size byte chunks. Only full chunks count.
//  3. One running FNV-1a 64-bit hash over the bytes; its value after each chunk is
//     that prefix's hash.
//
// The Python reference is src/icr/routing/prefix.py. Both are checked against
// router/testdata/vectors.json.
package policies

import (
	"bytes"
	"encoding/json"
)

const (
	fnvOffset uint64 = 0xcbf29ce484222325
	fnvPrime  uint64 = 0x100000001b3
)

type message struct {
	Role    string          `json:"role"`
	Content json.RawMessage `json:"content"`
}

type contentPart struct {
	Text string `json:"text"`
}

// CanonicalText extracts the prompt text from an OpenAI chat request body.
// It returns nil if the body has no messages.
func CanonicalText(body []byte) []byte {
	var req struct {
		Messages []message `json:"messages"`
	}
	if json.Unmarshal(body, &req) != nil {
		return nil
	}
	return canonicalFromMessages(req.Messages)
}

func canonicalFromMessages(messages []message) []byte {
	var buf bytes.Buffer
	for _, m := range messages {
		buf.WriteString(m.Role)
		buf.WriteByte('\n')
		var text string
		if json.Unmarshal(m.Content, &text) == nil {
			buf.WriteString(text)
		} else {
			var parts []contentPart // OpenAI content parts: keep the text ones
			if json.Unmarshal(m.Content, &parts) == nil {
				for _, p := range parts {
					buf.WriteString(p.Text)
				}
			}
		}
		buf.WriteByte('\n')
	}
	return buf.Bytes()
}

// PrefixHashes returns the hash of every full-chunk prefix of text, shortest first.
func PrefixHashes(text []byte, chunkSize, maxChunks int) []uint64 {
	full := len(text) / chunkSize
	if full > maxChunks {
		full = maxChunks
	}
	hashes := make([]uint64, 0, full)
	h := fnvOffset
	for i := 0; i < full; i++ {
		for _, b := range text[i*chunkSize : (i+1)*chunkSize] {
			h = (h ^ uint64(b)) * fnvPrime
		}
		hashes = append(hashes, h)
	}
	return hashes
}
