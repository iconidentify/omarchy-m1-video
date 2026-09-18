/* SPDX-License-Identifier: LGPL-2.1-or-later */
/* Test-only fake evidence. Never compiled into the configured plugin/driver. */
#include "content.h"
#include "runtime.h"
#include <assert.h>
static const char *mode;
static unsigned model_length = 345600, content_maps, content_unmaps, manifest_reads;
static int evidence_fds[128], evidence_count, model_video;
static void *content_mapping;
static bool fail_unmap;
static uint64_t clock_jump;
static char model_self_id[129], model_peer_id[129];
static unsigned model_stats, model_directories, model_links;
static int last_stat_fd;
static unsigned last_stat_mode;
static char last_evidence[256];
int __real_fstat(int, struct stat *);
int __real_close(int);
int __real_clock_gettime(clockid_t, struct timespec *);
void *__real_mmap(void *,size_t,int,int,int,off_t);
int __real_munmap(void *,size_t);
static bool evidence_fd(int fd) {
    for (int i=0;i<evidence_count;i++) if(evidence_fds[i]==fd) return true;
    return false;
}
static int evidence_open(const char *name) {
    snprintf(last_evidence,sizeof(last_evidence),"%s",name);
    unsigned char bytes[4096]; size_t length=0;
    if(!strcmp(name,HEVC_CONTENT_MANIFEST)) {
        manifest_reads++;
        if(!strcmp(mode,"missing-manifest")) {errno=ENOENT;return -1;}
        const char *kernel=!strcmp(mode,"bad-kernel") ? "bb" : "aa";
        const char *vb2=!strcmp(mode,"bad-vb2") ? "bb" : !strcmp(mode,"builtin") ? "builtin" : "aa";
        const char *avd=!strcmp(mode,"bad-avd") ? "bb" : "aa";
        const char *self=!strcmp(mode,"bad-client") ? "bb" : model_self_id;
        if(!strcmp(mode,"changed-proof") && manifest_reads>1) kernel="bb";
        length=snprintf((char*)bytes,sizeof(bytes),
            "kernel_source %s\navd_patchset %s\nkernel %s\napple_avd %s\nvideobuf2_common %s\nvideobuf2_v4l2 aa\nvideobuf2_dma_contig aa\nva %s\ngst %s\n",
            HEVC_CONTENT_KERNEL,HEVC_CONTENT_PATCHES,kernel,avd,vb2,self,self);
    } else {
        assert(!strcmp(name,"/sys/kernel/notes") ||
            !strcmp(name,"/sys/module/apple_avd/notes/.note.gnu.build-id") ||
            !strcmp(name,"/sys/module/videobuf2_common/notes/.note.gnu.build-id") ||
            !strcmp(name,"/sys/module/videobuf2_v4l2/notes/.note.gnu.build-id") ||
            !strcmp(name,"/sys/module/videobuf2_dma_contig/notes/.note.gnu.build-id"));
        const unsigned char note[]={4,0,0,0,1,0,0,0,3,0,0,0,'G','N','U',0,0xaa,0,0,0};
        memcpy(bytes,note,sizeof(note)); length=sizeof(note);
    }
    int fd=memfd_create("synthetic-runtime-evidence",MFD_CLOEXEC);
    assert(fd>=0 && write(fd,bytes,length)==(ssize_t)length && lseek(fd,0,SEEK_SET)==0);
    assert(evidence_count<128);evidence_fds[evidence_count++]=fd;return fd;
}
__attribute__((visibility("default"))) int __wrap_fstat(int fd,struct stat *st) {
    model_stats++;last_stat_fd=fd;last_stat_mode=0;
    if(fd==model_video) {memset(st,0,sizeof(*st));st->st_mode=S_IFCHR|0600;st->st_rdev=makedev(81,0);last_stat_mode=st->st_mode;return 0;}
    int result=__real_fstat(fd,st);
    if(!result && evidence_fd(fd)) {st->st_uid=!strcmp(mode,"untrusted-owner")?1000:0;st->st_mode=S_IFREG|(!strcmp(mode,"writable-manifest")?0666:0600);}
    if(!result)last_stat_mode=st->st_mode;
    return result;
}
__attribute__((visibility("default"))) int __wrap_lstat(const char *name,struct stat *st) {
    model_directories++;
    assert(!strcmp(name,"/etc/apple-avd-observer"));
    memset(st,0,sizeof(*st));st->st_mode=S_IFDIR|0755;st->st_uid=!strcmp(mode,"untrusted-directory")?1000:0;return 0;
}
__attribute__((visibility("default"))) ssize_t __wrap_readlink(const char *name,char *data,size_t length) {
    model_links++;
    assert(!strcmp(name,"/sys/dev/char/81:0/device/driver/module"));
    const char *target=!strcmp(mode,"wrong-device")?"../../../unrelated":"../../../apple_avd";
    assert(strlen(target)<length);memcpy(data,target,strlen(target));return strlen(target);
}
static int evidence_close(int fd) {
    for(int i=0;i<evidence_count;i++) if(evidence_fds[i]==fd) {evidence_fds[i]=-1;return __real_close(fd);}
    abort();
}
static void model_identify(void) {
    struct hevc_content_self self;
    hevc_content_identify(&self,(const void*)model_identify);assert(self.id[0]);strcpy(model_self_id,self.id);
}
static void fill_plane(int fd,off_t offset,unsigned index) {
    unsigned char *data=malloc(model_length);assert(data);
    memset(data,0x11,model_length);
    memset(data+HEVC_CONTENT_COMP_START,0x40+index,HEVC_CONTENT_COMP_BYTES);
    memset(data+model_length-HEVC_CONTENT_MV_BYTES,0x90+index,HEVC_CONTENT_MV_BYTES);
    assert(pwrite(fd,data,model_length,offset)==model_length);free(data);
}
static void check_slot(struct hevc_content_pool *pool,unsigned index,bool copy,unsigned capture) {
    assert(pool->slot[index].valid && pool->slot[index].copied==copy);
    assert(pool->slot[index].before_ns && pool->slot[index].after_ns>=pool->slot[index].before_ns);
    assert(pool->slot[index].identity.capture_index==capture);
    assert(pool->slot[index].provenance.device_major==81);
    for(unsigned n=0;n<HEVC_CONTENT_BYTES;n++)
        assert(pool->slot[index].bytes[n]==(copy?(n<HEVC_CONTENT_COMP_BYTES?0x40+capture:0x90+capture):0));
}
static bool is_refusal(void) {
    const char *cases[]={"missing-manifest","bad-kernel","bad-vb2","bad-avd","bad-client","builtin",
        "untrusted-owner","untrusted-directory","writable-manifest","wrong-device",
        "changed-proof","disabled","stale","foreign-run","foreign-lease","overflow","bad-planes","bad-extent","no-retention","mmap-failure","munmap-failure","slow-copy","expired","wrong-codec","noncoherent"};
    for(unsigned i=0;i<sizeof(cases)/sizeof(*cases);i++) if(!strcmp(mode,cases[i])) return true;
    return false;
}

__attribute__((visibility("default"))) int __wrap_fstat64(int fd,struct stat *st) {return __wrap_fstat(fd,st);}
__attribute__((visibility("default"))) int __wrap_lstat64(const char *name,struct stat *st) {return __wrap_lstat(name,st);}

static void model_peer(const void *address) {
    struct hevc_content_self self;hevc_content_identify(&self,address);strcpy(model_peer_id,self.id);
}
static void diagnose_refusal(const struct hevc_content_pool *p) {
    fprintf(stderr,"unexpected copy refusal: stopped=%u used=%u maps=%u unmaps=%u manifests=%u stats=%u dirs=%u links=%u last=%s self=%s peer=%s errno=%d stat_fd=%d video_fd=%d stat_mode=%o\n",
        p->stopped,p->used,content_maps,content_unmaps,manifest_reads,model_stats,model_directories,model_links,
        last_evidence[0]?last_evidence:"none",model_self_id,model_peer_id,errno,last_stat_fd,model_video,last_stat_mode);
}

/* Fortified glibc can route a known-size buffer through this entry point. */
__attribute__((visibility("default"))) ssize_t __wrap___readlink_chk(const char *name,char *data,size_t length,size_t capacity) {
    assert(length<=capacity);return __wrap_readlink(name,data,length);
}
