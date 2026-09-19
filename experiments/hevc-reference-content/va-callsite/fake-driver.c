/* SPDX-License-Identifier: GPL-2.0-only */
#include <stdbool.h>
#include <stdint.h>
#include <string.h>
#include <pthread.h>
#include <linux/videodev2.h>
#include <va/va_backend.h>

#define CONTENT_SLOTS 8
#define CONTENT_BYTES 184320
#define OBSERVER_ABI UINT64_C(0x7634726f62730001)

struct observer_session {
    uint64_t run[2], context_generation, nonce;
    VAContextID context;
};
struct observer_target {
    VASurfaceID surface;
    uint64_t surface_generation, allocation_generation, writer;
};
struct observer_receipt {
    struct observer_session session;
    struct observer_target target;
    uint64_t lease, submitted, completed, last_reference;
    uint32_t capture_index, planes;
    uint64_t plane_size[VIDEO_MAX_PLANES];
};
enum content_client { CONTENT_VA = 1 };
struct content_identity {
    enum content_client client;
    uint64_t run[2], context_generation, session, lease;
    uint64_t allocation_generation, writer, submitted, completed;
    uint32_t capture_index, planes;
    uint32_t allocation_memory, allocation_flags, allocation_type;
    uint64_t plane_size[VIDEO_MAX_PLANES];
    union {
        struct { uint32_t context, surface; uint64_t surface_generation, last_reference; } va;
        struct { uint64_t request; uint32_t frame; } gst;
    } detail;
};
struct content_provenance {
    uint32_t device_major, device_minor;
    char builds[9][129];
};
struct content_pool {
    bool enabled, stopped;
    unsigned used;
    pthread_t owner;
    struct {
        bool valid, copied;
        uint64_t elapsed_ns, before_ns, after_ns;
        struct content_identity identity;
        struct content_provenance provenance;
        unsigned char bytes[CONTENT_BYTES];
    } slot[CONTENT_SLOTS];
};

enum {
    MODE_NORMAL,
    MODE_WRONG_SURFACE,
    MODE_END_ONCE,
    MODE_END_ALWAYS,
    MODE_SNAPSHOT_FAIL,
    MODE_BAD_ABI,
    MODE_WRONG_RECEIPT,
    MODE_CLOSE_ONCE,
};

struct fake_counts {
    unsigned open, select, begin, snapshot, end, close;
    unsigned destroy_context, destroy_config;
    unsigned copy_true, copy_false;
};

static struct fake_counts counts;
static int mode;

__attribute__((visibility("default")))
uint64_t v4l2r_observer_client_abi(void)
{
    return mode == MODE_BAD_ABI ? OBSERVER_ABI + 1 : OBSERVER_ABI;
}

__attribute__((visibility("default")))
void fake_reset(void)
{
    memset(&counts, 0, sizeof(counts));
    mode = MODE_NORMAL;
}

__attribute__((visibility("default")))
void fake_set_mode(int value)
{
    mode = value;
}

__attribute__((visibility("default")))
struct fake_counts fake_get_counts(void)
{
    return counts;
}

__attribute__((visibility("default")))
VAStatus fake_end_picture(VADriverContextP driver, VAContextID context)
{
    (void)driver;
    (void)context;
    return VA_STATUS_SUCCESS;
}

__attribute__((visibility("default")))
VAStatus fake_destroy_context(VADriverContextP driver, VAContextID context)
{
    (void)driver;
    (void)context;
    counts.destroy_context++;
    return VA_STATUS_SUCCESS;
}

__attribute__((visibility("default")))
VAStatus fake_destroy_config(VADriverContextP driver, VAConfigID config)
{
    (void)driver;
    (void)config;
    counts.destroy_config++;
    return VA_STATUS_SUCCESS;
}

__attribute__((visibility("default")))
VAStatus v4l2r_observer_open(VADriverContextP driver, VAContextID context,
                             struct observer_session *session)
{
    if (!driver || !driver->pDriverData || context != 7 || !session)
        return VA_STATUS_ERROR_INVALID_PARAMETER;
    counts.open++;
    *session = (struct observer_session) {
        .run = {11, 12}, .context_generation = 13, .nonce = 14,
        .context = context,
    };
    return VA_STATUS_SUCCESS;
}

__attribute__((visibility("default")))
VAStatus v4l2r_observer_select(VADriverContextP driver,
                               const struct observer_session *session,
                               VASurfaceID surface,
                               struct observer_target *target)
{
    (void)driver;
    if (!session || session->nonce != 14 || !target)
        return VA_STATUS_ERROR_INVALID_PARAMETER;
    counts.select++;
    *target = (struct observer_target) {
        .surface = mode == MODE_WRONG_SURFACE ? surface + 1 : surface,
        .surface_generation = 21,
        .allocation_generation = 22,
        .writer = 23 + surface,
    };
    return VA_STATUS_SUCCESS;
}

__attribute__((visibility("default")))
VAStatus v4l2r_observer_begin(VADriverContextP driver,
                              const struct observer_session *session,
                              const struct observer_target *target,
                              uint64_t deadline,
                              struct observer_receipt *receipt)
{
    (void)driver;
    (void)deadline;
    if (!session || !target || !receipt)
        return VA_STATUS_ERROR_INVALID_PARAMETER;
    counts.begin++;
    memset(receipt, 0, sizeof(*receipt));
    receipt->session = *session;
    receipt->target = *target;
    if (mode == MODE_WRONG_RECEIPT)
        receipt->target.surface++;
    receipt->lease = 31;
    receipt->submitted = 32;
    receipt->completed = 32;
    receipt->last_reference = 30;
    receipt->capture_index = target->surface;
    receipt->planes = 1;
    receipt->plane_size[0] = 368128;
    return VA_STATUS_SUCCESS;
}

__attribute__((visibility("default")))
VAStatus v4l2r_observer_end(VADriverContextP driver,
                            const struct observer_session *session,
                            uint64_t lease)
{
    (void)driver;
    if (!session || lease != 31)
        return VA_STATUS_ERROR_INVALID_PARAMETER;
    counts.end++;
    if (mode == MODE_END_ALWAYS || (mode == MODE_END_ONCE && counts.end == 1))
        return VA_STATUS_ERROR_OPERATION_FAILED;
    return VA_STATUS_SUCCESS;
}

__attribute__((visibility("default")))
VAStatus v4l2r_observer_close(VADriverContextP driver,
                              const struct observer_session *session)
{
    (void)driver;
    if (!session || session->nonce != 14)
        return VA_STATUS_ERROR_INVALID_PARAMETER;
    counts.close++;
    if (mode == MODE_CLOSE_ONCE && counts.close == 1)
        return VA_STATUS_ERROR_OPERATION_FAILED;
    return VA_STATUS_SUCCESS;
}

__attribute__((visibility("default")))
void v4l2r_content_init(struct content_pool *pool, bool enabled)
{
    memset(pool, 0, sizeof(*pool));
    pool->enabled = enabled;
    pool->owner = pthread_self();
}

__attribute__((visibility("default")))
bool v4l2r_content_snapshot(VADriverContextP driver,
                            const struct observer_receipt *receipt,
                            struct content_pool *pool, bool copy)
{
    (void)driver;
    if (!receipt || !pool || !pool->enabled || pool->used >= CONTENT_SLOTS)
        return false;
    counts.snapshot++;
    counts.copy_true += copy;
    counts.copy_false += !copy;
    if (mode == MODE_SNAPSHOT_FAIL)
        return false;
    pool->slot[pool->used].valid = true;
    pool->slot[pool->used].copied = copy;
    pool->slot[pool->used].identity = (struct content_identity) {
        .client = CONTENT_VA,
        .run = {receipt->session.run[0], receipt->session.run[1]},
        .context_generation = receipt->session.context_generation,
        .session = receipt->session.nonce,
        .lease = receipt->lease,
        .allocation_generation = receipt->target.allocation_generation,
        .writer = receipt->target.writer,
        .submitted = receipt->submitted,
        .completed = receipt->completed,
        .capture_index = receipt->capture_index,
        .planes = receipt->planes,
        .detail.va = {
            .context = receipt->session.context,
            .surface = receipt->target.surface,
            .surface_generation = receipt->target.surface_generation,
            .last_reference = receipt->last_reference,
        },
    };
    if (copy)
        memset(pool->slot[pool->used].bytes, 0xa5, CONTENT_BYTES);
    pool->used++;
    return true;
}
