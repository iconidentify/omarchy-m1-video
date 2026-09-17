#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Hash-locked C extraction and explicit non-address push-site selection.

This narrow scanner is not a general C parser. Original bytes, comments and
licences are preserved; masked source is used only to locate balanced spans.
"""
import re
FUNCTIONS=('set_scaling_lists','hevc_set_flags','set_header','stream_weights',
           'stream_slice_dqtblk','set_slice','submit_slice_segment','stream_slices')
SITES={
 'hdr_34_start_hdr':'HDR_START','hdr_50_mode':'HDR_MODE',
 'hdr_54_height_width':'HDR_DIM','hdr_28_height_width_shift3':'HDR_SHIFT3',
 'hdr_2c_sps_txfm':'HDR_TXFM','hdr_30_sps_pcm':'HDR_PCM',
 'hdr_34_sps_flags':'HDR_SPSFLAGS','hdr_5c_pps_flags':'HDR_PPSFLAGS',
 'hdr_60_pps_qp':'HDR_QP','hdr_58_pixfmt_zero':'HDR_ZERO',
 'hdr_98_const_30':'HDR_FEAT','hdr_7c_pps_scl_dims':'SCL_DIMS',
 'dc_16x16':'SCL_DC16','dc_32x32':'SCL_DC32','scaling_4x4':'SCL_4',
 'scaling_8x8':'SCL_8','scaling_16x16':'SCL_16','scaling_32x32':'SCL_32',
 'cm3_mark_end_section':'SCL_OFF','slc_bcc_cmd_quantization':'QP',
 'slc_bd0_cmd_deblocking_filter':'DBLK','slc_76c_cmd_weights_denom':'WT_HDR',
 'slc_luma_weights':'WT_LUMA','slc_luma_offsets':'WT_LUMA_OFF',
 'slc_chroma_weights[0]':'WT_CHR','slc_chroma_weights[1]':'WT_CHR',
 'slc_chroma_offsets[0]':'WT_CHR_OFF','slc_chroma_offsets[1]':'WT_CHR_OFF',
 'cm3_cmd_set_cabac_xy':'LOC_CABAC','cm3_cmd_set_ctb_xy':'LOC_CTB',
 'cm3_set_ctb_xy':'LOC_CTB','cm3_set_mv_xy':'LOC_MV',
 **{'hdr_%x_zero'%i:'HDR_ZERO' for i in range(0x64,0x7c,4)},
}
SITES.update({'hdr_1bc_width_align':'HDR_STRIDE','hdr_1c0_width_align':'HDR_STRIDE'})

def extract(text,name):
 masked=re.sub(r'/\*.*?\*/|//[^\n]*|"(?:\\.|[^"\\])*"',
               lambda m:re.sub(r'[^\n]',' ',m.group()),text,flags=re.S)
 matches=list(re.finditer(r'\bstatic\s+[^;{}]*?\b'+name+r'\s*\([^;{}]*?\)\s*\{',masked))
 assert len(matches)==1, name
 m=matches[0];depth=1
 for i in range(m.end(),len(masked)):
  depth+=(masked[i]=='{')-(masked[i]=='}')
  if not depth:return text[m.start():i+1]
 raise ValueError(name)

def instrument(text):
    original=text
    for name in FUNCTIONS[:-1]:
        body=extract(original,name)
        revised=body
        for match in reversed(list(re.finditer(r'\bpush\(',body))):
            depth=1
            for end in range(match.end(),len(body)):
                depth+=(body[end]=='(')-(body[end]==')')
                if not depth:break
            if body[end+1]!=';':raise ValueError('push statement shape changed')
            statement=body[match.start():end+2]
            labels=re.findall(r'"([^"\n]*)"',statement)
            if len(labels)!=1:raise ValueError('push label shape changed')
            label=labels[0]
            site=SITES.get(label)
            if name=='set_header' and label in ('','zero'):site='HDR_ZERO'
            extra=''
            if site:
                extra='avd_cmdtrace_word(ctx, CMD_SITE_'+site+');'
                if site=='SCL_OFF':extra+=' avd_cmdtrace_inactive(ctx, CMD_SITE_SCL_OFF);'
            if label=='slc_bdc_slice_size':
                extra='avd_cmdtrace_slice_meta(ctx, size, offset, flags, sl->data_byte_offset);'
            if extra:
                revised=revised[:match.start()]+'{ '+statement+' '+extra+' }'+revised[end+2:]
        if name=='stream_slice_dqtblk':
            revised=revised[:-1]+'\tif (sl->slice_type == V4L2_HEVC_SLICE_TYPE_I)\n\t\tavd_cmdtrace_inactive(ctx, CMD_SITE_WT_SKIP);\n}'
        if text.count(body)!=1:raise ValueError('function substitution drift')
        text=text.replace(body,revised,1)
    return text
