/* SPDX-License-Identifier: LGPL-2.1-or-later */
/* Exercise the pinned fast utility path on every build host, including ARM
 * where GStreamer's normal configuration selects its bytewise implementation. */
#include <gst/gstconfig.h>
#undef GST_HAVE_UNALIGNED_ACCESS
#define GST_HAVE_UNALIGNED_ACCESS 1
#include <gst/gst.h>
#include <assert.h>
#include <stdio.h>

int main (void)
{
  guint8 bytes[32];
  const guint64 value = G_GUINT64_CONSTANT (0xfedcba9876543210);
  for (guint offset = 1; offset <= 8; offset++) {
    guint8 *p = bytes + offset;
    GST_WRITE_UINT16_BE (p, (guint16) value);
    assert (p[0] == 0x32 && p[1] == 0x10);
    assert (GST_READ_UINT16_BE (p) == (guint16) value);
    GST_WRITE_UINT16_LE (p, (guint16) value);
    assert (p[0] == 0x10 && p[1] == 0x32);
    assert (GST_READ_UINT16_LE (p) == (guint16) value);
    GST_WRITE_UINT32_BE (p, (guint32) value);
    assert (p[0] == 0x76 && p[3] == 0x10);
    assert (GST_READ_UINT32_BE (p) == (guint32) value);
    GST_WRITE_UINT32_LE (p, (guint32) value);
    assert (p[0] == 0x10 && p[3] == 0x76);
    assert (GST_READ_UINT32_LE (p) == (guint32) value);
    GST_WRITE_UINT64_BE (p, value);
    assert (p[0] == 0xfe && p[7] == 0x10);
    assert (GST_READ_UINT64_BE (p) == value);
    GST_WRITE_UINT64_LE (p, value);
    assert (p[0] == 0x10 && p[7] == 0xfe);
    assert (GST_READ_UINT64_LE (p) == value);
  }
  puts ("PASS pinned fast unaligned IO: 16/32/64-bit, both byte orders, offsets 1..8");
  return 0;
}
