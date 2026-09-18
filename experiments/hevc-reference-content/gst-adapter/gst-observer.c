/* SPDX-License-Identifier: LGPL-2.1-or-later */
/* Default-off pause/retain for patched gst_v4l2_request_queue. Fake ioctl OK. */
#include "gst-observer.h"
#include "gst-types-min.h"

#include <stdint.h>
#include <string.h>

static int enabled;
static int paused;
static unsigned run_id = 1;
static unsigned generation;
static unsigned next_writer;
static GstV4l2Decoder *held_decoder;
static struct gst_hevc_receipt receipts[8];
static int n_receipts;
static int held_fds[8];
static int n_held;

void gst_hevc_observer_set_enabled(int on)
{
	enabled = on ? 1 : 0;
}

int gst_hevc_observer_enabled(void)
{
	return enabled;
}

static int hold_fd(int fd)
{
	int i;
	if (fd < 0 || n_held >= 8)
		return 0;
	for (i = 0; i < n_held; i++)
		if (held_fds[i] == fd)
			return 1;
	held_fds[n_held++] = fd;
	return 1;
}

int gst_hevc_observer_admit_queue(GstV4l2Request *request)
{
	struct gst_hevc_receipt rec;
	if (!enabled)
		return 1;
	if (!request || !request->decoder)
		return 0;
	if (paused)
		return 0;
	if (n_receipts >= 8)
		return 0;
	memset(&rec, 0, sizeof(rec));
	rec.run = run_id;
	rec.context = (unsigned)(uintptr_t)request->decoder;
	rec.allocation = (unsigned)request->fd;
	rec.generation = generation;
	rec.writer_job = ++next_writer;
	rec.request_fd = request->fd;
	rec.frame_num = request->frame_num;
	receipts[n_receipts++] = rec;
	return 1;
}

int gst_hevc_observer_admit_free(GstV4l2Request *request)
{
	int i;
	if (!enabled || !paused || !request)
		return 1;
	for (i = 0; i < n_held; i++)
		if (held_fds[i] == request->fd)
			return 0;
	return 1;
}

int gst_hevc_observer_admit_flush(GstV4l2Decoder *decoder)
{
	(void)decoder;
	if (!enabled)
		return 1;
	if (paused)
		return 0;
	return 1;
}

int gst_hevc_observer_begin(GstV4l2Decoder *decoder, int deadline_ms)
{
	guint n, i;
	if (!enabled || !decoder || paused)
		return 0;
	if (deadline_ms <= 0 || deadline_ms > 2000)
		return 0;
	paused = 1;
	held_decoder = decoder;
	generation++;
	n_held = 0;
	n = decoder->pending_requests ? gst_vec_deque_get_length(decoder->pending_requests) : 0;
	for (i = 0; i < n; i++) {
		GstV4l2Request *req = gst_vec_deque_peek_nth(decoder->pending_requests, i);
		if (!req)
			continue;
		if (req->pending) {
			/* Drain requires the test to complete the request; we do not invent it. */
			paused = 0;
			held_decoder = NULL;
			return 0;
		}
		if (!hold_fd(req->fd))
			return 0;
	}
	(void)deadline_ms;
	return 1;
}

int gst_hevc_observer_end(GstV4l2Decoder *decoder)
{
	if (!enabled)
		return 1;
	if (!paused || decoder != held_decoder)
		return 0;
	paused = 0;
	held_decoder = NULL;
	n_held = 0;
	return 1;
}

int gst_hevc_observer_receipt(const GstV4l2Request *request, struct gst_hevc_receipt *out)
{
	int i;
	if (!request || !out)
		return 0;
	for (i = 0; i < n_receipts; i++) {
		if (receipts[i].request_fd == request->fd &&
		    receipts[i].frame_num == request->frame_num) {
			*out = receipts[i];
			return 1;
		}
	}
	return 0;
}
