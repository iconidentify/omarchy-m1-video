/* SPDX-License-Identifier: LGPL-2.1-or-later */
/* Included after the real H265 client type, before its callback definitions. */
typedef struct _GstHevcCallsite {
  struct hevc_content_pool pool;
  GstHevcObserverSession session;
  GstHevcObserverReceipt receipt;
  GThread *owner;
  GstVideoCodecFrame *held_frame;
  GstH265Picture *held_picture;
  gboolean copy, attempted, success, in_callback, cancel_held;
  gint cancel_state;
} GstHevcCallsite;

static GstFlowReturn gst_v4l2_codec_h265_dec_output_picture (GstH265Decoder *,
    GstVideoCodecFrame *, GstH265Picture *);

static gboolean
content_client (GstH265Decoder *decoder)
{
  return GST_IS_H265_DECODER (decoder) &&
      GST_H265_DECODER_GET_CLASS (decoder)->output_picture ==
      gst_v4l2_codec_h265_dec_output_picture;
}

gboolean
gst_hevc_callsite_arm (GstH265Decoder *decoder, gboolean copy)
{
  if (!content_client (decoder) || (copy != FALSE && copy != TRUE))
    return FALSE;
  GstV4l2CodecH265Dec *self = GST_V4L2_CODEC_H265_DEC (decoder);
  gboolean ok = FALSE;
  GST_VIDEO_DECODER_STREAM_LOCK (decoder);
  if (self->content_callsite)
    goto done;
  GstHevcCallsite *state = g_try_new0 (GstHevcCallsite, 1);
  if (!state)
    goto done;
  gst_hevc_content_init (&state->pool, TRUE); /* allocate before native begin */
  g_rec_mutex_lock (&gst_hevc_observer_mutex);
  if (!gst_hevc_callsite_open_before_queue (self->decoder, &state->session)) {
    g_rec_mutex_unlock (&gst_hevc_observer_mutex);
    g_free (state);
    goto done;
  }
  state->owner = g_thread_ref (g_thread_self ());
  state->copy = copy;
  self->content_callsite = state;
  gst_object_ref (self); /* explicit finish owns this reference, also on errors */
  g_rec_mutex_unlock (&gst_hevc_observer_mutex);
  ok = TRUE;
done:
  GST_VIDEO_DECODER_STREAM_UNLOCK (decoder);
  return ok;
}

/* Runs only inside the production output callback, under stream -> observer
 * locks. The automatic leave runs AFTER the observer lock is released and
 * framework frame/picture ownership has been settled. */
static gboolean
content_before_output (GstV4l2CodecH265Dec *self, GstV4l2Request *request,
    GstVideoCodecFrame *frame, GstH265Picture *picture, GstHevcCallsite **active)
{
  GstHevcCallsite *state = self->content_callsite;
  if (!state)
    return TRUE; /* default off: no session, pool, runtime reads or map */
  if (state->owner != g_thread_self () || state->in_callback || state->receipt.lease)
    return FALSE;
  state->in_callback = TRUE;
  *active = state;
  if (state->attempted)
    return state->success;
  state->attempted = TRUE;
  pthread_setcancelstate (PTHREAD_CANCEL_DISABLE, &state->cancel_state);
  state->cancel_held = TRUE;
  GstHevcObserverTarget target;
  if (!gst_hevc_callsite_output_matches (request, frame->output_buffer) ||
      !gst_hevc_observer_select (self->decoder, &state->session, request, &target) ||
      !gst_hevc_observer_begin (self->decoder, &state->session, request, &target,
          0, &state->receipt))
    return FALSE;
  gboolean ok = state->receipt.frame_num == frame->system_frame_number &&
      state->receipt.frame_num == GST_CODEC_PICTURE (picture)->system_frame_number &&
      gst_hevc_content_snapshot (self->decoder, &state->receipt, &state->pool, state->copy);
  if (!gst_hevc_observer_end (self->decoder, &state->session, state->receipt.lease)) {
    /* Transfer callback ownership; do not publish, drop or recycle while paused.
     * Same-owner finish retries end and then drops these exact objects. */
    state->held_frame = frame;
    state->held_picture = picture;
    return FALSE;
  }
  state->receipt.lease = 0;
  state->success = ok;
  return ok;
}

static void
content_callback_leave (GstHevcCallsite **active)
{
  GstHevcCallsite *state = *active;
  if (!state)
    return;
  state->in_callback = FALSE;
  if (!state->receipt.lease && state->cancel_held) {
    state->cancel_held = FALSE;
    pthread_setcancelstate (state->cancel_state, NULL);
  }
}

const struct hevc_content_pool *
gst_hevc_callsite_result (GstH265Decoder *decoder)
{
  if (!content_client (decoder))
    return NULL;
  const struct hevc_content_pool *result = NULL;
  GST_VIDEO_DECODER_STREAM_LOCK (decoder);
  GstHevcCallsite *state = GST_V4L2_CODEC_H265_DEC (decoder)->content_callsite;
  if (state && state->owner == g_thread_self () && !state->in_callback &&
      state->success && !state->receipt.lease && state->pool.used == 1 &&
      state->pool.slot[0].valid)
    result = &state->pool;
  GST_VIDEO_DECODER_STREAM_UNLOCK (decoder);
  return result; /* borrowed private copy, valid only until same-owner finish */
}

gboolean
gst_hevc_callsite_finish (GstH265Decoder *decoder)
{
  if (!content_client (decoder))
    return FALSE;
  GstV4l2CodecH265Dec *self = GST_V4L2_CODEC_H265_DEC (decoder);
  gboolean ok = FALSE, restore = FALSE;
  gint cancel = 0;
  GST_VIDEO_DECODER_STREAM_LOCK (decoder);
  GstHevcCallsite *state = self->content_callsite;
  if (!state || state->owner != g_thread_self () || state->in_callback)
    goto done;
  state->in_callback = TRUE;
  if (state->receipt.lease) {
    if (!gst_hevc_observer_end (self->decoder, &state->session, state->receipt.lease))
      goto retry;
    state->receipt.lease = 0;
  }
  if (state->held_frame) {
    gst_video_decoder_drop_frame (GST_VIDEO_DECODER (self),
        g_steal_pointer (&state->held_frame));
    g_clear_pointer (&state->held_picture, gst_h265_picture_unref);
  }
  g_rec_mutex_lock (&gst_hevc_observer_mutex);
  if (!gst_hevc_observer_close (self->decoder, &state->session)) {
    g_rec_mutex_unlock (&gst_hevc_observer_mutex);
    goto retry;
  }
  restore = state->cancel_held;
  cancel = state->cancel_state;
  self->content_callsite = NULL;
  g_rec_mutex_unlock (&gst_hevc_observer_mutex);
  g_thread_unref (state->owner);
  g_free (state);
  ok = TRUE;
  goto done;
retry:
  state->in_callback = FALSE;
  if (!state->receipt.lease) {
    restore = state->cancel_held;
    cancel = state->cancel_state;
    state->cancel_held = FALSE;
  }
done:
  GST_VIDEO_DECODER_STREAM_UNLOCK (decoder);
  if (ok)
    gst_object_unref (self);
  if (restore)
    pthread_setcancelstate (cancel, NULL);
  return ok;
}
