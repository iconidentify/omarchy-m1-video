/* SPDX-License-Identifier: LGPL-2.1-or-later */
#ifndef HEVC_CONTENT_RUNTIME_H
#define HEVC_CONTENT_RUNTIME_H
#include <elf.h>
#include <fcntl.h>
#include <link.h>
#include <linux/videodev2.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/ioctl.h>
#include <sys/stat.h>
#include <sys/sysmacros.h>
#include <unistd.h>

#define HEVC_CONTENT_MANIFEST "/etc/apple-avd-observer/approved-builds"
#define HEVC_CONTENT_KERNEL "94fb23346d522edf53722357c426a3e58030beea"
#define HEVC_CONTENT_PATCHES "029f57377a00f3584678f80a8011d8ba7a17c83f1708d9a429d3c91dbb2d0390"

/* Only used before begin by the pool constructor. No dynamic-loader operation
 * is permitted during a native lease (loader/API lock inversion). */
struct hevc_content_self { const void *address; char id[129]; };
static inline bool hevc_content_note(const unsigned char *data, size_t size, char id[129])
{
    bool found = false;
    for (size_t offset = 0; offset < size;) {
        if (size - offset < 12) return false;
        uint32_t n[3]; memcpy(n, data + offset, sizeof(n)); offset += 12;
        if (n[0] > size - offset || n[0] > UINT32_MAX - 3 || n[1] > UINT32_MAX - 3) return false;
        size_t names = ((size_t)n[0] + 3) & ~(size_t)3;
        size_t desc = ((size_t)n[1] + 3) & ~(size_t)3;
        if (names > size - offset || desc > size - offset - names) return false;
        if (n[2] == NT_GNU_BUILD_ID && n[0] == 4 && !memcmp(data + offset, "GNU\0", 4)) {
            if (found || !n[1] || n[1] > 64) return false;
            for (unsigned i = 0; i < n[1]; i++) {
                unsigned byte = data[offset + names + i];
                id[i * 2] = "0123456789abcdef"[byte >> 4];
                id[i * 2 + 1] = "0123456789abcdef"[byte & 15];
            }
            id[n[1] * 2] = 0; found = true;
        }
        offset += names + desc;
    }
    return found;
}

static int hevc_content_image(struct dl_phdr_info *info, size_t size, void *opaque)
{
    (void)size;
    struct hevc_content_self *self = opaque;
    uintptr_t address = (uintptr_t)self->address;
    bool owner = false;
    for (unsigned i = 0; i < info->dlpi_phnum; i++) {
        const ElfW(Phdr) *p = &info->dlpi_phdr[i];
        if (p->p_vaddr > UINTPTR_MAX - info->dlpi_addr) continue;
        uintptr_t start = info->dlpi_addr + p->p_vaddr;
        if (p->p_type == PT_LOAD && address >= start && address - start < p->p_memsz) owner = true;
    }
    if (!owner) return 0;
    for (unsigned i = 0; i < info->dlpi_phnum; i++) {
        const ElfW(Phdr) *p = &info->dlpi_phdr[i];
        if (p->p_type == PT_NOTE && p->p_memsz) {
            /* PT_NOTE describes metadata; the loader need not map it. Only
             * dereference notes wholly inside a readable PT_LOAD segment. */
            if (p->p_vaddr > UINTPTR_MAX - info->dlpi_addr || p->p_memsz > 65536) {
                self->id[0] = 0; return 1;
            }
            uintptr_t start = info->dlpi_addr + p->p_vaddr;
            bool readable = false;
            for (unsigned j = 0; j < info->dlpi_phnum; j++) {
                const ElfW(Phdr) *load = &info->dlpi_phdr[j];
                if (load->p_type != PT_LOAD || !(load->p_flags & PF_R) ||
                    load->p_vaddr > UINTPTR_MAX - info->dlpi_addr) continue;
                uintptr_t mapped = info->dlpi_addr + load->p_vaddr;
                if (start >= mapped && start - mapped < load->p_memsz &&
                    p->p_memsz <= load->p_memsz - (start - mapped) &&
                    p->p_memsz <= UINTPTR_MAX - start) readable = true;
            }
            if (!readable) { self->id[0] = 0; return 1; }
            char id[129] = {0};
            if (hevc_content_note((const unsigned char *)start, p->p_memsz, id)) {
                if (self->id[0]) { self->id[0] = 0; return 1; }
                memcpy(self->id, id, sizeof(id));
            }
        }
    }
    return 1;
}

static inline void hevc_content_identify(struct hevc_content_self *self, const void *address)
{
    memset(self, 0, sizeof(*self)); self->address = address;
    dl_iterate_phdr(hevc_content_image, self);
}

static inline bool hevc_content_read(const char *path, unsigned char *data, size_t capacity,
                                     size_t *size, bool manifest)
{
    int fd = open(path, O_RDONLY | O_CLOEXEC | O_NOFOLLOW | O_NONBLOCK);
    if (fd < 0) return false;
    struct stat st;
    bool ok = fstat(fd, &st) == 0 && S_ISREG(st.st_mode);
    if (manifest) ok = ok && st.st_uid == 0 && !(st.st_mode & 022);
    size_t used = 0;
    while (ok && used < capacity) {
        ssize_t n = read(fd, data + used, capacity - used);
        if (n < 0) { ok = false; break; }
        if (!n) break;
        used += (size_t)n;
    }
    unsigned char extra;
    if (ok && used == capacity && read(fd, &extra, 1) != 0) ok = false;
    if (close(fd)) ok = false;
    *size = used; return ok;
}

static inline bool hevc_content_build_id(const char *path, const char *expected)
{
    unsigned char data[65536]; size_t size = 0; char actual[129] = {0};
    return hevc_content_read(path, data, sizeof(data), &size, false) &&
        hevc_content_note(data, size, actual) && !strcmp(actual, expected);
}

/* Explicit administrator-approved deployment evidence, not a --coherent flag
 * or arbitrary caller-selected JSON. No manifest is installed by this project.
 * Root owns the containing /etc directory and this non-symlink regular file. */
static inline bool hevc_content_runtime(int video_fd, enum hevc_content_client client,
                                       const struct hevc_content_self *self,
                                       struct hevc_content_provenance *proof)
{
    static const char *keys[] = {"kernel_source", "avd_patchset", "kernel", "apple_avd",
        "videobuf2_common", "videobuf2_v4l2", "videobuf2_dma_contig", "va", "gst"};
    char values[9][129] = {{0}};
    unsigned char manifest[4096]; size_t size = 0;
    struct stat directory;
    if (lstat("/etc/apple-avd-observer", &directory) || !S_ISDIR(directory.st_mode) ||
        directory.st_uid != 0 || (directory.st_mode & 022)) return false;
    if (!self || !self->id[0] ||
        !hevc_content_read(HEVC_CONTENT_MANIFEST, manifest, sizeof(manifest) - 1, &size, true)) return false;
    manifest[size] = 0;
    if (memchr(manifest, 0, size)) return false;
    char *cursor = (char *)manifest;
    while (*cursor) {
        char *end = strchr(cursor, '\n'); if (!end) return false; *end = 0;
        char *space = strchr(cursor, ' '); if (!space) return false; *space++ = 0;
        unsigned key;
        for (key = 0; key < 9 && strcmp(cursor, keys[key]); key++);
        size_t length = strlen(space);
        if (key == 9 || values[key][0] || !length || length > 128) return false;
        for (size_t i = 0; i < length; i++)
            if (!((space[i] >= '0' && space[i] <= '9') || (space[i] >= 'a' && space[i] <= 'f')) &&
                strcmp(space, "builtin")) return false;
        memcpy(values[key], space, length + 1); cursor = end + 1;
    }
    for (unsigned key = 0; key < 9; key++) if (!values[key][0]) return false;
    if (strcmp(values[0], HEVC_CONTENT_KERNEL) || strcmp(values[1], HEVC_CONTENT_PATCHES) ||
        (client != HEVC_CONTENT_VA && client != HEVC_CONTENT_GST) ||
        strcmp(values[client == HEVC_CONTENT_VA ? 7 : 8], self->id)) return false;
    struct stat device;
    if (fstat(video_fd, &device) || !S_ISCHR(device.st_mode)) return false;
    char path[256], target[256];
    snprintf(path, sizeof(path), "/sys/dev/char/%u:%u/device/driver/module",
             major(device.st_rdev), minor(device.st_rdev));
    ssize_t n = readlink(path, target, sizeof(target) - 1);
    if (n <= 0 || n >= (ssize_t)sizeof(target) - 1) return false;
    target[n] = 0;
    const char *base = strrchr(target, '/');
    if (!base || strcmp(base + 1, "apple_avd")) return false;
    struct v4l2_capability cap = {0};
    /* QUERYCAP reports the platform driver name, not its module filename. */
    if (ioctl(video_fd, VIDIOC_QUERYCAP, &cap) ||
        memcmp(cap.driver, "avd\0", sizeof("avd"))) return false;
    if (!hevc_content_build_id("/sys/kernel/notes", values[2])) return false;
    for (unsigned i = 3; i <= 6; i++) {
        /* Built-in status needs separate reviewed evidence; missing notes are
         * also possible for loadable modules. This first experiment refuses it. */
        if (!strcmp(values[i], "builtin")) return false;
        snprintf(path, sizeof(path), "/sys/module/%s/notes/.note.gnu.build-id", keys[i]);
        if (!hevc_content_build_id(path, values[i])) return false;
    }
    if (!proof) return false;
    memset(proof, 0, sizeof(*proof));
    proof->device_major = major(device.st_rdev); proof->device_minor = minor(device.st_rdev);
    memcpy(proof->builds, values, sizeof(values));
    return true;
}
#endif
