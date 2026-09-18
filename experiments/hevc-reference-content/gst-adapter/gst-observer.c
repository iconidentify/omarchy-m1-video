/* SPDX-License-Identifier: LGPL-2.1-or-later */
#include <gst/gst.h>
#include <linux/videodev2.h>
#include "gst-compat.h"
#include "extracted-structs.inc"
#include "gst-observer.h"
#include <pthread.h>
#include <string.h>
#include <time.h>

static pthread_mutex_t mu = PTHREAD_MUTEX_INITIALIZER;
static int enabled;
static int paused;
static unsigned next_writer;
static GstV4l2Decoder *held_decoder;
static struct gst_hevc_receipt receipts[8];
static int n_receipts;
static GstV4l2Request *held_req[8];
static GstBuffer *held_pic[8];
static GstMemory *held_bit[8];
static int n_held;
static GstV4l2Request *live[8];
static int n_live;

void gst_hevc_observer_set_enabled(int on)
{
	pthread_mutex_lock(&mu);
	if (paused && !on) {
		pthread_mutex_unlock(&mu);
		return;
	}
	enabled = on ? 1 : 0;
	pthread_mutex_unlock(&mu);
}

int gst_hevc_observer_enabled(void)
{
	int e;
	pthread_mutex_lock(&mu);
	e = enabled;
	pthread_mutex_unlock(&mu);
	return e;
}

int gst_hevc_observer_paused(void)
{
	int p;
	pthread_mutex_lock(&mu);
	p = paused;
	pthread_mutex_unlock(&mu);
	return p;
}

int gst_hevc_observer_admit_queue(GstV4l2Request *request)
{
	int ok = 1;
	pthread_mutex_lock(&mu);
	if (enabled && paused)
		ok = 0;
	if (!request || !request->decoder)
		ok = 0;
	pthread_mutex_unlock(&mu);
	return ok;
}

int gst_hevc_observer_record(GstV4l2Request *request)
{
	struct gst_hevc_receipt rec;
	int i;
	if (!request)
		return 0;
	pthread_mutex_lock(&mu);
	if (!enabled) {
		pthread_mutex_unlock(&mu);
		return 1;
	}
	memset(&rec, 0, sizeof(rec));
	rec.object = request;
	rec.context = request->decoder;
	rec.object_generation = 1;
	rec.writer_job = ++next_writer;
	for (i = 0; i < n_receipts; i++) {
		if (receipts[i].object == request) {
			rec.object_generation = receipts[i].object_generation + 1;
			receipts[i] = rec;
			for (i = 0; i < n_live; i++)
				if (live[i] == request)
					live[i] = request;
			pthread_mutex_unlock(&mu);
			return 1;
		}
	}
	if (n_receipts >= 8) {
		pthread_mutex_unlock(&mu);
		return 0;
	}
	receipts[n_receipts++] = rec;
	if (n_live < 8)
		live[n_live++] = request;
	pthread_mutex_unlock(&mu);
	return 1;
}

int gst_hevc_observer_admit_free(GstV4l2Request *request)
{
	int i, ok = 1;
	pthread_mutex_lock(&mu);
	if (enabled && paused && request) {
		for (i = 0; i < n_held; i++)
			if (held_req[i] == request)
				ok = 0;
	}
	pthread_mutex_unlock(&mu);
	return ok;
}

int gst_hevc_observer_admit_flush(GstV4l2Decoder *decoder)
{
	int ok = 1;
	pthread_mutex_lock(&mu);
	if (enabled && paused && decoder == held_decoder)
		ok = 0;
	pthread_mutex_unlock(&mu);
	return ok;
}

int gst_hevc_observer_begin(GstV4l2Decoder *decoder, int deadline_ms)
{
	int n, i;
	GstV4l2Request *pending[8];
	struct timespec start, now;

	if (!decoder || deadline_ms <= 0 || deadline_ms > 2000)
		return 0;
	pthread_mutex_lock(&mu);
	if (!enabled || paused) {
		pthread_mutex_unlock(&mu);
		return 0;
	}
	paused = 1;
	held_decoder = decoder;
	n_held = 0;
	n = n_live;
	if (n > 8)
		n = 8;
	for (i = 0; i < n; i++)
		pending[i] = live[i];
	pthread_mutex_unlock(&mu);

	clock_gettime(CLOCK_MONOTONIC, &start);
	for (i = 0; i < n; i++) {
		GstV4l2Request *req = pending[i];
		if (!req)
			continue;
		if (req->pending) {
			clock_gettime(CLOCK_MONOTONIC, &now);
			if ((now.tv_sec - start.tv_sec) * 1000 +
			    (now.tv_nsec - start.tv_nsec) / 1000000 >= deadline_ms) {
				pthread_mutex_lock(&mu);
				paused = 0;
				held_decoder = NULL;
				pthread_mutex_unlock(&mu);
				return 0;
			}
			if (gst_v4l2_request_set_done(req) <= 0 || req->pending) {
				pthread_mutex_lock(&mu);
				paused = 0;
				held_decoder = NULL;
				pthread_mutex_unlock(&mu);
				return 0;
			}
		}
		pthread_mutex_lock(&mu);
		if (n_held < 8) {
			held_req[n_held] = gst_v4l2_request_ref(req);
			held_pic[n_held] = req->pic_buf ? gst_buffer_ref(req->pic_buf) : NULL;
			held_bit[n_held] = req->bitstream ? gst_memory_ref(req->bitstream) : NULL;
			n_held++;
		}
		pthread_mutex_unlock(&mu);
	}
	return 1;
}

int gst_hevc_observer_end(GstV4l2Decoder *decoder)
{
	int i;
	pthread_mutex_lock(&mu);
	if (!enabled || !paused || decoder != held_decoder) {
		pthread_mutex_unlock(&mu);
		return 0;
	}
	for (i = 0; i < n_held; i++) {
		if (held_req[i])
			gst_v4l2_request_unref(held_req[i]);
		if (held_pic[i])
			gst_buffer_unref(held_pic[i]);
		if (held_bit[i])
			gst_memory_unref(held_bit[i]);
		held_req[i] = NULL;
		held_pic[i] = NULL;
		held_bit[i] = NULL;
	}
	n_held = 0;
	paused = 0;
	held_decoder = NULL;
	pthread_mutex_unlock(&mu);
	return 1;
}

int gst_hevc_observer_receipt(const GstV4l2Request *request, struct gst_hevc_receipt *out)
{
	int i, ok = 0;
	if (!request || !out)
		return 0;
	pthread_mutex_lock(&mu);
	for (i = 0; i < n_receipts; i++) {
		if (receipts[i].object == request) {
			*out = receipts[i];
			ok = 1;
		}
	}
	pthread_mutex_unlock(&mu);
	return ok;
}
