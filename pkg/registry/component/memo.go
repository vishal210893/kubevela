/*
Copyright 2026 The KubeVela Authors.

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
*/

package component

import (
	"sync"
	"time"
)

// ContentRevisionMemoTTL is how long a content-revision probe, and the
// registry it was resolved from, are reused.
//
// This is not a staleness budget for what runs in the cluster; the package a
// render reads is still revalidated exactly, by revision. It only bounds how
// quickly a moved revision is noticed, and it exists because every Application
// naming a package asks on every one of its own reconciles. Without it the
// cost of noticing would scale with the number of Applications rather than
// with the number of registries.
const ContentRevisionMemoTTL = 30 * time.Second

// TTLMemo remembers what a function returned, under a key, for a while.
//
// It is deliberately much smaller than RevisionCache: there is no bound on the
// number of entries, no negative caching and no singleflight, because the keys
// are registries rather than packages and a cluster configures a handful of
// them. A failed call is not stored at all, so a transient failure is retried
// on the next call rather than held for the TTL.
type TTLMemo[T any] struct {
	mu      sync.Mutex
	ttl     time.Duration
	entries map[string]ttlMemoEntry[T]
}

type ttlMemoEntry[T any] struct {
	value T
	at    time.Time
}

// NewTTLMemo returns a memo holding each entry for ttl.
func NewTTLMemo[T any](ttl time.Duration) *TTLMemo[T] {
	return &TTLMemo[T]{ttl: ttl, entries: map[string]ttlMemoEntry[T]{}}
}

// Load returns the value stored under key, calling fetch when there is none or
// the one there has aged out.
func (m *TTLMemo[T]) Load(key string, fetch func() (T, error)) (T, error) {
	if value, ok := m.get(key); ok {
		return value, nil
	}
	value, err := fetch()
	if err != nil {
		var zero T
		return zero, err
	}
	m.put(key, value)
	return value, nil
}

// Put stores value under key without calling anything. It lets one fetch that
// returned several keys' worth of data fill them all in.
func (m *TTLMemo[T]) Put(key string, value T) { m.put(key, value) }

// Reset empties the memo. It exists for tests, which would otherwise carry an
// entry from one case into the next.
func (m *TTLMemo[T]) Reset() {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.entries = map[string]ttlMemoEntry[T]{}
}

func (m *TTLMemo[T]) get(key string) (T, bool) {
	m.mu.Lock()
	defer m.mu.Unlock()
	entry, ok := m.entries[key]
	if !ok || time.Since(entry.at) > m.ttl {
		var zero T
		return zero, false
	}
	return entry.value, true
}

func (m *TTLMemo[T]) put(key string, value T) {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.entries[key] = ttlMemoEntry[T]{value: value, at: time.Now()}
}
