/* SPDX-License-Identifier: LGPL-2.1-or-later */
/* Minimal types matching pinned gstv4l2decoder.c field use. Not GStreamer. */
#ifndef GST_TYPES_MIN_H
#define GST_TYPES_MIN_H
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <time.h>
#include <unistd.h>
#include <sys/ioctl.h>
#include <linux/videodev2.h>
#include <linux/media.h>

typedef int gboolean;
typedef int gint;
typedef unsigned guint;
typedef uint32_t guint32;
typedef size_t gsize;
typedef char gchar;
typedef struct { int unused; } GstObject;
typedef void GstMemory;
typedef void GstBuffer;
typedef void GstPoll;
typedef void GstPollFD;
typedef int GstPadDirection;
#define TRUE 1
#define FALSE 0
#define GST_PAD_SINK 1
#define GST_PAD_SRC 2
#define GST_VIDEO_MAX_PLANES 4
#define GST_TRACE_OBJECT(obj, fmt, ...) ((void)0)
#define GST_ERROR_OBJECT(obj, fmt, ...) ((void)0)
#define MAX(a, b) ((a) > (b) ? (a) : (b))
#define G_DEFINE_TYPE_WITH_CODE(...)
#define GST_TYPE_OBJECT 0
#define GST_DEBUG_CATEGORY_INIT(...)
static inline const char *g_strerror(int e) { return strerror(e); }

struct GstVecDeque {
	void *items[8];
	unsigned len;
};
typedef struct GstVecDeque GstVecDeque;
static inline unsigned gst_vec_deque_get_length(GstVecDeque *d) { return d ? d->len : 0; }
static inline void gst_vec_deque_push_tail(GstVecDeque *d, void *item)
{
	if (d && d->len < 8)
		d->items[d->len++] = item;
}
static inline void *gst_vec_deque_peek_head(GstVecDeque *d)
{
	return (d && d->len) ? d->items[0] : NULL;
}
static inline void *gst_vec_deque_peek_nth(GstVecDeque *d, unsigned i)
{
	return (d && i < d->len) ? d->items[i] : NULL;
}

struct _GstV4l2Decoder;
struct _GstV4l2Request;
typedef struct _GstV4l2Decoder GstV4l2Decoder;
typedef struct _GstV4l2Request GstV4l2Request;

struct _GstV4l2Request {
	gint ref_count;
	GstV4l2Decoder *decoder;
	gint fd;
	guint32 frame_num;
	GstMemory *bitstream;
	GstBuffer *pic_buf;
	GstPoll *poll;
	int pollfd;
	gboolean pending;
	gboolean failed;
	gboolean hold_pic_buf;
	gboolean sub_request;
};

struct _GstV4l2Decoder {
	GstObject parent;
	gboolean opened;
	gint media_fd;
	gint video_fd;
	GstVecDeque *request_pool;
	GstVecDeque *pending_requests;
	guint version;
	enum v4l2_buf_type src_buf_type;
	enum v4l2_buf_type sink_buf_type;
	gboolean mplane;
	gchar *media_device;
	gchar *video_device;
	guint render_delay;
	gboolean supports_holding_capture;
	gboolean supports_remove_buffers;
	gboolean doc_mode;
};

static inline GstV4l2Request *gst_v4l2_request_ref(GstV4l2Request *r) { return r; }
static inline gsize gst_memory_get_sizes(GstMemory *m, void *a, void *b)
{
	(void)m;
	(void)a;
	(void)b;
	return 16;
}
static inline unsigned gst_v4l2_codec_memory_get_index(GstMemory *m)
{
	(void)m;
	return 0;
}
static inline unsigned gst_v4l2_codec_buffer_get_index(GstBuffer *b)
{
	(void)b;
	return 1;
}
static inline unsigned gst_buffer_n_memory(GstBuffer *b)
{
	(void)b;
	return 1;
}
static inline GstMemory *gst_buffer_peek_memory(GstBuffer *b, unsigned i)
{
	(void)b;
	(void)i;
	return (GstMemory *)1;
}
static inline gsize gst_buffer_get_size(GstBuffer *b)
{
	(void)b;
	return 16;
}
void gst_v4l2_request_set_done(GstV4l2Request *request);
int gst_v4l2_decoder_streamoff(GstV4l2Decoder *self, GstPadDirection d);
int gst_v4l2_decoder_streamon(GstV4l2Decoder *self, GstPadDirection d);
static inline void g_free(void *p) { (void)p; }
static inline void g_object_unref(void *p) { (void)p; }
static inline void gst_poll_free(void *p) { (void)p; }

#endif
