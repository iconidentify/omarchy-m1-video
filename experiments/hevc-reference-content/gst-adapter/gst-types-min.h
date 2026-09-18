/* SPDX-License-Identifier: LGPL-2.1-or-later */
/* Plugin-private structs from pinned gstv4l2decoder.c; configured Gst/GLib headers. */
#ifndef GST_TYPES_MIN_H
#define GST_TYPES_MIN_H
#include <gst/gst.h>
#include <gst/video/video.h>
#if __has_include(<gst/gstvecdeque.h>)
#include <gst/gstvecdeque.h>
#else
typedef struct GstVecDeque {
	gpointer items[8];
	guint len;
} GstVecDeque;
static inline GstVecDeque *gst_vec_deque_new(guint n)
{
	(void)n;
	return g_new0(GstVecDeque, 1);
}
static inline void gst_vec_deque_free(GstVecDeque *d) { g_free(d); }
static inline guint gst_vec_deque_get_length(GstVecDeque *d) { return d ? d->len : 0; }
static inline void gst_vec_deque_push_tail(GstVecDeque *d, gpointer item)
{
	if (d && d->len < 8)
		d->items[d->len++] = item;
}
static inline gpointer gst_vec_deque_peek_head(GstVecDeque *d)
{
	return (d && d->len) ? d->items[0] : NULL;
}
static inline gpointer gst_vec_deque_pop_head(GstVecDeque *d)
{
	gpointer item;
	guint i;
	if (!d || !d->len)
		return NULL;
	item = d->items[0];
	for (i = 1; i < d->len; i++)
		d->items[i - 1] = d->items[i];
	d->len--;
	return item;
}
#endif
#include <linux/videodev2.h>
#include <linux/media.h>
#include <unistd.h>
#include <errno.h>

#undef GST_TRACE_OBJECT
#undef GST_ERROR_OBJECT
#undef GST_DEBUG_OBJECT
#undef GST_WARNING_OBJECT
#define GST_TRACE_OBJECT(obj, fmt, ...) ((void)0)
#define GST_ERROR_OBJECT(obj, fmt, ...) ((void)0)
#define GST_DEBUG_OBJECT(obj, fmt, ...) ((void)0)
#define GST_WARNING_OBJECT(obj, fmt, ...) ((void)0)

typedef struct _GstV4l2Request GstV4l2Request;
typedef struct _GstV4l2Decoder GstV4l2Decoder;

struct _GstV4l2Request {
	gint ref_count;
	GstV4l2Decoder *decoder;
	gint fd;
	guint32 frame_num;
	GstMemory *bitstream;
	GstBuffer *pic_buf;
	GstPoll *poll;
	GstPollFD pollfd;
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

static inline guint gst_v4l2_codec_memory_get_index(GstMemory *m)
{
	(void)m;
	return 0;
}
static inline guint gst_v4l2_codec_buffer_get_index(GstBuffer *b)
{
	(void)b;
	return 1;
}

GstV4l2Request *gst_v4l2_request_ref(GstV4l2Request *request);
void gst_v4l2_request_unref(GstV4l2Request *request);
gint gst_v4l2_request_set_done(GstV4l2Request *request);
gboolean gst_v4l2_decoder_dequeue_sink(GstV4l2Decoder *self);
gboolean gst_v4l2_decoder_dequeue_src(GstV4l2Decoder *self, guint32 *out_frame_num);
gboolean gst_v4l2_decoder_streamoff(GstV4l2Decoder *self, GstPadDirection d);
gboolean gst_v4l2_decoder_streamon(GstV4l2Decoder *self, GstPadDirection d);
gboolean gst_v4l2_decoder_flush(GstV4l2Decoder *self);
gboolean gst_v4l2_request_queue(GstV4l2Request *request, guint flags);
void gst_v4l2_request_free(GstV4l2Request *request);

#endif
