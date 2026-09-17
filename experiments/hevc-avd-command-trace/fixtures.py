# SPDX-License-Identifier: GPL-2.0-only
"""Authored synthetic controls for offline tests; no captured vector facts."""
import parser

def row(seed=0, picture=24):
    c={name:([0]*n if kind=='BYTES' else 0) for kind,name,n in parser.LAYOUT}
    c.update(chroma_format_idc=1,pic_width_in_luma_samples=128+(seed%3)*64,
             pic_height_in_luma_samples=96,log2_diff_max_min_luma_coding_block_size=3,
             log2_diff_max_min_luma_transform_block_size=3,
             max_transform_hierarchy_depth_inter=2,max_transform_hierarchy_depth_intra=2,
             slice_type=seed%3,slice_pic_order_cnt=picture,init_qp_minus26=seed%52-26,
             pps_cb_qp_offset=seed%13-6,pps_cr_qp_offset=6-seed%13,
             num_ref_idx_l0_active_minus1=14,num_ref_idx_l1_active_minus1=14,
             slice_segment_addr=seed%4,bit_size=1048568,data_byte_offset=512,
             slice_tc_offset_div2=seed%13-6,slice_beta_offset_div2=6-seed%13,
             luma_log2_weight_denom=seed%8,nal_unit_type=1,nuh_temporal_id_plus1=1)
    if seed&1:c['sps_flags']|=2
    if seed&2:c['pps_flags']|=256|512
    if seed&4:c['sps_flags']|=256
    if seed&8:c['slice_flags']|=128
    if seed&16:c['slice_flags']|=1
    for kind,name,n in parser.LAYOUT:
        if name.startswith('scaling_list'):c[name]=[(i*37+seed*17)%255+1 for i in range(n)]
        elif kind=='BYTES' and ('weight' in name or 'offset' in name):
            c[name]=[(i*3+seed)%31-15 & 255 for i in range(n)]
    return dict(picture=picture,poc=picture,type=c['slice_type'],controls=parser.pack_controls(c),
                decomp=seed&1,revision=3 if seed&1 else 4,quirks=seed%4,bytesperline=256)

def snapshot(windows,run=7,context=3):
    lines=[f'H 2 {run} {context} 4 0 300 300 2048 24 34 1024 {parser.CAPTURE_SIZE} {parser.WINDOW_SIZE}']
    bypic={w['picture']:w for w in windows}
    for pic in range(1,301):
        kind=bypic[pic]['type'] if pic in bypic else 2
        lines.append(f'P {pic} {pic} {kind} {pic%16} 0 {int(kind==2)}')
    for w in windows:
        pairs=' '.join(f'{site} {word}' for site,word in zip(w['sites'],w['words']))
        lines.append('W '+' '.join(str(w[k]) for k in ('picture','poc','type','nwords','nbytes','inactive','decomp','revision','quirks','bytesperline'))+' '+pairs)
        lines.append('C '+' '.join(map(str,w['controls'])))
    return '\n'.join(lines)+'\n'
