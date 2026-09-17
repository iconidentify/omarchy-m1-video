// SPDX-License-Identifier: GPL-2.0-only
/* Experimental, default-off metadata recorder. No decoder behavior changes. */
#include <linux/debugfs.h>
#include <linux/seq_file.h>
#include <linux/slab.h>
#include <linux/uaccess.h>
#include <linux/sched.h>
#include <media/videobuf2-dma-contig.h>
#include "avd.h"
#include "avd-trace.h"

static DEFINE_MUTEX(atr_control_lock);
static DEFINE_SPINLOCK(atr_lock);
static struct atr_capture *capture;
static struct dentry *atr_dir;
static u64 open_contexts, next_context, next_allocation, last_run;
static bool snapshot_busy;

/* Under atr_lock. Records contain scalars only, never retained buffer pointers. */
static bool selected(struct avd_ctx *ctx)
{
	return capture && atr_selected(capture, ctx->trace_context);
}
static bool detail(struct avd_ctx *ctx)
{
	return selected(ctx) && capture->pictures >= ATR_FIRST &&
		capture->pictures <= ATR_LAST;
}

/* 18 values: buffer, timestamp, copied, intra, writer, completed, allocation,
 * plane length, compressed start/size/offsets[4], MV size/offset, bounds, memory.
 * Allocation is the vb2 buf_init lifetime, including DMABUF plane replacement.
 */
static void buffer_values(struct avd_ctx *ctx, struct avd_decoded_buffer *buf,
			  unsigned long long *v)
{
	struct vb2_buffer *vb = &buf->base.vb.vb2_buf;
	u64 len = vb->planes[0].length;
	u64 mv = (u64)DIV_ROUND_UP(fmt_width(ctx), 64) *
		 DIV_ROUND_UP(fmt_height(ctx), 64) * 256;
	u64 end = (u64)buf->comp.start_offset + buf->comp.size;
	bool bounds = len >= mv && end <= len - mv;
	unsigned int i;

	v[0] = vb->index;
	v[1] = vb->timestamp;
	v[2] = vb->copied_timestamp;
	v[3] = buf->hevc.is_intra;
	v[4] = buf->trace_writer;
	v[5] = buf->trace_completed;
	v[6] = buf->trace_allocation;
	v[7] = len;
	v[8] = buf->comp.start_offset;
	v[9] = buf->comp.size;
	for (i = 0; i < 4; i++) {
		v[10 + i] = buf->comp.offsets[i];
		bounds &= buf->comp.offsets[i] < buf->comp.size;
	}
	v[14] = mv;
	v[15] = len >= mv ? len - mv : 0;
	v[16] = bounds;
	v[17] = vb->memory;
}

/* Decode the actual emitted address privately; export only its relative offset. */
static u64 relative_address(struct avd_ctx *ctx, struct avd_decoded_buffer *ref,
                           unsigned int end, unsigned int shift)
{
	struct avd_segment *seg = &ctx->job.segments[ctx->job.num];
	u32 stride = ctx->dev->variant->quirks & AVD_QUIRK_LSR ? 1 : 2;
	u32 i = seg->num - (end + 1) * stride;
	u64 addr = seg->instructions[i];
	u64 base = vb2_dma_contig_plane_dma_addr(&ref->base.vb.vb2_buf, 0);
	if (stride == 1)
		addr <<= shift;
	else
		addr |= (u64)seg->instructions[i + 1] << 32;
	/* Invalid addresses remain evidence without exporting an absolute address. */
	if (addr < base || addr - base >= ref->base.vb.vb2_buf.planes[0].length)
		return U64_MAX;
	return addr - base;
}

void avd_trace_open(struct avd_ctx *ctx)
{
	unsigned long flags;
	spin_lock_irqsave(&atr_lock, flags);
	ctx->trace_context = ++next_context;
	ctx->trace_pid = task_tgid_nr(current);
	open_contexts++;
	if (capture)
		atr_open(capture, ctx->trace_pid);
	spin_unlock_irqrestore(&atr_lock, flags);
}

void avd_trace_job(struct avd_ctx *ctx)
{
	unsigned long flags;
	spin_lock_irqsave(&atr_lock, flags);
	if (capture)
		atr_bind(capture, ctx->trace_pid, ctx->trace_context,
			 ctx->coded_fmt_desc->fourcc == V4L2_PIX_FMT_HEVC_SLICE);
	spin_unlock_irqrestore(&atr_lock, flags);
}

void avd_trace_close(struct avd_ctx *ctx)
{
	unsigned long flags;
	spin_lock_irqsave(&atr_lock, flags);
	if (capture)
		atr_close(capture, ctx->trace_context);
	open_contexts--;
	spin_unlock_irqrestore(&atr_lock, flags);
}

int avd_trace_buf_init(struct vb2_buffer *vb)
{
	struct avd_ctx *ctx = vb2_get_drv_priv(vb->vb2_queue);
	struct avd_decoded_buffer *buf;
	unsigned long flags;
	if (V4L2_TYPE_IS_OUTPUT(vb->type))
		return 0;
	buf = vb2_to_avd_decoded_buf(vb);
	spin_lock_irqsave(&atr_lock, flags);
	if (capture && (capture->phase == ATR_ARMED || selected(ctx)) &&
	    ctx->trace_pid == capture->pid) {
		buf->trace_allocation = ++next_allocation;
		buf->trace_writer = 0;
		buf->trace_completed = false;
	}
	spin_unlock_irqrestore(&atr_lock, flags);
	return 0;
}

void avd_trace_buf_cleanup(struct vb2_buffer *vb)
{
	struct avd_decoded_buffer *buf;
	unsigned long flags;
	if (V4L2_TYPE_IS_OUTPUT(vb->type))
		return;
	buf = vb2_to_avd_decoded_buf(vb);
	spin_lock_irqsave(&atr_lock, flags);
	buf->trace_allocation = 0;
	buf->trace_writer = 0;
	buf->trace_completed = false;
	spin_unlock_irqrestore(&atr_lock, flags);
}

void avd_trace_start(struct avd_ctx *ctx, struct avd_decoded_buffer *dst,
	const struct v4l2_ctrl_hevc_decode_params *decode,
	const struct v4l2_ctrl_hevc_slice_params *sl, u32 slices, u32 entries)
{
	struct atr_record *r;
	unsigned long flags;
	u64 previous;
	spin_lock_irqsave(&atr_lock, flags);
	if (selected(ctx)) {
		atr_start(capture, ctx->trace_context, slices, entries);
		previous = dst->trace_writer;
		dst->trace_writer = capture->pictures;
		dst->trace_completed = false;
		r = atr_append(capture, ctx->trace_context, ATR_START);
		if (r) {
			r->v[0] = previous;
			r->v[1] = (u32)decode->pic_order_cnt_val;
			r->v[2] = (u32)sl->slice_pic_order_cnt;
			r->v[3] = sl->slice_type;
			r->v[4] = slices;
			r->v[5] = entries;
			r->v[6] = decode->num_active_dpb_entries;
			r->v[7] = fmt_width(ctx);
			r->v[8] = fmt_height(ctx);
			buffer_values(ctx, dst, &r->v[9]);
		}
	}
	spin_unlock_irqrestore(&atr_lock, flags);
}

void avd_trace_done(struct avd_ctx *ctx, enum vb2_buffer_state result)
{
	struct atr_record *r;
	struct vb2_v4l2_buffer *vb;
	struct avd_decoded_buffer *dst;
	unsigned long flags;
	spin_lock_irqsave(&atr_lock, flags);
	if (selected(ctx)) {
		vb = v4l2_m2m_next_dst_buf(ctx->fh.m2m_ctx);
		r = atr_append(capture, ctx->trace_context, ATR_DONE);
		if (vb) {
			dst = vb2_to_avd_decoded_buf(&vb->vb2_buf);
			dst->trace_completed = result == VB2_BUF_STATE_DONE;
			if (r) {
				r->v[0] = result;
				buffer_values(ctx, dst, &r->v[1]);
			}
		} else {
			capture->errors |= ATR_ORDER;
		}
		atr_done(capture, ctx->trace_context, result == VB2_BUF_STATE_DONE);
	}
	spin_unlock_irqrestore(&atr_lock, flags);
}

void avd_trace_table(struct avd_ctx *ctx, unsigned int slot,
	const struct v4l2_hevc_dpb_entry *dpb, struct avd_decoded_buffer *ref,
	bool matched, u32 word)
{
	struct atr_record *r;
	unsigned long flags;
	spin_lock_irqsave(&atr_lock, flags);
	if (detail(ctx)) {
		r = atr_append(capture, ctx->trace_context, ATR_TABLE);
		if (r) {
			r->v[0] = slot;
			r->v[1] = (u32)dpb->pic_order_cnt_val;
			r->v[2] = dpb->flags;
			r->v[3] = dpb->timestamp;
			r->v[4] = word;
			r->v[5] = matched;
			buffer_values(ctx, ref, &r->v[6]);
			for (unsigned int i = 0; i < 4; i++)
				r->v[24 + i] = relative_address(ctx, ref, 3 - i, 7);
		}
	}
	spin_unlock_irqrestore(&atr_lock, flags);
}

void avd_trace_list(struct avd_ctx *ctx, u32 list, u32 position, u32 slot, u32 word)
{
	struct atr_record *r;
	unsigned long flags;
	spin_lock_irqsave(&atr_lock, flags);
	if (detail(ctx)) {
		r = atr_append(capture, ctx->trace_context, ATR_LIST);
		if (r) {
			r->v[0] = list;
			r->v[1] = position;
			r->v[2] = slot;
			r->v[3] = word;
		}
	}
	spin_unlock_irqrestore(&atr_lock, flags);
}

void avd_trace_motion(struct avd_ctx *ctx,
	const struct v4l2_ctrl_hevc_slice_params *sl, bool first,
	struct avd_decoded_buffer *ref, bool matched, u32 slot, u64 timestamp,
	bool valid, u32 word, bool emitted)
{
	struct atr_record *r;
	unsigned long flags;
	spin_lock_irqsave(&atr_lock, flags);
	if (detail(ctx)) {
		r = atr_append(capture, ctx->trace_context, ATR_MOTION);
		if (r) {
			r->v[0] = sl->flags;
			r->v[1] = sl->slice_type;
			r->v[2] = sl->five_minus_max_num_merge_cand;
			r->v[3] = sl->num_ref_idx_l0_active_minus1;
			r->v[4] = sl->num_ref_idx_l1_active_minus1;
			r->v[5] = sl->collocated_ref_idx;
			r->v[6] = first;
			r->v[7] = slot;
			r->v[8] = timestamp;
			r->v[9] = !!ref;
			r->v[10] = matched;
			r->v[11] = valid;
			r->v[12] = word;
			r->v[13] = emitted;
			if (ref)
				buffer_values(ctx, ref, &r->v[14]);
			for (unsigned int i = 0; i < 16; i++) {
				r->v[32 + i] = sl->ref_idx_l0[i];
				r->v[48 + i] = sl->ref_idx_l1[i];
			}
			if (emitted)
				r->v[64] = relative_address(ctx, ref, 0, 8);
			r->v[65] = ctx->dev->variant->quirks;
		}
	}
	spin_unlock_irqrestore(&atr_lock, flags);
}

/* "arm RUN TGID", "seal RUN", or "off". No state reset with open contexts. */
static ssize_t control_write(struct file *file, const char __user *data,
			     size_t count, loff_t *pos)
{
	char text[80], op[8], first[24], second[24], extra;
	unsigned long long run = 0, pid = 0;
	struct atr_capture *fresh = NULL, *old = NULL;
	unsigned long flags;
	int ret = 0, n;
	bool arm, seal;
	if (!count || count >= sizeof(text))
		return -EINVAL;
	if (copy_from_user(text, data, count))
		return -EFAULT;
	text[count] = 0;
	if (memchr(text, 0, count))
		return -EINVAL;
	n = sscanf(text, "%7s %23s %23s %c", op, first, second, &extra);
	arm = n == 3 && !strcmp(op, "arm");
	seal = n == 2 && !strcmp(op, "seal");
	if (!arm && !seal && !(n == 1 && !strcmp(op, "off")))
		return -EINVAL;
	if ((arm || seal) && (kstrtoull(first, 10, &run) || !run))
		return -EINVAL;
	if (arm && (kstrtoull(second, 10, &pid) || !pid || pid > INT_MAX))
		return -EINVAL;
	mutex_lock(&atr_control_lock);
	if (arm) {
		fresh = kvzalloc(sizeof(*fresh), GFP_KERNEL);
		if (!fresh) {
			mutex_unlock(&atr_control_lock);
			return -ENOMEM;
		}
		fresh->run = run;
		fresh->pid = pid;
		fresh->phase = ATR_ARMED;
	}
	spin_lock_irqsave(&atr_lock, flags);
	if (open_contexts || (arm && run <= last_run)) {
		ret = -EBUSY;
	} else if (seal) {
		if (!capture || capture->run != run || !atr_seal(capture))
			ret = -EINVAL;
	} else {
		old = capture;
		capture = fresh;
		fresh = NULL;
		if (arm)
			last_run = run;
	}
	spin_unlock_irqrestore(&atr_lock, flags);
	kvfree(old);
	kvfree(fresh);
	mutex_unlock(&atr_control_lock);
	return ret ? ret : count;
}

static int snapshot_show(struct seq_file *s, void *unused)
{
	const struct atr_capture *c = s->private;
	unsigned int i, j;
	seq_printf(s, "H 1 %llu %llu %llu %llu %llu %llu %llu %llu %u %u %u %zu\n",
		c->run, c->context, c->phase, c->errors, c->count, c->attempted,
		c->pictures, c->completions, ATR_CAPACITY, ATR_FIRST, ATR_LAST,
		sizeof(struct atr_record));
	for (i = 0; i < c->count; i++) {
		const struct atr_record *r = &c->records[i];
		seq_printf(s, "R %llu %llu %llu %llu %llu", r->run, r->context,
			r->sequence, r->kind, r->picture);
		for (j = 0; j < ATR_VALUES; j++)
			seq_printf(s, " %llu", r->v[j]);
		seq_putc(s, '\n');
	}
	return 0;
}

static int snapshot_open(struct inode *inode, struct file *file)
{
	struct atr_capture *copy;
	unsigned long flags;
	bool sealed;
	int ret;
	mutex_lock(&atr_control_lock);
	if (snapshot_busy) {
		mutex_unlock(&atr_control_lock);
		return -EBUSY;
	}
	copy = kvzalloc(sizeof(*copy), GFP_KERNEL);
	if (!copy) {
		mutex_unlock(&atr_control_lock);
		return -ENOMEM;
	}
	spin_lock_irqsave(&atr_lock, flags);
	sealed = capture && capture->phase == ATR_SEALED;
	spin_unlock_irqrestore(&atr_lock, flags);
	/* Sealed captures are immutable. control_lock excludes replacement/free. */
	if (sealed) {
		memcpy(copy, capture, sizeof(*copy));
		snapshot_busy = true;
	}
	mutex_unlock(&atr_control_lock);
	if (!sealed) {
		kvfree(copy);
		return -EBUSY;
	}
	ret = single_open(file, snapshot_show, copy);
	if (ret) {
		kvfree(copy);
		mutex_lock(&atr_control_lock);
		snapshot_busy = false;
		mutex_unlock(&atr_control_lock);
	}
	return ret;
}

static int snapshot_release(struct inode *inode, struct file *file)
{
	struct seq_file *s = file->private_data;
	kvfree(s->private);
	mutex_lock(&atr_control_lock);
	snapshot_busy = false;
	mutex_unlock(&atr_control_lock);
	return single_release(inode, file);
}

/* A fixed-size status read lets the guarded supervisor stop on sticky errors. */
static ssize_t status_read(struct file *file, char __user *data, size_t size,
			   loff_t *pos)
{
	char text[320];
	unsigned long flags;
	int len;
	spin_lock_irqsave(&atr_lock, flags);
	if (capture)
		len = scnprintf(text, sizeof(text),
			"S 1 %llu %llu %llu %llu %llu %llu %llu %llu %llu\n",
			capture->run, capture->context, capture->phase, capture->errors,
			capture->count, capture->attempted, capture->pictures,
			capture->completions, open_contexts);
	else
		len = scnprintf(text, sizeof(text), "S 1 0 0 0 0 0 0 0 0 %llu\n",
				open_contexts);
	spin_unlock_irqrestore(&atr_lock, flags);
	return simple_read_from_buffer(data, size, pos, text, len);
}

static const struct file_operations status_fops = {
	.owner = THIS_MODULE, .read = status_read, .llseek = default_llseek,
};
static const struct file_operations control_fops = {
	.owner = THIS_MODULE, .write = control_write, .llseek = noop_llseek,
};
static const struct file_operations snapshot_fops = {
	.owner = THIS_MODULE, .open = snapshot_open, .read = seq_read,
	.llseek = seq_lseek, .release = snapshot_release,
};
void avd_trace_init(void)
{
	atr_dir = debugfs_create_dir("apple_avd_hevc_trace", NULL);
	debugfs_create_file("control", 0200, atr_dir, NULL, &control_fops);
	debugfs_create_file("snapshot", 0400, atr_dir, NULL, &snapshot_fops);
	debugfs_create_file("status", 0400, atr_dir, NULL, &status_fops);
}
void avd_trace_exit(void)
{
	debugfs_remove_recursive(atr_dir);
	kvfree(capture);
}
