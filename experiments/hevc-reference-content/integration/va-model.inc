/* SPDX-License-Identifier: GPL-3.0-or-later */
/* Appended to the existing public API fixture, using its actual driver objects. */
static int capture_file;
static unsigned selected_capture;
static struct hevc_content_pool pool;
extern void v4l2r_content_init(struct hevc_content_pool *,bool);
extern bool v4l2r_content_snapshot(VADriverContextP,const struct v4l2r_observer_receipt *,struct hevc_content_pool *,bool);
static off_t capture_offset(unsigned index) { return (off_t)(index+1)*1048576; }
int __wrap_open(const char *name,int flags,...) {
    return name[0]=='/'?evidence_open(name):base_open(name,flags);
}
int __wrap_open64(const char *name,int flags,...) {return __wrap_open(name,flags);}
int __wrap___open_2(const char *name,int flags) {return __wrap_open(name,flags);}
int __wrap___open64_2(const char *name,int flags) {return __wrap_open(name,flags);}
int __wrap_close(int fd) {return evidence_fd(fd)?evidence_close(fd):base_close(fd);}
int __wrap_ioctl(int fd,unsigned long op,...) {
    void *arg=NULL;
    if(op!=MEDIA_REQUEST_IOC_REINIT && op!=MEDIA_REQUEST_IOC_QUEUE) {
        va_list ap;va_start(ap,op);arg=va_arg(ap,void*);va_end(ap);
    }
    int result=base_ioctl(fd,op,arg);if(result) return result;
    if(op==VIDIOC_ENUM_FMT && V4L2_TYPE_IS_OUTPUT(((struct v4l2_fmtdesc*)arg)->type))
        ((struct v4l2_fmtdesc*)arg)->pixelformat=V4L2_PIX_FMT_HEVC_SLICE;
    if(op==VIDIOC_QUERYCAP) strcpy((char*)((struct v4l2_capability*)arg)->driver,"apple-avd");
    if(op==VIDIOC_S_FMT || op==VIDIOC_G_FMT) {
        struct v4l2_format *f=arg;
        if(!V4L2_TYPE_IS_OUTPUT(f->type)) {
            f->fmt.pix_mp.width=448;f->fmt.pix_mp.height=240;
            f->fmt.pix_mp.plane_fmt[0].bytesperline=448;f->fmt.pix_mp.plane_fmt[0].sizeimage=model_length;
            fds[fd_slot(fd)].formats[0]=*f;
        }
    }
    if(op==VIDIOC_QUERYBUF) {
        struct v4l2_buffer *b=arg;
        if(!V4L2_TYPE_IS_OUTPUT(b->type)) {
            b->m.planes[0].m.mem_offset=capture_offset(b->index);
            assert(!ftruncate(capture_file,capture_offset(b->index)+model_length));
            fill_plane(capture_file,capture_offset(b->index),b->index);
        }
    }
    return result;
}
int __wrap_clock_gettime(clockid_t id,struct timespec *ts) {
    int r=base_clock_gettime(id,ts);
    if(id==CLOCK_MONOTONIC) {
        uint64_t value=(uint64_t)ts->tv_sec*1000000000+ts->tv_nsec+clock_jump;
        ts->tv_sec=value/1000000000;ts->tv_nsec=value%1000000000;
        if(content_mapping && !strcmp(mode,"slow-copy")) clock_jump+=30000000;
    }
    return r;
}
void *__wrap_mmap(void *addr,size_t length,int prot,int flags,int fd,off_t offset) {
    if(prot!=PROT_READ) return base_mmap(addr,length,prot,flags,fd,offset);
    assert(fd==model_video && offset==capture_offset(selected_capture));
    assert(length==model_length && flags==MAP_SHARED);content_maps++;
    if(!strcmp(mode,"mmap-failure")) {errno=ENOMEM;return MAP_FAILED;}
    content_mapping=__real_mmap(addr,length,prot,flags,capture_file,offset);
    assert(content_mapping!=MAP_FAILED);return content_mapping;
}
void *__wrap_mmap64(void *addr,size_t length,int prot,int flags,int fd,off_t offset) {
    return __wrap_mmap(addr,length,prot,flags,fd,offset);
}
int __wrap_munmap(void *addr,size_t length) {
    if(addr!=content_mapping) return base_munmap(addr,length);
    assert(length==model_length);content_unmaps++;
    if(fail_unmap) {errno=EIO;return -1;}
    int result=__real_munmap(addr,length);if(!result)content_mapping=NULL;return result;
}
int main(int argc,char **argv) {
    assert(argc==2);mode=argv[1];model_identify();model_peer((const void*)v4l2r_content_snapshot);
    if(!strcmp(mode,"padded")) model_length=368128;
    if(!strcmp(mode,"bad-extent")) model_length=345599;
    capture_file=memfd_create("VA-capture-allocations",MFD_CLOEXEC);assert(capture_file>=0);
    setup();observed_codec=codec;observed_codec.pixelformat=V4L2_PIX_FMT_HEVC_SLICE;
    observed_codec.end_picture=observer_codec_end;V4L2R_CONFIG(drv,cfg)->codec=&observed_codec;
    drv->decoders[0].pixelformats[0]=V4L2_PIX_FMT_HEVC_SLICE;
    cid=context();VASurfaceID first=surface();sid=surface();
    assert(picture(cid,first)==VA_STATUS_SUCCESS);reference_id=first;
    assert(picture(cid,sid)==VA_STATUS_SUCCESS);reference_id=VA_INVALID_ID;
    assert(v4l2r_observer_open(&va,cid,&session)==VA_STATUS_SUCCESS);
    assert(v4l2r_observer_select(&va,&session,sid,&target)==VA_STATUS_SUCCESS);
    struct v4l2r_context *ctx=V4L2R_CONTEXT(drv,cid);model_video=ctx->video_fd;
    v4l2r_content_init(&pool,strcmp(mode,"disabled"));begin();
    selected_capture=receipt.capture_index;assert(selected_capture==1);
    if(!strcmp(mode,"stale")) receipt.target.allocation_generation++;
    if(!strcmp(mode,"wrong-codec")) observed_codec.pixelformat=V4L2_PIX_FMT_H264;
    if(!strcmp(mode,"noncoherent")) ctx->captures[selected_capture].observer_flags=V4L2_MEMORY_FLAG_NON_COHERENT;
    if(!strcmp(mode,"expired")) clock_jump=UINT64_C(3000000000);
    if(!strcmp(mode,"foreign-run")) receipt.session.run[0]++;
    if(!strcmp(mode,"foreign-lease")) receipt.lease++;
    if(!strcmp(mode,"overflow")) receipt.plane_size[0]=UINT64_MAX;
    if(!strcmp(mode,"bad-planes")) receipt.planes=HEVC_CONTENT_PLANES+1;
    bool ended=!strcmp(mode,"no-retention");
    if(ended) end();
    fail_unmap=!strcmp(mode,"munmap-failure");
    bool ok=v4l2r_content_snapshot(&va,&receipt,&pool,true);
    if(is_refusal()) {
        assert(!ok && !pool.slot[0].valid);
        if(!strcmp(mode,"munmap-failure")) {
            assert(content_mapping && ctx->observer_content_map==content_mapping);
            assert(v4l2r_observer_end(&va,&session,receipt.lease)!=VA_STATUS_SUCCESS);
            assert(table.vaDestroyContext(&va,cid)==VA_STATUS_ERROR_OPERATION_FAILED);
            fail_unmap=false;
        } else if(strcmp(mode,"changed-proof") && strcmp(mode,"mmap-failure") && strcmp(mode,"slow-copy")) assert(content_maps==0);
    } else {
        if(!ok) diagnose_refusal(&pool);
        assert(ok);
        assert(pool.slot[0].identity.client==HEVC_CONTENT_VA &&
            pool.slot[0].identity.context_generation==session.context_generation &&
            pool.slot[0].identity.detail.va.context==session.context &&
            pool.slot[0].identity.detail.va.surface==sid &&
            pool.slot[0].identity.writer==target.writer &&
            pool.slot[0].identity.allocation_generation==target.allocation_generation);
        check_slot(&pool,0,true,selected_capture);
        assert(v4l2r_content_snapshot(&va,&receipt,&pool,false));check_slot(&pool,1,false,selected_capture);
        pthread_t thread;assert(!pthread_create(&thread,NULL,foreign,NULL));assert(!pthread_join(thread,NULL));
        for(unsigned i=2;i<HEVC_CONTENT_SLOTS;i++) assert(v4l2r_content_snapshot(&va,&receipt,&pool,true));
        assert(content_maps==8 && content_unmaps==8);
        assert(!v4l2r_content_snapshot(&va,&receipt,&pool,true));
        v4l2r_content_init(&pool,true);
        assert(!v4l2r_content_snapshot(&va,&receipt,&pool,true));assert(content_maps==8);
    }
    if(!strcmp(mode,"foreign-run")) receipt.session.run[0]--;
    if(!strcmp(mode,"foreign-lease")) receipt.lease--;
    if(!ended) end();assert(!content_mapping && !ctx->observer_content_map);
    assert(v4l2r_observer_close(&va,&session)==VA_STATUS_SUCCESS);
    teardown();assert(!__real_close(capture_file));
    for(int i=0;i<evidence_count;i++) assert(evidence_fds[i]==-1);
    printf("PASS actual VA content %s\n",mode);return 0;
}
