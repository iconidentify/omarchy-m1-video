/* SPDX-License-Identifier: LGPL-2.1-or-later */
#ifndef GST_HEVC_OBSERVER_H
#define GST_HEVC_OBSERVER_H
#include <gst/gst.h>

typedef struct _GstV4l2Request GstV4l2Request;
typedef struct _GstV4l2Decoder GstV4l2Decoder;

void gst_hevc_observer_set_enabled(int enabled);
int gst_hevc_observer_enabled(void);
int gst_hevc_observer_paused(void);
int gst_hevc_observer_begin(GstV4l2Decoder *decoder, int deadline_ms);
int gst_hevc_observer_end(GstV4l2Decoder *decoder);
int gst_hevc_observer_admit_queue(GstV4l2Request *request);
int gst_hevc_observer_record(GstV4l2Request *request);
int gst_hevc_observer_admit_free(GstV4l2Request *request);
int gst_hevc_observer_admit_flush(GstV4l2Decoder *decoder);
GstV4l2Request *gst_v4l2_request_ref(GstV4l2Request *request);
void gst_v4l2_request_unref(GstV4l2Request *request);
gint gst_v4l2_request_set_done(GstV4l2Request *request);
gboolean gst_v4l2_request_queue(GstV4l2Request *request, guint flags);
gboolean gst_v4l2_decoder_flush(GstV4l2Decoder *self);

struct gst_hevc_receipt {
	const GstV4l2Request *object;
	GstV4l2Decoder *context;
	unsigned object_generation;
	unsigned writer_job;
};

int gst_hevc_observer_receipt(const GstV4l2Request *request, struct gst_hevc_receipt *out);

#endif
