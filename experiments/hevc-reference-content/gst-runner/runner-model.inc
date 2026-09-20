/* SPDX-License-Identifier: LGPL-2.1-or-later */
/* Test-only extension of the complete pinned plugin and syscall model. */
static gboolean runner_short_write;

ssize_t __real_write (int, const void *, size_t);
int __real_fsync (int);
gint __real_g_mkstemp_full (gchar *, gint, gint);

__attribute__((visibility("default"))) gint
__wrap_g_mkstemp_full (gchar *name, gint flags, gint mode_bits)
{
  int fd = __real_g_mkstemp_full (name, flags, mode_bits);
  if (fd >= 0)
    runner_report_fd = fd;
  return fd;
}

static int
runner_close (int fd)
{
  if (fd != runner_report_fd)
    return base_close (fd);
  runner_report_fd = -1;
  int result = __real_close (fd);
  if (!strcmp (mode, "runner-close-failure")) {
    errno = EIO;
    return -1;
  }
  return result;
}

__attribute__((visibility("default"))) ssize_t
__wrap_write (int fd, const void *data, size_t size)
{
  if (fd != runner_report_fd)
    return __real_write (fd, data, size);
  if (!strcmp (mode, "runner-write-failure")) {
    errno = ENOSPC;
    return -1;
  }
  if (!strcmp (mode, "runner-short-write") && !runner_short_write && size > 1) {
    runner_short_write = TRUE;
    return __real_write (fd, data, size / 2);
  }
  return __real_write (fd, data, size);
}

__attribute__((visibility("default"))) int
__wrap_fsync (int fd)
{
  if (fd == runner_report_fd && !strcmp (mode, "runner-fsync-failure")) {
    errno = EIO;
    return -1;
  }
  return __real_fsync (fd);
}

static gchar *
runner_status (void)
{
  gchar *status = NULL;
  g_object_get (client, "hevc-observer-status", &status, NULL);
  assert (status);
  return status;
}

static void
runner_expect_status (const gchar *expected)
{
  gchar *status = runner_status ();
  assert (!g_strcmp0 (status, expected));
  g_free (status);
}

static void
runner_configure (const gchar *frames, gboolean copy)
{
  client->streaming = FALSE;
  g_object_set (client, "hevc-observer-frames", frames,
      "hevc-observer-copy", copy,
      "hevc-observer-report", runner_report_path, NULL);
  client->streaming = TRUE;
  runner_expect_status ("configured");
}

static void
runner_check_normalized_report (void)
{
  gchar *data = NULL;
  gsize size = 0;
  assert (g_file_get_contents (runner_report_path, &data, &size, NULL));
  assert (size > 0 && size <= GST_HEVC_RUNNER_REPORT_BYTES && data[size - 1] == '\n');
  assert (strstr (data, "\"schema\":\"omarchy.hevc.gst-observer-result/v1\""));
  assert (strstr (data, "\"capture_index\""));
  assert (!strstr (data, "raw") && !strstr (data, "bytes") &&
      !strstr (data, "pointer") && !strstr (data, "dma") &&
      !strstr (data, "receipt") && !strstr (data, "lease"));
  g_free (data);
}

static void
runner_queue_output (guint32 frame, GstFlowReturn expected)
{
  schedule_queue (frame);
  if (client->content_callsite) {
    for (guint i = 0; i < client->content_callsite->count; i++)
      if (client->content_callsite->frames[i] == frame) {
        scheduled_maps++;
        break;
      }
  }
  assert (output (frame) == expected);
}

static void *
runner_stream (void *unused)
{
  (void) unused;
  if (!strcmp (mode, "runner-partial-config") ||
      !strcmp (mode, "runner-duplicate-config") ||
      !strcmp (mode, "runner-late-config") ||
      !strcmp (mode, "runner-invalid-selectors") ||
      !strcmp (mode, "runner-duplicate-selectors")) {
    assert (!gst_hevc_runner_arm (client));
    runner_expect_status ("configuration-refused");
    return NULL;
  }

  if (!strcmp (mode, "runner-arm-refusal")) {
    gpointer pool = client->src_pool;
    client->src_pool = NULL;
    assert (!gst_hevc_runner_arm (client));
    client->src_pool = pool;
    runner_expect_status ("arm-refused");
    return NULL;
  }

  if (!strcmp (mode, "runner-actual-arm")) {
    GstMemory *held[4];
    for (guint i = 0; i < G_N_ELEMENTS (held); i++) {
      held[i] = gst_v4l2_codec_allocator_alloc (client->sink_allocator);
      assert (held[i]);
    }
    assert (GST_H265_DECODER_GET_CLASS (client)->start_picture (
        GST_H265_DECODER (client), NULL, NULL, NULL) == GST_FLOW_ERROR);
    for (guint i = 0; i < G_N_ELEMENTS (held); i++)
      gst_memory_unref (held[i]);
    assert (client->content_callsite);
    runner_expect_status ("armed");
    assert (gst_hevc_runner_abort (client,
        GST_HEVC_RUNNER_STREAM_FAILURE) == GST_FLOW_ERROR);
    runner_expect_status ("armed-stream-failure");
    return NULL;
  }

  assert (gst_hevc_runner_arm (client));
  runner_expect_status ("armed");

  if (!strcmp (mode, "runner-mutable-config")) {
    g_object_set (client, "hevc-observer-frames", "32", NULL);
    runner_queue_output (31, GST_FLOW_ERROR);
    runner_expect_status ("configuration-refused");
    return NULL;
  }

  if (!strcmp (mode, "runner-collision")) {
    assert (g_file_set_contents (runner_report_path, "sentinel\n", -1, NULL));
  }
  if (!strcmp (mode, "runner-incomplete")) {
    runner_queue_output (31, GST_FLOW_OK);
    assert (GST_VIDEO_DECODER_GET_CLASS (client)->finish (
        GST_VIDEO_DECODER (client)) == GST_FLOW_ERROR);
    runner_expect_status ("incomplete-observation");
    return NULL;
  }
  if (!strcmp (mode, "runner-cleanup-quarantine")) {
    fail_unmap = TRUE;
    runner_queue_output (31, GST_FLOW_ERROR);
    runner_expect_status ("cleanup-quarantine");
    assert (client->content_callsite && gst_hevc_observer_busy (decoder));
    fail_unmap = FALSE;
    assert (gst_hevc_callsite_finish (GST_H265_DECODER (client)));
    return NULL;
  }

  runner_queue_output (31,
      !strcmp (mode, "runner-downstream-failure") ||
      !strcmp (mode, "runner-write-failure") ||
      !strcmp (mode, "runner-fsync-failure") ||
      !strcmp (mode, "runner-close-failure") ||
      !strcmp (mode, "runner-collision") ? GST_FLOW_ERROR : GST_FLOW_OK);

  if (!strcmp (mode, "runner-downstream-failure"))
    runner_expect_status ("armed-stream-failure");
  else if (!strcmp (mode, "runner-write-failure") ||
      !strcmp (mode, "runner-fsync-failure") ||
      !strcmp (mode, "runner-close-failure") ||
      !strcmp (mode, "runner-collision"))
    runner_expect_status ("report-failure");
  else
    runner_expect_status ("success");
  return NULL;
}

static void
runner_json_determinism (void)
{
  GstHevcRunner runner = {.frames = {11}, .count = 1, .copy = TRUE};
  struct hevc_content_pool pool = {.used = 1};
  pool.slot[0].valid = pool.slot[0].copied = TRUE;
  pool.slot[0].identity = (struct hevc_content_identity) {
    .client = HEVC_CONTENT_GST,
    .run = {1, 2}, .context_generation = 3, .session = 4,
    .allocation_generation = 5, .writer = 6, .submitted = 7,
    .completed = 8, .capture_index = 9,
    .detail.gst = {.request = 10, .frame = 11},
  };
  memset (pool.slot[0].bytes, 0x5a, sizeof (pool.slot[0].bytes));
  GString *first = NULL, *second = NULL;
  assert (gst_hevc_runner_json (&runner, &pool, &first));
  assert (gst_hevc_runner_json (&runner, &pool, &second));
  assert (!strcmp (first->str, second->str));
  assert (strstr (first->str, "\"sha256\":\""));
  g_string_free (first, TRUE);
  g_string_free (second, TRUE);
}

int
main (int argc, char **argv)
{
  assert (argc == 3);
  mode = argv[1];
  runner_report_path = argv[2];
  model_identify ();
  model_peer ((const void *) gst_hevc_content_snapshot);
  g_setenv ("GST_PLUGIN_SYSTEM_PATH_1_0", "", TRUE);
  g_setenv ("GST_PLUGIN_PATH_1_0", "", TRUE);
  gst_init (NULL, NULL);
  GST_DEBUG_CATEGORY_INIT (gstv4l2codecs_debug, "v4l2codecs", 0,
      "model plugin log");
  GST_DEBUG_CATEGORY_INIT (v4l2_h265dec_debug, "v4l2codecs-h265dec", 0,
      "model client log");
  setup ();

  if (!strcmp (mode, "runner-default-off")) {
    runner_queue_output (31, GST_FLOW_OK);
    assert (!client->content_runner && !g_file_test (runner_report_path,
        G_FILE_TEST_EXISTS));
    teardown ();
    printf ("PASS actual Gst runner %s (synthetic V4L2/runtime; no device)\n",
        mode);
    return 0;
  }
  if (!strcmp (mode, "runner-json-determinism")) {
    runner_json_determinism ();
    teardown ();
    printf ("PASS actual Gst runner %s (synthetic V4L2/runtime; no device)\n",
        mode);
    return 0;
  }

  if (!strcmp (mode, "runner-partial-config")) {
    client->streaming = FALSE;
    g_object_set (client, "hevc-observer-frames", "31", NULL);
    client->streaming = TRUE;
  } else if (!strcmp (mode, "runner-duplicate-config")) {
    client->streaming = FALSE;
    g_object_set (client, "hevc-observer-frames", "31", NULL);
    g_object_set (client, "hevc-observer-frames", "32",
        "hevc-observer-copy", TRUE,
        "hevc-observer-report", runner_report_path, NULL);
    client->streaming = TRUE;
  } else if (!strcmp (mode, "runner-late-config")) {
    g_object_set (client, "hevc-observer-frames", "31",
        "hevc-observer-copy", TRUE,
        "hevc-observer-report", runner_report_path, NULL);
  } else if (!strcmp (mode, "runner-invalid-selectors")) {
    runner_configure (" 31", TRUE);
  } else if (!strcmp (mode, "runner-duplicate-selectors")) {
    runner_configure ("31,31", TRUE);
  } else {
    runner_configure (!strcmp (mode, "runner-incomplete") ? "31,32" : "31",
        strcmp (mode, "runner-copy-off") != 0);
  }

  pthread_t thread;
  assert (!pthread_create (&thread, NULL, runner_stream, NULL));
  assert (!pthread_join (thread, NULL));

  gboolean success = !strcmp (mode, "runner-copy-off") ||
      !strcmp (mode, "runner-copy-on") ||
      !strcmp (mode, "runner-short-write");
  if (success) {
    assert (g_file_test (runner_report_path, G_FILE_TEST_IS_REGULAR));
    assert (!client->content_callsite);
    runner_check_normalized_report ();
  } else if (!strcmp (mode, "runner-collision")) {
    gchar *sentinel = NULL;
    assert (g_file_get_contents (runner_report_path, &sentinel, NULL, NULL));
    assert (!strcmp (sentinel, "sentinel\n"));
    g_free (sentinel);
    assert (!g_remove (runner_report_path));
  } else {
    assert (!g_file_test (runner_report_path, G_FILE_TEST_EXISTS));
  }
  assert (!content_mapping && !gst_hevc_observer_busy (decoder));
  teardown ();
  for (int i = 0; i < evidence_count; i++)
    assert (evidence_fds[i] == -1);
  printf ("PASS actual Gst runner %s (synthetic V4L2/runtime; no device)\n",
      mode);
  return 0;
}
