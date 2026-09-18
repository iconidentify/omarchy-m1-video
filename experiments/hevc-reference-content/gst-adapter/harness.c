/* SPDX-License-Identifier: LGPL-2.1-or-later */
/* Execute patched gst_v4l2_request_queue / flush / free. Fake ioctl. No device. */
#include "gst-types-min.h"
#include "gst-observer.h"
#include <stdio.h>

static int fail_ioctl;
static int ioctl_count;
static unsigned long last_req;

int ioctl(int fd, unsigned long request, ...)
{
	(void)fd;
	ioctl_count++;
	last_req = request;
	if (fail_ioctl) {
		errno = EIO;
		return -1;
	}
	return 0;
}

void gst_v4l2_request_set_done(GstV4l2Request *request)
{
	if (request)
		request->pending = FALSE;
}

int gst_v4l2_decoder_streamoff(GstV4l2Decoder *self, GstPadDirection d)
{
	(void)self;
	(void)d;
	return 1;
}
int gst_v4l2_decoder_streamon(GstV4l2Decoder *self, GstPadDirection d)
{
	(void)self;
	(void)d;
	return 1;
}

#include "extracted-gst.inc"

#define CHECK(c) do { if (!(c)) { fprintf(stderr, "fail %d: %s\n", __LINE__, #c); return 1; } } while (0)

int main(void)
{
	GstVecDeque pending = {0};
	GstV4l2Decoder dec = {.video_fd = 3, .pending_requests = &pending, .render_delay = 4,
			      .supports_holding_capture = 1, .mplane = 0,
			      .sink_buf_type = V4L2_BUF_TYPE_VIDEO_OUTPUT,
			      .src_buf_type = V4L2_BUF_TYPE_VIDEO_CAPTURE};
	GstV4l2Request req = {.decoder = &dec, .fd = 11, .frame_num = 28, .bitstream = (void *)1,
			      .pic_buf = (void *)1};
	struct gst_hevc_receipt rec;

	CHECK(gst_v4l2_request_queue(&req, 0));
	CHECK(req.pending);
	CHECK(gst_hevc_observer_receipt(&req, &rec) == 0); /* default-off: no receipts */

	gst_hevc_observer_set_enabled(1);
	req.pending = FALSE;
	pending.len = 0;
	CHECK(gst_v4l2_request_queue(&req, 0));
	CHECK(gst_hevc_observer_receipt(&req, &rec));
	CHECK(rec.request_fd == 11 && rec.frame_num == 28 && rec.writer_job == 1);
	CHECK(rec.generation == 0);
	req.pending = FALSE; /* completed before pause */
	CHECK(gst_hevc_observer_begin(&dec, 100));
	CHECK(!gst_v4l2_request_queue(&req, 0)); /* producers stopped */
	gst_v4l2_request_free(&req);
	CHECK(req.decoder == &dec); /* retained: free is refused */
	CHECK(!gst_v4l2_decoder_flush(&dec));
	CHECK(gst_hevc_observer_end(&dec));
	gst_v4l2_request_free(&req);
	CHECK(req.decoder == NULL);

	/* Incomplete pending request: begin must not invent completion. */
	req.pending = TRUE;
	pending.len = 0;
	gst_vec_deque_push_tail(&pending, &req);
	CHECK(!gst_hevc_observer_begin(&dec, 100));

	puts("PASS: patched gst_v4l2_request_queue pause/retain/receipt; default-off; no invented drain");
	return 0;
}
