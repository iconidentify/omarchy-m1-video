/* SPDX-License-Identifier: LGPL-2.1-or-later */
static struct hevc_content_pool pool;
static unsigned selected_capture;
extern void gst_hevc_content_init(struct hevc_content_pool *,gboolean);
extern gboolean gst_hevc_content_snapshot(GstV4l2Decoder *,const GstHevcObserverReceipt *,struct hevc_content_pool *,gboolean);
__attribute__((visibility("default"))) int __wrap_open(const char *name,int flags,...) {
    return name[0]=='/'?evidence_open(name):base_open(name,flags);
}
__attribute__((visibility("default"))) int __wrap_open64(const char *name,int flags,...) {return __wrap_open(name,flags);}
__attribute__((visibility("default"))) int __wrap_close(int fd) {return evidence_fd(fd)?evidence_close(fd):base_close(fd);}
__attribute__((visibility("default"))) int __wrap_ioctl(int fd,unsigned long op,...) {
    void *arg=NULL;
    if(op!=MEDIA_REQUEST_IOC_REINIT && op!=MEDIA_REQUEST_IOC_QUEUE) {
        va_list ap;va_start(ap,op);arg=va_arg(ap,void*);va_end(ap);
    }
    int result=base_ioctl(fd,op,arg);if(result) return result;
    if(op==VIDIOC_QUERYCAP) {strcpy((char*)((struct v4l2_capability*)arg)->driver,"apple-avd");model_video=fd;}
    if(op==VIDIOC_CREATE_BUFS) {
        struct v4l2_create_buffers *b=arg;
        if(b->count && !V4L2_TYPE_IS_OUTPUT(b->format.type)) fill_plane(capture_base[b->index],0,b->index);
    }
    return result;
}
__attribute__((visibility("default"))) int __wrap_clock_gettime(clockid_t id,struct timespec *ts) {
    int r=base_clock_gettime(id,ts);
    if(id==CLOCK_MONOTONIC) {
        uint64_t value=(uint64_t)ts->tv_sec*1000000000+ts->tv_nsec+clock_jump;
        ts->tv_sec=value/1000000000;ts->tv_nsec=value%1000000000;
        if(content_mapping && !strcmp(mode,"slow-copy")) clock_jump+=30000000;
    }
    return r;
}
__attribute__((visibility("default"))) void *__wrap_mmap(void *addr,size_t length,int prot,int flags,int fd,off_t offset) {
    assert(prot==PROT_READ && flags==MAP_SHARED && offset==0 && length==model_length);
    struct stat actual,expected;
    assert(!__real_fstat(fd,&actual) && !__real_fstat(capture_base[selected_capture],&expected));
    assert(actual.st_ino==expected.st_ino && actual.st_dev==expected.st_dev);content_maps++;
    if(!strcmp(mode,"mmap-failure")) {errno=ENOMEM;return MAP_FAILED;}
    content_mapping=__real_mmap(addr,length,prot,flags,fd,offset);
    assert(content_mapping!=MAP_FAILED);return content_mapping;
}
__attribute__((visibility("default"))) void *__wrap_mmap64(void *addr,size_t length,int prot,int flags,int fd,off_t offset) {
    return __wrap_mmap(addr,length,prot,flags,fd,offset);
}
__attribute__((visibility("default"))) int __wrap_munmap(void *addr,size_t length) {
    assert(addr==content_mapping && length==model_length);content_unmaps++;
    if(fail_unmap) {errno=EIO;return -1;}
    int result=__real_munmap(addr,length);if(!result)content_mapping=NULL;return result;
}
int main(int argc,char **argv) {
    assert(argc==2);mode=argv[1];model_identify();model_peer((const void*)gst_hevc_content_snapshot);if(!strcmp(mode,"padded"))model_length=368128;
    if(!strcmp(mode,"bad-extent")) model_length=345599;
    g_setenv("GST_PLUGIN_SYSTEM_PATH_1_0","",TRUE);g_setenv("GST_PLUGIN_PATH_1_0","",TRUE);gst_init(NULL,NULL);
    GST_DEBUG_CATEGORY_INIT(gstv4l2codecs_debug,"v4l2codecs",0,"model plugin log");
    GST_DEBUG_CATEGORY_INIT(v4l2_h265dec_debug,"v4l2codecs-h265dec",0,"model client log");
    start();selected_capture=last_capture;
    gst_hevc_content_init(&pool,strcmp(mode,"disabled"));
    assert(gst_hevc_observer_begin(decoder,&session,request,&target,0,&receipt));
    assert(receipt.capture_index==selected_capture);
    if(!strcmp(mode,"stale"))receipt.target.allocation++;
    if(!strcmp(mode,"expired"))clock_jump=UINT64_C(3000000000);
    if(!strcmp(mode,"foreign-run")) receipt.session.run[0]++;
    if(!strcmp(mode,"foreign-lease")) receipt.lease++;
    if(!strcmp(mode,"overflow")) receipt.plane_size[0]=UINT64_MAX;
    if(!strcmp(mode,"bad-planes")) receipt.planes=HEVC_CONTENT_PLANES+1;
    bool ended=!strcmp(mode,"no-retention");
    if(ended) end();
    fail_unmap=!strcmp(mode,"munmap-failure");
    gboolean ok=gst_hevc_content_snapshot(decoder,&receipt,&pool,TRUE);
    if(is_refusal()) {
        assert(!ok && !pool.slot[0].valid);
        if(!strcmp(mode,"munmap-failure")) {
            assert(content_mapping);
            assert(!gst_hevc_observer_end(decoder,&session,receipt.lease));
            assert(!gst_v4l2_decoder_close(decoder));fail_unmap=false;
        } else if(strcmp(mode,"changed-proof") && strcmp(mode,"mmap-failure") && strcmp(mode,"slow-copy")) assert(content_maps==0);
    } else {
        if(!ok) diagnose_refusal(&pool);
        assert(ok);
        assert(pool.slot[0].identity.client==HEVC_CONTENT_GST &&
            pool.slot[0].identity.context_generation==session.context &&
            pool.slot[0].identity.detail.gst.request==target.request &&
            pool.slot[0].identity.detail.gst.frame==receipt.frame_num &&
            pool.slot[0].identity.writer==target.writer &&
            pool.slot[0].identity.allocation_generation==target.allocation);
        check_slot(&pool,0,true,selected_capture);
        assert(gst_hevc_content_snapshot(decoder,&receipt,&pool,FALSE));check_slot(&pool,1,false,selected_capture);
        pthread_t thread;assert(!pthread_create(&thread,NULL,foreign,NULL));assert(!pthread_join(thread,NULL));
        for(unsigned i=2;i<HEVC_CONTENT_SLOTS;i++)assert(gst_hevc_content_snapshot(decoder,&receipt,&pool,TRUE));
        assert(content_maps==8 && content_unmaps==8);
        assert(!gst_hevc_content_snapshot(decoder,&receipt,&pool,TRUE));
        gst_hevc_content_init(&pool,TRUE);
        assert(!gst_hevc_content_snapshot(decoder,&receipt,&pool,TRUE));assert(content_maps==8);
    }
    if(!strcmp(mode,"foreign-run")) receipt.session.run[0]--;
    if(!strcmp(mode,"foreign-lease")) receipt.lease--;
    if(!ended) end();assert(!content_mapping);assert(gst_hevc_observer_close(decoder,&session));teardown();
    for(int i=0;i<evidence_count;i++)assert(evidence_fds[i]==-1);
    if(!strcmp(mode,"copy")) printf("model device-link calls=%u fortified=%u\n",model_links,model_fortified_links);
    printf("PASS actual Gst content %s\n",mode);return 0;
}
