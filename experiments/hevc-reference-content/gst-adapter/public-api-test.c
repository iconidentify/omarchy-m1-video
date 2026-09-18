/* SPDX-License-Identifier: LGPL-2.1-or-later */
/* Actual complete HEVC client and decoder/allocator/pool code. The fixture
 * provides synthetic device properties and fake V4L2 syscalls, never /dev. */
#define _GNU_SOURCE
#include <assert.h>
#include <errno.h>
#include <fcntl.h>
#include <poll.h>
#include <pthread.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdatomic.h>
#include <sys/mman.h>
#include <time.h>
#include <unistd.h>
#include "gstv4l2codech265dec.c"
#include "linux/media.h"

/* plugin.c owns this logging category in the module; the fixture does not
 * register plugins or enumerate real devices. */
GST_DEBUG_CATEGORY_EXTERN (gstv4l2codecs_debug);
#define LIMIT 1024
struct model_fd { int fd, kind, output, capture; guint32 frame; gboolean ready; };
static struct model_fd model[LIMIT];
static unsigned nfd, output_count, capture_count, queued_count, completed_count, ioctls;
static int output_base[32], capture_base[32], last_capture;
static unsigned ready_requests[32], nr_ready;
static unsigned long fail_ioctl;
static gboolean fail_decode, bad_index, poll_blocked, poll_eintr, fast_clock;
static unsigned polls, fail_poll_nth;
static guint64 fake_now;
static GstClockTime last_poll_timeout;
static _Atomic gboolean producer_block, producer_entered, producer_release, owner_ready, owner_release;
static GstV4l2CodecH265Dec *client;
static GstV4l2Decoder *decoder;
static GstV4l2Request *request;
static GstBuffer *picture;
static GstMemory *bitstream;
static GstHevcObserverSession session;
static GstHevcObserverTarget target;
static GstHevcObserverReceipt receipt;

int __real_close (int fd);
int __real_clock_gettime (clockid_t id, struct timespec *ts);
static unsigned slot (int fd)
{
  for (unsigned i = 0; i < nfd; i++) if (model[i].fd == fd) return i;
  assert(!"unknown fake device fd"); return 0;
}
static int model_new_fd (int kind)
{
  assert(nfd < LIMIT);
  int original = memfd_create ("gst-observer-model", MFD_CLOEXEC);
  assert(original >= 0 && !ftruncate(original, 262144));
  int fd = fcntl(original, F_DUPFD_CLOEXEC, 100 + nfd);
  assert(fd >= 0); assert(!__real_close(original));
  model[nfd++] = (struct model_fd){.fd=fd, .kind=kind, .output=-1, .capture=-1};
  return fd;
}
__attribute__((visibility("default"))) int __wrap_open (const char *name, int flags, ...)
{
  (void)flags;
  assert(!strcmp(name, "observer-video") || !strcmp(name, "observer-media"));
  return model_new_fd (!strcmp(name,"observer-video") ? 1 : 2);
}
__attribute__((visibility("default"))) int __wrap_open64 (const char *name, int flags, ...)
{
  return __wrap_open(name,flags);
}
__attribute__((visibility("default"))) int __wrap_close (int fd)
{
  (void)slot(fd);
  return __real_close(fd);
}
__attribute__((visibility("default"))) int __wrap_clock_gettime (clockid_t id, struct timespec *ts)
{
  if (!fast_clock || id != CLOCK_MONOTONIC) return __real_clock_gettime(id,ts);
  fake_now += GST_MSECOND;
  ts->tv_sec=fake_now/GST_SECOND; ts->tv_nsec=fake_now%GST_SECOND; return 0;
}
static void fill_format(struct v4l2_format *fmt)
{
  if (V4L2_TYPE_IS_MULTIPLANAR(fmt->type)) {
    fmt->fmt.pix_mp.width=64; fmt->fmt.pix_mp.height=64;
    if (!fmt->fmt.pix_mp.pixelformat) fmt->fmt.pix_mp.pixelformat=V4L2_PIX_FMT_NV12;
    fmt->fmt.pix_mp.num_planes=1;
    fmt->fmt.pix_mp.plane_fmt[0].bytesperline=64;
    fmt->fmt.pix_mp.plane_fmt[0].sizeimage=6144;
  } else abort();
}
__attribute__((visibility("default"))) int __wrap_ioctl (int fd, unsigned long operation, ...)
{
  unsigned i=slot(fd); ioctls++;
  va_list ap; va_start(ap,operation); void *arg=va_arg(ap,void*); va_end(ap);
  if (operation==fail_ioctl) { errno=EIO; return -1; }
  if (operation==VIDIOC_QUERYCAP) {
    struct v4l2_capability *c=arg; memset(c,0,sizeof(*c));
    c->capabilities=V4L2_CAP_VIDEO_M2M_MPLANE; c->version=(6<<16)|(12<<8);return 0;
  }
  if (operation==VIDIOC_CREATE_BUFS) {
    struct v4l2_create_buffers *b=arg;
    b->capabilities=V4L2_BUF_CAP_SUPPORTS_REMOVE_BUFS|V4L2_BUF_CAP_SUPPORTS_M2M_HOLD_CAPTURE_BUF;
    if (!b->count) return 0;
    assert(b->count==1);
    gboolean sink=V4L2_TYPE_IS_OUTPUT(b->format.type);
    unsigned *count=sink?&output_count:&capture_count;
    int *base=sink?output_base:capture_base;
    unsigned index=0;while(index<32 && base[index]) index++;
    assert(index<32);b->index=index;*count=MAX(*count,index+1);base[index]=model_new_fd(4);
    return 0;
  }
  if (operation==VIDIOC_REMOVE_BUFS) {
    struct v4l2_remove_buffers *b=arg;
    int *base=V4L2_TYPE_IS_OUTPUT(b->type)?output_base:capture_base;
    for (unsigned n=b->index;n<b->index+b->count;n++) {
      if(base[n]) {assert(!__real_close(base[n]));base[n]=0;}
    }
    return 0;
  }
  if (operation==VIDIOC_REQBUFS) {
    struct v4l2_requestbuffers *b=arg; assert(!b->count);return 0;
  }
  if (operation==VIDIOC_G_FMT || operation==VIDIOC_S_FMT) {fill_format(arg);return 0;}
  if (operation==VIDIOC_QUERYBUF) {
    struct v4l2_buffer *b=arg; assert(b->length>=1);b->length=1;b->m.planes[0].length=6144;return 0;
  }
  if (operation==VIDIOC_EXPBUF) {
    struct v4l2_exportbuffer *b=arg;
    int base=(V4L2_TYPE_IS_OUTPUT(b->type)?output_base:capture_base)[b->index];assert(base);
    b->fd=fcntl(base,F_DUPFD_CLOEXEC,100+nfd); assert(b->fd>=0);
    model[nfd++]=(struct model_fd){.fd=b->fd,.kind=4};return 0;
  }
  if (operation==MEDIA_IOC_REQUEST_ALLOC) {*(int*)arg=model_new_fd(3);return 0;}
  if (operation==MEDIA_REQUEST_IOC_REINIT) {model[i].ready=FALSE;return 0;}
  if (operation==VIDIOC_QBUF) {
    struct v4l2_buffer *b=arg;
    if(V4L2_TYPE_IS_OUTPUT(b->type)) {
      unsigned r=slot(b->request_fd);model[r].output=b->index;
      model[r].frame=b->timestamp.tv_sec*1000000+b->timestamp.tv_usec;
    } else last_capture=b->index;
    return 0;
  }
  if(operation==MEDIA_REQUEST_IOC_QUEUE) {
    if(atomic_load(&producer_block)) {
      atomic_store(&producer_entered,TRUE);
      while(!atomic_load(&producer_release)) sched_yield();
    }
    assert(nr_ready<32);model[i].capture=last_capture;model[i].ready=TRUE;
    ready_requests[nr_ready++]=i;queued_count++;return 0;
  }
  if(operation==VIDIOC_DQBUF) {
    struct v4l2_buffer *b=arg;
    if(!nr_ready) {errno=EAGAIN;return -1;}
    struct model_fd *r=&model[ready_requests[0]];
    if(V4L2_TYPE_IS_OUTPUT(b->type)) {b->index=r->output;return 0;}
    b->index=r->capture + (bad_index ? 1 : 0);b->timestamp.tv_sec=r->frame/1000000;b->timestamp.tv_usec=r->frame%1000000;
    if(fail_decode) b->flags|=V4L2_BUF_FLAG_ERROR;
    memmove(ready_requests,ready_requests+1,--nr_ready*sizeof(ready_requests[0]));
    completed_count++;return 0;
  }
  if(operation==VIDIOC_STREAMON) return 0;
  if(operation==VIDIOC_STREAMOFF) {nr_ready=0;return 0;}
  if(operation==VIDIOC_S_EXT_CTRLS || operation==VIDIOC_S_CTRL) return 0;
  fprintf(stderr,"unmodelled ioctl %lx\n",operation);abort();
}
__attribute__((visibility("default"))) gint __wrap_gst_poll_wait (GstPoll *poll, GstClockTime timeout)
{
  (void)poll;last_poll_timeout=timeout;
  if (++polls == fail_poll_nth) return 0;
  if(poll_eintr) {errno=EINTR;return -1;}
  if(poll_blocked) return 0;
  return nr_ready?1:0;
}
static void setup(void)
{
  static GstV4l2CodecDevice device;
  device.name="observer-model";device.function=MEDIA_ENT_F_PROC_VIDEO_DECODER;
  device.video_device_path="observer-video";device.media_device_path="observer-media";
  device.src_caps=gst_caps_from_string("video/x-raw,format=NV12,width=64,height=64");
  GTypeInfo type={.class_size=sizeof(GstV4l2CodecH265DecClass),
    .class_init=(GClassInitFunc)gst_v4l2_codec_h265_dec_class_init,.class_data=&device,
    .instance_size=sizeof(GstV4l2CodecH265Dec),.instance_init=(GInstanceInitFunc)gst_v4l2_codec_h265_dec_init};
  GType tid=g_type_register_static(GST_TYPE_H265_DECODER,"ObserverModelH265",&type,0);
  client=g_object_new(tid,NULL);gst_object_ref_sink(client);decoder=client->decoder;
  assert(gst_v4l2_decoder_open(decoder));
  assert(gst_v4l2_decoder_set_sink_fmt(decoder,V4L2_PIX_FMT_HEVC_SLICE,64,64,8));
  gst_v4l2_decoder_set_render_delay(decoder,16);
  client->sink_allocator=gst_v4l2_codec_allocator_new(decoder,GST_PAD_SINK,4);
  client->src_allocator=gst_v4l2_codec_allocator_new(decoder,GST_PAD_SRC,4);
  assert(client->sink_allocator && client->src_allocator);
  GstVideoInfoDmaDrm info;gst_video_info_dma_drm_init(&info);
  assert(gst_video_info_set_format(&info.vinfo,GST_VIDEO_FORMAT_NV12,64,64));
  client->src_pool=gst_v4l2_codec_pool_new(client->src_allocator,&info);
  assert(gst_v4l2_decoder_streamon(decoder,GST_PAD_SINK));
  assert(gst_v4l2_decoder_streamon(decoder,GST_PAD_SRC));client->streaming=TRUE;
  gst_caps_unref(device.src_caps);
}
static GstV4l2Request *new_request(guint32 frame,GstBuffer **out_picture,GstMemory **out_bits)
{
  GstBuffer *p=NULL;GstMemory *b=gst_v4l2_codec_allocator_alloc(client->sink_allocator);assert(b);
  GstBufferPoolAcquireParams params={.flags=GST_BUFFER_POOL_ACQUIRE_FLAG_DONTWAIT};
  assert(gst_buffer_pool_acquire_buffer(GST_BUFFER_POOL(client->src_pool),&p,&params)==GST_FLOW_OK);
  GstV4l2Request *r=gst_v4l2_decoder_alloc_request(decoder,frame,b,p);assert(r);
  *out_picture=p;*out_bits=b;return r;
}
static void begin(void)
{
  assert(gst_hevc_observer_begin(decoder,&session,request,&target,0,&receipt));
  assert(receipt.lease && receipt.completed==receipt.submitted);
  assert(receipt.target.writer==target.writer && receipt.target.allocation==target.allocation);
  assert(receipt.planes==1 && receipt.plane_size[0]==6144);
}
static void end(void)
{
  assert(gst_hevc_observer_end(decoder,&session,receipt.lease));
}
static void start(void)
{
  setup();assert(gst_hevc_observer_open(decoder,&session));
  request=new_request(31,&picture,&bitstream);assert(gst_v4l2_request_queue(request,0));
  assert(gst_hevc_observer_select(decoder,&session,request,&target));
}
static void teardown(void)
{
  if(request) {gst_v4l2_request_unref(request);request=NULL;}
  gst_clear_buffer(&picture);g_clear_pointer(&bitstream,gst_memory_unref);
  assert(gst_v4l2_decoder_streamoff(decoder,GST_PAD_SINK));
  assert(gst_v4l2_decoder_streamoff(decoder,GST_PAD_SRC));
  g_clear_object(&client->src_pool);
  gst_v4l2_codec_h265_dec_reset_allocation(client);
  assert(gst_v4l2_decoder_close(decoder));gst_object_unref(client);
  for(unsigned i=0;i<nfd;i++) {errno=0;assert(fcntl(model[i].fd,F_GETFD)<0 && errno==EBADF);}
}
static void *foreign(void *unused)
{
  (void)unused;
  for(unsigned i=0;i<20;i++) {
    assert(!gst_hevc_observer_end(decoder,&session,receipt.lease));
    assert(!gst_v4l2_request_queue(request,0));
    assert(!gst_v4l2_decoder_flush(decoder));
    assert(!gst_v4l2_decoder_close(decoder));
    assert(!gst_v4l2_decoder_streamoff(decoder,GST_PAD_SRC));
    assert(gst_v4l2_decoder_remove_buffers(decoder,GST_PAD_SRC,receipt.capture_index,1)<0);
    gst_v4l2_codec_allocator_detach(client->src_allocator);
    assert(!gst_v4l2_decoder_alloc_request(decoder,32,bitstream,picture));
    assert(!gst_v4l2_codec_h265_dec_stop(GST_VIDEO_DECODER(client)));
    assert(!gst_v4l2_codec_h265_dec_flush(GST_VIDEO_DECODER(client)));
    GstMapInfo map;
    assert(!gst_memory_map(gst_buffer_peek_memory(picture,0),&map,GST_MAP_READ));
  }
  return NULL;
}
static void lifecycle(void)
{
  start();begin();unsigned count=ioctls;
  assert(!gst_hevc_observer_close(decoder,&session));
  assert(!gst_hevc_observer_end(decoder,&session,receipt.lease+1));
  guint64 lease=receipt.lease;
  assert(!gst_hevc_observer_begin(decoder,&session,request,&target,0,&receipt));
  assert(receipt.lease==lease);
  pthread_t thread;assert(!pthread_create(&thread,NULL,foreign,NULL));assert(!pthread_join(thread,NULL));
  assert(ioctls==count && client->streaming);end();
  assert(!gst_hevc_observer_end(decoder,&session,lease));begin();
  assert(receipt.lease!=lease && !gst_hevc_observer_end(decoder,&session,lease));end();
  GstV4l2Request *old=request;
  gst_v4l2_request_unref(request);request=NULL;
  gst_clear_buffer(&picture);g_clear_pointer(&bitstream,gst_memory_unref);
  request=new_request(32,&picture,&bitstream);assert(request==old);
  assert(gst_v4l2_request_queue(request,0));
  assert(!gst_hevc_observer_begin(decoder,&session,request,&target,0,&receipt));
  assert(gst_hevc_observer_select(decoder,&session,request,&target));begin();end();
  assert(gst_hevc_observer_close(decoder,&session));
  GstHevcObserverSession stale=session;assert(gst_hevc_observer_open(decoder,&session));
  assert(session.nonce!=stale.nonce);
  assert(!gst_hevc_observer_end(decoder,&stale,receipt.lease));
  teardown();
}
static void readers(void)
{
  start();
  GstBuffer *pic2;GstMemory *bit2;
  GstV4l2Request *r2=new_request(32,&pic2,&bit2);assert(gst_v4l2_request_queue(r2,0));
  assert(queued_count==2 && !completed_count);begin();assert(completed_count==2);
  gst_v4l2_request_unref(r2);gst_buffer_unref(pic2);gst_memory_unref(bit2);
  end();teardown();
}
static void *producer(void *arg)
{
  assert(gst_v4l2_request_queue(arg,0));return NULL;
}
static void contention(void)
{
  start();GstBuffer *p;GstMemory *b;GstV4l2Request *r=new_request(32,&p,&b);
  atomic_store(&producer_block,TRUE);pthread_t t;assert(!pthread_create(&t,NULL,producer,r));
  while(!atomic_load(&producer_entered)) sched_yield();
  guint64 now=gst_hevc_observer_now();
  assert(!gst_hevc_observer_begin(decoder,&session,request,&target,now+10*GST_MSECOND,&receipt));
  assert(gst_hevc_observer_now()-now<GST_SECOND/2);
  atomic_store(&producer_release,TRUE);assert(!pthread_join(t,NULL));begin();end();
  gst_v4l2_request_unref(r);gst_buffer_unref(p);gst_memory_unref(b);teardown();
}
static void *cancel_owner(void *unused)
{
  (void)unused;assert(gst_hevc_observer_open(decoder,&session));
  assert(gst_hevc_observer_select(decoder,&session,request,&target));begin();
  atomic_store(&owner_ready,TRUE);while(!atomic_load(&owner_release)) sched_yield();
  end();pthread_testcancel();return NULL;
}
static void cancellation(void)
{
  setup();request=new_request(31,&picture,&bitstream);assert(gst_v4l2_request_queue(request,0));
  pthread_t t;assert(!pthread_create(&t,NULL,cancel_owner,NULL));
  while(!atomic_load(&owner_ready)) sched_yield();assert(!pthread_cancel(t));
  assert(!gst_v4l2_decoder_close(decoder));atomic_store(&owner_release,TRUE);
  void *result;assert(!pthread_join(t,&result));assert(result==PTHREAD_CANCELED);teardown();
}
static void retention(void)
{
  start();begin();GstV4l2Request *old=request;
  unsigned before=ioctls;
  gst_v4l2_request_unref(request);request=NULL;
  assert(ioctls==before); /* real final-unref/REINIT must not run before end */
  gst_clear_buffer(&picture);g_clear_pointer(&bitstream,gst_memory_unref);
  assert(ioctls==before);end();assert(ioctls==before+1);
  request=new_request(32,&picture,&bitstream);assert(request==old);
  assert(gst_v4l2_request_queue(request,0));
  assert(gst_hevc_observer_select(decoder,&session,request,&target));begin();end();teardown();
}
static void recycling(void)
{
  setup();assert(gst_hevc_observer_open(decoder,&session));
  guint64 allocations[4]={0},last_writer=0,last_request=0;
  for(unsigned i=0;i<12;i++) {
    request=new_request(31+i,&picture,&bitstream);assert(gst_v4l2_request_queue(request,0));
    assert(gst_hevc_observer_select(decoder,&session,request,&target));begin();
    assert(receipt.capture_index<4);
    if(allocations[receipt.capture_index]) assert(allocations[receipt.capture_index]==target.allocation);
    else allocations[receipt.capture_index]=target.allocation;
    for(unsigned j=0;j<4;j++)
      if(j!=receipt.capture_index && allocations[j]) assert(allocations[j]!=target.allocation);
    assert(target.writer!=last_writer && target.request!=last_request);
    last_writer=target.writer;last_request=target.request;end();
    gst_v4l2_request_unref(request);request=NULL;
    gst_clear_buffer(&picture);g_clear_pointer(&bitstream,gst_memory_unref);
  }
  for(unsigned i=0;i<4;i++) assert(allocations[i]);teardown();
}
static void unqueued(void)
{
  start();GstBuffer *p;GstMemory *b;GstV4l2Request *r=new_request(32,&p,&b);
  assert(!gst_hevc_observer_begin(decoder,&session,request,&target,0,&receipt));
  gst_v4l2_request_unref(r);gst_buffer_unref(p);gst_memory_unref(b);
  begin();end();teardown();
}
static void default_off(void)
{
  setup();
  for(unsigned i=0;i<8;i++) {
    request=new_request(31+i,&picture,&bitstream);assert(gst_v4l2_request_queue(request,0));
    assert(!gst_hevc_observer_begin(decoder,&session,request,&target,0,&receipt));
    assert(gst_v4l2_request_set_done(request)>0 && !gst_v4l2_request_failed(request));
    gst_v4l2_request_unref(request);request=NULL;
    gst_clear_buffer(&picture);g_clear_pointer(&bitstream,gst_memory_unref);
  }
  assert(queued_count==8 && completed_count==8);teardown();
}
static void queue_error(void)
{
  setup();assert(gst_hevc_observer_open(decoder,&session));
  request=new_request(31,&picture,&bitstream);fail_ioctl=MEDIA_REQUEST_IOC_QUEUE;
  assert(!gst_v4l2_request_queue(request,0));fail_ioctl=0;
  assert(!gst_hevc_observer_select(decoder,&session,request,&target));
  assert(!gst_hevc_observer_begin(decoder,&session,request,&target,0,&receipt));teardown();
}
static void partial(void)
{
  start();GstBuffer *p;GstMemory *b;GstV4l2Request *r=new_request(32,&p,&b);
  unsigned before=ioctls;
  assert(!gst_v4l2_request_queue(r,V4L2_BUF_FLAG_M2M_HOLD_CAPTURE_BUF));assert(ioctls==before);
  assert(!gst_hevc_observer_begin(decoder,&session,request,&target,0,&receipt));
  gst_v4l2_request_unref(r);gst_buffer_unref(p);gst_memory_unref(b);begin();end();teardown();
}
static char trace_record[512];
static void trace_sink(GstDebugCategory *cat,GstDebugLevel level,const gchar *file,
    const gchar *function,gint line,GObject *object,GstDebugMessage *message,gpointer data)
{
  (void)cat;(void)level;(void)file;(void)function;(void)line;(void)object;(void)data;
  const char *text=gst_debug_message_get(message);
  if(g_str_has_prefix(text,"observer-queue ")) g_strlcpy(trace_record,text,sizeof(trace_record));
}
static void trace_join(void)
{
  gst_debug_add_log_function(trace_sink,NULL,NULL);
  gst_debug_set_threshold_for_name("v4l2codecs-decoder",GST_LEVEL_TRACE);
  start();begin();char expected[512];
  g_snprintf(expected,sizeof(expected),"observer-queue run=%016" G_GINT64_MODIFIER "x%016"
      G_GINT64_MODIFIER "x context=%" G_GUINT64_FORMAT " allocation=%" G_GUINT64_FORMAT
      " request=%" G_GUINT64_FORMAT " writer=%" G_GUINT64_FORMAT " frame=%u capture=%u",
      receipt.session.run[0],receipt.session.run[1],receipt.session.context,target.allocation,
      target.request,target.writer,receipt.frame_num,receipt.capture_index);
  assert(!strcmp(trace_record,expected));end();teardown();gst_debug_remove_log_function(trace_sink);
}
static void deadline_poll(void)
{
  start();fast_clock=TRUE;guint64 now=gst_hevc_observer_now();
  assert(gst_hevc_observer_begin(decoder,&session,request,&target,now+20*GST_MSECOND,&receipt));
  assert(last_poll_timeout>0 && last_poll_timeout<20*GST_MSECOND);
  end();fast_clock=FALSE;teardown();
}
static void late_timeout(void)
{
  start();GstBuffer *p;GstMemory *b;GstV4l2Request *r=new_request(32,&p,&b);
  assert(gst_v4l2_request_queue(r,0));fail_poll_nth=2;
  assert(!gst_hevc_observer_begin(decoder,&session,request,&target,0,&receipt));
  assert(completed_count==1 && !gst_hevc_observer_busy(decoder));
  unsigned before=ioctls;gst_v4l2_request_unref(request);request=NULL;
  assert(ioctls==before+1); /* failed begin released the selected request pin */
  gst_v4l2_request_unref(r);gst_buffer_unref(p);gst_memory_unref(b);teardown();
}
static void gates(void)
{
  start();begin();assert(!gst_v4l2_decoder_flush(decoder));end();teardown();
}
static void output_publication(void)
{
  start();
  /* Framework input fixture, not a decoded bitstream. The actual H265 output
   * callback owns/releases a real GstH265Picture, GstBuffer and request. */
  GstH265Picture *pic=gst_h265_picture_new();
  gst_h265_picture_set_user_data(pic,gst_v4l2_request_ref(request),(GDestroyNotify)gst_v4l2_request_unref);
  GstVideoCodecFrame *frame=g_new0(GstVideoCodecFrame,1);
  frame->ref_count=1;frame->system_frame_number=31;
  frame->pts=frame->dts=frame->duration=GST_CLOCK_TIME_NONE;
  frame->input_buffer=gst_buffer_new();frame->output_buffer=gst_buffer_ref(picture);
  GST_VIDEO_CODEC_FRAME_SET_DECODE_ONLY(frame);
  assert(gst_v4l2_codec_h265_dec_output_picture(GST_H265_DECODER(client),frame,pic)==GST_FLOW_OK);
  assert(!gst_hevc_observer_begin(decoder,&session,request,&target,0,&receipt));teardown();
}
static void identities(void)
{
  start();GstHevcObserverSession bad=session;
  bad.run[0]^=1;
  assert(!gst_hevc_observer_begin(decoder,&bad,request,&target,0,&receipt));
  bad=session;bad.context++;
  assert(!gst_hevc_observer_begin(decoder,&bad,request,&target,0,&receipt));
  GstHevcObserverTarget wrong=target;wrong.allocation++;
  assert(!gst_hevc_observer_begin(decoder,&session,request,&wrong,0,&receipt));
  wrong=target;wrong.writer++;
  assert(!gst_hevc_observer_begin(decoder,&session,request,&wrong,0,&receipt));
  GstV4l2Decoder *other=g_object_new(GST_TYPE_V4L2_DECODER,NULL);
  assert(!gst_hevc_observer_select(other,&session,request,&wrong));
  gst_object_unref(other);begin();end();teardown();
}
static void unsupported(void)
{
  setup();assert(gst_hevc_observer_open(decoder,&session));
  bitstream=gst_v4l2_codec_allocator_alloc(client->sink_allocator);assert(bitstream);
  picture=gst_buffer_new();request=gst_v4l2_decoder_alloc_request(decoder,31,bitstream,picture);
  assert(request);unsigned before=ioctls;
  assert(!gst_v4l2_request_queue(request,0));assert(ioctls==before);
  gst_v4l2_request_unref(request);request=NULL;
  gst_clear_buffer(&picture);g_clear_pointer(&bitstream,gst_memory_unref);
  request=new_request(32,&picture,&bitstream);
  assert(gst_v4l2_request_queue(request,0));
  assert(gst_hevc_observer_select(decoder,&session,request,&target));begin();end();teardown();
}
static void sticky_publication(void)
{
  start();begin();guint index=receipt.capture_index;end();
  gst_hevc_observer_buffer_publish(picture);
  gst_v4l2_request_unref(request);request=NULL;
  gst_clear_buffer(&picture);g_clear_pointer(&bitstream,gst_memory_unref);
  gboolean reused=FALSE;
  for(unsigned i=0;i<4;i++) {
    request=new_request(32+i,&picture,&bitstream);assert(gst_v4l2_request_queue(request,0));
    guint current=gst_v4l2_codec_memory_get_index(gst_buffer_peek_memory(picture,0));
    if(current==index) {reused=TRUE;assert(!gst_hevc_observer_select(decoder,&session,request,&target));}
    else {assert(gst_hevc_observer_select(decoder,&session,request,&target));begin();end();}
    assert(gst_v4l2_request_set_done(request)>0);
    gst_v4l2_request_unref(request);request=NULL;
    gst_clear_buffer(&picture);g_clear_pointer(&bitstream,gst_memory_unref);
  }
  assert(reused);teardown();
}
static void retirement(void)
{
  start();begin();end();assert(gst_v4l2_decoder_flush(decoder));
  assert(!gst_hevc_observer_begin(decoder,&session,request,&target,0,&receipt));
  assert(gst_hevc_observer_close(decoder,&session));
  assert(!gst_hevc_observer_open(decoder,&session));teardown();
}
static void shared_memory(void)
{
  start();begin();GstMemory *mem=gst_buffer_peek_memory(picture,0);
  assert(!gst_memory_share(mem,0,-1));end();
  GstMemory *alias=gst_memory_share(mem,0,-1);assert(alias);
  gst_memory_unref(alias); /* closed aliases still invalidate observation */
  assert(!gst_hevc_observer_begin(decoder,&session,request,&target,0,&receipt));teardown();
}
static void failures(const char *name)
{
  start();
  if(!strcmp(name,"timeout")) poll_blocked=TRUE;
  else if(!strcmp(name,"eintr")) {poll_eintr=TRUE;fast_clock=TRUE;}
  else if(!strcmp(name,"decode-error")) fail_decode=TRUE;
  else if(!strcmp(name,"wrong-index")) bad_index=TRUE;
  else if(!strcmp(name,"export")) {
    int fds[GST_VIDEO_MAX_PLANES];gsize sizes[GST_VIDEO_MAX_PLANES], offsets[GST_VIDEO_MAX_PLANES];guint n;
    assert(gst_v4l2_decoder_export_buffer(decoder,GST_PAD_SRC,0,fds,sizes,offsets,&n));
    for(guint i=0;i<n;i++) assert(!__real_close(fds[i]));
  }
  else if(!strcmp(name,"published")) gst_hevc_observer_buffer_publish(picture);
  else if(!strcmp(name,"mapped")) {
    GstMapInfo map;assert(gst_memory_map(gst_buffer_peek_memory(picture,0),&map,GST_MAP_READ));
    gst_memory_unmap(gst_buffer_peek_memory(picture,0),&map);
  } else if(!strcmp(name,"raw-fd")) assert(gst_v4l2_request_get_fd(request)>=0);
  else if(!strcmp(name,"expired")) {
    assert(!gst_hevc_observer_begin(decoder,&session,request,&target,1,&receipt));begin();end();teardown();return;
  } else abort();
  assert(!gst_hevc_observer_begin(decoder,&session,request,&target,0,&receipt));
  assert(!gst_hevc_observer_busy(decoder));
  poll_blocked=poll_eintr=fast_clock=fail_decode=FALSE;teardown();
}
int main(int argc,char **argv)
{
  assert(argc==2);g_setenv("GST_PLUGIN_SYSTEM_PATH_1_0","",TRUE);g_setenv("GST_PLUGIN_PATH_1_0","",TRUE);
  gst_init(NULL,NULL);
  GST_DEBUG_CATEGORY_INIT(gstv4l2codecs_debug,"v4l2codecs",0,"model plugin log");
  GST_DEBUG_CATEGORY_INIT(v4l2_h265dec_debug,"v4l2codecs-h265dec",0,"model client log");
  if(!strcmp(argv[1],"lifecycle")) lifecycle();
  else if(!strcmp(argv[1],"readers")) readers();
  else if(!strcmp(argv[1],"contention")) contention();
  else if(!strcmp(argv[1],"cancellation")) cancellation();
  else if(!strcmp(argv[1],"retention")) retention();
  else if(!strcmp(argv[1],"recycling")) recycling();
  else if(!strcmp(argv[1],"unqueued")) unqueued();
  else if(!strcmp(argv[1],"default-off")) default_off();
  else if(!strcmp(argv[1],"queue-error")) queue_error();
  else if(!strcmp(argv[1],"partial")) partial();
  else if(!strcmp(argv[1],"trace-join")) trace_join();
  else if(!strcmp(argv[1],"deadline-poll")) deadline_poll();
  else if(!strcmp(argv[1],"late-timeout")) late_timeout();
  else if(!strcmp(argv[1],"gates")) gates();
  else if(!strcmp(argv[1],"output-publication")) output_publication();
  else if(!strcmp(argv[1],"identities")) identities();
  else if(!strcmp(argv[1],"unsupported")) unsupported();
  else if(!strcmp(argv[1],"sticky-publication")) sticky_publication();
  else if(!strcmp(argv[1],"retirement")) retirement();
  else if(!strcmp(argv[1],"shared-memory")) shared_memory();
  else failures(argv[1]);
  printf("PASS actual Gst observer %s (fake V4L2, no device)\n",argv[1]);return 0;
}
