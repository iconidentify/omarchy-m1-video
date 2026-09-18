/* SPDX-License-Identifier: GPL-3.0-or-later */
#ifndef V4L2R_CONTENT_H
#define V4L2R_CONTENT_H
#include "observer.h"
#include "content.h"
/* Experimental real-driver API, not a libva ABI. Initialize before begin;
 * snapshot only from the lease owner. Always end, retrying failed cleanup.
 * Valid bytes remain private; serialize/hash only after successful end. */
V4L2R_OBSERVER_API void v4l2r_content_init(struct hevc_content_pool *, bool enabled);
V4L2R_OBSERVER_API bool v4l2r_content_snapshot(VADriverContextP,
    const struct v4l2r_observer_receipt *, struct hevc_content_pool *, bool copy);
#endif
