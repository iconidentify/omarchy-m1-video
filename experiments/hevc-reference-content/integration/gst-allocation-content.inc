/* SPDX-License-Identifier: LGPL-2.1-or-later */
#include "content.h"

gboolean gst_hevc_content_buffer_copy(GstBuffer *buffer, GstV4l2Decoder *decoder,
    const GstHevcObserverReceipt *receipt, struct hevc_content_pool *pool,
    const struct hevc_content_identity *identity, gboolean copy, guint64 deadline, void **held_map, size_t *held_length)
{
    GST_HEVC_OBSERVER_LOCK;
    GstV4l2CodecBuffer *buf = observer_buffer(buffer, decoder);
    if (!gst_hevc_observer_retained(decoder) || !buf || !buf->observer_policy_valid ||
        buf->observer_published || buf->observer_generation != receipt->target.allocation ||
        buf->observer_writer != receipt->target.writer || buf->observer_completed != receipt->target.writer ||
        buf->num_mems != 1 || buf->index != (gint)receipt->capture_index) return FALSE;
    const struct v4l2_create_buffers *allocation = &buf->observer_policy;
    GstMemory *mem = buf->mem[0];
    if (allocation->memory != V4L2_MEMORY_MMAP || allocation->flags || allocation->count != 1 ||
        allocation->index != receipt->capture_index ||
        allocation->format.type != V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE ||
        allocation->format.fmt.pix_mp.pixelformat != V4L2_PIX_FMT_NV12 ||
        allocation->format.fmt.pix_mp.num_planes != 1 ||
        !mem || mem->parent || mem->offset || mem->maxsize != receipt->plane_size[0] ||
        !gst_is_fd_memory(mem) ||
        !hevc_content_layout(allocation->format.fmt.pix_mp.width, allocation->format.fmt.pix_mp.height,
            allocation->format.fmt.pix_mp.plane_fmt[0].bytesperline, mem->maxsize)) return FALSE;
    /* Original internal EXPBUF fd, not a public export/map and not borrowed input. */
    return hevc_content_transfer(gst_fd_memory_get_fd(mem), 0, mem->maxsize,
                                 pool, identity, copy, deadline, held_map, held_length);
}
