/* SPDX-License-Identifier: LGPL-2.1-or-later */
#ifndef HEVC_CONTENT_INTEGRATION_H
#define HEVC_CONTENT_INTEGRATION_H

#include <stdbool.h>
#include <errno.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdint.h>
#include <string.h>
#include <sys/mman.h>
#include <time.h>

#define HEVC_CONTENT_BYTES 184320u
#define HEVC_CONTENT_SLOTS 8u
#define HEVC_CONTENT_COMP_START 161280u
#define HEVC_CONTENT_COMP_BYTES 177152u
#define HEVC_CONTENT_MV_BYTES 7168u
#define HEVC_CONTENT_PLANES 8u
#define HEVC_CONTENT_COPY_NS UINT64_C(20000000)

enum hevc_content_client { HEVC_CONTENT_VA = 1, HEVC_CONTENT_GST = 2 };

/* Metadata, never a capability. Generations are scoped to client + run. */
struct hevc_content_identity {
    enum hevc_content_client client;
    uint64_t run[2], context_generation, session, lease;
    uint64_t allocation_generation, writer, submitted, completed;
    uint32_t capture_index, planes;
    uint32_t allocation_memory, allocation_flags, allocation_type;
    uint64_t plane_size[HEVC_CONTENT_PLANES];
    union {
        struct { uint32_t context, surface; uint64_t surface_generation, last_reference; } va;
        struct { uint64_t request; uint32_t frame; } gst;
    } detail;
};

struct hevc_content_provenance {
    uint32_t device_major, device_minor;
    char builds[9][129];
};

/* Allocate/zero before begin. A slot is consumed even if a later step fails.
 * No hashing/serialization is performed by the copy API. Raw bytes are private. */
struct hevc_content_pool {
    bool enabled, stopped;
    unsigned used;
    pthread_t owner;
    struct {
        bool valid, copied;
        uint64_t elapsed_ns, before_ns, after_ns;
        struct hevc_content_identity identity;
        struct hevc_content_provenance provenance;
        unsigned char bytes[HEVC_CONTENT_BYTES];
    } slot[HEVC_CONTENT_SLOTS];
};

static inline bool hevc_content_same(const struct hevc_content_identity *a,
                                     const struct hevc_content_identity *b)
{
    if (a->client != b->client || a->run[0] != b->run[0] || a->run[1] != b->run[1] ||
        a->context_generation != b->context_generation || a->session != b->session ||
        a->lease != b->lease || a->allocation_generation != b->allocation_generation ||
        a->writer != b->writer || a->submitted != b->submitted || a->completed != b->completed ||
        a->capture_index != b->capture_index || a->planes != b->planes ||
        a->allocation_memory != b->allocation_memory || a->allocation_flags != b->allocation_flags ||
        a->allocation_type != b->allocation_type ||
        memcmp(a->plane_size, b->plane_size, sizeof(a->plane_size))) return false;
    if (a->client == HEVC_CONTENT_VA)
        return a->detail.va.context == b->detail.va.context && a->detail.va.surface == b->detail.va.surface &&
            a->detail.va.surface_generation == b->detail.va.surface_generation &&
            a->detail.va.last_reference == b->detail.va.last_reference;
    return a->client == HEVC_CONTENT_GST && a->detail.gst.request == b->detail.gst.request &&
        a->detail.gst.frame == b->detail.gst.frame;
}

static inline uint64_t hevc_content_now(void)
{
    struct timespec value;
    if (clock_gettime(CLOCK_MONOTONIC, &value)) return 0;
    return (uint64_t)value.tv_sec * UINT64_C(1000000000) + value.tv_nsec;
}

static inline bool hevc_content_layout(uint32_t width, uint32_t height,
                                        uint32_t stride, uint64_t length)
{
    return width == 448 && height == 240 && stride == 448 &&
        (length == 345600 || length == 368128) &&
        HEVC_CONTENT_COMP_START + HEVC_CONTENT_COMP_BYTES <= length - HEVC_CONTENT_MV_BYTES;
}

/* This function is private to the actual retained-allocation adapters. Passing
 * metadata here does not establish ownership or coherence: callers must have
 * checked actual allocation state and runtime build identity under their lock. */
static inline bool hevc_content_transfer(int fd, off_t offset, uint64_t length,
    struct hevc_content_pool *pool, const struct hevc_content_identity *identity,
    bool copy, uint64_t deadline, void **held_map, size_t *held_length)
{
    if (!pool || !pool->enabled || pool->stopped) return false;
    if (pool->used >= HEVC_CONTENT_SLOTS) { pool->stopped = true; return false; }
    if (!identity || !held_map || !held_length || *held_map ||
        (length != 345600 && length != 368128) || offset < 0 ||
        !deadline || hevc_content_now() >= deadline) { pool->stopped = true; return false; }
    unsigned index = pool->used++;
    pool->slot[index].valid = false;
    /* Off/on use the identical bounded map and unmap. No pointer escapes. */
    void *map = mmap(NULL, (size_t)length, PROT_READ, MAP_SHARED, fd, offset);
    if (map == MAP_FAILED) { pool->stopped = true; return false; }
    *held_map = map; *held_length = (size_t)length;
    uint64_t before = hevc_content_now();
    bool ok = before && before < deadline;
    if (ok && copy) {
        memcpy(pool->slot[index].bytes, (const unsigned char *)map + HEVC_CONTENT_COMP_START,
               HEVC_CONTENT_COMP_BYTES);
        memcpy(pool->slot[index].bytes + HEVC_CONTENT_COMP_BYTES,
               (const unsigned char *)map + length - HEVC_CONTENT_MV_BYTES, HEVC_CONTENT_MV_BYTES);
    }
    uint64_t after = hevc_content_now();
    if (munmap(map, (size_t)length)) ok = false;
    else { *held_map = NULL; *held_length = 0; }
    ok = ok && after >= before && after < deadline && after - before <= HEVC_CONTENT_COPY_NS;
    if (!ok) { pool->stopped = true; return false; }
    pool->slot[index].identity = *identity;
    pool->slot[index].copied = copy;
    pool->slot[index].elapsed_ns = after - before;
    pool->slot[index].before_ns = before;
    pool->slot[index].after_ns = after;
    /* The caller marks valid only after its final identity/provenance check. */
    return true;
}

#endif
