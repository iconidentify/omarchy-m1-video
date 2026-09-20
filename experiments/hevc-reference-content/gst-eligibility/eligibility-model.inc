/* SPDX-License-Identifier: LGPL-2.1-or-later */
/* Test-only extension of the complete pinned plugin and V4L2 syscall model. */
static void
eligibility_replace_source_pool (const gchar *frames, guint ordinary,
    guint expected_total)
{
  assert (ordinary >= 2);
  client->streaming = FALSE;
  runner_configure (frames, TRUE);
  client->streaming = FALSE;
  client->min_pool_size = ordinary - 2;
  assert (gst_video_info_set_format (&client->vinfo_drm.vinfo,
      GST_VIDEO_FORMAT_NV12, 448, 240));
  GstCaps *caps = gst_caps_from_string (
      "video/x-raw,format=NV12,width=448,height=240");
  assert (caps);
  GstQuery *query = gst_query_new_allocation (caps, TRUE);
  gst_caps_unref (caps);
  gst_query_add_allocation_meta (query, GST_VIDEO_META_API_TYPE, NULL);
  gst_query_add_allocation_pool (query, NULL, 6144, 2, 0);
  assert (gst_v4l2_codec_h265_dec_decide_allocation (
      GST_VIDEO_DECODER (client), query));
  gst_query_unref (query);
  assert (client->content_runner->allocation_frozen);
  assert (client->content_runner->remaining_allocations ==
      client->content_runner->count);
  assert (gst_v4l2_codec_allocator_get_pool_size (client->src_allocator) ==
      expected_total);
  client->streaming = TRUE;
  assert (gst_hevc_runner_arm (client));
  runner_expect_status ("armed");
}

static GstBuffer *
eligibility_acquire (guint32 number, gboolean expected)
{
  GstVideoCodecFrame frame = { 0 };
  frame.ref_count = 1;
  frame.system_frame_number = number;
  gboolean result = gst_v4l2_codec_h265_dec_ensure_output_buffer (client,
      &frame);
  assert (result == expected);
  assert (!result || frame.output_buffer);
  return frame.output_buffer;
}

static guint32
eligibility_index (GstBuffer *buffer)
{
  assert (buffer);
  return gst_v4l2_codec_buffer_get_index (buffer);
}

static void
eligibility_schedule (guint32 number)
{
  schedule_release_request ();
  picture = eligibility_acquire (number, TRUE);
  bitstream = gst_v4l2_codec_allocator_alloc (client->sink_allocator);
  assert (bitstream);
  request = gst_v4l2_decoder_alloc_request (decoder, number, bitstream,
      picture);
  assert (request && gst_v4l2_request_queue (request, 0));
  selected_capture = last_capture;
}

static void
eligibility_abort (void)
{
  if (client->content_runner && client->content_runner->armed &&
      !client->content_runner->terminal)
    assert (gst_hevc_runner_abort (client,
        GST_HEVC_RUNNER_STREAM_FAILURE) == GST_FLOW_ERROR);
}

static void
eligibility_default_off (void)
{
  setup ();
  GstBuffer *first = eligibility_acquire (1, TRUE);
  guint32 first_index = eligibility_index (first);
  gst_buffer_unref (first);
  GstBuffer *second = eligibility_acquire (2, TRUE);
  assert (eligibility_index (second) != first_index);
  gst_buffer_unref (second);
  assert (!client->content_runner);
  teardown ();
}

static void
eligibility_late_selected (void)
{
  setup ();
  eligibility_replace_source_pool ("31", 4, 5);
  guint32 recycled = G_MAXUINT32;
  for (guint32 number = 0; number < 12; number++) {
    eligibility_schedule (number);
    guint32 current = eligibility_index (picture);
    if (!number)
      recycled = current;
    else
      assert (current == recycled);
    assert (output (number) == GST_FLOW_OK);
  }

  eligibility_schedule (31);
  assert (eligibility_index (picture) != recycled);
  assert (client->content_runner->remaining_allocations == 0);
  scheduled_maps++;
  assert (output (31) == GST_FLOW_OK);
  runner_expect_status ("success");
  runner_check_normalized_report ();
  assert (!client->content_callsite);
  teardown ();
}

static void
eligibility_reordered (void)
{
  setup ();
  eligibility_replace_source_pool ("31,33", 2, 4);
  GstBuffer *later = eligibility_acquire (33, TRUE);
  GstBuffer *earlier = eligibility_acquire (31, TRUE);
  assert (eligibility_index (later) != eligibility_index (earlier));
  assert (!client->content_runner->remaining_allocations);
  gst_buffer_unref (later);
  gst_buffer_unref (earlier);
  eligibility_abort ();
  teardown ();
}

static void
eligibility_duplicate (void)
{
  setup ();
  eligibility_replace_source_pool ("31,33", 2, 4);
  GstBuffer *selected = eligibility_acquire (31, TRUE);
  assert (!eligibility_acquire (31, FALSE));
  assert (client->content_runner->remaining_allocations == 1);
  gst_buffer_unref (selected);
  eligibility_abort ();
  teardown ();
}

static void
eligibility_presupplied (void)
{
  setup ();
  eligibility_replace_source_pool ("31", 2, 3);
  GstVideoCodecFrame frame = { 0 };
  frame.ref_count = 1;
  frame.system_frame_number = 1;
  frame.output_buffer = gst_buffer_new ();
  assert (!gst_v4l2_codec_h265_dec_ensure_output_buffer (client, &frame));
  gst_buffer_unref (frame.output_buffer);
  eligibility_abort ();
  teardown ();
}

static void
eligibility_publish_all (void)
{
  guint count = gst_v4l2_codec_allocator_get_pool_size (client->src_allocator);
  GstBuffer *buffers[16] = { 0 };
  assert (count <= G_N_ELEMENTS (buffers));
  for (guint i = 0; i < count; i++) {
    assert (gst_buffer_pool_acquire_buffer (GST_BUFFER_POOL (client->src_pool),
        &buffers[i], NULL) == GST_FLOW_OK);
    gst_hevc_observer_buffer_publish (buffers[i]);
  }
  for (guint i = 0; i < count; i++)
    gst_buffer_unref (buffers[i]);
}

static void
eligibility_shortage (void)
{
  setup ();
  eligibility_replace_source_pool ("31", 2, 3);
  eligibility_publish_all ();
  assert (!eligibility_acquire (31, FALSE));
  assert (client->content_runner->remaining_allocations == 1);
  eligibility_abort ();
  teardown ();
}

struct EligibilityWait
{
  _Atomic gboolean entered;
  _Atomic gboolean done;
  GstBuffer *buffer;
};

static void *
eligibility_wait_thread (void *data)
{
  struct EligibilityWait *wait = data;
  atomic_store (&wait->entered, TRUE);
  wait->buffer = eligibility_acquire (2, FALSE);
  atomic_store (&wait->done, TRUE);
  return NULL;
}

static void
eligibility_flush_wait (void)
{
  setup ();
  eligibility_replace_source_pool ("31", 2, 3);
  GstBuffer *ordinary[2] = {
    eligibility_acquire (1, TRUE), eligibility_acquire (2, TRUE)
  };
  struct EligibilityWait wait = { 0 };
  pthread_t thread;
  assert (!pthread_create (&thread, NULL, eligibility_wait_thread, &wait));
  while (!atomic_load (&wait.entered))
    sched_yield ();
  g_usleep (10000);
  assert (!atomic_load (&wait.done));
  gst_v4l2_codec_allocator_set_flushing (client->src_allocator, TRUE);
  assert (!pthread_join (thread, NULL));
  assert (atomic_load (&wait.done) && !wait.buffer);
  gst_v4l2_codec_allocator_set_flushing (client->src_allocator, FALSE);
  gst_buffer_unref (ordinary[0]);
  gst_buffer_unref (ordinary[1]);
  eligibility_abort ();
  teardown ();
}

static void
eligibility_alias_sticky (void)
{
  setup ();
  eligibility_replace_source_pool ("31", 2, 3);
  GstBuffer *mapped = NULL;
  assert (gst_buffer_pool_acquire_buffer (GST_BUFFER_POOL (client->src_pool),
      &mapped, NULL) == GST_FLOW_OK);
  guint32 mapped_index = eligibility_index (mapped);
  GstMemory *memory = gst_buffer_peek_memory (mapped, 0);
  GstMapInfo map;
  assert (gst_memory_map (memory, &map, GST_MAP_READ));
  gst_memory_unmap (memory, &map);
  GstMemory *alias = gst_memory_share (memory, 0, -1);
  assert (alias);
  gst_memory_unref (alias);
  gst_buffer_unref (mapped);

  GstBuffer *selected = eligibility_acquire (31, TRUE);
  assert (eligibility_index (selected) != mapped_index);
  GstHevcObserverReceipt receipt = { 0 };
  gst_hevc_observer_buffer_writer (selected, decoder, 77, FALSE);
  gst_hevc_observer_buffer_writer (selected, decoder, 77, TRUE);
  assert (gst_hevc_observer_buffer_identity (selected, decoder, &receipt));
  gst_hevc_observer_buffer_publish (selected);
  assert (!gst_hevc_observer_buffer_identity (selected, decoder, &receipt));
  gst_buffer_unref (selected);
  eligibility_abort ();
  teardown ();
}

static void
eligibility_incomplete (void)
{
  setup ();
  eligibility_replace_source_pool ("31", 2, 3);
  assert (gst_hevc_runner_after_drain (client, GST_FLOW_OK) == GST_FLOW_ERROR);
  runner_expect_status ("incomplete-observation");
  teardown ();
}

static void
eligibility_bad_config (void)
{
  setup ();
  client->streaming = FALSE;
  g_object_set (client, "hevc-observer-frames", "31", NULL);
  assert (gst_video_info_set_format (&client->vinfo_drm.vinfo,
      GST_VIDEO_FORMAT_NV12, 448, 240));
  GstCaps *caps = gst_caps_from_string (
      "video/x-raw,format=NV12,width=448,height=240");
  assert (caps);
  GstQuery *query = gst_query_new_allocation (caps, TRUE);
  gst_caps_unref (caps);
  gst_query_add_allocation_meta (query, GST_VIDEO_META_API_TYPE, NULL);
  gst_query_add_allocation_pool (query, NULL, 6144, 2, 0);
  assert (!gst_v4l2_codec_h265_dec_decide_allocation (
      GST_VIDEO_DECODER (client), query));
  gst_query_unref (query);
  assert (!client->src_allocator && !client->sink_allocator);
  runner_expect_status ("configuration-refused");
  teardown ();
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

  if (!strcmp (mode, "eligibility-default-off"))
    eligibility_default_off ();
  else if (!strcmp (mode, "eligibility-late-selected"))
    eligibility_late_selected ();
  else if (!strcmp (mode, "eligibility-reordered"))
    eligibility_reordered ();
  else if (!strcmp (mode, "eligibility-duplicate"))
    eligibility_duplicate ();
  else if (!strcmp (mode, "eligibility-presupplied"))
    eligibility_presupplied ();
  else if (!strcmp (mode, "eligibility-shortage"))
    eligibility_shortage ();
  else if (!strcmp (mode, "eligibility-flush-wait"))
    eligibility_flush_wait ();
  else if (!strcmp (mode, "eligibility-alias-sticky"))
    eligibility_alias_sticky ();
  else if (!strcmp (mode, "eligibility-incomplete"))
    eligibility_incomplete ();
  else if (!strcmp (mode, "eligibility-bad-config"))
    eligibility_bad_config ();
  else
    abort ();

  for (int i = 0; i < evidence_count; i++)
    assert (evidence_fds[i] == -1);
  printf ("PASS Gst eligibility %s (synthetic V4L2/runtime; no device)\n",
      mode);
  return 0;
}
