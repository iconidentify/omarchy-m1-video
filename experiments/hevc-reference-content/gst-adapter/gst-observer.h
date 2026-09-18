/* SPDX-License-Identifier: LGPL-2.1-or-later */
#ifndef GST_HEVC_OBSERVER_H
#define GST_HEVC_OBSERVER_H
#include "gst-types-min.h"

void gst_hevc_observer_set_enabled(int enabled);
int gst_hevc_observer_enabled(void);
int gst_hevc_observer_paused(void);
int gst_hevc_observer_begin(GstV4l2Decoder *decoder, int deadline_ms);
int gst_hevc_observer_end(GstV4l2Decoder *decoder);
int gst_hevc_observer_admit_queue(GstV4l2Request *request);
int gst_hevc_observer_record(GstV4l2Request *request);
int gst_hevc_observer_admit_free(GstV4l2Request *request);
int gst_hevc_observer_admit_flush(GstV4l2Decoder *decoder);

struct gst_hevc_receipt {
	unsigned run;
	unsigned long context;
	unsigned allocation;
	unsigned generation;
	unsigned writer_job;
	int request_fd;
	unsigned frame_num;
};

int gst_hevc_observer_receipt(const GstV4l2Request *request, struct gst_hevc_receipt *out);

#endif
