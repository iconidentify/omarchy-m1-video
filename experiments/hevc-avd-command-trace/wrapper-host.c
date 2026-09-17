/* SPDX-License-Identifier: GPL-2.0-only */
/* Exact wrapper functions run with pthread mutexes and bounded host seq stubs.
 * This checks synchronization/lifetime contracts, not Linux IRQ behavior. */
#define _GNU_SOURCE
#include <assert.h>
#include <errno.h>
#include <limits.h>
#include <pthread.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/types.h>
#include <stdatomic.h>
#include "v4l2-controls.h"
typedef uint8_t u8;typedef uint16_t u16;typedef uint32_t u32;
typedef unsigned long long u64;
#define __user
#define GFP_KERNEL 0
#define DEFINE_MUTEX(name) pthread_mutex_t name=PTHREAD_MUTEX_INITIALIZER
#define DEFINE_SPINLOCK(name) DEFINE_MUTEX(name)
#define mutex_lock(lock) assert(!pthread_mutex_lock(lock))
#define mutex_unlock(lock) assert(!pthread_mutex_unlock(lock))
#define spin_lock_irqsave(lock,flags) do {(flags)=0;mutex_lock(lock);}while(0)
#define spin_unlock_irqrestore(lock,flags) do {(void)(flags);mutex_unlock(lock);}while(0)
static size_t live_bytes,peak_bytes,alloc_calls;
static int alloc_fail,seq_fail;
static void *kvzalloc(size_t size,int unused) {
 (void)unused;alloc_calls++;
 if(alloc_fail)return NULL;
 size_t *p=calloc(1,sizeof(size_t)+size);assert(p);*p=size;
 live_bytes+=size;if(live_bytes>peak_bytes)peak_bytes=live_bytes;return p+1;
}
static void kvfree(void *ptr) {if(ptr){size_t *p=(size_t*)ptr-1;assert(live_bytes>=*p);live_bytes-=*p;free(p);}}
static int copy_from_user(void *to,const void *from,size_t n){memcpy(to,from,n);return 0;}
static int kstrtoull(const char *s,int base,unsigned long long *out) {
 char *end;errno=0;*out=strtoull(s,&end,base);return errno || *end || end==s ? -EINVAL:0;
}
struct inode {int unused;};struct file {void *private_data;};
struct seq_file {void *private;char line[32768];size_t used;};
struct seq_operations {
 void *(*start)(struct seq_file*,loff_t*);void *(*next)(struct seq_file*,void*,loff_t*);
 void (*stop)(struct seq_file*,void*);int (*show)(struct seq_file*,void*);
};
static int seq_open(struct file *f,const struct seq_operations *ops) {
 (void)ops;if(seq_fail)return -ENOMEM;f->private_data=calloc(1,sizeof(struct seq_file));assert(f->private_data);return 0;
}
static int seq_release(struct inode *i,struct file *f){(void)i;free(f->private_data);f->private_data=NULL;return 0;}
static void seq_printf(struct seq_file *s,const char *fmt,...) {
 va_list ap;va_start(ap,fmt);int n=vsnprintf(s->line+s->used,sizeof(s->line)-s->used,fmt,ap);va_end(ap);
 assert(n>=0 && (size_t)n<sizeof(s->line)-s->used);s->used+=n;
}
static void seq_putc(struct seq_file *s,int c){assert(s->used+1<sizeof(s->line));s->line[s->used++]=c;s->line[s->used]=0;}
#define V4L2_PIX_FMT_HEVC_SLICE 123
struct desc {unsigned fourcc;};struct variant {unsigned revision,quirks;};struct dev {struct variant *variant;};
struct avd_ctx {u64 trace_context,trace_pid;struct desc *coded_fmt_desc;struct dev *dev;unsigned decomp;
 struct {struct {struct {struct {unsigned bytesperline;}plane_fmt[1];}pix_mp;}fmt;}decoded_fmt;
 struct {unsigned num;struct {unsigned num,instructions[512];}segments[2];}job;
};
struct avd_decoded_buffer {struct {struct {struct {unsigned index;}vb2_buf;}vb;}base;};
static inline u32 avd_cmdtrace_last_word(struct avd_ctx *c){return c->job.segments[c->job.num].instructions[c->job.segments[c->job.num].num-1];}
#include "wrapper-functions.h"
static int write_op(const char *text){loff_t pos=0;return control_write(NULL,text,strlen(text),&pos);}
static void fill_sealed(void) {
#ifdef TEST_COMMAND
 capture->phase=CMD_SEALED;
 capture->pictures=capture->completions=300;
 for(unsigned i=0;i<CMD_WINDOW;i++) {
  capture->window[i].nwords=CMD_WORDS;
  for(unsigned j=0;j<CMD_WORDS;j++) {capture->window[i].sites[j]=32;capture->window[i].words[j]=UINT32_MAX;}
  memset(capture->window[i].controls,255,CMD_CONTROL);
 }
#else
 capture->phase=ATR_SEALED;capture->count=ATR_CAPACITY;
 for(unsigned i=0;i<ATR_CAPACITY;i++)for(unsigned j=0;j<ATR_VALUES;j++)capture->records[i].v[j]=UINT64_MAX;
#endif
}
static void *racer(void *unused) {
 (void)unused;
 for(unsigned i=0;i<1000;i++) {assert(write_op("off")==-EBUSY);assert(write_op("arm 3 123")==-EBUSY);}
 return NULL;
}
#ifdef TEST_COMMAND
static struct avd_ctx ctx;
static void *complete_jobs(void *unused) {
 (void)unused;for(unsigned i=0;i<1000;i++)avd_cmdtrace_done(&ctx,1);return NULL;
}
#endif
int main(void) {
 assert(write_op("")==-EINVAL);assert(write_op("arm 0 1")==-EINVAL);
 alloc_fail=1;assert(write_op("arm 1 123")==-ENOMEM);assert(!capture && live_bytes==0);alloc_fail=0;
 assert(write_op("arm 1 123")>0);size_t initial_calls=alloc_calls;
 assert(write_op("arm 2 123")==-EBUSY);assert(alloc_calls==initial_calls);
 struct file reader={0},other={0};struct inode inode={0};
 assert(snapshot_open(&inode,&reader)==-EBUSY);
 fill_sealed();seq_fail=1;assert(snapshot_open(&inode,&reader)==-ENOMEM);assert(!snapshot_busy);seq_fail=0;
 assert(snapshot_open(&inode,&reader)==0);void *pinned=capture;
 assert(snapshot_open(&inode,&other)==-EBUSY);
 pthread_t thread;assert(!pthread_create(&thread,NULL,racer,NULL));
 struct seq_file *seq=reader.private_data;loff_t pos=0;unsigned count=0;size_t maximum=0;
 for(void *v=snapshot_seq_start(seq,&pos);v;v=snapshot_seq_next(seq,v,&pos)) {
  seq->used=0;assert(!snapshot_seq_show(seq,v));if(seq->used>maximum)maximum=seq->used;
  assert(seq->private==pinned);count++;
 }
 assert(count==snapshot_rows(pinned));assert(!pthread_join(thread,NULL));
 assert(alloc_calls==initial_calls);assert(!snapshot_release(&inode,&reader));
 assert(write_op("off")>0);assert(live_bytes==0);assert(write_op("arm 1 123")==-EBUSY);
 assert(write_op("arm 2 123")>0);
#ifdef TEST_COMMAND
 struct desc desc={.fourcc=999};struct variant variant={.revision=3};struct dev dev={.variant=&variant};
 ctx=(struct avd_ctx){.trace_context=8,.trace_pid=123,.coded_fmt_desc=&desc,.dev=&dev};
 /* job.codec is zero at this point, so only the negotiated fourcc is valid. */
 avd_cmdtrace_open(&ctx);avd_cmdtrace_job(&ctx);assert(capture->errors&CMD_FOREIGN);
 avd_cmdtrace_close(&ctx);assert(write_op("off")>0);assert(write_op("arm 3 123")>0);
 desc.fourcc=V4L2_PIX_FMT_HEVC_SLICE;avd_cmdtrace_open(&ctx);avd_cmdtrace_job(&ctx);assert(capture->phase==CMD_ACTIVE);
 assert(!pthread_create(&thread,NULL,complete_jobs,NULL));
 for(unsigned i=0;i<1000;i++)assert(write_op("off")==-EBUSY);
 assert(!pthread_join(thread,NULL));avd_cmdtrace_close(&ctx);assert(write_op("seal 3")>0);
 assert(capture->errors & CMD_ORDER);assert(snapshot_open(&inode,&reader)==0);assert(!snapshot_release(&inode,&reader));
#endif
 assert(write_op("off")>0);assert(!live_bytes);
#ifdef TEST_COMMAND
 struct v4l2_ctrl_hevc_sps sps={0};struct v4l2_ctrl_hevc_pps pps={0};
 struct v4l2_ctrl_hevc_scaling_matrix sc={0};struct v4l2_ctrl_hevc_decode_params dec={0};
 struct v4l2_ctrl_hevc_slice_params sl={.slice_type=2};struct avd_decoded_buffer dst={0};
 struct avd_ctx before=ctx;size_t calls=alloc_calls;
 avd_cmdtrace_start(&ctx,&sps,&pps,&sc,&dec,&sl,1,1,&dst);
 avd_cmdtrace_word(&ctx,20);avd_cmdtrace_inactive(&ctx,27);avd_cmdtrace_slice_meta(&ctx,1,0,0,0);avd_cmdtrace_done(&ctx,1);
 assert(!memcmp(&before,&ctx,sizeof ctx) && alloc_calls==calls && !capture);
 assert(write_op("arm 4 123")>0);avd_cmdtrace_open(&ctx);avd_cmdtrace_job(&ctx);
 calls=alloc_calls;ctx.job.segments[0].num=1;ctx.job.segments[0].instructions[0]=0x2d906800;
 for(unsigned i=1;i<=300;i++) {
  dec.pic_order_cnt_val=sl.slice_pic_order_cnt=i;
  avd_cmdtrace_start(&ctx,&sps,&pps,&sc,&dec,&sl,1,1,&dst);
  avd_cmdtrace_word(&ctx,20);avd_cmdtrace_inactive(&ctx,27);avd_cmdtrace_slice_meta(&ctx,0x10001,4097,8192,512);
  avd_cmdtrace_done(&ctx,1);
 }
 assert(alloc_calls==calls && !capture->errors);
 assert(capture->window[0].poc==24 && capture->window[0].nbytes==1392);
 assert(capture->window[0].words[0]==0x2d906800 && capture->window[0].slice_coded==4609);
 assert(write_op("seal 4")==-EBUSY);avd_cmdtrace_close(&ctx);assert(write_op("seal 4")>0);
 assert(snapshot_open(&inode,&reader)==0);assert(!snapshot_release(&inode,&reader));assert(write_op("off")>0);
#endif
 assert(peak_bytes<=CAPTURE_BYTES);printf("PASS: exact wrapper pin/free, allocation failure, reader contention and completion/off overlap; peak=%zu max_row=%zu\n",peak_bytes,maximum);
 return 0;
}
