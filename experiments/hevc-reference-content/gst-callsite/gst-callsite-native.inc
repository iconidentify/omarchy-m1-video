/* SPDX-License-Identifier: LGPL-2.1-or-later */
/* Included by the complete decoder source; keep checks in its owning layer. */
gboolean
gst_hevc_callsite_open_before_queue (GstV4l2Decoder *self,
    GstHevcObserverSession *session)
{
  GST_HEVC_OBSERVER_LOCK;
  return self && !self->observer_submitted && !self->observer_unqueued &&
      gst_hevc_observer_open (self, session);
}

gboolean
gst_hevc_callsite_output_matches (GstV4l2Request *request, GstBuffer *buffer)
{
  GST_HEVC_OBSERVER_LOCK;
  return request && buffer && request->pic_buf == buffer;
}
