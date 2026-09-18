/* SPDX-License-Identifier: LGPL-2.1-or-later */
#ifndef GST_HEVC_CONTENT_H
#define GST_HEVC_CONTENT_H
#include "gst-observer.h"
#include "content.h"
/* Internal experimental plugin API. Initialize before begin; call before
 * picture publication from the lease owner. Always end/retry failed cleanup.
 * Valid bytes remain private; serialize/hash only after successful end. */
void gst_hevc_content_init(struct hevc_content_pool *, gboolean enabled);
gboolean gst_hevc_content_snapshot(GstV4l2Decoder *, const GstHevcObserverReceipt *,
    struct hevc_content_pool *, gboolean copy);
#endif
