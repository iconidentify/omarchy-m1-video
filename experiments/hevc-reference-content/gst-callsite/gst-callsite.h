/* SPDX-License-Identifier: LGPL-2.1-or-later */
#ifndef GST_HEVC_CALLSITE_H
#define GST_HEVC_CALLSITE_H
#include "gst-content.h"
typedef struct _GstH265Decoder GstH265Decoder;

/* Internal experiment, not a public GStreamer ABI or a launch property.
 * Arm on the streaming owner before the first request is allocated/queued.
 * One output is observed; copy=FALSE performs the matching no-copy control.
 * The caller owns the element and must finish on that same thread, including
 * after GST_FLOW_ERROR. Failed finish retains ownership for an explicit retry.
 * No manifest, kernel join, raw-byte publication or hardware approval is supplied. */
gboolean gst_hevc_callsite_arm (GstH265Decoder *, gboolean copy);
/* Immutable selection hints, not writer identity or a kernel association.
 * 1..8 distinct system_frame_numbers, in any order. Results are in callback
 * order and available only after every selection succeeds. No partial success
 * is exposed. Missing selections remain incomplete until explicit finish.
 * A hint can only succeed on an allocation that has never been published, so
 * in practice it must land within roughly the first pool-size outputs; see the
 * publication boundary in SCHEDULING.md. A plan that cannot be satisfied fails
 * the observation and returns GST_FLOW_ERROR for that and every later output,
 * which upstream sees only as a generic streaming failure. */
gboolean gst_hevc_callsite_arm_frames (GstH265Decoder *, gboolean copy,
    const guint32 *frames, guint count);
const struct hevc_content_pool *gst_hevc_callsite_result (GstH265Decoder *);
gboolean gst_hevc_callsite_finish (GstH265Decoder *);

/* Private decoder-side checks; these do not authorize a copy. */
gboolean gst_hevc_callsite_open_before_queue (GstV4l2Decoder *, GstHevcObserverSession *);
gboolean gst_hevc_callsite_output_matches (GstV4l2Request *, GstBuffer *);
gboolean gst_hevc_callsite_frame_matches (GstV4l2Request *, guint32 frame);
#endif
