# Helm Chart LRU Cache Eviction Strategy — Design Spec

**Date**: 2026-04-07
**Author**: Vishal Kumar (viskumar)
**Status**: Draft
**Related**: #6973 (Native Helm Rendering), #7080

---

## Context

The native Helm provider caches fetched Helm charts on the controller to avoid repeated network calls during reconciliation. The current caching uses TTL-based expiry (24h for immutable versions, 5m for mutable), but has no mechanism to bound memory usage. This design also extends the immutable TTL from 24h to 30 days — with LRU eviction handling memory pressure, there is no reason to re-fetch bytes that provably never change. At scale (100+ Applications consuming different charts), the unbounded `sync.Map` in `pkg/utils/cache.go` can grow indefinitely until the controller pod is OOM-killed.

This design introduces an LRU eviction layer with byte-size limits, implemented as a generic reusable package.

### Target Scale

- **Phase 1 (this design)**: 50-200 unique charts, single hub controller, ~1GB pod memory budget
- **Phase 2 (future)**: 500+ unique charts, multi-cluster hub caching for 10+ tenant clusters, 2-4GB pod memory budget. No implementation in this spike — configurability is built in for future scaling.

---

## Cache Design & Policy Questions

This section captures the key design questions discussed and the rationale behind each decision.

### Background: Why Charts Are Fetched Every Reconcile

KubeVela's reconciler is **stateless by design** — it re-renders the full Application spec into Kubernetes resources on every reconcile cycle. For `helmchart` components, "rendering" means fetching the chart and templating it with values to produce the resource list. This happens every cycle because:

1. **No persistent render cache**: The rendered output isn't stored between reconciles. The reconciler re-computes from source every time.
2. **Values can change**: The Application's `properties.values` can be updated at any time. The reconciler must re-template the chart with current values to detect drift.
3. **Mutable versions**: If the version is `latest`, upstream chart bytes could change at any time. The reconciler must re-fetch to detect this.
4. **No input fingerprinting**: There's no mechanism to say "inputs haven't changed, skip rendering." The reconciler doesn't hash (chart version + values) and compare against the last reconcile. Re-rendering every time is simpler and always correct.
5. **ResourceTracker pattern**: KubeVela doesn't use `.Owns()` to watch child resources. It reconciles on a fixed 5-minute `ApplicationReSyncPeriod`. Every resync triggers a full re-render, which requires the chart.

This is exactly why caching matters — the reconciler *will* request the chart every 5 minutes for every Application. Without caching, that's a network call per app per cycle. With caching, it's a local memory lookup.

### Background: Immutable vs Mutable Chart Versions

This distinction drives TTL assignment and is referenced throughout the design:

- **Immutable version**: A specific semantic version like `12.1.0`, `v2.3.1`. Once a chart is published at that version, the bytes never change (Helm registry convention — you cannot republish the same semver with different content). Safe to cache with a long TTL (30 days default) because the cached bytes are always correct.

- **Mutable version**: A tag like `latest`, `dev`, `main`, `nightly`, or any non-semver string. The chart bytes behind this tag can change at any time (e.g., someone pushes a new build and re-tags `latest`). Must use a short TTL (5m default) because the cached bytes could become stale at any moment.

Example in Application YAML:

```yaml
# Immutable — cached 30 days, always correct
component:
  type: helmchart
  properties:
    chart: postgresql
    version: "12.1.0"        # semver -> immutable

# Mutable — cached 5m, re-fetched frequently
component:
  type: helmchart
  properties:
    chart: my-internal-app
    version: "latest"         # tag -> mutable, could change anytime
```

Detection is in `determineCacheTTL()` — checks if the version string matches a semver pattern. If yes, immutable TTL. If no, mutable TTL.

### 1. Why Do We Need Caching?

From a Helm perspective, caching solves three problems:

1. **Network latency**: Fetching a chart from a remote Helm repo or OCI registry takes 100-500ms per fetch. With 200 Applications reconciling every 5 minutes, that's 200 fetches per cycle — 20-100 seconds of pure network I/O per reconcile loop.
2. **Registry rate limits**: Public registries (Docker Hub, Artifact Hub) and even private registries impose rate limits. Without caching, every reconcile triggers a fresh pull, quickly exhausting quotas.
3. **Idempotent reconciliation**: Immutable chart versions (e.g., `postgresql@12.1.0`) produce identical bytes every time. Re-fetching wastes resources for data that provably hasn't changed.

#### How the Current TTL Cache Prevents Redundant Fetches

The existing `MemoryCacheStore` (TTL-based) already eliminates most network calls during reconciliation. The reconcile flow is:

```
Reconcile fires (every 5 min via ApplicationReSyncPeriod)
  -> fetchChart()
    -> cache.Get(key)
      -> HIT (within TTL)?   -> return cached chart, NO network call
      -> MISS (expired/absent)? -> fetch from registry, cache.Put(), return
```

For an immutable chart like `postgresql@12.1.0` with 30-day TTL:
- First reconcile: cache miss -> network fetch -> cached
- Next ~8,640 reconciles over 30 days: cache hit -> no network call
- After 30 days: TTL expires -> re-fetch -> cached again
- Under LRU pressure: may be evicted earlier if not recently accessed

For a mutable chart like `my-app@latest` with 5m TTL:
- First reconcile: cache miss -> network fetch -> cached
- Next reconcile (5 min later): TTL just expired -> re-fetch
- Effectively re-fetches every cycle, which is correct for mutable versions

**The problem this design solves is not "charts are fetched too often"** — TTL already handles that. The problem is **unbounded memory growth**. The current `sync.Map` never evicts entries based on size. With 200 cached charts (parsed `*chart.Chart` objects at 2-10MB each), that's potentially 1-2GB of memory with no upper bound and no eviction until TTL expires. Deleted Applications' charts linger for up to 30 days (immutable) or 5m (mutable). The LRU + byte-size limit caps this at a configurable maximum (256MB default with compressed bytes).

### 2. LRU vs TTL — Why Both?

**If TTL is already configured, do we still need LRU?**

Yes. TTL and LRU solve different problems:

| Concern | TTL alone | LRU + TTL |
|---------|-----------|-----------|
| **Stale data** (mutable charts like `latest`) | TTL expires after 5m, forcing re-fetch. Solves correctness. | Same — TTL handles correctness. |
| **Memory bounds** | No limit. 200 immutable charts with 30-day TTL = all 200 resident for 30 days. Memory grows monotonically within TTL window. | LRU caps memory at `maxBytes`. Under pressure, least-recently-accessed charts are evicted even within their TTL window. Memory is bounded. |
| **Cold chart cleanup** | A chart whose Application was deleted lingers in cache until its 30-day TTL expires. | Deleted app's chart stops being accessed, falls to LRU tail, evicted when space is needed. Faster reclamation. |

**Bottom line**: TTL ensures correctness (mutable charts re-fetch). LRU ensures bounded memory. They are complementary, not alternatives.

### 3. Cache Granularity — Per Chart Version

Cache granularity is about what the cache key represents — what unit of data gets one slot in the cache. There are two options:

**Option A: Per chart version** (chosen)

Each unique (chart + version) combination is one cache entry:

```
Cache:
  "repo/bitnami-postgresql/12.1.0"  -> [tgz bytes for 12.1.0]
  "repo/bitnami-postgresql/12.2.0"  -> [tgz bytes for 12.2.0]
  "repo/bitnami-redis/7.0.5"        -> [tgz bytes for 7.0.5]
  "oci/ghcr-myapp/latest"           -> [tgz bytes for latest]
```

Flat map. One key = one tgz.

**Option B: Per chart (entire chart level)**

Each chart name is one cache entry, containing a nested map of all its versions:

```
Cache:
  "repo/bitnami-postgresql" -> {
      "12.1.0": [tgz bytes],
      "12.2.0": [tgz bytes],
      "11.9.0": [tgz bytes],   <- old version nobody uses anymore
  }
  "repo/bitnami-redis" -> {
      "7.0.5": [tgz bytes],
  }
```

**Why Option B is worse:**

1. **LRU granularity is wrong**: If App-A uses `postgresql@12.1.0` and App-B uses `postgresql@12.2.0`, accessing `12.2.0` marks the *entire* `postgresql` entry as recently used. Now `12.1.0` can't be individually evicted — it rides on `12.2.0`'s access recency. To free memory, LRU would have to evict *all* postgresql versions or *none*. Coarse, wasteful eviction.

2. **Byte accounting is messy**: With per-version, each entry's size is exactly `len(tgzBytes)`. With per-chart, the entry size changes every time a new version is added or removed — you'd need to track sub-entry sizes and update `currentBytes` on nested mutations.

3. **Partial eviction complexity**: To handle point 1, you'd need "evict the least-recently-used *version within* a chart entry" — that's LRU-within-LRU. Two layers of eviction logic for zero benefit.

4. **Real-world access pattern**: Applications pin a specific version. `App-A` always asks for `12.1.0`, `App-B` always asks for `12.2.0`. They never ask for "give me all versions of postgresql." There's no read pattern that benefits from grouping versions together.

**Concrete example of the problem:**

```
Scenario: maxBytes = 10MB, 3 charts cached

Per-version cache (Option A):
  "postgresql/12.1.0"  -> 2MB  (App-A uses this, accessed 1 min ago)
  "postgresql/11.9.0"  -> 2MB  (App deleted, last accessed 3 hours ago)
  "redis/7.0.5"        -> 3MB  (App-B uses this, accessed 2 min ago)
  "nginx/1.25.0"       -> 3MB  (App-C uses this, accessed 30 min ago)

New entry arrives: "grafana/10.0.0" -> 2MB, need to evict 2MB
-> Evicts "postgresql/11.9.0" (LRU tail, 3 hours stale). Clean, surgical.

Per-chart cache (Option B):
  "postgresql" -> {"12.1.0": 2MB, "11.9.0": 2MB} = 4MB total
  "redis"      -> {"7.0.5": 3MB}
  "nginx"      -> {"1.25.0": 3MB}

New entry arrives: "grafana/10.0.0" -> 2MB, need to evict 2MB
-> LRU sees "postgresql" was accessed 1 min ago (via 12.1.0), "nginx" 30 min ago
-> Evicts "nginx/1.25.0" (3MB) — but App-C still needs this!
-> Meanwhile "postgresql/11.9.0" (2MB, unused for 3 hours) survives because
   it's grouped with the actively-used 12.1.0
```

Per-version gives precise, correct eviction. Per-chart gives coarse, incorrect eviction.

**Decision**: Per chart version. Cache key: `<source_type>/<sanitized_source>/<version>` (e.g., `repo/bitnami-postgresql/12.1.0`).

### 4. Eviction Strategy — LRU over LFU

**Should we use LFU (Least Frequently Used) instead of LRU?**

No. LRU wins decisively for this use case:

| Factor | LRU | LFU |
|--------|-----|-----|
| **Reconcile pattern** | KubeVela reconciles every app on a fixed 5-min resync. Every active app's chart gets accessed at the same frequency (~1 hit per resync). LRU uses recency to break ties. | Uniform frequency = no signal. LFU degenerates to random eviction. |
| **New chart penalty** | New chart enters with normal priority. | New chart enters with frequency=1, immediately vulnerable to eviction — "cold start" problem. |
| **Deleted app cleanup** | Chart quickly falls to LRU tail when app stops reconciling. Evicted naturally. | Deleted app's chart retains high frequency from historical access. Stale popular entries resist eviction — classic LFU pollution. |
| **Implementation** | O(1) with doubly-linked list + map. `hashicorp/golang-lru` provides this. | Frequency buckets or min-heap. More state, more complexity. |
| **K8s ecosystem precedent** | client-go, apiserver, controller-runtime all use LRU. | Not used in K8s core components. |

### 5. Policy-Based Control Per Application

> **Open question for team discussion**: Should different applications be able to define their own eviction strategies (e.g., LRU, LFU, TTL-only)?

Currently, per-application control is limited to TTL overrides via the CUE template's `parameter.options.cache` fields (`immutableTTL`, `mutableTTL`, `ttl`). The eviction strategy (LRU) is controller-wide.

**Points to discuss**:
- Is there a real use case where Application A needs LRU and Application B needs LFU on the same controller?
- Per-app eviction strategies would require multiple cache instances or a partitioned cache, adding significant complexity.
- The current design favors simplicity: one shared LRU cache, per-app TTL overrides for correctness knobs.

### 6. Cache Type Configuration

> **Open question for team discussion**: If cache strategy selection is supported, should it be configurable per-application in the Application YAML (like TTL), or controller-wide?

**Points to discuss**:
- Cache strategy should **not** be a controller flag. It follows the same pattern as TTL — per-component configuration via the CUE template's `parameter.options.cache` fields. This is consistent with how `immutableTTL`/`mutableTTL` already work at the application level.
- Example: `parameter.options.cache.strategy: "lru" | "lfu" | "ttl-only"` alongside existing TTL fields.
- This means the shared `LRUByteStore` would need to support per-entry eviction hints, or the Helm provider would need to manage multiple cache instances (one per strategy). Both add complexity.
- Recommendation: ship LRU-only in v1. If a concrete use case emerges for per-app strategy selection, expose it in the Application YAML (not controller flags). The interface-based package design supports adding new cache backends without breaking changes.

### 7. Eviction Triggers Beyond Capacity

Three eviction triggers are implemented:

| Trigger | When | How |
|---------|------|-----|
| **Byte pressure** (primary) | `Put()` when `currentBytes + newSize > maxBytes` | Synchronous. Evicts LRU tail entries in a loop until space available. |
| **TTL on access** (lazy) | `Get()` on an expired entry | Returns cache miss, removes entry, decrements byte counter. Prevents serving stale data. |
| **TTL sweep** (background) | Every 60s (configurable) | Goroutine iterates entries, removes TTL-expired ones. Catches stale mutable entries that nobody is accessing. |

**Evaluated and rejected:**

- **System memory pressure** (cgroup limit proximity): Adds OS coupling. Setting `maxBytes` relative to pod limits is the right abstraction — the OOM killer handles the rest.
- **Custom predicate-based eviction** (e.g., "evict all charts from repo X"): Over-engineering. `Remove(key)` covers targeted eviction. No framework needed.
- **Manual purge**: Could add `Purge()` for debug/ops scenarios. Not in v1 scope.

**Configuration**: All three triggers are configurable via `--helm-cache-max-bytes` (byte pressure threshold), `--helm-cache-sweep-interval` (sweep frequency), and per-entry TTL passed on each `Put()` call by the Helm provider.

---

## Decisions Summary

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Eviction strategy | LRU-primary, TTL sweep secondary | LRU bounds memory; TTL ensures mutable chart correctness |
| LRU + TTL interaction | LRU drives evictions by access recency; TTL fires independently | Tighter memory control than TTL-first |
| Cache storage format | Compressed `.tgz` bytes | ~20-25x smaller than parsed `*chart.Chart` Go structs. 200 charts at ~200KB avg = ~40MB vs ~1GB. |
| Cache granularity | Per chart-version | Charts immutable at version; LRU naturally evicts unused versions |
| Size limit | Total bytes (not entry count) | Charts vary 100x in size (10KB to 2MB). Byte limit maps to pod memory budget. |
| Library | `hashicorp/golang-lru/v2` | K8s ecosystem standard, O(1), `OnEvicted` callback, generic types, zero transitive deps |
| Package location | `pkg/utils/cache/` (generic byte store) | Helm-agnostic. Reusable by workflow, vela-go-definitions without Helm coupling. |
| LRU vs LFU | LRU | Uniform reconcile frequency neutralizes LFU's advantage; LFU has cold-start and stale-popularity problems |

---

## Package Structure

```
pkg/utils/cache/
  lru.go          -- LRUByteStore implementation
  lru_test.go     -- Unit tests
  options.go      -- Functional options for construction
```

### Core Types

```go
type LRUByteStore struct {
    mu           sync.Mutex
    inner        *lru.Cache[string, *entry]  // hashicorp/golang-lru/v2
    maxBytes     int64
    currentBytes int64
    stopCh       chan struct{}
}

type entry struct {
    data      []byte
    size      int64
    ttl       time.Duration
    createdAt time.Time
}
```

### Public API

```go
func NewLRUByteStore(opts ...Option) (*LRUByteStore, error)

func (s *LRUByteStore) Get(key string) ([]byte, bool)
func (s *LRUByteStore) Put(key string, data []byte, ttl time.Duration) error
func (s *LRUByteStore) Remove(key string)
func (s *LRUByteStore) Stop()

func (s *LRUByteStore) Len() int
func (s *LRUByteStore) CurrentBytes() int64
```

### Functional Options

```go
func WithMaxBytes(n int64) Option               // default: 256MB
func WithMaxEntries(n int) Option               // internal safety cap, default: 1000
func WithSweepInterval(d time.Duration) Option  // TTL sweep frequency, default: 60s
func WithOnEvict(fn func(key string, size int64)) Option  // metrics hook
```

### Key Behaviors

- `Get()` checks TTL before returning — expired entries return miss and get removed
- `Put()` evicts LRU entries in a loop until `currentBytes + newSize <= maxBytes`
- `Put()` returns `ErrEntryTooLarge` if a single entry exceeds `maxBytes` (caller logs warning, skips caching)
- `OnEvicted` callback from golang-lru decrements `currentBytes` automatically
- Background sweep goroutine iterates entries every 60s to proactively remove TTL-expired items
- Single `sync.Mutex` for all operations (`Get` mutates LRU order, so no `RWMutex`)

---

## Eviction Flow

```
Put("bitnami-postgres/12.1.0", tgzBytes, 30d)
  |
  +-- 1. BYTE PRESSURE (synchronous, inline)
  |     currentBytes + len(tgzBytes) > maxBytes?
  |     YES -> loop: evict LRU tail, decrement currentBytes, repeat
  |     NO  -> insert directly
  |
  +-- 2. TTL ON ACCESS (lazy, in Get())
  |     Get("my-app/latest")
  |     -> entry.createdAt + entry.ttl < now?
  |     YES -> return miss, delete entry, decrement currentBytes
  |     NO  -> return data, promote to MRU head
  |
  +-- 3. TTL SWEEP (background goroutine, every 60s)
        for each entry in cache:
          if entry.createdAt + entry.ttl < now:
            remove entry, decrement currentBytes
```

**Under byte pressure**: Eviction is strictly LRU — least recently accessed goes first, regardless of remaining TTL. A `latest` chart accessed 1 second ago survives over an immutable `v1.0.0` not accessed in 2 hours. This is correct: access recency reflects actual demand from active reconcile loops.

**Entry larger than maxBytes**: Rejected with `ErrEntryTooLarge`. A 300MB umbrella chart should not flush a 256MB cache.

---

## Helm Provider Integration

The Helm provider at `pkg/cue/cuex/providers/helm/helm.go` is the caller. It owns all Helm-specific logic. The generic `LRUByteStore` knows nothing about Helm.

### Provider Struct Change

```go
type Provider struct {
    cache    *cache.LRUByteStore   // was: *utils.MemoryCacheStore
    cacheTTL *CacheTTLConfig
    // ... rest unchanged
}
```

### Fetch Flow

```
fetchChart(ctx, params, options)
  |
  +-- Build cache key (unchanged): "repo/bitnami-postgresql/12.1.0"
  |
  +-- cache.Get(key) -> hit?
  |     YES -> loader.LoadArchive(tgzBytes) -> return *chart.Chart
  |     NO  -> continue to fetch
  |
  +-- Fetch from source (unchanged):
  |     fetchOCIChart() / fetchURLChart() / fetchRepoChart()
  |     returns: *chart.Chart
  |
  +-- Serialize: chartutil.Save(chart) -> []byte (compressed tgz)
  |
  +-- determineCacheTTL(version, options) -> ttl
  |
  +-- cache.Put(key, tgzBytes, ttl)
  |     if ErrEntryTooLarge: log warning, skip caching, return chart
  |
  +-- return *chart.Chart
```

### Key Points

- **Compress/decompress is the Helm provider's job**: `chartutil.Save()` on Put, `loader.LoadArchive()` on Get. The cache stores opaque `[]byte`.
- **Parse cost on cache hit**: `loader.LoadArchive()` on ~200KB takes ~2-5ms. With 4 concurrent reconcilers on 5-min resync, negligible.
- **Migration**: Replace `utils.NewMemoryCacheStore()` with `cache.NewLRUByteStore(opts...)`. The old `MemoryCacheStore` in `pkg/utils/cache.go` remains for `helm_helper.go` index caching (separate concern).
- **No CUE template changes**: Per-chart TTL overrides via `parameter.options.cache` continue to work — they feed into `determineCacheTTL()` which passes the TTL to `cache.Put()`.

### Immutable vs Mutable Versions

The Helm provider distinguishes between immutable and mutable chart versions for TTL assignment:

- **Immutable version**: A specific semantic version like `12.1.0`, `v2.3.1`. Once published, the chart bytes never change (Helm registry convention). Cached with 30-day TTL (default).
- **Mutable version**: A tag like `latest`, `dev`, `main`, `nightly`. The bytes behind this tag can change at any time. Cached with 5m TTL (default) to ensure the controller picks up upstream changes.

Detection is in `determineCacheTTL()` — checks if the version string matches a semver pattern. This logic is unchanged.

---

## Controller Configuration

### New Flags

Added to `cmd/core/app/config/controller.go`:

```
--helm-cache-max-bytes         Maximum bytes for Helm chart cache (default: 268435456 / 256MB)
--helm-cache-sweep-interval    TTL sweep interval for expired cache entries (default: 60s)
```

### Helm Values Override

```yaml
# charts/vela-core/values.yaml
controller:
  helmCache:
    maxBytes: 268435456    # 256MB
    sweepInterval: 60s
```

Flows into controller deployment as args:

```yaml
args:
  - --helm-cache-max-bytes={{ .Values.controller.helmCache.maxBytes }}
  - --helm-cache-sweep-interval={{ .Values.controller.helmCache.sweepInterval }}
```

### Flags Not Exposed (and Why)

| Flag | Reason |
|------|--------|
| `--helm-cache-max-entries` | Internal safety cap (1000). Byte limit is the user-facing constraint. Exposing both confuses. |
| `--helm-cache-immutable-ttl` | Already configurable per-component via CUE `parameter.options.cache.immutableTTL`. |
| `--helm-cache-mutable-ttl` | Same — per-component CUE config is sufficient. |
| `--helm-cache-enabled` | Setting `max-bytes=0` disables caching (all `Put()` calls become no-ops, `Get()` always misses). No separate toggle. |

### Sizing Guidance

| Pod Memory | Recommended `max-bytes` | Approximate Coverage |
|-----------|------------------------|---------------------|
| 512MB | 64MB | ~50-100 charts |
| 1GB | 256MB (default) | ~200 charts |
| 2GB | 512MB | ~400 charts |
| 4GB | 1GB | ~500+ charts, multi-tenant |

---

## Observability

The `WithOnEvict` callback is the hook point. The Helm provider registers it to expose cache behavior without the cache package importing any metrics library.

```go
store, _ := cache.NewLRUByteStore(
    cache.WithMaxBytes(maxBytes),
    cache.WithOnEvict(func(key string, size int64) {
        metrics.HelmCacheEvictions.Inc()
        metrics.HelmCacheBytes.Sub(float64(size))
    }),
)
```

### Metrics (registered by Helm provider, not the cache package)

| Metric | Type | Labels | Purpose |
|--------|------|--------|---------|
| `helm_cache_hits_total` | Counter | `source_type` (repo/oci/url) | Cache effectiveness |
| `helm_cache_misses_total` | Counter | `source_type`, `reason` (expired/evicted/absent) | Diagnose eviction pressure |
| `helm_cache_size_bytes` | Gauge | -- | Current usage, alertable against `max-bytes` |

---

## Testing Strategy

Ginkgo/Gomega test suite for the cache package, following KubeVela's project-wide testing convention:

```go
// pkg/utils/cache/lru_suite_test.go
func TestLRUByteStore(t *testing.T) {
    RegisterFailHandler(Fail)
    RunSpecs(t, "LRUByteStore Suite")
}
```

| Describe Block | It Block | Verifies |
|---------------|----------|----------|
| `LRUByteStore` | `should store and retrieve data` | Basic Put/Get round-trip |
| | `should return miss for expired TTL entry` | Put with 50ms TTL, sleep, verify miss |
| | `should sweep expired entries in background` | Background goroutine removes TTL-expired entries |
| | `should evict LRU tail under byte pressure` | Fill to maxBytes, insert new, verify oldest evicted |
| | `should evict in LRU order based on access pattern` | Access A->B->C, pressure evicts A first |
| | `should reject entry larger than maxBytes` | Single entry > maxBytes returns ErrEntryTooLarge |
| | `should decrement bytes on Remove` | Explicit removal updates currentBytes correctly |
| | `should handle concurrent Put/Get/Remove` | 10 goroutines operating in parallel without races |
| | `should fire OnEvict callback with correct key and size` | Callback receives evicted entry metadata |
| | `should stop sweep goroutine cleanly` | Stop() exits background goroutine, no leaks |

Uses `Describe/Context/It/By` patterns with `Expect()` matchers. Run with:

```bash
ginkgo -v ./pkg/utils/cache/
```

---

## Multi-Cluster Considerations

For Phase 1 (single hub, 50-200 charts), multi-cluster impact is minimal.

**Cache key is cluster-agnostic**: `repo/bitnami-postgresql/12.1.0` — no cluster in the key. Two apps in different tenant clusters using the same chart version share one cache entry. No duplication.

**Cache size scales with unique chart-versions across all clusters**, not with cluster count. 10 tenant clusters all using the same 50 charts = 50 cache entries, not 500.

### Future Phase 2 Considerations (Documented, Not Implemented)

| Concern | Impact | Future Mitigation |
|---------|--------|-------------------|
| Different tenants use different chart repos with auth | Cache key includes repo URL — naturally separated. Auth is per-fetch, not cached. | None needed |
| Tenant isolation (timing side-channel) | Cache is internal to the controller, not exposed to tenants | None needed |
| Hub controller memory at 500+ charts | Increase `--helm-cache-max-bytes` | Already configurable |
| Per-tenant cache quotas | Not in scope | Cache key prefix partitioning possible later (YAGNI) |

**Design decision**: Single shared cache, no per-cluster partitioning. Chart bytes are repo-scoped, not cluster-scoped. Partitioning would waste memory by duplicating identical entries.

---

## Dependencies

| Dependency | Version | Purpose |
|-----------|---------|---------|
| `github.com/hashicorp/golang-lru/v2` | Latest | LRU cache with O(1) ops, `OnEvicted` callback, generic types |

New dependency. Zero transitive dependencies. Widely used in K8s ecosystem (client-go, apiserver).

---

## Out of Scope

- Per-application eviction strategy configuration (LRU vs LFU per app)
- User-selectable cache type via controller flags
- System memory pressure-based eviction (cgroup monitoring)
- Disk-backed cache tier
- Per-tenant cache quotas in multi-cluster
- Cache warming/preloading

---

## Appendix: Brainstorming Q&A Log

This section records the design questions posed during brainstorming, the options considered, the chosen answer, and the reasoning behind each decision.

### Q1: What is the target scale for this cache?

**Options**:
- (A) **Small-medium controller**: 50-200 unique charts, single hub, ~1GB pod memory budget
- (B) **Large enterprise**: 500+ unique charts, multi-cluster hub caching for 10+ tenant clusters, 2-4GB pod memory budget
- (C) **Both** — defaults for (A), configurable up to (B)

**Chosen**: **(A)** — start with small-medium, scale to (B) when requirements arise.

**Reasoning**: Designing for (A) keeps defaults simple and avoids over-engineering. The configuration knobs (`--helm-cache-max-bytes`) built into the design allow scaling to (B) without code changes — just flag adjustments. No need to solve multi-tenant cache partitioning or 4GB memory budgets until there's a concrete requirement.

---

### Q2: How should LRU and TTL interact when evicting?

**Options**:
- (A) **TTL-first, LRU as backstop**: Items expire naturally by TTL. LRU only kicks in when cache exceeds max size — evicts least-recently-used entries even if their TTL hasn't expired yet. Simpler, predictable.
- (B) **LRU-first, TTL as cleanup**: LRU drives all evictions based on access patterns. TTL runs as a secondary sweep to catch stale mutable entries (e.g., `latest` tag that changed upstream). More aggressive memory control.
- (C) **Dual-trigger**: Whichever fires first wins — if TTL expires, remove it; if cache is full and a new entry arrives, evict LRU regardless of TTL. Most memory-safe but could evict hot immutable charts under pressure.

**Chosen**: **(B)** — LRU-primary, TTL as secondary sweep.

**Reasoning**: This gives tighter memory control. LRU ensures that under memory pressure, the least-recently-accessed entries are evicted first based on actual usage patterns from reconcile loops. TTL runs independently as a background sweep to handle correctness — ensuring mutable charts like `latest` are re-fetched after 5 minutes even if they're recently accessed. The key insight is that access recency (LRU) reflects real demand from active Applications, while TTL reflects data freshness. Separating these concerns gives precise control over both memory and correctness.

---

### Q3: What should the cache store — compressed bytes or parsed chart objects?

**Options**:
- (A) **Keep caching parsed `*chart.Chart`**: No parse overhead on cache hit, but memory footprint is larger (a typical chart with 20-30 templates can be 2-10MB in-memory as Go structs). For 200 charts at ~5MB avg, that's ~1GB.
- (B) **Cache compressed `.tgz` bytes**: Much smaller footprint (~50-500KB per chart). For 200 charts at ~200KB avg, that's ~40MB. But requires decompression + parsing on every cache hit (~2-5ms per hit).
- (C) **Two-tier**: Keep compressed bytes as the LRU-managed store (bounded), with a small hot-path cache of parsed charts (e.g., last 20 accessed) that gets evicted aggressively. Most complex.

**Chosen**: **(B)** — cache compressed `.tgz` bytes.

**Reasoning**: The 20-25x memory reduction is the decisive factor. 200 charts at ~200KB compressed = ~40MB vs ~1GB for parsed Go structs. The parse cost (`loader.LoadArchive()` on ~200KB) is ~2-5ms per cache hit — negligible for a reconciler running on 5-minute resync periods. With 4 concurrent reconcilers, that's ~4 parses every 5 minutes per chart. This also makes the `--helm-cache-max-bytes` flag intuitive — users can reason about "200MB of compressed charts" much easier than estimating Go struct overhead with pointers, string headers, and slice capacities.

---

### Q4: Where should the cache package live?

**Options**:
- (A) **`pkg/cache/helmchart/`** inside kubevela core: Other repos import it via `github.com/oam-dev/kubevela/pkg/cache/helmchart`. Simple, but couples dependents to the full kubevela module (heavy dependency tree).
- (B) **`pkg/utils/cache/`** as a generic LRU+TTL cache (not Helm-specific): The LRU+TTL cache is a general-purpose `[]byte` store with size-based eviction. Helm-specific logic (key building, version mutability detection, compression) stays in the Helm provider. Other repos get a lightweight cache without Helm coupling.
- (C) **Separate Go module** (e.g., `github.com/oam-dev/kubevela/pkg/cache` with its own `go.mod`): Truly independent import path, no kubevela dependency tree. But adds module maintenance overhead (versioning, releases).

**Chosen**: **(B)** — generic byte store in `pkg/utils/cache/`.

**Reasoning**: The cache itself is just "LRU + TTL + byte store with max size." The Helm-specific concerns (key format, mutability detection, compress/decompress) are caller responsibilities. This gives maximum reuse without Helm coupling. The workflow repo and vela-go-definitions can import `pkg/utils/cache` without pulling in Helm dependencies. A separate Go module (Option C) would work but adds versioning and release overhead that isn't justified until there are external consumers outside the OAM-dev org.

---

### Q5: Should the max cache size be specified in entry count or total bytes?

**Options**:
- (A) **Entry count** (e.g., `--helm-cache-max-entries=200`): Simple to implement — LRU evicts by count. But charts vary wildly in size (10KB CRD-only chart vs 2MB umbrella chart), so 200 entries could mean 20MB or 400MB.
- (B) **Total bytes** (e.g., `--helm-cache-max-bytes=256MB`): Tracks actual memory pressure. Each `Put()` records the byte length, evicts LRU entries until the new entry fits. More predictable resource planning, maps directly to pod memory limits.
- (C) **Both with either-triggers-eviction** (e.g., max 500 entries AND max 256MB): Belt and suspenders. Whichever limit is hit first triggers LRU eviction.

**Chosen**: **(B)** — total bytes.

**Reasoning**: Since we're caching compressed bytes, the size is known exactly at insertion time (`len(tgzBytes)`). Users can set the limit relative to their pod memory budget (e.g., "I have 1GB pod, allocate 256MB for chart cache"). Entry count is misleading when chart sizes vary 100x — a limit of 200 entries could mean 20MB (all small CRD charts) or 400MB (all large umbrella charts). Byte-based limits give predictable, plannable memory usage that maps directly to Kubernetes resource requests/limits.
