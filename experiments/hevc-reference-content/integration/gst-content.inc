/* SPDX-License-Identifier: LGPL-2.1-or-later */
#include "gst-content.h"
#include "runtime.h"
static struct hevc_content_self content_gst_self;
static pthread_once_t content_gst_once = PTHREAD_ONCE_INIT;
static atomic_bool content_gst_ready;

static gboolean content_gst_identity(GstV4l2Decoder *self,
    const GstHevcObserverReceipt *receipt, struct hevc_content_identity *out)
{
    GstHevcObserverReceipt current = {0};
    GstV4l2Request *request = self->observer_request;
    if (!request || !self->observer_lease || self->observer_lease != receipt->lease ||
        self->observer_failed || self->observer_retired || request->pending || request->failed ||
        gst_vec_deque_get_length(self->pending_requests) ||
        self->observer_completed != self->observer_submitted ||
        self->observer_completed != receipt->completed || self->observer_submitted != receipt->submitted ||
        request->observer_completed != receipt->target.writer ||
        !observer_selection(self, request, &current) ||
        current.target.request != receipt->target.request || current.target.allocation != receipt->target.allocation ||
        current.target.writer != receipt->target.writer || current.frame_num != receipt->frame_num ||
        current.capture_index != receipt->capture_index || current.planes != 1 || receipt->planes != 1 ||
        current.plane_size[0] != receipt->plane_size[0]) return FALSE;
    *out = (struct hevc_content_identity) {
        .client = HEVC_CONTENT_GST, .run = {receipt->session.run[0], receipt->session.run[1]},
        .context_generation = receipt->session.context, .session = receipt->session.nonce,
        .lease = receipt->lease, .allocation_generation = current.target.allocation,
        .writer = current.target.writer, .submitted = receipt->submitted, .completed = receipt->completed,
        .allocation_memory = V4L2_MEMORY_MMAP, .allocation_type = V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE,
        .capture_index = current.capture_index, .planes = 1, .plane_size = {current.plane_size[0]},
        .detail.gst = {.request = current.target.request, .frame = current.frame_num},
    };
    return TRUE;
}

gboolean gst_hevc_content_snapshot(GstV4l2Decoder *self, const GstHevcObserverReceipt *receipt,
    struct hevc_content_pool *pool, gboolean copy)
{
    if (!self || !receipt || !pool || !pthread_equal(pool->owner, pthread_self()) ||
        !pool->enabled || pool->stopped || !atomic_load(&content_gst_ready) || (copy != FALSE && copy != TRUE)) return FALSE;
    if (!g_rec_mutex_trylock(&gst_hevc_observer_mutex)) return FALSE;
    gboolean ok = FALSE;
    struct hevc_content_identity identity, after;
    struct hevc_content_provenance proof, final_proof;
    if (!observer_session_valid(self, &receipt->session) ||
        self->observer_content_count >= HEVC_CONTENT_SLOTS ||
        gst_hevc_observer_now() >= self->observer_content_deadline ||
        !content_gst_identity(self, receipt, &identity) ||
        !hevc_content_runtime(self->video_fd, HEVC_CONTENT_GST, &content_gst_self, &proof)) goto done;
    self->observer_content_count++;
    unsigned index = pool->used;
    ok = gst_hevc_content_buffer_copy(self->observer_picture, self, receipt, pool, &identity,
                                     copy, self->observer_content_deadline, &self->observer_content_map, &self->observer_content_map_length);
    if (ok) ok = content_gst_identity(self, receipt, &after) && hevc_content_same(&identity, &after) &&
        hevc_content_runtime(self->video_fd, HEVC_CONTENT_GST, &content_gst_self, &final_proof) &&
        !memcmp(&proof, &final_proof, sizeof(proof)) &&
        gst_hevc_observer_now() < self->observer_content_deadline;
    if (ok) { pool->slot[index].provenance = proof; pool->slot[index].valid = true; }
done:
    g_rec_mutex_unlock(&gst_hevc_observer_mutex);
    if (!ok) pool->stopped = true;
    return ok;
}

static void content_gst_identify(void)
{
    hevc_content_identify(&content_gst_self, (const void *)gst_hevc_content_snapshot);
    atomic_store(&content_gst_ready, true);
}

void gst_hevc_content_init(struct hevc_content_pool *pool, gboolean enabled)
{
    memset(pool, 0, sizeof(*pool)); pool->enabled = enabled; pool->owner = pthread_self();
    pthread_once(&content_gst_once, content_gst_identify);
}

gboolean gst_hevc_content_allocation(GstV4l2Decoder *self, GstPadDirection direction,
    gint index, struct v4l2_create_buffers *record)
{
    GST_HEVC_OBSERVER_LOCK;
    if (!self->observer_allocation_valid || index < 0 ||
        self->observer_allocation.index != (guint)index ||
        self->observer_allocation.format.type != direction_to_buffer_type(self, direction)) return FALSE;
    *record = self->observer_allocation;
    return TRUE;
}
