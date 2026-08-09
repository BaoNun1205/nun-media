import math
from typing import Any, Dict, List, Optional, Tuple

class RenderContext:
    def __init__(self, width: int, height: int, fps: float, duration_ms: int, timeline_items: List[Dict[str, Any]]):
        self.width = width
        self.height = height
        self.fps = fps
        self.duration_ms = duration_ms
        self.timeline_items = timeline_items

def _parse_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default

from stitch_studio.image_animation_expr import PRESETS_MAP, evaluate_channel_expr

def build_static_image_filters(context: RenderContext) -> Tuple[List[str], List[str], str]:
    """
    Builds the ffmpeg filter chains for static timeline images.
    Returns:
        inputs: List of ffmpeg input arguments (e.g. ['-i', 'image.png', ...])
        filter_complex: The filter_complex string
        final_video_label: The output pad label of the final composition
    """
    inputs: List[str] = []
    filters: List[str] = []
    
    # Sort items by track order. If track order is not explicit, assume they are already sorted or use start time.
    # For now, timeline_items should be passed in z-order (bottom to top).
    image_items = [item for item in context.timeline_items if item.get("kind") == "image" and not item.get("hidden")]
    
    if not image_items:
        return [], [], "[0:v]"
        
    current_base = "[0:v]"
    
    for i, item in enumerate(image_items):
        # Image source path (assuming it's stored in projectAssetId or sourceAssetId logic, but for now we expect the caller to resolve paths)
        image_path = item.get("_resolved_path")
        if not image_path:
            continue
            
        input_index = len(inputs) + 1 # +1 because 0 is the base video
        inputs.extend(["-loop", "1", "-i", str(image_path)])
        
        start_sec = _parse_float(item.get("start"), 0.0)
        duration_sec = _parse_float(item.get("duration"), 0.0)
        end_sec = start_sec + duration_sec
        
        params = item.get("params") or {}
        transform = params.get("imageTransform") or {}
        
        # Base Transform
        scale = _parse_float(transform.get("scale"), 1.0)
        x_pct = _parse_float(transform.get("x"), 0.5)
        y_pct = _parse_float(transform.get("y"), 0.5)
        
        # Animation Logic
        animation = params.get("imageAnimation") or {}
        combo_spec = PRESETS_MAP.get(f"combo:{(animation.get('combo') or {}).get('presetId')}") if (animation.get("combo") or {}).get("presetId") else None
        in_spec = PRESETS_MAP.get(f"in:{(animation.get('in') or {}).get('presetId')}") if (animation.get("in") or {}).get("presetId") else None
        out_spec = PRESETS_MAP.get(f"out:{(animation.get('out') or {}).get('presetId')}") if (animation.get("out") or {}).get("presetId") else None
        
        in_dur = min(float((animation.get("in") or {}).get("duration", 0.5)), duration_sec)
        max_out_dur = max(0.0, duration_sec - in_dur)
        out_dur = min(float((animation.get("out") or {}).get("duration", 0.5)), max_out_dur)
        
        # Calculate t_expr for each state
        t_current = f"(t-{start_sec})"
        in_t_expr = f"min(1, max(0, {t_current}/{in_dur}))" if in_dur > 0 else "1.0"
        out_start = duration_sec - out_dur
        out_t_expr = f"min(1, max(0, ({t_current}-{out_start})/{out_dur}))" if out_dur > 0 else "0.0"
        combo_t_expr = f"min(1, max(0, {t_current}/{duration_sec}))" if duration_sec > 0 else "0.0"

        # Channels
        scale_exprs = []
        trans_x_exprs = []
        trans_y_exprs = []
        rot_exprs = []
        opac_exprs = []
        blur_exprs = []
        
        combo_safe_scale = 1.0

        if combo_spec:
            c = combo_spec.get("channels", {})
            if "scale" in c: scale_exprs.append(evaluate_channel_expr(c["scale"], combo_t_expr))
            if "translateX" in c: trans_x_exprs.append(evaluate_channel_expr(c["translateX"], combo_t_expr))
            if "translateY" in c: trans_y_exprs.append(evaluate_channel_expr(c["translateY"], combo_t_expr))
            if "rotation" in c: rot_exprs.append(evaluate_channel_expr(c["rotation"], combo_t_expr))
            if "opacity" in c: opac_exprs.append(evaluate_channel_expr(c["opacity"], combo_t_expr))
            if "blur" in c: blur_exprs.append(evaluate_channel_expr(c["blur"], combo_t_expr))
            combo_safe_scale = max(combo_safe_scale, combo_spec.get("safeScale", 1.0))
            
        if in_spec and in_dur > 0:
            c = in_spec.get("channels", {})
            # We use if(lte(t_current, in_dur), ..., 1.0) because after IN duration it stays at t=1.0 state. 
            # evaluate_channel_expr already handles t=1.0 if we pass bounded in_t_expr.
            if "scale" in c: scale_exprs.append(evaluate_channel_expr(c["scale"], in_t_expr))
            if "translateX" in c: trans_x_exprs.append(evaluate_channel_expr(c["translateX"], in_t_expr))
            if "translateY" in c: trans_y_exprs.append(evaluate_channel_expr(c["translateY"], in_t_expr))
            if "rotation" in c: rot_exprs.append(evaluate_channel_expr(c["rotation"], in_t_expr))
            if "opacity" in c: opac_exprs.append(evaluate_channel_expr(c["opacity"], in_t_expr))
            if "blur" in c: blur_exprs.append(evaluate_channel_expr(c["blur"], in_t_expr))
            combo_safe_scale = max(combo_safe_scale, in_spec.get("safeScale", 1.0))
            
        if out_spec and out_dur > 0:
            c = out_spec.get("channels", {})
            if "scale" in c: scale_exprs.append(evaluate_channel_expr(c["scale"], out_t_expr))
            if "translateX" in c: trans_x_exprs.append(evaluate_channel_expr(c["translateX"], out_t_expr))
            if "translateY" in c: trans_y_exprs.append(evaluate_channel_expr(c["translateY"], out_t_expr))
            if "rotation" in c: rot_exprs.append(evaluate_channel_expr(c["rotation"], out_t_expr))
            if "opacity" in c: opac_exprs.append(evaluate_channel_expr(c["opacity"], out_t_expr))
            if "blur" in c: blur_exprs.append(evaluate_channel_expr(c["blur"], out_t_expr))
            combo_safe_scale = max(combo_safe_scale, out_spec.get("safeScale", 1.0))
            
        # Combine Semantics
        final_anim_scale = "*".join(scale_exprs) if scale_exprs else "1.0"
        final_anim_tx = "+".join(trans_x_exprs) if trans_x_exprs else "0.0"
        final_anim_ty = "+".join(trans_y_exprs) if trans_y_exprs else "0.0"
        final_anim_rot = "+".join(rot_exprs) if rot_exprs else "0.0"
        final_anim_opac = "*".join(opac_exprs) if opac_exprs else "1.0"
        
        # Blur is max() of all
        final_anim_blur = "0.0"
        if blur_exprs:
            final_anim_blur = blur_exprs[0]
            for b_expr in blur_exprs[1:]:
                final_anim_blur = f"max({final_anim_blur},{b_expr})"

        # We need to scale the image based on the canvas size.
        contain_scale = f"min({context.width}/iw,{context.height}/ih)"
        final_scale_w = f"iw*{contain_scale}*{scale}*{combo_safe_scale}*({final_anim_scale})"
        final_scale_h = f"ih*{contain_scale}*{scale}*{combo_safe_scale}*({final_anim_scale})"
        
        # Calculate X and Y (centered at x_pct, y_pct)
        # delta.translateX is percentage relative to width. Wait, in CSS we translate % of the element size.
        # But in ffmpeg overlay, x and y are top-left of the overlay.
        # overlay_x = context.width * x_pct - final_image_width / 2 + delta.tx / 100 * context.width
        overlay_x = f"({context.width}*{x_pct})-w/2+({final_anim_tx}/100)*{context.width}"
        overlay_y = f"({context.height}*{y_pct})-h/2+({final_anim_ty}/100)*{context.height}"
        
        img_label = f"[img{i}]"
        
        # Start building filter chain for this image
        img_chain = []
        
        # 1. Format to RGBA
        img_chain.append("format=rgba")
        
        # 2. Add IN fade if opacity expr exists
        if in_spec and "opacity" in in_spec.get("channels", {}) and in_dur > 0:
            # Check how long the fade takes. We look at the first keyframe reaching 1.0
            points = in_spec["channels"]["opacity"].get("points", [])
            fade_frac = 1.0
            for p in points:
                if p[1] >= 1.0:
                    fade_frac = p[0]
                    break
            fade_dur = in_dur * fade_frac
            if fade_dur > 0:
                img_chain.append(f"fade=t=in:st={start_sec}:d={fade_dur}:alpha=1")

        # 3. Add OUT fade if opacity expr exists
        if out_spec and "opacity" in out_spec.get("channels", {}) and out_dur > 0:
            # Check when the fade starts. We look at the last keyframe at 1.0
            points = out_spec["channels"]["opacity"].get("points", [])
            fade_start_frac = 0.0
            for p in points:
                if p[1] < 1.0:
                    break
                fade_start_frac = p[0]
            fade_dur = out_dur * (1.0 - fade_start_frac)
            if fade_dur > 0:
                out_fade_st = (start_sec + duration_sec) - fade_dur
                img_chain.append(f"fade=t=out:st={out_fade_st}:d={fade_dur}:alpha=1")
                
        # 4. Scale with eval=frame
        if final_anim_scale != "1.0":
            img_chain.append(f"scale=w='{final_scale_w}':h='{final_scale_h}':eval=frame")
        else:
            img_chain.append(f"scale=w='{final_scale_w}':h='{final_scale_h}'")
            
        # 5. Rotate
        if final_anim_rot != "0.0":
            # Convert degrees to radians
            rot_rad = f"({final_anim_rot})*PI/180"
            img_chain.append(f"rotate=a='{rot_rad}':c=black@0:ow='hypot(iw,ih)':oh='hypot(iw,ih)'")

        # Join the image chain
        scaled_label = f"[scaled{i}]"
        out_label = f"[base{i+1}]"
        
        filters.append(f"[{input_index}:v]{','.join(img_chain)}{scaled_label}")
        
        # 6. Overlay filter with enable and translation
        filters.append(
            f"{current_base}{scaled_label}overlay=x='{overlay_x}':y='{overlay_y}':enable='between(t,{start_sec},{end_sec})'{out_label}"
        )
        
        current_base = out_label
        
    return inputs, filters, current_base

