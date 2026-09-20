/* SPDX-License-Identifier: LGPL-2.1-or-later */
/* Included by the pinned complete v4l2slh265dec implementation. */
#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <linux/fs.h>
#include <glib/gstdio.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <unistd.h>

#define GST_HEVC_RUNNER_REPORT_BYTES 8192u
#define GST_HEVC_RUNNER_SCHEMA "omarchy.hevc.gst-observer-result/v1"

enum GstHevcRunnerStatus
{
  GST_HEVC_RUNNER_DISABLED,
  GST_HEVC_RUNNER_CONFIGURED,
  GST_HEVC_RUNNER_ARMED,
  GST_HEVC_RUNNER_CONFIG_REFUSED,
  GST_HEVC_RUNNER_ARM_REFUSED,
  GST_HEVC_RUNNER_STREAM_FAILURE,
  GST_HEVC_RUNNER_INCOMPLETE,
  GST_HEVC_RUNNER_CLEANUP_QUARANTINE,
  GST_HEVC_RUNNER_REPORT_FAILURE,
  GST_HEVC_RUNNER_SUCCESS,
};

enum
{
  GST_HEVC_RUNNER_SET_FRAMES = 1u << 0,
  GST_HEVC_RUNNER_SET_COPY = 1u << 1,
  GST_HEVC_RUNNER_SET_REPORT = 1u << 2,
  GST_HEVC_RUNNER_SET_ALL = (1u << 3) - 1,
};

struct _GstHevcRunner
{
  gchar *frames_text;
  gchar *report_path;
  guint32 frames[HEVC_CONTENT_SLOTS];
  guint count;
  guint set_mask;
  gboolean copy;
  gboolean invalid;
  gboolean locked;
  gboolean armed;
  gboolean terminal;
  gint status;
};

static const gchar *
gst_hevc_runner_status_name (enum GstHevcRunnerStatus status)
{
  switch (status) {
    case GST_HEVC_RUNNER_DISABLED:
      return "disabled";
    case GST_HEVC_RUNNER_CONFIGURED:
      return "configured";
    case GST_HEVC_RUNNER_ARMED:
      return "armed";
    case GST_HEVC_RUNNER_CONFIG_REFUSED:
      return "configuration-refused";
    case GST_HEVC_RUNNER_ARM_REFUSED:
      return "arm-refused";
    case GST_HEVC_RUNNER_STREAM_FAILURE:
      return "armed-stream-failure";
    case GST_HEVC_RUNNER_INCOMPLETE:
      return "incomplete-observation";
    case GST_HEVC_RUNNER_CLEANUP_QUARANTINE:
      return "cleanup-quarantine";
    case GST_HEVC_RUNNER_REPORT_FAILURE:
      return "report-failure";
    case GST_HEVC_RUNNER_SUCCESS:
      return "success";
  }
  return "invalid-status";
}

static GstHevcRunner *
gst_hevc_runner_ensure (GstV4l2CodecH265Dec * self)
{
  if (!self->content_runner) {
    self->content_runner = g_new0 (GstHevcRunner, 1);
    g_atomic_int_set (&self->content_runner->status,
        GST_HEVC_RUNNER_DISABLED);
  }
  return self->content_runner;
}

static void
gst_hevc_runner_message (GstV4l2CodecH265Dec * self,
    enum GstHevcRunnerStatus status, gboolean terminal)
{
  GstHevcRunner *runner = self->content_runner;
  if (!runner)
    return;
  g_atomic_int_set (&runner->status, status);
  if (!terminal || runner->terminal)
    return;
  runner->terminal = TRUE;
  const gchar *name = gst_hevc_runner_status_name (status);
  GstStructure *structure = gst_structure_new (
      "omarchy-hevc-observer-status", "status", G_TYPE_STRING, name,
      "terminal", G_TYPE_BOOLEAN, TRUE, NULL);
  gst_element_post_message (GST_ELEMENT (self),
      gst_message_new_element (GST_OBJECT (self), structure));
  if (status != GST_HEVC_RUNNER_SUCCESS)
    GST_ELEMENT_ERROR (self, STREAM, FAILED,
        ("HEVC observer runner failed"),
        ("omarchy-hevc-observer-status=%s", name));
}

static void
gst_hevc_runner_update_configured (GstV4l2CodecH265Dec * self)
{
  GstHevcRunner *runner = self->content_runner;
  if (runner && !runner->invalid && runner->set_mask == GST_HEVC_RUNNER_SET_ALL)
    g_atomic_int_set (&runner->status, GST_HEVC_RUNNER_CONFIGURED);
}

static void
gst_hevc_runner_set_property (GstV4l2CodecH265Dec * self, guint prop_id,
    const GValue * value)
{
  GST_VIDEO_DECODER_STREAM_LOCK (self);
  GstHevcRunner *runner = gst_hevc_runner_ensure (self);
  guint bit = prop_id == PROP_HEVC_OBSERVER_FRAMES ?
      GST_HEVC_RUNNER_SET_FRAMES :
      prop_id == PROP_HEVC_OBSERVER_COPY ? GST_HEVC_RUNNER_SET_COPY :
      GST_HEVC_RUNNER_SET_REPORT;
  if (runner->set_mask & bit || runner->locked || self->streaming ||
      self->content_callsite) {
    runner->invalid = TRUE;
    g_atomic_int_set (&runner->status, GST_HEVC_RUNNER_CONFIG_REFUSED);
    GST_VIDEO_DECODER_STREAM_UNLOCK (self);
    return;
  }
  runner->set_mask |= bit;
  if (prop_id == PROP_HEVC_OBSERVER_FRAMES)
    runner->frames_text = g_value_dup_string (value);
  else if (prop_id == PROP_HEVC_OBSERVER_COPY)
    runner->copy = g_value_get_boolean (value);
  else
    runner->report_path = g_value_dup_string (value);
  gst_hevc_runner_update_configured (self);
  GST_VIDEO_DECODER_STREAM_UNLOCK (self);
}

static void
gst_hevc_runner_get_property (GstV4l2CodecH265Dec * self, guint prop_id,
    GValue * value)
{
  GST_VIDEO_DECODER_STREAM_LOCK (self);
  GstHevcRunner *runner = self->content_runner;
  if (prop_id == PROP_HEVC_OBSERVER_STATUS) {
    enum GstHevcRunnerStatus status = runner ?
        g_atomic_int_get (&runner->status) : GST_HEVC_RUNNER_DISABLED;
    g_value_set_string (value, gst_hevc_runner_status_name (status));
  } else if (prop_id == PROP_HEVC_OBSERVER_FRAMES) {
    g_value_set_string (value, runner ? runner->frames_text : NULL);
  } else if (prop_id == PROP_HEVC_OBSERVER_COPY) {
    g_value_set_boolean (value, runner ? runner->copy : FALSE);
  } else {
    g_value_set_string (value, runner ? runner->report_path : NULL);
  }
  GST_VIDEO_DECODER_STREAM_UNLOCK (self);
}

static void
gst_hevc_runner_install_properties (GObjectClass * klass)
{
  g_object_class_install_property (klass, PROP_HEVC_OBSERVER_FRAMES,
      g_param_spec_string ("hevc-observer-frames",
          "HEVC observer frame selectors",
          "Private experiment: comma-separated system frame numbers", NULL,
          G_PARAM_READWRITE | G_PARAM_STATIC_STRINGS));
  g_object_class_install_property (klass, PROP_HEVC_OBSERVER_COPY,
      g_param_spec_boolean ("hevc-observer-copy", "HEVC observer copy mode",
          "Private experiment: copy selected compressed/MV ranges", FALSE,
          G_PARAM_READWRITE | G_PARAM_STATIC_STRINGS));
  g_object_class_install_property (klass, PROP_HEVC_OBSERVER_REPORT,
      g_param_spec_string ("hevc-observer-report", "HEVC observer report",
          "Private experiment: exclusive normalized report destination", NULL,
          G_PARAM_READWRITE | G_PARAM_STATIC_STRINGS));
  g_object_class_install_property (klass, PROP_HEVC_OBSERVER_STATUS,
      g_param_spec_string ("hevc-observer-status", "HEVC observer status",
          "Private experiment: attributable runner state", "disabled",
          G_PARAM_READABLE | G_PARAM_STATIC_STRINGS));
}

static gboolean
gst_hevc_runner_parse_frames (GstHevcRunner * runner)
{
  if (!runner->frames_text || !*runner->frames_text)
    return FALSE;
  gchar **values = g_strsplit (runner->frames_text, ",", -1);
  gboolean ok = TRUE;
  runner->count = 0;
  for (guint i = 0; values[i]; i++) {
    gchar *end = NULL;
    for (const gchar *digit = values[i]; *digit; digit++) {
      if (*digit < '0' || *digit > '9') {
        ok = FALSE;
        break;
      }
    }
    if (!ok)
      break;
    errno = 0;
    guint64 value = g_ascii_strtoull (values[i], &end, 10);
    if (!*values[i] || errno || !end || *end || value >= G_MAXUINT32 ||
        runner->count >= HEVC_CONTENT_SLOTS) {
      ok = FALSE;
      break;
    }
    for (guint j = 0; j < runner->count; j++) {
      if (runner->frames[j] == (guint32) value) {
        ok = FALSE;
        break;
      }
    }
    if (!ok)
      break;
    runner->frames[runner->count++] = (guint32) value;
  }
  g_strfreev (values);
  return ok && runner->count;
}

static gboolean
gst_hevc_runner_arm (GstV4l2CodecH265Dec * self)
{
  gboolean ok = TRUE;
  GST_VIDEO_DECODER_STREAM_LOCK (self);
  GstHevcRunner *runner = self->content_runner;
  if (!runner)
    goto done;
  if (runner->terminal) {
    ok = g_atomic_int_get (&runner->status) == GST_HEVC_RUNNER_SUCCESS;
    goto done;
  }
  if (runner->armed)
    goto done;
  runner->locked = TRUE;
  if (runner->invalid || runner->set_mask != GST_HEVC_RUNNER_SET_ALL ||
      !gst_hevc_runner_parse_frames (runner) ||
      !runner->report_path || !*runner->report_path) {
    gst_hevc_runner_message (self, GST_HEVC_RUNNER_CONFIG_REFUSED, TRUE);
    ok = FALSE;
    goto done;
  }
  if (!gst_hevc_callsite_arm_frames (GST_H265_DECODER (self), runner->copy,
          runner->frames, runner->count)) {
    gst_hevc_runner_message (self, GST_HEVC_RUNNER_ARM_REFUSED, TRUE);
    ok = FALSE;
    goto done;
  }
  runner->armed = TRUE;
  g_atomic_int_set (&runner->status, GST_HEVC_RUNNER_ARMED);
done:
  GST_VIDEO_DECODER_STREAM_UNLOCK (self);
  return ok;
}

static gboolean
gst_hevc_runner_json (GstHevcRunner * runner,
    const struct hevc_content_pool * pool, GString ** output)
{
  if (!runner || !pool || pool->used != runner->count || !pool->used ||
      pool->used > HEVC_CONTENT_SLOTS)
    return FALSE;
  GString *json = g_string_sized_new (1024);
  if (!json)
    return FALSE;
  g_string_append_printf (json, "{\"schema\":\"%s\",\"count\":%u,"
      "\"outputs\":[", GST_HEVC_RUNNER_SCHEMA, pool->used);
  guint64 run[2] = { 0, 0 }, context = 0, session = 0;
  guint32 seen[HEVC_CONTENT_SLOTS] = { 0 };
  guint64 requests[HEVC_CONTENT_SLOTS] = { 0 };
  for (guint i = 0; i < pool->used; i++) {
    const struct hevc_content_identity *identity = &pool->slot[i].identity;
    if (!pool->slot[i].valid || pool->slot[i].copied != runner->copy ||
        identity->client != HEVC_CONTENT_GST ||
        identity->detail.gst.frame == G_MAXUINT32 ||
        identity->capture_index == G_MAXUINT32 ||
        !(identity->run[0] || identity->run[1]) ||
        !identity->context_generation || !identity->session ||
        !identity->detail.gst.request || !identity->allocation_generation ||
        !identity->writer || !identity->submitted || !identity->completed ||
        identity->completed < identity->submitted)
      goto fail;
    gboolean selected = FALSE;
    for (guint j = 0; j < runner->count; j++)
      selected |= runner->frames[j] == identity->detail.gst.frame;
    if (!selected)
      goto fail;
    for (guint j = 0; j < i; j++)
      if (seen[j] == identity->detail.gst.frame ||
          requests[j] == identity->detail.gst.request)
        goto fail;
    seen[i] = identity->detail.gst.frame;
    requests[i] = identity->detail.gst.request;
    if (!i) {
      run[0] = identity->run[0];
      run[1] = identity->run[1];
      context = identity->context_generation;
      session = identity->session;
    } else if (run[0] != identity->run[0] || run[1] != identity->run[1] ||
        context != identity->context_generation || session != identity->session) {
      goto fail;
    }
    g_string_append_printf (json,
        "%s{\"system_frame_number\":%u,\"request\":\"%016" PRIx64 "\","
        "\"run\":[\"%016" PRIx64 "\",\"%016" PRIx64 "\"],"
        "\"context_generation\":\"%016" PRIx64 "\","
        "\"session\":\"%016" PRIx64 "\","
        "\"allocation_generation\":\"%016" PRIx64 "\","
        "\"writer\":\"%016" PRIx64 "\","
        "\"submitted\":\"%016" PRIx64 "\","
        "\"completed\":\"%016" PRIx64 "\","
        "\"capture_index\":%u,\"copied\":%s,\"sha256\":",
        i ? "," : "", identity->detail.gst.frame,
        identity->detail.gst.request, identity->run[0], identity->run[1],
        identity->context_generation, identity->session,
        identity->allocation_generation, identity->writer,
        identity->submitted, identity->completed, identity->capture_index,
        pool->slot[i].copied ? "true" : "false");
    if (pool->slot[i].copied) {
      gchar *digest = g_compute_checksum_for_data (G_CHECKSUM_SHA256,
          pool->slot[i].bytes, HEVC_CONTENT_BYTES);
      if (!digest)
        goto fail;
      g_string_append_printf (json, "\"%s\"", digest);
      g_free (digest);
    } else {
      g_string_append (json, "null");
    }
    g_string_append_c (json, '}');
    if (json->len >= GST_HEVC_RUNNER_REPORT_BYTES)
      goto fail;
  }
  g_string_append (json, "]}\n");
  if (json->len > GST_HEVC_RUNNER_REPORT_BYTES)
    goto fail;
  *output = json;
  return TRUE;
fail:
  g_string_free (json, TRUE);
  return FALSE;
}

static gboolean
gst_hevc_runner_write_all (gint fd, const gchar * data, gsize size)
{
  while (size) {
    ssize_t written = write (fd, data, size);
    if (written < 0) {
      if (errno == EINTR)
        continue;
      return FALSE;
    }
    if (!written)
      return FALSE;
    data += written;
    size -= written;
  }
  return TRUE;
}

static gboolean
gst_hevc_runner_publish (const gchar * path, const GString * json)
{
  gboolean ok = FALSE;
  gchar *temporary = g_strdup_printf ("%s.tmp.XXXXXX", path);
  if (!temporary)
    return FALSE;
  gint fd = g_mkstemp_full (temporary, O_RDWR | O_CLOEXEC,
      S_IRUSR | S_IWUSR);
  if (fd < 0)
    goto done;
  if (fchmod (fd, S_IRUSR | S_IWUSR) < 0 ||
      !gst_hevc_runner_write_all (fd, json->str, json->len) ||
      fsync (fd) < 0) {
    close (fd);
    fd = -1;
    goto done;
  }
  if (close (fd) < 0) {
    fd = -1;
    goto done;
  }
  fd = -1;
#ifdef SYS_renameat2
  if (syscall (SYS_renameat2, AT_FDCWD, temporary, AT_FDCWD, path,
          RENAME_NOREPLACE) < 0)
    goto done;
  ok = TRUE;
#endif
done:
  if (fd >= 0)
    close (fd);
  if (!ok && unlink (temporary) < 0 && errno != ENOENT)
    ok = FALSE;
  g_free (temporary);
  return ok;
}

static GstFlowReturn
gst_hevc_runner_abort (GstV4l2CodecH265Dec * self,
    enum GstHevcRunnerStatus status)
{
  GstHevcRunner *runner = self->content_runner;
  if (!runner)
    return GST_FLOW_ERROR;
  if (self->content_callsite &&
      !gst_hevc_callsite_finish (GST_H265_DECODER (self))) {
    gst_hevc_runner_message (self, GST_HEVC_RUNNER_CLEANUP_QUARANTINE, TRUE);
    return GST_FLOW_ERROR;
  }
  runner->armed = FALSE;
  gst_hevc_runner_message (self, status, TRUE);
  return GST_FLOW_ERROR;
}

static GstFlowReturn
gst_hevc_runner_complete (GstV4l2CodecH265Dec * self)
{
  GstHevcRunner *runner = self->content_runner;
  const struct hevc_content_pool *pool =
      gst_hevc_callsite_result (GST_H265_DECODER (self));
  GString *json = NULL;
  gboolean normalized = gst_hevc_runner_json (runner, pool, &json);
  if (!gst_hevc_callsite_finish (GST_H265_DECODER (self))) {
    if (json)
      g_string_free (json, TRUE);
    gst_hevc_runner_message (self, GST_HEVC_RUNNER_CLEANUP_QUARANTINE, TRUE);
    return GST_FLOW_ERROR;
  }
  runner->armed = FALSE;
  if (!normalized || !gst_hevc_runner_publish (runner->report_path, json)) {
    if (json)
      g_string_free (json, TRUE);
    gst_hevc_runner_message (self, GST_HEVC_RUNNER_REPORT_FAILURE, TRUE);
    return GST_FLOW_ERROR;
  }
  g_string_free (json, TRUE);
  gst_hevc_runner_message (self, GST_HEVC_RUNNER_SUCCESS, TRUE);
  return GST_FLOW_OK;
}

static GstFlowReturn
gst_hevc_runner_after_output (GstV4l2CodecH265Dec * self, GstFlowReturn flow)
{
  GstHevcRunner *runner = self->content_runner;
  if (!runner)
    return flow;
  if (runner->terminal)
    return g_atomic_int_get (&runner->status) == GST_HEVC_RUNNER_SUCCESS ?
        flow : GST_FLOW_ERROR;
  if (runner->invalid)
    return runner->armed ?
        gst_hevc_runner_abort (self, GST_HEVC_RUNNER_CONFIG_REFUSED) :
        GST_FLOW_ERROR;
  if (flow != GST_FLOW_OK)
    return runner->armed ?
        gst_hevc_runner_abort (self, GST_HEVC_RUNNER_STREAM_FAILURE) : flow;
  if (runner->armed &&
      gst_hevc_callsite_result (GST_H265_DECODER (self)))
    return gst_hevc_runner_complete (self);
  return flow;
}

static GstFlowReturn
gst_hevc_runner_after_drain (GstV4l2CodecH265Dec * self, GstFlowReturn flow)
{
  GstHevcRunner *runner = self->content_runner;
  if (!runner)
    return flow;
  if (runner->terminal)
    return g_atomic_int_get (&runner->status) == GST_HEVC_RUNNER_SUCCESS ?
        flow : GST_FLOW_ERROR;
  if (runner->invalid)
    return runner->armed ?
        gst_hevc_runner_abort (self, GST_HEVC_RUNNER_CONFIG_REFUSED) :
        GST_FLOW_ERROR;
  if (flow != GST_FLOW_OK)
    return runner->armed ?
        gst_hevc_runner_abort (self, GST_HEVC_RUNNER_STREAM_FAILURE) : flow;
  if (runner->armed) {
    if (gst_hevc_callsite_result (GST_H265_DECODER (self)))
      return gst_hevc_runner_complete (self);
    return gst_hevc_runner_abort (self, GST_HEVC_RUNNER_INCOMPLETE);
  }
  if (runner->set_mask || runner->invalid)
    return gst_hevc_runner_abort (self,
        runner->invalid || runner->set_mask != GST_HEVC_RUNNER_SET_ALL ?
        GST_HEVC_RUNNER_CONFIG_REFUSED : GST_HEVC_RUNNER_INCOMPLETE);
  return flow;
}

static GstFlowReturn
gst_v4l2_codec_h265_dec_runner_handle_frame (GstVideoDecoder * decoder,
    GstVideoCodecFrame * frame)
{
  GstFlowReturn flow = GST_VIDEO_DECODER_CLASS (parent_class)->handle_frame (
      decoder, frame);
  GstV4l2CodecH265Dec *self = GST_V4L2_CODEC_H265_DEC (decoder);
  if (flow != GST_FLOW_OK && self->content_runner &&
      self->content_runner->armed && !self->content_runner->terminal)
    return gst_hevc_runner_abort (self, GST_HEVC_RUNNER_STREAM_FAILURE);
  return flow;
}

static GstFlowReturn
gst_v4l2_codec_h265_dec_runner_finish (GstVideoDecoder * decoder)
{
  GstFlowReturn flow = GST_VIDEO_DECODER_CLASS (parent_class)->finish (decoder);
  return gst_hevc_runner_after_drain (GST_V4L2_CODEC_H265_DEC (decoder), flow);
}

static GstFlowReturn
gst_v4l2_codec_h265_dec_runner_drain (GstVideoDecoder * decoder)
{
  GstFlowReturn flow = GST_VIDEO_DECODER_CLASS (parent_class)->drain (decoder);
  return gst_hevc_runner_after_drain (GST_V4L2_CODEC_H265_DEC (decoder), flow);
}

static void
gst_hevc_runner_dispose (GstV4l2CodecH265Dec * self)
{
  GstHevcRunner *runner = self->content_runner;
  if (!runner)
    return;
  g_free (runner->frames_text);
  g_free (runner->report_path);
  g_free (runner);
  self->content_runner = NULL;
}
