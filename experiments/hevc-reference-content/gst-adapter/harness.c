/* SPDX-License-Identifier: LGPL-2.1-or-later */
#include <gst/gst.h>
#include <gst/video/video.h>
#include <linux/videodev2.h>
#include "gst-compat.h"
#include "extracted-structs.inc"
#include "gst-observer.h"
#include <stdio.h>
#include <string.h>

static int fail_ioctl;
static int poll_timeout;
static int ioctl_count;

int ioctl(int fd, unsigned long request, ...)
{
	(void)fd;
	(void)request;
	ioctl_count++;
	if (fail_ioctl) {
		errno = EIO;
		return -1;
	}
	return 0;
}

GstV4l2Request *gst_v4l2_request_ref(GstV4l2Request *request)
{
	if (request)
		request->ref_count++;
	return request;
}

void gst_v4l2_request_unref(GstV4l2Request *request)
{
	if (request && request->ref_count > 0)
		request->ref_count--;
}

gint gst_poll_wait(GstPoll *poll, GstClockTime timeout)
{
	(void)poll;
	(void)timeout;
	if (poll_timeout)
		return 0;
	return 1;
}

gboolean gst_v4l2_decoder_streamoff(GstV4l2Decoder *self, GstPadDirection d)
{
	(void)self;
	(void)d;
	return TRUE;
}
gboolean gst_v4l2_decoder_streamon(GstV4l2Decoder *self, GstPadDirection d)
{
	(void)self;
	(void)d;
	return TRUE;
}

#undef g_free
#define g_free(p) ((void)(p))
#undef g_object_unref
#define g_object_unref(p) ((void)(p))
#undef gst_poll_free
#define gst_poll_free(p) ((void)(p))
#undef close
#define close(fd) ((void)(fd))
#include "extracted-gst.inc"

#define CHECK(c) do { if (!(c)) { fprintf(stderr, "fail %d: %s\n", __LINE__, #c); return 1; } } while (0)

static void init_dec(GstV4l2Decoder *dec, GstVecDeque *pending)
{
	memset(dec, 0, sizeof(*dec));
	dec->video_fd = 3;
	dec->pending_requests = pending;
	dec->render_delay = 8;
	dec->supports_holding_capture = TRUE;
	dec->sink_buf_type = V4L2_BUF_TYPE_VIDEO_OUTPUT;
	dec->src_buf_type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
}

int main(int argc, char **argv)
{
	const char *mode = argc > 1 ? argv[1] : "success";
	GstVecDeque *pending;
	GstV4l2Decoder dec;
	GstV4l2Request req;
	GstMemory *bitstream;
	GstBuffer *picture;
	struct gst_hevc_receipt rec, rec2;
	int rc;

	gst_init(NULL, NULL);
	pending = gst_vec_deque_new(8);
	bitstream = gst_allocator_alloc(NULL, 16, NULL);
	picture = gst_buffer_new_allocate(NULL, 16, NULL);
	CHECK(bitstream && picture);
	init_dec(&dec, pending);
	memset(&req, 0, sizeof(req));
	req.decoder = &dec;
	req.fd = 11;
	req.frame_num = 28;
	req.bitstream = bitstream;
	req.pic_buf = picture;
	req.ref_count = 1;

	if (!strcmp(mode, "success")) {
		CHECK(gst_v4l2_request_queue(&req, 0));
		CHECK(gst_hevc_observer_receipt(&req, &rec) == 0);
		gst_hevc_observer_set_enabled(1);
		req.pending = FALSE;
		while (gst_vec_deque_get_length(pending))
			gst_vec_deque_pop_head(pending);
		CHECK(gst_v4l2_request_queue(&req, 0));
		CHECK(gst_hevc_observer_receipt(&req, &rec));
		CHECK(rec.object == &req && rec.writer_job == 1);
		CHECK(rec.object_generation == 1 && rec.context == &dec);
		req.pending = FALSE;
		CHECK(gst_hevc_observer_begin(&dec, 200));
		CHECK(GST_MINI_OBJECT_REFCOUNT_VALUE(GST_MINI_OBJECT(picture)) >= 2);
		CHECK(GST_MINI_OBJECT_REFCOUNT_VALUE(GST_MINI_OBJECT(bitstream)) >= 2);
		CHECK(!gst_v4l2_request_queue(&req, 0));
		gst_hevc_observer_set_enabled(0);
		CHECK(gst_hevc_observer_paused());
		CHECK(!gst_v4l2_request_queue(&req, 0));
		gst_v4l2_request_free(&req);
		CHECK(req.decoder == &dec);
		CHECK(!gst_v4l2_decoder_flush(&dec));
		CHECK(gst_hevc_observer_end(&dec));
		puts("PASS: success pause/retain after successful queue");
		gst_vec_deque_free(pending);
		gst_memory_unref(bitstream);
		gst_buffer_unref(picture);
		return 0;
	}
	if (!strcmp(mode, "fail-ioctl")) {
		gst_hevc_observer_set_enabled(1);
		fail_ioctl = 1;
		rc = gst_v4l2_request_queue(&req, 0);
		CHECK(rc == FALSE);
		CHECK(gst_hevc_observer_receipt(&req, &rec) == 0);
		puts("PASS: failed ioctl does not mint a writer receipt");
		gst_vec_deque_free(pending);
		gst_memory_unref(bitstream);
		gst_buffer_unref(picture);
		return 0;
	}
	if (!strcmp(mode, "reuse")) {
		gst_hevc_observer_set_enabled(1);
		CHECK(gst_v4l2_request_queue(&req, 0));
		CHECK(gst_hevc_observer_receipt(&req, &rec));
		req.pending = FALSE;
		while (gst_vec_deque_get_length(pending))
			gst_vec_deque_pop_head(pending);
		CHECK(gst_v4l2_request_queue(&req, 0));
		CHECK(gst_hevc_observer_receipt(&req, &rec2));
		CHECK(rec2.object == rec.object);
		CHECK(rec2.writer_job != rec.writer_job);
		CHECK(rec2.object_generation != rec.object_generation);
		puts("PASS: reused request object retires previous writer_job");
		gst_vec_deque_free(pending);
		gst_memory_unref(bitstream);
		gst_buffer_unref(picture);
		return 0;
	}
	if (!strcmp(mode, "drain-timeout")) {
		gst_hevc_observer_set_enabled(1);
		CHECK(gst_v4l2_request_queue(&req, 0));
		poll_timeout = 1;
		CHECK(!gst_hevc_observer_begin(&dec, 50));
		CHECK(!gst_hevc_observer_paused());
		puts("PASS: begin does not invent completion on drain timeout");
		gst_vec_deque_free(pending);
		gst_memory_unref(bitstream);
		gst_buffer_unref(picture);
		return 0;
	}
	fprintf(stderr, "unknown mode\n");
	gst_vec_deque_free(pending);
	gst_memory_unref(bitstream);
	gst_buffer_unref(picture);
	return 2;
}
