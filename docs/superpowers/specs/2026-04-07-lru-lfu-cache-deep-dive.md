# LRU and LFU Cache — Deep Dive

A comprehensive guide covering internals, implementation, design decisions, pitfalls, and interview preparation.

---

## Table of Contents

1. [What is a Cache Eviction Policy?](#1-what-is-a-cache-eviction-policy)
2. [LRU Cache — Least Recently Used](#2-lru-cache--least-recently-used)
3. [LFU Cache — Least Frequently Used](#3-lfu-cache--least-frequently-used)
4. [LRU vs LFU — Head-to-Head Comparison](#4-lru-vs-lfu--head-to-head-comparison)
5. [Design Decisions and Tradeoffs](#5-design-decisions-and-tradeoffs)
6. [Common Pitfalls](#6-common-pitfalls)
7. [Variants and Hybrid Approaches](#7-variants-and-hybrid-approaches)
8. [Interview Questions](#8-interview-questions)

---

## 1. What is a Cache Eviction Policy?

A cache has limited capacity. When full and a new entry needs to be inserted, the cache must decide which existing entry to remove (evict). The eviction policy defines this decision.

**Common eviction policies:**

| Policy | Evicts | Signal Used |
|--------|--------|-------------|
| LRU (Least Recently Used) | Entry not accessed for the longest time | Recency of access |
| LFU (Least Frequently Used) | Entry accessed the fewest times | Frequency of access |
| FIFO (First In, First Out) | Oldest inserted entry | Insertion order |
| LRU-K | Entry whose K-th most recent access is oldest | K-distance recency |
| ARC (Adaptive Replacement Cache) | Dynamically balances recency and frequency | Both signals |
| TTL (Time To Live) | Entry whose time limit has expired | Wall clock time |
| Random | Random entry | None (probabilistic) |

The two most important and most frequently asked in interviews are **LRU** and **LFU**.

---

## 2. LRU Cache — Least Recently Used

### 2.1 Core Idea

Evict the entry that hasn't been accessed for the longest time. The assumption: if you haven't used it recently, you're unlikely to use it soon.

**Access** = any `get()` or `put()` operation on the key.

### 2.2 Data Structure

LRU requires O(1) for both `get` and `put`. This is achieved by combining:

1. **HashMap** — O(1) key lookup
2. **Doubly Linked List** — O(1) insertion, deletion, and move-to-front

```
HashMap: key -> Node(key, value)

Doubly Linked List (most recent at head, least recent at tail):

  HEAD <-> [C] <-> [A] <-> [B] <-> TAIL
           ^                 ^
       most recent      least recent
       (MRU)            (LRU — evict this)
```

**Why doubly linked list?**
- Singly linked list requires O(n) to remove a node (need to find predecessor)
- Doubly linked list removes a node in O(1) because each node has a `prev` pointer

**Why not just a LinkedHashMap?**
- Java's `LinkedHashMap` with `accessOrder=true` actually does this internally
- But understanding the raw implementation is critical for interviews and custom requirements

### 2.3 Operations

| Operation | Steps | Time |
|-----------|-------|------|
| `get(key)` | HashMap lookup -> if found, move node to head -> return value | O(1) |
| `put(key, value)` | If key exists: update value, move to head. If new: insert at head, if over capacity evict tail. | O(1) |
| `evict()` | Remove tail node, remove from HashMap | O(1) |

### 2.4 Java Implementation

```java
import java.util.HashMap;
import java.util.Map;

public class LRUCache {

    // Doubly linked list node
    static class Node {
        int key;
        int value;
        Node prev;
        Node next;

        Node(int key, int value) {
            this.key = key;
            this.value = value;
        }
    }

    private final int capacity;
    private final Map<Integer, Node> map;

    // Sentinel nodes — eliminates null checks at boundaries
    private final Node head;
    private final Node tail;

    public LRUCache(int capacity) {
        this.capacity = capacity;
        this.map = new HashMap<>();

        // head and tail are dummy sentinels, never removed
        this.head = new Node(-1, -1);
        this.tail = new Node(-1, -1);
        head.next = tail;
        tail.prev = head;
    }

    public int get(int key) {
        Node node = map.get(key);
        if (node == null) {
            return -1; // cache miss
        }
        // Move to head (mark as most recently used)
        moveToHead(node);
        return node.value;
    }

    public void put(int key, int value) {
        Node node = map.get(key);

        if (node != null) {
            // Key exists — update value and move to head
            node.value = value;
            moveToHead(node);
        } else {
            // New key — check capacity
            if (map.size() >= capacity) {
                // Evict LRU entry (tail.prev is the least recently used)
                Node lru = tail.prev;
                removeNode(lru);
                map.remove(lru.key);
            }
            // Insert new node at head
            Node newNode = new Node(key, value);
            addToHead(newNode);
            map.put(key, newNode);
        }
    }

    // --- Internal linked list operations ---

    private void addToHead(Node node) {
        node.prev = head;
        node.next = head.next;
        head.next.prev = node;
        head.next = node;
    }

    private void removeNode(Node node) {
        node.prev.next = node.next;
        node.next.prev = node.prev;
    }

    private void moveToHead(Node node) {
        removeNode(node);
        addToHead(node);
    }
}
```

### 2.5 Why Sentinel Nodes?

Without sentinels, every `addToHead()` and `removeNode()` needs null checks:

```java
// WITHOUT sentinels — error-prone
private void removeNode(Node node) {
    if (node.prev != null) {
        node.prev.next = node.next;
    } else {
        head = node.next; // node was head
    }
    if (node.next != null) {
        node.next.prev = node.prev;
    } else {
        tail = node.prev; // node was tail
    }
}
```

With sentinels, `node.prev` and `node.next` are never null for real data nodes. The code is simpler, less buggy, and fewer edge cases.

### 2.6 Thread-Safe LRU

The basic implementation is NOT thread-safe. For concurrent access:

```java
import java.util.concurrent.locks.ReentrantReadWriteLock;

public class ConcurrentLRUCache {
    private final LRUCache cache;
    private final ReentrantReadWriteLock lock = new ReentrantReadWriteLock();

    public ConcurrentLRUCache(int capacity) {
        this.cache = new LRUCache(capacity);
    }

    public int get(int key) {
        // IMPORTANT: get() is NOT a read-only operation in LRU!
        // It modifies the linked list (moves node to head).
        // Must use WRITE lock, not read lock.
        lock.writeLock().lock();
        try {
            return cache.get(key);
        } finally {
            lock.writeLock().unlock();
        }
    }

    public void put(int key, int value) {
        lock.writeLock().lock();
        try {
            cache.put(key, value);
        } finally {
            lock.writeLock().unlock();
        }
    }
}
```

**Critical insight**: You cannot use `ReadWriteLock` with read lock for `get()` because LRU's `get()` mutates the list order. Both `get()` and `put()` require the write lock. This is a common interview gotcha.

**Alternative**: Use `synchronized` or a simple `ReentrantLock` (no read/write distinction needed since all ops are writes). The `ReentrantReadWriteLock` above is shown to illustrate the pitfall.

### 2.7 Using Java's LinkedHashMap

Java provides a shortcut — `LinkedHashMap` with `accessOrder=true`:

```java
import java.util.LinkedHashMap;
import java.util.Map;

public class LRUCacheLinkedHashMap extends LinkedHashMap<Integer, Integer> {
    private final int capacity;

    public LRUCacheLinkedHashMap(int capacity) {
        // accessOrder=true makes it ordered by access time, not insertion time
        super(capacity, 0.75f, true);
        this.capacity = capacity;
    }

    @Override
    protected boolean removeEldestEntry(Map.Entry<Integer, Integer> eldest) {
        return size() > capacity;
    }

    public int get(int key) {
        return super.getOrDefault(key, -1);
    }
}
```

**When to use this vs custom implementation:**
- Interview: Usually expected to implement from scratch (HashMap + Doubly Linked List)
- Production: `LinkedHashMap` is fine for simple cases, but lacks hooks for eviction callbacks, byte-size tracking, or TTL integration

### 2.8 LRU Strengths

1. **Simple mental model**: "most recently used stays" is easy to reason about
2. **O(1) all operations**: Get, put, evict are all constant time
3. **Adapts to workload shifts**: When access patterns change, the cache naturally adjusts within one full cycle
4. **Low overhead per entry**: Just two extra pointers (prev, next)
5. **Temporal locality**: Exploits the principle that recently accessed data is likely to be accessed again

### 2.9 LRU Weaknesses

1. **Scan pollution**: A sequential scan of N items (where N > cache size) flushes the entire cache, evicting hot entries that will be needed again immediately. One bad scan destroys the cache.
2. **No frequency signal**: An item accessed 1,000 times and an item accessed once are treated the same — whoever was accessed more recently stays. A single access can save a cold item and evict a hot one.
3. **Pathological workload**: If the working set is slightly larger than the cache, LRU can achieve 0% hit rate — cycling through entries just before they'd be needed again.

---

## 3. LFU Cache — Least Frequently Used

### 3.1 Core Idea

Evict the entry that has been accessed the fewest times overall. The assumption: items accessed many times are more valuable than items accessed few times.

**Frequency** = total number of `get()` + `put()` calls on the key since insertion.

### 3.2 Data Structure

LFU requires O(1) for `get` and `put`. This is harder than LRU and uses:

1. **HashMap (key -> Node)** — O(1) key lookup
2. **HashMap (frequency -> Doubly Linked List)** — groups nodes by their access frequency
3. **Min frequency tracker** — tracks the current minimum frequency for O(1) eviction

```
keyMap:   key -> Node(key, value, freq)

freqMap:  1 -> [D] <-> [E]        <- min frequency (evict from here)
          2 -> [B]
          5 -> [A] <-> [C]

minFreq = 1
```

Within each frequency bucket, nodes are ordered by recency (most recent at head, least recent at tail). This breaks ties: among entries with the same frequency, evict the least recently used.

### 3.3 Operations

| Operation | Steps | Time |
|-----------|-------|------|
| `get(key)` | Lookup in keyMap -> remove from freqMap[freq] -> increment freq -> add to freqMap[freq+1] -> update minFreq if needed | O(1) |
| `put(key, value)` | If exists: update + same as get. If new: evict if full (remove tail of freqMap[minFreq]), insert with freq=1, set minFreq=1 | O(1) |
| `evict()` | Remove tail of freqMap[minFreq] linked list | O(1) |

### 3.4 Java Implementation

```java
import java.util.HashMap;
import java.util.Map;

public class LFUCache {

    static class Node {
        int key;
        int value;
        int frequency;
        Node prev;
        Node next;

        Node(int key, int value) {
            this.key = key;
            this.value = value;
            this.frequency = 1; // starts at 1 on first insert
        }
    }

    // A doubly linked list with sentinel nodes for a specific frequency bucket
    static class DoublyLinkedList {
        Node head;
        Node tail;
        int size;

        DoublyLinkedList() {
            head = new Node(-1, -1);
            tail = new Node(-1, -1);
            head.next = tail;
            tail.prev = head;
            size = 0;
        }

        void addToHead(Node node) {
            node.prev = head;
            node.next = head.next;
            head.next.prev = node;
            head.next = node;
            size++;
        }

        void removeNode(Node node) {
            node.prev.next = node.next;
            node.next.prev = node.prev;
            size--;
        }

        Node removeTail() {
            if (size == 0) return null;
            Node lfu = tail.prev;
            removeNode(lfu);
            return lfu;
        }

        boolean isEmpty() {
            return size == 0;
        }
    }

    private final int capacity;
    private int minFrequency;
    private final Map<Integer, Node> keyMap;        // key -> Node
    private final Map<Integer, DoublyLinkedList> freqMap;  // frequency -> DLL

    public LFUCache(int capacity) {
        this.capacity = capacity;
        this.minFrequency = 0;
        this.keyMap = new HashMap<>();
        this.freqMap = new HashMap<>();
    }

    public int get(int key) {
        Node node = keyMap.get(key);
        if (node == null) {
            return -1;
        }
        updateFrequency(node);
        return node.value;
    }

    public void put(int key, int value) {
        if (capacity == 0) return;

        Node node = keyMap.get(key);

        if (node != null) {
            // Key exists — update value and frequency
            node.value = value;
            updateFrequency(node);
        } else {
            // New key — evict if at capacity
            if (keyMap.size() >= capacity) {
                // Evict least frequent (and among those, least recent)
                DoublyLinkedList minFreqList = freqMap.get(minFrequency);
                Node evicted = minFreqList.removeTail();
                keyMap.remove(evicted.key);
            }

            // Insert new node with frequency 1
            Node newNode = new Node(key, value);
            keyMap.put(key, newNode);
            freqMap.computeIfAbsent(1, k -> new DoublyLinkedList()).addToHead(newNode);
            minFrequency = 1; // new node always has freq=1, so min is always 1
        }
    }

    private void updateFrequency(Node node) {
        int oldFreq = node.frequency;
        DoublyLinkedList oldList = freqMap.get(oldFreq);
        oldList.removeNode(node);

        // If we emptied the min frequency bucket, increment minFrequency
        if (oldFreq == minFrequency && oldList.isEmpty()) {
            minFrequency++;
        }

        // Move to next frequency bucket
        node.frequency++;
        freqMap.computeIfAbsent(node.frequency, k -> new DoublyLinkedList()).addToHead(node);
    }
}
```

### 3.5 Why minFrequency Works

The `minFrequency` variable seems fragile — how do we know it's correct without scanning all frequencies?

**Key insight**: `minFrequency` only needs to change in two cases:

1. **New entry inserted**: Always has `frequency=1`, so `minFrequency = 1`. Guaranteed.
2. **Entry promoted from minFrequency bucket**: If the minFrequency bucket becomes empty after promotion, `minFrequency++`. This works because the promoted node went to `minFrequency + 1`, which is now the new minimum.

`minFrequency` never needs to decrease (except on new insert, which resets to 1). It never needs to skip values. The proof: any node at frequency F was previously at frequency F-1. So if F-1's bucket is empty and F is the smallest non-empty bucket, minFrequency = F is correct.

### 3.6 LFU Strengths

1. **Protects hot entries**: An item accessed 1,000 times won't be evicted by a one-time scan — its high frequency shields it
2. **Resists scan pollution**: Unlike LRU, a sequential scan of cold data won't flush hot entries because the scanner entries have low frequency
3. **Good for stable workloads**: When certain items are consistently popular over time, LFU keeps them cached

### 3.7 LFU Weaknesses

1. **Cold start problem**: New entries start with `frequency=1` and are immediately vulnerable to eviction, even if they'll become hot. A burst of new entries can evict each other before building up frequency.
2. **Stale popularity (cache pollution)**: An item that was popular in the past but is no longer needed retains its high frequency count. It resists eviction even though nobody accesses it anymore. This is the **"frequency pollution"** problem.
3. **Difficulty adapting to workload shifts**: If the popular set changes (e.g., a new product launch replaces old popular items), LFU is slow to adapt because old items have accumulated high frequencies.
4. **Higher memory overhead**: Each entry needs a frequency counter. The freqMap adds a DLL per active frequency level.
5. **More complex implementation**: Two HashMaps, frequency buckets, minFrequency tracking vs LRU's single HashMap + single DLL.

---

## 4. LRU vs LFU — Head-to-Head Comparison

### 4.1 Feature Comparison

| Aspect | LRU | LFU |
|--------|-----|-----|
| **Eviction signal** | Recency (time since last access) | Frequency (total access count) |
| **Data structures** | 1 HashMap + 1 DLL | 2 HashMaps + N DLLs (one per frequency) |
| **Time complexity** | O(1) get/put | O(1) get/put |
| **Space per entry** | 2 pointers (prev/next) | 2 pointers + 1 int (frequency) |
| **Implementation complexity** | Low (~60 lines) | Medium (~100 lines) |
| **Scan resistance** | Poor — scans flush the cache | Good — scans don't build frequency |
| **Adapts to workload shifts** | Fast — within one cache cycle | Slow — old frequencies linger |
| **Cold start handling** | Fair — new entry is MRU | Poor — new entry has freq=1 |
| **Cache pollution** | Low — stale entries naturally age out | High — stale popular entries resist eviction |

### 4.2 When to Use LRU

- **Temporal locality**: Workloads where recently accessed items are likely accessed again soon
- **Shifting access patterns**: When the "hot set" changes frequently
- **Simple requirements**: When you need a straightforward, well-understood cache
- **Uniform frequency workloads**: When all items are accessed at similar rates (LFU degenerates to random)
- **Examples**: Web browser cache, OS page cache, database buffer pool, Kubernetes controller caches

### 4.3 When to Use LFU

- **Stable hot set**: When a small set of items receives the vast majority of requests consistently
- **Scan-heavy workloads**: When periodic batch scans could pollute an LRU cache
- **CDN/content caching**: Popular videos/images remain popular for extended periods
- **Examples**: CDN edge caches, DNS resolvers, content recommendation caches

### 4.4 Workload Simulation

```
Access pattern: A A A A B B B C C C [scan: D E F G H I J K L M] A B C

LRU (capacity=5):
  After A A A A B B B C C C: [C, B, A, ?, ?] — all hot items cached
  After scan D E F G H I J K L M: [M, L, K, J, I] — HOT ITEMS EVICTED!
  Access A: MISS! Must re-fetch.
  Access B: MISS! Must re-fetch.
  Access C: MISS! Must re-fetch.
  Hit rate during scan + re-access: very poor

LFU (capacity=5):
  After A A A A B B B C C C: A(freq=4) B(freq=3) C(freq=3) — all cached
  After scan D E F G H I J: A(4) B(3) C(3) still cached! D,E,F,G... evicted
    each scan item enters with freq=1, immediately evicted when next one arrives
  Access A: HIT (freq=5)
  Access B: HIT (freq=4)
  Access C: HIT (freq=4)
  Hit rate: excellent — scan didn't damage hot entries
```

This is LFU's strongest scenario. But flip the script:

```
Access pattern: A A A A A (A becomes "stale") B B B B B B B B B B

LRU (capacity=2):
  After A's: [A] -> After B's: [B, A] or [B] if A was evicted
  A is evicted when not accessed. Correct behavior.

LFU (capacity=2):
  After A x5: A(freq=5)
  After B x10: B(freq=10), A(freq=5) — A STILL in cache despite being stale!
  A's high historical frequency prevents eviction.
  New entry C would be evicted (freq=1) before stale A (freq=5).
```

This is LFU's weakness — stale popularity pollution.

---

## 5. Design Decisions and Tradeoffs

### 5.1 Capacity: Count-Based vs Size-Based

**Count-based** (`maxEntries=1000`):
- Simple — LRU evicts one entry per insert over capacity
- Assumes entries are roughly equal size
- Fails when entry sizes vary widely (1KB metadata vs 10MB image)

**Size-based** (`maxBytes=256MB`):
- Each entry tracks its byte size
- On insert, evict LRU entries in a loop until `currentBytes + newEntrySize <= maxBytes`
- Must handle: what if a single entry exceeds maxBytes? (Reject it — don't flush everything)
- More accurate memory control, but slightly more bookkeeping

**When to use which:**
- Count-based: Cache entries are same type, similar size (e.g., database rows, config entries)
- Size-based: Cache entries vary in size (e.g., HTTP responses, files, serialized objects)

### 5.2 TTL Integration

Pure LRU/LFU don't consider time — an entry from 30 days ago with recent access is treated the same as one from 5 minutes ago. For caches where data can become stale, you need TTL:

**Approach 1 — Lazy expiry (check on access):**
```java
public int get(int key) {
    Node node = map.get(key);
    if (node == null) return -1;
    if (System.currentTimeMillis() > node.expiresAt) {
        // Expired — treat as miss, remove
        removeNode(node);
        map.remove(key);
        return -1;
    }
    moveToHead(node);
    return node.value;
}
```
- Pro: Zero background overhead
- Con: Expired entries occupy memory until accessed

**Approach 2 — Background sweep:**
```java
ScheduledExecutorService sweeper = Executors.newSingleThreadScheduledExecutor();
sweeper.scheduleAtFixedRate(() -> {
    for (Map.Entry<Integer, Node> entry : map.entrySet()) {
        if (System.currentTimeMillis() > entry.getValue().expiresAt) {
            removeNode(entry.getValue());
            map.remove(entry.getKey());
        }
    }
}, 60, 60, TimeUnit.SECONDS);
```
- Pro: Proactively frees memory from expired entries
- Con: Sweep cost is O(n), needs locking, sweep interval is a tuning knob

**Approach 3 — Both (recommended):**
Lazy expiry on `get()` for correctness (never serve stale data) + background sweep for memory reclamation (don't let expired entries accumulate).

### 5.3 Concurrency Strategy

| Strategy | Pros | Cons |
|----------|------|------|
| **Single global lock** (`synchronized` / `ReentrantLock`) | Simple, correct | Contention under high concurrency |
| **Striped locks** (lock per hash bucket) | Less contention | Complex, LRU list operations still need global coordination |
| **Lock-free** (CAS-based concurrent linked list) | Maximum throughput | Extremely complex, hard to get right, rarely worth it |
| **Read-write lock** | Reads don't block each other | **Doesn't work for LRU** — `get()` mutates list order |
| **Single-writer / multiple-reader with buffered writes** | Good throughput | Access events are buffered and applied in batch by a single writer |

For most applications, **single global lock** is sufficient. Caffeine (Java's best cache library) uses a buffered write approach inspired by database write-ahead logs.

### 5.4 HashMap Load Factor and Initial Capacity

```java
// Bad — resizes HashMap multiple times as cache fills
Map<Integer, Node> map = new HashMap<>();

// Good — pre-size to avoid resizing
// capacity / load_factor + 1 avoids any resize
Map<Integer, Node> map = new HashMap<>(capacity * 4 / 3 + 1, 0.75f);
```

For a cache with known max capacity, pre-sizing the HashMap eliminates rehashing and reduces GC pressure.

---

## 6. Common Pitfalls

### 6.1 LRU: Using ReadWriteLock Incorrectly

```java
// BUG: get() is NOT read-only — it modifies the linked list
lock.readLock().lock();
try {
    return cache.get(key); // MOVES node to head — this is a WRITE
} finally {
    lock.readLock().unlock();
}
```

Multiple threads holding read locks will concurrently modify the linked list, causing corruption. **Always use write lock for both get() and put().**

### 6.2 LRU: Forgetting to Remove from HashMap on Eviction

```java
// BUG: removes from linked list but forgets HashMap
Node lru = tail.prev;
removeNode(lru);
// map.remove(lru.key); ← MISSING! HashMap now has dangling reference
```

This causes a memory leak and incorrect behavior — `get()` finds the node in HashMap but it's disconnected from the list.

### 6.3 LRU: Not Storing Key in Node

```java
// BUG: Node without key
static class Node {
    int value;  // no key field!
    Node prev, next;
}
```

When evicting the tail node, you need the key to remove it from the HashMap. Without the key stored in the node, you'd need an O(n) scan of the HashMap to find which key maps to this node.

### 6.4 LFU: Not Resetting minFrequency on New Insert

```java
// BUG: minFrequency not reset
Node newNode = new Node(key, value); // freq = 1
keyMap.put(key, newNode);
freqMap.computeIfAbsent(1, k -> new DoublyLinkedList()).addToHead(newNode);
// minFrequency = 1; ← MISSING! minFrequency might still be 5 from earlier
```

Without resetting `minFrequency = 1`, the next eviction will try to evict from frequency bucket 5 instead of 1, potentially evicting the wrong entry or crashing on an empty list.

### 6.5 LFU: Not Cleaning Empty Frequency Buckets

```java
private void updateFrequency(Node node) {
    int oldFreq = node.frequency;
    DoublyLinkedList oldList = freqMap.get(oldFreq);
    oldList.removeNode(node);

    // BUG: if oldList is now empty and oldFreq == minFrequency,
    // we must increment minFrequency
    // Also: optionally remove empty list from freqMap to prevent memory leak
    if (oldFreq == minFrequency && oldList.isEmpty()) {
        minFrequency++;
        freqMap.remove(oldFreq); // optional but prevents accumulating empty lists
    }

    node.frequency++;
    freqMap.computeIfAbsent(node.frequency, k -> new DoublyLinkedList()).addToHead(node);
}
```

### 6.6 General: put() on Existing Key Counts as Access

Both LRU and LFU must handle `put(existingKey, newValue)` as an access:
- LRU: move to head (mark as recently used)
- LFU: increment frequency

A common bug is treating `put()` on an existing key as a no-op for ordering/frequency.

### 6.7 General: Capacity Zero

```java
// BUG: division by zero or negative capacity
public LRUCache(int capacity) {
    this.capacity = capacity; // what if capacity = 0?
}
```

Handle `capacity <= 0` explicitly — either throw `IllegalArgumentException` or make every `get()` return -1 and every `put()` a no-op.

---

## 7. Variants and Hybrid Approaches

### 7.1 LRU-K

Tracks the K-th most recent access time. Evicts the entry whose K-th access is oldest. LRU is LRU-1. LRU-2 is commonly used in database buffer pools — it requires an entry to be accessed at least twice before it's "established," which resists scan pollution.

### 7.2 2Q (Two-Queue)

Uses two queues:
- **A1 (FIFO)**: New entries go here first
- **Am (LRU)**: Entries promoted from A1 on second access

An entry must be accessed twice to earn LRU protection. Single-access scan items never leave A1 and don't pollute Am.

### 7.3 ARC (Adaptive Replacement Cache)

IBM's patented algorithm that dynamically balances between recency (LRU) and frequency (LFU):
- Maintains two LRU lists: L1 (recency) and L2 (frequency)
- Also maintains "ghost" lists of recently evicted entries to detect workload pattern
- Dynamically adjusts the size split between L1 and L2 based on which ghost list gets more hits

ARC adapts to workload changes automatically — the gold standard but complex and patented (expired 2024).

### 7.4 W-TinyLFU (Caffeine)

Used by Java's Caffeine library (the state-of-the-art cache):
- **Window cache** (1% of total, LRU): Absorbs burst traffic and new entries
- **Main cache** (99%, segmented LRU): Entries must pass a frequency filter to enter
- **TinyLFU admission filter**: Count-Min Sketch estimates frequency with minimal memory. New entry must have higher estimated frequency than the entry it would evict.

This gives near-optimal hit rates across diverse workloads while using O(1) operations and minimal memory overhead.

### 7.5 CLOCK

An approximation of LRU used in OS page replacement:
- Entries arranged in a circular buffer with a "reference bit"
- On access: set reference bit = 1
- On eviction: sweep clockwise. If reference bit = 1, clear it and move on. If reference bit = 0, evict.
- Approximates LRU without the overhead of maintaining a linked list

---

## 8. Interview Questions

### 8.1 High-Level Design Questions

**Q1: Design a caching system for a web application that serves 10,000 requests/second**

Key points to discuss:
- **Scale**: Single machine cache (in-process) vs distributed cache (Redis/Memcached)?
- **Eviction policy**: LRU for general web traffic (strong temporal locality)
- **TTL**: Different TTLs for different content types (static assets: long, API responses: short)
- **Cache-aside vs write-through**: Cache-aside is simpler, write-through ensures consistency
- **Thundering herd**: When a popular key expires, 1000 requests simultaneously try to populate it. Use singleflight/mutex per key.
- **Cache warming**: On cold start, pre-populate from database for known hot keys
- **Metrics**: Hit rate, eviction rate, latency percentiles

**Q2: How would you design a CDN's edge cache eviction policy?**

Key points:
- LFU is better than LRU here — popular content stays popular for days/weeks
- But pure LFU has stale popularity problem — combine with time-windowed frequency (only count accesses in last 24h)
- Size-weighted eviction: a 100MB video occupying cache is different from a 5KB CSS file. Consider `frequency / size` as eviction priority.
- Multi-tier: Memory (hot, small) -> SSD (warm, large) -> Origin (cold, fetch)
- Regional differences: Content popular in Asia may not be popular in Europe — per-region policies

**Q3: You're designing a database buffer pool. Which eviction policy and why?**

Key points:
- **LRU-2 or 2Q**, not simple LRU — database workloads have sequential scans (full table scans) that would destroy an LRU cache
- Buffer pool must handle: index lookups (random access, high locality) AND sequential scans (one-time access, cache-hostile)
- LRU-2 requires two accesses to earn cache residency, so single-pass scan pages don't evict hot index pages
- MySQL InnoDB uses a modified LRU with a "young" and "old" sublist (similar to 2Q)
- PostgreSQL uses a CLOCK variant for its shared buffers

**Q4: Design a cache for a Kubernetes controller that reconciles 500 resources every 5 minutes**

Key points:
- All resources accessed at same frequency (once per reconcile) — LFU degenerates, use LRU
- Cache key: resource identity (namespace/name/version)
- Size-based limit: resources vary in size, byte-based maxSize maps to pod memory limits
- TTL for correctness: mutable resources need short TTL to detect upstream changes
- Single shared cache, not per-resource-type, to maximize memory utilization
- OnEvict callback for Prometheus metrics (not imported into cache package)
- Controller pod can be OOM-killed if cache is unbounded — maxBytes is critical

**Q5: How would you handle cache warming after a pod restart?**

Key points:
- Cold cache after restart = spike in cache misses = spike in backend load
- Options: (1) Accept cold start — simplest, cache fills naturally within one reconcile cycle. (2) Persist cache to disk (PVC) — survives restarts but adds I/O complexity and stale data risk. (3) Peer-based warming — fetch hot keys from sibling pods. (4) Background pre-fetch — on startup, proactively fetch known-needed entries before serving traffic.
- For Kubernetes controllers: cold start is usually acceptable because the reconcile loop naturally populates the cache within 5 minutes

---

### 8.2 Low-Level Implementation Questions

**Q1: Implement an LRU cache with O(1) get and put** (LeetCode 146)

This is the most common cache interview question. The answer is the HashMap + Doubly Linked List implementation in Section 2.4. Key things interviewers look for:
- Sentinel nodes (shows clean coding practice)
- Key stored in Node (needed for HashMap removal on eviction)
- `moveToHead` = `removeNode` + `addToHead` (clean decomposition)
- Handling `put()` on existing key (update value + move to head)

**Q2: Implement an LFU cache with O(1) get and put** (LeetCode 460)

The answer is the dual-HashMap + frequency-bucketed DLL implementation in Section 3.4. Key things interviewers look for:
- `minFrequency` tracking and its correctness argument
- `computeIfAbsent` for lazy bucket creation
- Resetting `minFrequency = 1` on every new insert
- Incrementing `minFrequency` when its bucket becomes empty

**Q3: How would you modify your LRU cache to support TTL per entry?**

```java
static class Node {
    int key, value;
    long expiresAt;  // System.currentTimeMillis() + ttlMillis
    Node prev, next;
}

public int get(int key) {
    Node node = map.get(key);
    if (node == null) return -1;
    if (System.currentTimeMillis() > node.expiresAt) {
        // Expired — treat as miss
        removeNode(node);
        map.remove(key);
        return -1;
    }
    moveToHead(node);
    return node.value;
}

public void put(int key, int value, long ttlMillis) {
    // Same as before, but set expiresAt on the node
    Node newNode = new Node(key, value);
    newNode.expiresAt = System.currentTimeMillis() + ttlMillis;
    // ... rest of put logic
}
```

Follow-up: "Expired entries still occupy memory. How do you clean them?"
- Background sweep thread (as shown in Section 5.2)
- Or: use a `DelayQueue<Node>` sorted by `expiresAt`, drain it periodically

**Q4: Your LRU cache's get() takes 2ms at p99 under high concurrency. How do you optimize?**

Diagnosis: The single global lock is contended.

Options:
1. **Striped locking**: Partition keys into N buckets, each with its own lock + LRU list. Reduces contention N-fold but each partition has its own LRU order (less globally optimal).
2. **Caffeine-style buffered writes**: `get()` records access events in a lock-free ring buffer. A single drain thread periodically applies them to the LRU list. `get()` becomes nearly lock-free.
3. **CLOCK approximation**: Replace the linked list with a circular buffer + reference bits. No move-to-head on access — just set a bit. Less accurate but no list mutation on read.

**Q5: How would you implement a size-bounded LRU cache where entries have different byte sizes?**

```java
public void put(int key, byte[] value, long ttlMillis) {
    long newSize = value.length;

    if (newSize > maxBytes) {
        // Single entry exceeds total cache size — reject
        return; // or throw
    }

    // Evict LRU entries until there's room
    while (currentBytes + newSize > maxBytes && !isEmpty()) {
        Node lru = tail.prev;
        currentBytes -= lru.size;
        removeNode(lru);
        map.remove(lru.key);
    }

    Node node = new Node(key, value, newSize);
    addToHead(node);
    map.put(key, node);
    currentBytes += newSize;
}
```

Key points:
- Must evict in a **loop** (one eviction may not free enough space)
- Track `currentBytes` — increment on insert, decrement on evict
- Reject entries that exceed total cache size (don't evict everything)
- The Node must store its size for correct decrement on eviction

**Q6: What happens if all entries in your LFU cache have the same frequency?**

LFU degenerates to LRU within that frequency bucket — it evicts the least recently used entry among those with the minimum frequency. This is by design: the DLL within each frequency bucket maintains recency order, and eviction takes from the tail (least recent).

This is also why LFU is a poor choice for workloads with uniform access frequency — it provides no advantage over LRU but adds implementation complexity.

**Q7: Can you implement LRU without a doubly linked list?**

Yes, alternatives exist:
1. **Java's `LinkedHashMap`** (accessOrder=true) — does it internally
2. **Timestamp-based**: Store `lastAccessedTime` per entry. On eviction, scan for min timestamp. But this is O(n) eviction.
3. **Min-heap by access time**: O(log n) eviction, O(log n) update on access. Better than scan but worse than DLL's O(1).
4. **Array-based circular buffer (CLOCK)**: O(1) amortized but approximate.

The HashMap + DLL approach is optimal at O(1) for all operations. Interviewers expect this answer.

**Q8: How does Java's `LinkedHashMap` implement LRU internally?**

`LinkedHashMap` extends `HashMap` and adds a doubly-linked list threading through all entries:
- Each `Entry` has `before` and `after` pointers (the DLL threading)
- `accessOrder=true` flag causes `get()` to call `afterNodeAccess()` which moves the entry to the tail of the DLL
- `put()` calls `afterNodeInsertion()` which checks `removeEldestEntry()` — if it returns true, removes the head of the DLL (the eldest/LRU entry)
- The iteration order follows the DLL: either insertion order (default) or access order

So internally, it's the exact same HashMap + DLL pattern — Java just provides it out of the box.
