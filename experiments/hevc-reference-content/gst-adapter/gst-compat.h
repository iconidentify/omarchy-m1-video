/* SPDX-License-Identifier: LGPL-2.1-or-later
 * Host GStreamer compat and plugin helpers. Plugin structs come from
 * extracted-structs.inc (pinned gstv4l2decoder.c). */
#ifndef GST_COMPAT_H
#define GST_COMPAT_H
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

#endif
