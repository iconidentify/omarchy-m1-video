/* SPDX-License-Identifier: LGPL-2.1-or-later */
#define _GNU_SOURCE
#include <assert.h>
#include "content.h"
#include "runtime.h"

/* Exercise the actual dl_iterate_phdr callback, including notes which are
 * described by ELF headers but not readable in the loaded image. No device. */
int main(void)
{
    unsigned char bytes[128] = {0};
    const uint32_t header[] = {4, 4, NT_GNU_BUILD_ID};
    memcpy(bytes, header, sizeof(header));
    memcpy(bytes + 12, "GNU\0", 4);
    memcpy(bytes + 16, "\x01\x23\x45\x67", 4);
    ElfW(Phdr) headers[3] = {
        {.p_type = PT_LOAD, .p_flags = PF_R, .p_vaddr = (uintptr_t)bytes, .p_memsz = sizeof(bytes)},
        {.p_type = PT_NOTE, .p_vaddr = (uintptr_t)bytes, .p_memsz = 20},
    };
    struct dl_phdr_info info = {.dlpi_phdr = headers, .dlpi_phnum = 2};
    struct hevc_content_self self = {.address = bytes + 64};
    assert(hevc_content_image(&info, sizeof(info), &self) == 1);
    assert(!strcmp(self.id, "01234567"));

    /* A later unreadable note must also invalidate an earlier valid ID. */
    void *guard = mmap(NULL, 4096, PROT_NONE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    assert(guard != MAP_FAILED);
    headers[2] = (ElfW(Phdr)){.p_type = PT_NOTE, .p_vaddr = (uintptr_t)guard, .p_memsz = 20};
    info.dlpi_phnum = 3;
    self.id[0] = 0;
    assert(hevc_content_image(&info, sizeof(info), &self) == 1 && !self.id[0]);
    assert(munmap(guard, 4096) == 0);
    info.dlpi_phnum = 2;

    /* Start in a load segment, but extend beyond its readable range. */
    headers[0].p_memsz = 19;
    self.address = bytes;
    assert(hevc_content_image(&info, sizeof(info), &self) == 1 && !self.id[0]);
    headers[0].p_memsz = sizeof(bytes);
    headers[0].p_flags = 0;
    assert(hevc_content_image(&info, sizeof(info), &self) == 1 && !self.id[0]);
    headers[0].p_flags = PF_R;

    /* Addition overflow, and an oversized note, must fail before dereference. */
    info.dlpi_addr = 1;
    headers[0].p_vaddr = (uintptr_t)bytes - 1;
    headers[1].p_vaddr = UINTPTR_MAX;
    assert(hevc_content_image(&info, sizeof(info), &self) == 1 && !self.id[0]);
    info.dlpi_addr = 0;
    headers[0].p_vaddr = (uintptr_t)bytes;
    headers[1].p_vaddr = (uintptr_t)bytes;
    headers[1].p_memsz = 65537;
    assert(hevc_content_image(&info, sizeof(info), &self) == 1 && !self.id[0]);

    /* Parser rejects truncation and duplicate IDs rather than using a prefix. */
    char id[129] = {0};
    assert(!hevc_content_note(bytes, 19, id));
    memcpy(bytes + 20, bytes, 20);
    assert(!hevc_content_note(bytes, 40, id));
    headers[1].p_memsz = 20;
    headers[2] = headers[1];
    info.dlpi_phnum = 3;
    assert(hevc_content_image(&info, sizeof(info), &self) == 1 && !self.id[0]);

    /* The real executable still has an admitted, mapped GNU build ID. */
    hevc_content_identify(&self, (const void *)main);
    assert(self.id[0]);
    puts("PASS runtime build-ID mapped-range and note regressions");
    return 0;
}
