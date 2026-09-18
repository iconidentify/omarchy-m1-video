/* SPDX-License-Identifier: GPL-2.0-or-later */
/* Included in the actual observer.c; never an alternative observer implementation. */
#include "va-content.h"
#include "runtime.h"
static struct hevc_content_self content_va_self;
static pthread_once_t content_va_once = PTHREAD_ONCE_INIT;
static atomic_bool content_va_ready;

static bool content_va_identity(struct v4l2r_context *ctx,
    const struct v4l2r_observer_receipt *receipt, struct hevc_content_identity *out)
{
    struct v4l2r_observer_target actual;
    struct v4l2r_capture_buffer *cap = selected(ctx, receipt->target.surface, &actual);
    if (!cap || !ctx->codec || ctx->codec->pixelformat != V4L2_PIX_FMT_HEVC_SLICE ||
        v4l2r_format_pixelformat(&ctx->output_format) != V4L2_PIX_FMT_HEVC_SLICE ||
        !ctx->observer_lease || ctx->observer_lease != receipt->lease ||
        actual.surface_generation != receipt->target.surface_generation ||
        actual.allocation_generation != receipt->target.allocation_generation ||
        actual.writer != receipt->target.writer ||
        ctx->completed != ctx->submitted || ctx->completed != receipt->completed ||
        ctx->submitted != receipt->submitted || cap->last_ref_seq != receipt->last_reference ||
        cap->observer_completed_writer != actual.writer || cap->last_ref_seq > ctx->completed ||
        receipt->capture_index != (uint32_t)(cap - ctx->captures) ||
        receipt->planes != 1 || cap->nb_planes != 1 || receipt->plane_size[0] != cap->plane_size[0] ||
        cap->observer_memory != V4L2_MEMORY_MMAP || cap->observer_flags ||
        cap->observer_count != 1 || cap->observer_index != receipt->capture_index ||
        cap->observer_type != V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE ||
        ctx->capture_format.type != V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE ||
        ctx->capture_format.fmt.pix_mp.pixelformat != V4L2_PIX_FMT_NV12 ||
        !hevc_content_layout(ctx->capture_format.fmt.pix_mp.width, ctx->capture_format.fmt.pix_mp.height,
            ctx->capture_format.fmt.pix_mp.plane_fmt[0].bytesperline, cap->plane_size[0])) return false;
    if (ctx->queued_capture) return false;
    *out = (struct hevc_content_identity) {
        .client = HEVC_CONTENT_VA,
        .run = {receipt->session.run[0], receipt->session.run[1]},
        .context_generation = receipt->session.context_generation,
        .session = receipt->session.nonce, .lease = receipt->lease,
        .allocation_generation = actual.allocation_generation, .writer = actual.writer,
        .submitted = receipt->submitted, .completed = receipt->completed,
        .capture_index = receipt->capture_index, .planes = 1,
        .allocation_memory = cap->observer_memory, .allocation_flags = cap->observer_flags,
        .allocation_type = cap->observer_type,
        .plane_size = {cap->plane_size[0]},
        .detail.va = {.context = receipt->session.context, .surface = actual.surface,
            .surface_generation = actual.surface_generation, .last_reference = cap->last_ref_seq},
    };
    return true;
}

V4L2R_OBSERVER_API bool v4l2r_content_snapshot(VADriverContextP va,
    const struct v4l2r_observer_receipt *receipt, struct hevc_content_pool *pool, bool copy)
{
    if (!va || !va->pDriverData || !receipt || !pool || !pthread_equal(pool->owner, pthread_self()) ||
        !pool->enabled || pool->stopped || !atomic_load(&content_va_ready)) return false;
    struct v4l2r_driver *drv = v4l2r_driver(va);
    if (pthread_mutex_trylock(&drv->api_mutex)) return false;
    struct v4l2r_context *ctx = session_context(drv, &receipt->session);
    bool ok = false;
    if (!ctx || drv->observer_active != ctx || !ctx->observer_lease ||
        v4l2r_now_ns() >= ctx->observer_content_deadline) goto unlock;
    if (pthread_mutex_trylock(&ctx->mutex)) goto unlock;
    struct hevc_content_identity identity, after;
    struct hevc_content_provenance proof, final_proof;
    if (ctx->observer_content_count >= HEVC_CONTENT_SLOTS ||
        !content_va_identity(ctx, receipt, &identity) ||
        !hevc_content_runtime(ctx->video_fd, HEVC_CONTENT_VA, &content_va_self, &proof)) goto unlock_context;
    ctx->observer_content_count++;
    unsigned index = pool->used;
    struct v4l2r_capture_buffer *cap = &ctx->captures[receipt->capture_index];
    ok = hevc_content_transfer(ctx->video_fd, cap->plane_mem_offset[0], cap->plane_size[0],
        pool, &identity, copy, ctx->observer_content_deadline,
        &ctx->observer_content_map, &ctx->observer_content_map_length);
    if (ok) ok = content_va_identity(ctx, receipt, &after) &&
        hevc_content_same(&identity, &after) &&
        hevc_content_runtime(ctx->video_fd, HEVC_CONTENT_VA, &content_va_self, &final_proof) &&
        !memcmp(&proof, &final_proof, sizeof(proof)) &&
        v4l2r_now_ns() < ctx->observer_content_deadline;
    if (ok) { pool->slot[index].provenance = proof; pool->slot[index].valid = true; }
unlock_context:
    pthread_mutex_unlock(&ctx->mutex);
unlock:
    pthread_mutex_unlock(&drv->api_mutex);
    if (!ok) pool->stopped = true;
    return ok;
}

static void content_va_identify(void)
{
    hevc_content_identify(&content_va_self, (const void *)v4l2r_content_snapshot);
    atomic_store(&content_va_ready, true);
}

V4L2R_OBSERVER_API void v4l2r_content_init(struct hevc_content_pool *pool, bool enabled)
{
    memset(pool, 0, sizeof(*pool)); pool->enabled = enabled; pool->owner = pthread_self();
    pthread_once(&content_va_once, content_va_identify);
}
