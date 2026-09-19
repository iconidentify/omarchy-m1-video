/* SPDX-License-Identifier: LGPL-2.1-or-later */
/* Extends the existing explicit V4L2/runtime model, not production code. */
static unsigned published, finished, dropped;
void __real_gst_hevc_observer_buffer_publish (GstBuffer *);
GstFlowReturn __real_gst_video_decoder_finish_frame (GstVideoDecoder *, GstVideoCodecFrame *);
GstFlowReturn __real_gst_video_decoder_drop_frame (GstVideoDecoder *, GstVideoCodecFrame *);

__attribute__((visibility("default"))) void __wrap_gst_hevc_observer_buffer_publish (GstBuffer *buffer)
{
  assert(!gst_hevc_observer_busy(decoder) && !content_mapping);
  GstHevcCallsite *state=client->content_callsite;
  if(state) assert(state->success && state->pool.slot[0].valid);
  published++;
  __real_gst_hevc_observer_buffer_publish(buffer);
}
static void *check_unlocked(void *unused)
{
  (void)unused;
  assert(g_rec_mutex_trylock(&gst_hevc_observer_mutex));
  g_rec_mutex_unlock(&gst_hevc_observer_mutex);
  return NULL;
}
static void framework_boundary(void)
{
  assert(!gst_hevc_observer_busy(decoder));
  pthread_t thread;
  assert(!pthread_create(&thread,NULL,check_unlocked,NULL));
  assert(!pthread_join(thread,NULL));
  /* Reentrant cleanup must not free the callback's state. */
  if(client->content_callsite) {
    assert(!gst_hevc_callsite_finish(GST_H265_DECODER(client)));
    assert(!gst_hevc_callsite_result(GST_H265_DECODER(client)));
  }
}
__attribute__((visibility("default"))) GstFlowReturn __wrap_gst_video_decoder_finish_frame(GstVideoDecoder *dec,GstVideoCodecFrame *frame)
{
  framework_boundary();finished++;
  return __real_gst_video_decoder_finish_frame(dec,frame);
}
__attribute__((visibility("default"))) GstFlowReturn __wrap_gst_video_decoder_drop_frame(GstVideoDecoder *dec,GstVideoCodecFrame *frame)
{
  framework_boundary();dropped++;
  return __real_gst_video_decoder_drop_frame(dec,frame);
}
static GstFlowReturn output(guint32 number)
{
  GstH265Picture *pic=gst_h265_picture_new();
  GST_CODEC_PICTURE(pic)->system_frame_number=number;
  gst_h265_picture_set_user_data(pic,gst_v4l2_request_ref(request),(GDestroyNotify)gst_v4l2_request_unref);
  GstVideoCodecFrame *frame=g_new0(GstVideoCodecFrame,1);
  frame->ref_count=1;frame->system_frame_number=number;
  frame->pts=frame->dts=frame->duration=GST_CLOCK_TIME_NONE;
  frame->input_buffer=gst_buffer_new();frame->output_buffer=gst_buffer_ref(picture);
  if(!strcmp(mode,"wrong-buffer")) {
    gst_buffer_unref(frame->output_buffer);frame->output_buffer=gst_buffer_new();
  }
  GST_VIDEO_CODEC_FRAME_SET_DECODE_ONLY(frame);
  GST_VIDEO_DECODER_STREAM_LOCK(client);
  GstFlowReturn result=GST_H265_DECODER_GET_CLASS(client)->output_picture(GST_H265_DECODER(client),frame,pic);
  GST_VIDEO_DECODER_STREAM_UNLOCK(client);
  return result;
}
static void *foreign_callsite(void *unused)
{
  (void)unused;
  assert(!gst_hevc_callsite_arm(GST_H265_DECODER(client),TRUE));
  assert(!gst_hevc_callsite_result(GST_H265_DECODER(client)));
  assert(!gst_hevc_callsite_finish(GST_H265_DECODER(client)));
  return NULL;
}
static void check_cancel_state(int expected)
{
  int previous;
  assert(!pthread_setcancelstate(PTHREAD_CANCEL_DISABLE,&previous));
  assert(previous==expected);
  assert(!pthread_setcancelstate(previous,NULL));
}
static void check_lifecycle(void)
{
  unsigned before=ioctls;
  assert(!gst_v4l2_codec_h265_dec_close(GST_VIDEO_DECODER(client)));
  assert(!gst_v4l2_codec_h265_dec_stop(GST_VIDEO_DECODER(client)));
  assert(!gst_v4l2_codec_h265_dec_flush(GST_VIDEO_DECODER(client)));
  GstH265SPS sps={.width=448,.height=240,.chroma_format_idc=1};
  assert(GST_H265_DECODER_GET_CLASS(client)->new_sequence(GST_H265_DECODER(client),&sps,4)==GST_FLOW_NOT_NEGOTIATED);
  gst_v4l2_codec_h265_dec_streamoff(client);
  gst_v4l2_codec_h265_dec_reset_allocation(client);
  assert(ioctls==before && client->streaming && client->src_allocator && client->sink_allocator);
}
static gboolean flush_peer_event(GstPad *pad,GstObject *parent,GstEvent *event)
{
  (void)pad;(void)parent;gst_event_unref(event);return TRUE;
}
/* Drive a real FLUSH_START/FLUSH_STOP pair through the framework while armed.
 * check_lifecycle() calls the vfuncs directly, so it cannot see what the base
 * class does with their return values: GstVideoDecoder discards flush()'s and
 * resets regardless. The refusal therefore cannot stop the flush, and it must
 * not strand the allocators FLUSH_START set flushing either. No request is
 * created in this mode, so both pools are full and the wait cannot block. */
static void check_armed_flush(void)
{
  GstVideoDecoder *base=GST_VIDEO_DECODER(client);
  assert(GST_VIDEO_DECODER_CLASS(parent_class)->start(base));
  GstPad *peer=gst_pad_new("model-peer",GST_PAD_SINK);
  gst_pad_set_event_function(peer,flush_peer_event);
  assert(gst_pad_set_active(peer,TRUE));assert(gst_pad_set_active(base->srcpad,TRUE));
  assert(gst_pad_link(base->srcpad,peer)==GST_PAD_LINK_OK);
  gst_segment_init(&base->input_segment,GST_FORMAT_TIME);
  gst_segment_init(&base->output_segment,GST_FORMAT_TIME);
  assert(client->content_callsite);
  assert(!gst_v4l2_codec_h265_dec_flush(base)); /* still reports refusal */
  assert(GST_VIDEO_DECODER_GET_CLASS(client)->sink_event(base,gst_event_new_flush_start()));
  assert(GST_VIDEO_DECODER_GET_CLASS(client)->sink_event(base,gst_event_new_flush_stop(TRUE)));
  /* The framework reset the decoder anyway; the arm and its session survive. */
  assert(client->content_callsite && client->streaming);
  assert(client->src_allocator && client->sink_allocator);
  /* Regression: both allocators must be usable again. Without clearing the
   * flushing state the element can never acquire a capture buffer again, and
   * no later finish recovers it. */
  assert(gst_v4l2_codec_allocator_wait_for_buffer(client->src_allocator));
  assert(gst_v4l2_codec_allocator_wait_for_buffer(client->sink_allocator));
  assert(gst_hevc_callsite_finish(GST_H265_DECODER(client)));
  assert(!client->content_callsite);
  assert(gst_v4l2_codec_allocator_wait_for_buffer(client->src_allocator));
  gst_pad_unlink(base->srcpad,peer);gst_pad_set_active(peer,FALSE);
  gst_pad_set_active(base->srcpad,FALSE);gst_object_unref(peer);
  assert(GST_VIDEO_DECODER_CLASS(parent_class)->stop(base));
}
int main(int argc,char **argv)
{
  assert(argc==2);mode=argv[1];model_identify();model_peer((const void*)gst_hevc_content_snapshot);
  if(!strcmp(mode,"padded"))model_length=368128;
  g_setenv("GST_PLUGIN_SYSTEM_PATH_1_0","",TRUE);g_setenv("GST_PLUGIN_PATH_1_0","",TRUE);gst_init(NULL,NULL);
  GST_DEBUG_CATEGORY_INIT(gstv4l2codecs_debug,"v4l2codecs",0,"model plugin log");
  GST_DEBUG_CATEGORY_INIT(v4l2_h265dec_debug,"v4l2codecs-h265dec",0,"model client log");
  setup();
  if(!strcmp(mode,"flush-armed")) {
    assert(gst_hevc_callsite_arm(GST_H265_DECODER(client),TRUE));
    check_armed_flush();
    teardown();
    for(int i=0;i<evidence_count;i++)assert(evidence_fds[i]==-1);
    printf("PASS actual Gst callsite %s (synthetic V4L2/runtime; no device)\n",mode);
    return 0;
  }
  bool disabled=!strcmp(mode,"disabled"), late=!strcmp(mode,"late-arm"), control=!strcmp(mode,"control");
  bool canceled=!strcmp(mode,"cancel-arm"), bad=!strcmp(mode,"wrong-buffer") || !strcmp(mode,"wrong-frame");
  bool fail=bad || !strcmp(mode,"missing-manifest") || !strcmp(mode,"mmap-failure") ||
      !strcmp(mode,"munmap-failure") || !strcmp(mode,"decode-error") || !strcmp(mode,"timeout") ||
      !strcmp(mode,"published") || !strcmp(mode,"flush") || !strcmp(mode,"changed-proof") ||
      !strcmp(mode,"slow-copy");
  if(!disabled && !late) {
    assert(gst_hevc_callsite_arm(GST_H265_DECODER(client),!control));
    assert(!gst_hevc_callsite_arm(GST_H265_DECODER(client),TRUE));
    assert(!gst_hevc_callsite_result(GST_H265_DECODER(client)));
    if(!strcmp(mode,"lifecycle"))check_lifecycle();
    pthread_t thread;assert(!pthread_create(&thread,NULL,foreign_callsite,NULL));assert(!pthread_join(thread,NULL));
    if(canceled)assert(gst_hevc_callsite_finish(GST_H265_DECODER(client)));
  }
  request=new_request(31,&picture,&bitstream);assert(gst_v4l2_request_queue(request,0));
  selected_capture=last_capture;
  if(late)assert(!gst_hevc_callsite_arm(GST_H265_DECODER(client),TRUE));
  GstBuffer *reader_picture=NULL;GstMemory *reader_bits=NULL;GstV4l2Request *reader=NULL;
  if(!strcmp(mode,"readers")) {
    reader=new_request(32,&reader_picture,&reader_bits);assert(gst_v4l2_request_queue(reader,0));
  }
  if(!strcmp(mode,"decode-error"))fail_decode=TRUE;
  if(!strcmp(mode,"timeout"))poll_blocked=TRUE;
  if(!strcmp(mode,"published"))__real_gst_hevc_observer_buffer_publish(picture);
  if(!strcmp(mode,"flush"))assert(gst_v4l2_decoder_flush(decoder));
  fail_unmap=!strcmp(mode,"munmap-failure");
  GstFlowReturn result=output(!strcmp(mode,"wrong-frame")?32:31);
  if(fail) {
    assert(result==GST_FLOW_ERROR && published==0 && finished==0);
    assert(!gst_hevc_callsite_result(GST_H265_DECODER(client)));
    if(fail_unmap) {
      assert(dropped==0 && content_mapping && gst_hevc_observer_busy(decoder));
      assert(client->content_callsite->held_frame && client->content_callsite->held_picture);
      check_cancel_state(PTHREAD_CANCEL_DISABLE);
      assert(!gst_hevc_callsite_finish(GST_H265_DECODER(client)));
      assert(!gst_v4l2_codec_h265_dec_flush(GST_VIDEO_DECODER(client)));
      assert(!gst_v4l2_codec_h265_dec_stop(GST_VIDEO_DECODER(client)));
      assert(!gst_v4l2_codec_h265_dec_close(GST_VIDEO_DECODER(client)));
      assert(!gst_hevc_callsite_result(GST_H265_DECODER(client)));
      fail_unmap=FALSE;
    } else {
      assert(dropped==1 && !gst_hevc_observer_busy(decoder));
      check_cancel_state(PTHREAD_CANCEL_ENABLE);
    }
  } else {
    assert(result==GST_FLOW_OK && published==1 && finished==1 && dropped==0);
    if(disabled || late || canceled) {
      assert(!client->content_callsite && content_maps==0 && manifest_reads==0);
    } else {
      const struct hevc_content_pool *result=gst_hevc_callsite_result(GST_H265_DECODER(client));
      assert(result && result->used==1);
      check_slot((struct hevc_content_pool*)result,0,!control,selected_capture);
      assert(content_maps==1 && content_unmaps==1);
      assert(completed_count==queued_count);
      /* A second actual output cannot spend another snapshot or reopen the session. */
      assert(output(31)==GST_FLOW_OK);
      assert(content_maps==1 && result->used==1);
      if(!strcmp(mode,"lifecycle"))check_lifecycle();
    }
  }
  if(client->content_callsite)assert(gst_hevc_callsite_finish(GST_H265_DECODER(client)));
  if(fail)assert(dropped==1);
  assert(!gst_hevc_callsite_finish(GST_H265_DECODER(client)));
  check_cancel_state(PTHREAD_CANCEL_ENABLE);
  assert(!content_mapping && !gst_hevc_observer_busy(decoder));
  if(reader) {gst_v4l2_request_unref(reader);gst_buffer_unref(reader_picture);gst_memory_unref(reader_bits);}
  poll_blocked=fail_decode=FALSE;teardown();
  for(int i=0;i<evidence_count;i++)assert(evidence_fds[i]==-1);
  printf("PASS actual Gst callsite %s (synthetic V4L2/runtime; no device)\n",mode);
  return 0;
}
