/* SPDX-License-Identifier: LGPL-2.1-or-later */
/* Extends the existing explicit V4L2/runtime model, not production code. */
static unsigned published, finished, dropped;
static unsigned scheduled_maps;
void __real_gst_hevc_observer_buffer_publish (GstBuffer *);
GstFlowReturn __real_gst_video_decoder_finish_frame (GstVideoDecoder *, GstVideoCodecFrame *);
GstFlowReturn __real_gst_video_decoder_drop_frame (GstVideoDecoder *, GstVideoCodecFrame *);

__attribute__((visibility("default"))) void __wrap_gst_hevc_observer_buffer_publish (GstBuffer *buffer)
{
  assert(!gst_hevc_observer_busy(decoder) && !content_mapping);
  GstHevcCallsite *state=client->content_callsite;
  if(state && !state->scheduled) assert(state->success && state->pool.slot[0].valid);
  if(state && state->scheduled) {
    assert(!state->failed && state->pool.used==scheduled_maps);
    assert(content_maps==scheduled_maps && content_unmaps==scheduled_maps);
    for(unsigned i=0;i<state->pool.used;i++) assert(state->pool.slot[i].valid);
  }
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
static void schedule_release_request(void)
{
  g_clear_pointer(&request,gst_v4l2_request_unref);
  gst_clear_buffer(&picture);g_clear_pointer(&bitstream,gst_memory_unref);
}
static void schedule_queue(guint32 number)
{
  schedule_release_request();
  request=new_request(number,&picture,&bitstream);
  assert(gst_v4l2_request_queue(request,0));selected_capture=last_capture;
}
static void schedule_tests(void)
{
  guint32 frames[HEVC_CONTENT_SLOTS]={31,0,2,3,4,5,6,7};
  gboolean control=!strcmp(mode,"schedule-control");
  gboolean budget=!strcmp(mode,"schedule-budget");
  guint count=budget?HEVC_CONTENT_SLOTS:3;
  if(!strcmp(mode,"schedule-invalid")) {
    guint32 duplicates[]={31,31};
    unsigned before=ioctls;
    assert(!gst_hevc_callsite_arm_frames(GST_H265_DECODER(client),TRUE,NULL,1));
    assert(!gst_hevc_callsite_arm_frames(GST_H265_DECODER(client),TRUE,frames,0));
    assert(!gst_hevc_callsite_arm_frames(GST_H265_DECODER(client),TRUE,frames,9));
    assert(!gst_hevc_callsite_arm_frames(GST_H265_DECODER(client),TRUE,duplicates,2));
    assert(!gst_hevc_callsite_arm_frames(GST_H265_DECODER(client),2,frames,3));
    assert(!client->content_callsite && !manifest_reads && ioctls==before);
    teardown();return;
  }
  if(!strcmp(mode,"schedule-reuse")) {frames[0]=4;count=1;}
  assert(gst_hevc_callsite_arm_frames(GST_H265_DECODER(client),!control,frames,count));
  assert(!gst_hevc_callsite_arm_frames(GST_H265_DECODER(client),TRUE,frames,count));
  if(!strcmp(mode,"schedule-cancel")) {
    assert(gst_hevc_callsite_finish(GST_H265_DECODER(client)));
    assert(!content_maps && !manifest_reads);teardown();return;
  }
  if(!strcmp(mode,"schedule-reader-reorder")) {
    GstV4l2Request *requests[3];GstBuffer *pictures[3];GstMemory *bits[3];
    const guint order[]={1,0,2};
    for(guint i=0;i<3;i++) {
      requests[i]=new_request(frames[i],&pictures[i],&bits[i]);
      assert(gst_v4l2_request_queue(requests[i],0));
    }
    assert(queued_count==3 && !completed_count);
    for(guint i=0;i<3;i++) {
      guint k=order[i];request=requests[k];picture=pictures[k];bitstream=bits[k];
      selected_capture=gst_v4l2_codec_memory_get_index(gst_buffer_peek_memory(picture,0));
      scheduled_maps++;assert(output(frames[k])==GST_FLOW_OK);
      assert(completed_count==3);
      check_slot(&client->content_callsite->pool,i,TRUE,selected_capture);
      const struct hevc_content_identity *id=&client->content_callsite->pool.slot[i].identity;
      assert(id->detail.gst.frame==frames[k] && id->submitted==3 && id->completed==3);
      if(i<2) assert(!gst_hevc_callsite_result(GST_H265_DECODER(client)));
      pthread_t thread;assert(!pthread_create(&thread,NULL,foreign_callsite,NULL));
      assert(!pthread_join(thread,NULL));
    }
    assert(gst_hevc_callsite_result(GST_H265_DECODER(client))->used==3);
    assert(gst_hevc_callsite_finish(GST_H265_DECODER(client)));
    request=NULL;picture=NULL;bitstream=NULL;
    for(guint i=0;i<3;i++) {
      gst_v4l2_request_unref(requests[i]);gst_buffer_unref(pictures[i]);gst_memory_unref(bits[i]);
    }
    check_cancel_state(PTHREAD_CANCEL_ENABLE);teardown();return;
  }
  if(!strcmp(mode,"schedule-reuse")) {
    /* Four real pool allocations have been published. Reuse cannot clear the
     * observer's sticky alias exclusion just because the plan wants it. */
    for(guint i=0;i<4;i++) {schedule_queue(i);assert(output(i)==GST_FLOW_OK);}
    schedule_queue(4);assert(output(4)==GST_FLOW_ERROR);
    assert(client->content_callsite->failed && !content_maps);
    assert(!gst_hevc_callsite_result(GST_H265_DECODER(client)));
  } else {
    if(!strcmp(mode,"schedule-mutable-plan")) frames[0]=999;
    /* Unselected output must execute the real framework path, without a map
     * or a manifest read. Its ordinal is not the selected writer identity. */
    schedule_queue(90);assert(output(90)==GST_FLOW_OK);
    assert(!content_maps && !manifest_reads && !gst_hevc_callsite_result(GST_H265_DECODER(client)));
    guint32 order[HEVC_CONTENT_SLOTS]={0,31,2,3,4,5,6,7};
    guint target_count=budget?HEVC_CONTENT_SLOTS:3;
    if(!strcmp(mode,"schedule-incomplete")) target_count=2;
    for(guint i=0;i<target_count;i++) {
      schedule_queue(order[i]);
      gboolean wrong=!strcmp(mode,"schedule-frame-mismatch") && i==1;
      gboolean middle=!strcmp(mode,"schedule-mid-failure") && i==1;
      gboolean unmap=!strcmp(mode,"schedule-munmap") && i==1;
      if(middle) __real_gst_hevc_observer_buffer_publish(picture);
      fail_unmap=unmap;
      if(wrong || middle || unmap) {
        assert(output(wrong?999:order[i])==GST_FLOW_ERROR);
        assert(client->content_callsite->failed);
        assert(!gst_hevc_callsite_result(GST_H265_DECODER(client)));
        if(unmap) {
          assert(content_mapping && gst_hevc_observer_busy(decoder));
          assert(client->content_callsite->held_frame && client->content_callsite->held_picture);
          assert(!gst_hevc_callsite_finish(GST_H265_DECODER(client)));
          check_cancel_state(PTHREAD_CANCEL_DISABLE);fail_unmap=FALSE;
        } else {
          assert(!content_mapping && !gst_hevc_observer_busy(decoder));
          unsigned before=content_maps;
          assert(output(order[i])==GST_FLOW_ERROR);assert(content_maps==before);
        }
        break;
      }
      scheduled_maps++;
      assert(output(order[i])==GST_FLOW_OK);
      assert(client->content_callsite->collected==i+1);
      assert(client->content_callsite->pool.used==i+1);
      check_slot(&client->content_callsite->pool,i,!control,selected_capture);
      const struct hevc_content_identity *id=&client->content_callsite->pool.slot[i].identity;
      assert(id->detail.gst.frame==order[i] && id->writer && id->detail.gst.request);
      if(i) {
        const struct hevc_content_identity *prior=&client->content_callsite->pool.slot[i-1].identity;
        assert(id->writer!=prior->writer && id->detail.gst.request!=prior->detail.gst.request);
        assert(id->session==prior->session && id->context_generation==prior->context_generation);
        assert(!memcmp(id->run,prior->run,sizeof(id->run)));
      }
      if(i+1<count) assert(!gst_hevc_callsite_result(GST_H265_DECODER(client)));
    }
    if(!strcmp(mode,"schedule-incomplete")) {
      assert(!gst_hevc_callsite_result(GST_H265_DECODER(client)));
      assert(!client->content_callsite->failed && !client->content_callsite->success);
    } else if(!client->content_callsite->failed) {
      const struct hevc_content_pool *result=gst_hevc_callsite_result(GST_H265_DECODER(client));
      assert(result && result->used==count);
      if(!strcmp(mode,"schedule-duplicate")) {
        assert(output(order[target_count-1])==GST_FLOW_ERROR);
        assert(client->content_callsite->failed && !gst_hevc_callsite_result(GST_H265_DECODER(client)));
        assert(content_maps==scheduled_maps);
      } else {
        schedule_queue(91);assert(output(91)==GST_FLOW_OK);
        assert(content_maps==scheduled_maps && result->used==count);
      }
    }
  }
  assert(gst_hevc_callsite_finish(GST_H265_DECODER(client)));
  assert(!gst_hevc_callsite_finish(GST_H265_DECODER(client)));
  check_cancel_state(PTHREAD_CANCEL_ENABLE);
  assert(!content_mapping && !gst_hevc_observer_busy(decoder));teardown();
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
  if(g_str_has_prefix(mode,"schedule-")) {
    schedule_tests();
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
