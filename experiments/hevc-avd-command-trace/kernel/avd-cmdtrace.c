// SPDX-License-Identifier: GPL-2.0-only
/* Default-off HEVC copied-control and selected-command recorder. */
#include <linux/debugfs.h>
#include <linux/seq_file.h>
#include <linux/slab.h>
#include <linux/uaccess.h>
#include <linux/sched.h>
#include "avd.h"
#include "avd-cmdtrace.h"
#include "avd-trace-core.h"

static DEFINE_MUTEX(cmd_control_lock);
static DEFINE_SPINLOCK(cmd_lock);
static struct cmd_capture *capture;
static struct dentry *cmd_dir;
static u64 open_contexts, last_run;
static bool snapshot_busy;

static bool selected(struct avd_ctx *ctx)
{
	return capture && cmd_selected(capture, ctx->trace_context);
}

static void pack_bytes(unsigned char *out, unsigned int *n,
		       const void *p, unsigned int len)
{
	const unsigned char *s = p;
	unsigned int i;
	for (i = 0; i < len; i++) {
		if (*n >= CMD_PACKED)
			return;
		out[(*n)++] = s[i];
	}
}

static void pack_u16(unsigned char *out, unsigned int *n, u16 v)
{
	out[(*n)++] = (unsigned char)v;
	out[(*n)++] = (unsigned char)(v >> 8);
}

static void pack_u32(unsigned char *out, unsigned int *n, u32 v)
{
	out[(*n)++] = (unsigned char)v;
	out[(*n)++] = (unsigned char)(v >> 8);
	out[(*n)++] = (unsigned char)(v >> 16);
	out[(*n)++] = (unsigned char)(v >> 24);
}

static void pack_u64(unsigned char *out, unsigned int *n, u64 v)
{
	unsigned int i;
	for (i = 0; i < 8; i++)
		out[(*n)++] = (unsigned char)(v >> (8 * i));
}

/* Named non-padding fields only. Reserved struct bytes are never copied. */
static unsigned int pack_controls(unsigned char *out,
				  const struct v4l2_ctrl_hevc_sps *sps,
				  const struct v4l2_ctrl_hevc_pps *pps,
				  const struct v4l2_ctrl_hevc_scaling_matrix *sc,
				  const struct v4l2_ctrl_hevc_slice_params *sl,
				  u64 flags)
{
	const struct v4l2_hevc_pred_weight_table *w = &sl->pred_weight_table;
	unsigned int n = 0;

#define W_U8(v, count) out[n++] = (unsigned char)(v)
#define W_S8(v, count) W_U8(v, count)
#define W_U16(v, count) pack_u16(out, &n, (v))
#define W_U32(v, count) pack_u32(out, &n, (u32)(v))
#define W_S32(v, count) W_U32(v, count)
#define W_U64(v, count) pack_u64(out, &n, (v))
#define W_BYTES(v, count) pack_bytes(out, &n, (v), (count))
#define FIELD(kind, name, member, count) W_##kind(member, count);
#include "control-layout.inc"
#undef FIELD
#undef W_U8
#undef W_S8
#undef W_U16
#undef W_U32
#undef W_S32
#undef W_U64
#undef W_BYTES
	return n;
}

void avd_cmdtrace_open(struct avd_ctx *ctx)
{
	unsigned long flags;
	spin_lock_irqsave(&cmd_lock, flags);
	open_contexts++;
	if (capture)
		cmd_open(capture, ctx->trace_pid);
	spin_unlock_irqrestore(&cmd_lock, flags);
}

void avd_cmdtrace_close(struct avd_ctx *ctx)
{
	unsigned long flags;
	spin_lock_irqsave(&cmd_lock, flags);
	if (capture)
		cmd_close(capture, ctx->trace_context);
	if (open_contexts)
		open_contexts--;
	spin_unlock_irqrestore(&cmd_lock, flags);
}

void avd_cmdtrace_job(struct avd_ctx *ctx)
{
	unsigned long flags;
	spin_lock_irqsave(&cmd_lock, flags);
	if (capture)
		cmd_bind(capture, ctx->trace_pid, ctx->trace_context,
			 ctx->coded_fmt_desc &&
			 ctx->coded_fmt_desc->fourcc == V4L2_PIX_FMT_HEVC_SLICE);
	spin_unlock_irqrestore(&cmd_lock, flags);
}

void avd_cmdtrace_start(struct avd_ctx *ctx,
			const struct v4l2_ctrl_hevc_sps *sps,
			const struct v4l2_ctrl_hevc_pps *pps,
			const struct v4l2_ctrl_hevc_scaling_matrix *sc,
			const struct v4l2_ctrl_hevc_decode_params *decode,
			const struct v4l2_ctrl_hevc_slice_params *sl,
			unsigned int slices, unsigned int entry_capacity,
			struct avd_decoded_buffer *dst)
{
	unsigned long flags;
	unsigned char packed[CMD_PACKED];
	unsigned int i;
	spin_lock_irqsave(&cmd_lock, flags);
	if (!selected(ctx)) {
		spin_unlock_irqrestore(&cmd_lock, flags);
		return;
	}
	cmd_start(capture, ctx->trace_context, slices, entry_capacity,
		  sl->num_entry_point_offsets,
		  !!(pps->flags & V4L2_HEVC_PPS_FLAG_TILES_ENABLED));
	cmd_hist_set(capture, decode->pic_order_cnt_val, sl->slice_type,
		     dst->base.vb.vb2_buf.index, decode->flags,
		     sl->slice_type == V4L2_HEVC_SLICE_TYPE_I);
	if (cmd_detail(capture)) {
		struct cmd_window *w = cmd_slot(capture);
		w->decomp = ctx->decomp;
		w->revision = ctx->dev->variant->revision;
		w->quirks = ctx->dev->variant->quirks;
		w->bytesperline = ctx->decoded_fmt.fmt.pix_mp.plane_fmt[0].bytesperline;
		for (i = 0; i < CMD_PACKED; i++)
			packed[i] = 0;
		if (pack_controls(packed, sps, pps, sc, sl, decode->flags) != CMD_PACKED)
			capture->errors |= CMD_OVERFLOW;
		else
			cmd_controls(capture, packed, CMD_PACKED);
	}
	spin_unlock_irqrestore(&cmd_lock, flags);
}

void avd_cmdtrace_done(struct avd_ctx *ctx, int success)
{
	unsigned long flags;
	spin_lock_irqsave(&cmd_lock, flags);
	if (capture)
		cmd_done(capture, ctx->trace_context, success);
	spin_unlock_irqrestore(&cmd_lock, flags);
}

void avd_cmdtrace_word(struct avd_ctx *ctx, unsigned int site)
{
	unsigned long flags;
	u32 word;
	spin_lock_irqsave(&cmd_lock, flags);
	if (selected(ctx) && cmd_detail(capture) &&
	    ctx->job.segments[ctx->job.num].num) {
		word = avd_cmdtrace_last_word(ctx);
		cmd_word(capture, site, word);
	}
	spin_unlock_irqrestore(&cmd_lock, flags);
}

void avd_cmdtrace_inactive(struct avd_ctx *ctx, unsigned int site)
{
	unsigned long flags;
	spin_lock_irqsave(&cmd_lock, flags);
	if (selected(ctx))
		cmd_inactive(capture, site);
	spin_unlock_irqrestore(&cmd_lock, flags);
}

void avd_cmdtrace_slice_meta(struct avd_ctx *ctx, unsigned int size,
			     unsigned int rel, unsigned int flags,
			     unsigned int data_byte_offset)
{
	unsigned long flags_irq;
	spin_lock_irqsave(&cmd_lock, flags_irq);
	if (selected(ctx) && cmd_detail(capture))
		cmd_slice_meta(capture, size, rel, flags, data_byte_offset);
	spin_unlock_irqrestore(&cmd_lock, flags_irq);
}

static ssize_t control_write(struct file *file, const char __user *data,
			     size_t count, loff_t *pos)
{
	char text[80], extra, op[8], first[24], second[24];
	unsigned long flags;
	unsigned long long run = 0, pid = 0;
	struct cmd_capture *fresh = NULL, *old = NULL;
	int n, arm, seal, ret = 0;
	if (*pos || count >= sizeof(text))
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
	mutex_lock(&cmd_control_lock);
	if (arm) {
		fresh = kvzalloc(sizeof(*fresh), GFP_KERNEL);
		if (!fresh) {
			mutex_unlock(&cmd_control_lock);
			return -ENOMEM;
		}
		fresh->run = run;
		fresh->pid = pid;
		fresh->phase = CMD_ARMED;
	}
	spin_lock_irqsave(&cmd_lock, flags);
	if (open_contexts || (arm && run <= last_run))
		ret = -EBUSY;
	else if (seal) {
		if (!capture || capture->run != run || !cmd_seal(capture))
			ret = -EINVAL;
	} else {
		old = capture;
		capture = fresh;
		fresh = NULL;
		if (arm)
			last_run = run;
	}
	spin_unlock_irqrestore(&cmd_lock, flags);
	kvfree(old);
	kvfree(fresh);
	mutex_unlock(&cmd_control_lock);
	return ret ? ret : count;
}

#define CMD_CAPACITY_MARK 2048

static int snapshot_show(struct seq_file *s, void *unused)
{
	const struct cmd_capture *c = s->private;
	unsigned int i, j;
	seq_printf(s, "H 1 %llu %llu %llu %llu %llu %llu %u %u %u %u %zu %zu\n",
		   c->run, c->context, c->phase, c->errors, c->pictures,
		   c->completions, CMD_CAPACITY_MARK, CMD_FIRST, CMD_LAST,
		   CMD_WORDS, sizeof(*c), sizeof(struct cmd_window));
	for (i = 0; i < CMD_PICTURES; i++)
		seq_printf(s, "P %u %u %u %u %u %u\n", c->hist[i].picture,
			   c->hist[i].poc, c->hist[i].type, c->hist[i].target,
			   c->hist[i].flags, c->hist[i].intra);
	for (i = 0; i < CMD_WINDOW; i++) {
		const struct cmd_window *w = &c->window[i];
		seq_printf(s, "W %u %u %u %u %u %u", w->picture, w->poc, w->type,
			   w->nwords, w->nbytes, w->inactive);
		for (j = 0; j < w->nwords; j++)
			seq_printf(s, " %u %u", w->sites[j], w->words[j]);
		seq_putc(s, '\n');
		seq_printf(s, "C");
		for (j = 0; j < CMD_CONTROL; j++)
			seq_printf(s, " %u", w->controls[j]);
		seq_putc(s, '\n');
	}
	return 0;
}

static int snapshot_open(struct inode *inode, struct file *file)
{
	struct cmd_capture *copy;
	unsigned long flags;
	bool sealed;
	int ret;
	mutex_lock(&cmd_control_lock);
	if (snapshot_busy) {
		mutex_unlock(&cmd_control_lock);
		return -EBUSY;
	}
	copy = kvzalloc(sizeof(*copy), GFP_KERNEL);
	if (!copy) {
		mutex_unlock(&cmd_control_lock);
		return -ENOMEM;
	}
	spin_lock_irqsave(&cmd_lock, flags);
	sealed = capture && capture->phase == CMD_SEALED;
	spin_unlock_irqrestore(&cmd_lock, flags);
	if (sealed) {
		memcpy(copy, capture, sizeof(*copy));
		snapshot_busy = true;
	}
	mutex_unlock(&cmd_control_lock);
	if (!sealed) {
		kvfree(copy);
		return -EBUSY;
	}
	ret = single_open(file, snapshot_show, copy);
	if (ret) {
		kvfree(copy);
		mutex_lock(&cmd_control_lock);
		snapshot_busy = false;
		mutex_unlock(&cmd_control_lock);
	}
	return ret;
}

static int snapshot_release(struct inode *inode, struct file *file)
{
	struct seq_file *s = file->private_data;
	kvfree(s->private);
	mutex_lock(&cmd_control_lock);
	snapshot_busy = false;
	mutex_unlock(&cmd_control_lock);
	return single_release(inode, file);
}

static ssize_t status_read(struct file *file, char __user *data, size_t size,
			   loff_t *pos)
{
	char text[320];
	unsigned long flags;
	int len;
	spin_lock_irqsave(&cmd_lock, flags);
	if (capture)
		len = scnprintf(text, sizeof(text),
				"S 1 %llu %llu %llu %llu %llu %llu %llu\n",
				capture->run, capture->context, capture->phase,
				capture->errors, capture->pictures,
				capture->completions, open_contexts);
	else
		len = scnprintf(text, sizeof(text),
				"S 1 0 0 0 0 0 0 %llu\n", open_contexts);
	spin_unlock_irqrestore(&cmd_lock, flags);
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

void avd_cmdtrace_init(void)
{
	BUILD_BUG_ON(CMD_PACKED > CMD_CONTROL);
	BUILD_BUG_ON(CMD_PACKED != 1380);
	BUILD_BUG_ON(PEAK_ALLOC_BYTES > ALLOCATION_LIMIT_BYTES);
	BUILD_BUG_ON(sizeof(struct atr_capture) != TRACE_CAPTURE_BYTES);
	cmd_dir = debugfs_create_dir("apple_avd_hevc_cmdtrace", NULL);
	debugfs_create_file("control", 0200, cmd_dir, NULL, &control_fops);
	debugfs_create_file("snapshot", 0400, cmd_dir, NULL, &snapshot_fops);
	debugfs_create_file("status", 0400, cmd_dir, NULL, &status_fops);
}

void avd_cmdtrace_exit(void)
{
	debugfs_remove_recursive(cmd_dir);
	kvfree(capture);
}
