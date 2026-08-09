from typing import Any, Dict, List, Optional

# Equivalent of easing.ts for FFmpeg expressions
def apply_easing_expr(t_expr: str, easing: str = "linear") -> str:
    # t_expr is assumed to be clamped to 0..1 already
    if easing == "easeInSine":
        return f"(1-cos(({t_expr})*PI/2))"
    elif easing == "easeOutSine":
        return f"sin(({t_expr})*PI/2)"
    elif easing == "easeInOutSine":
        return f"(-(cos(PI*({t_expr}))-1)/2)"
    elif easing == "easeOutCubic":
        return f"(1-pow(1-({t_expr}),3))"
    elif easing == "easeOutBack":
        # 1 + 2.70158 * pow(t - 1, 3) + 1.70158 * pow(t - 1, 2)
        return f"(1+2.70158*pow(({t_expr})-1,3)+1.70158*pow(({t_expr})-1,2))"
    return t_expr

def evaluate_channel_expr(channel: Dict[str, Any], t_expr: str) -> str:
    points = channel.get("points", [])
    if not points:
        return "0"
    if len(points) == 1:
        return str(points[0][1])

    easing = channel.get("easing", "linear")
    eased_t = apply_easing_expr(t_expr, easing)

    # Build piecewise expression
    # if(lt(easedT, p1.t), p1.v, if(lt(easedT, p2.t), lerp, ...))
    
    expr = str(points[-1][1]) # Fallback for last segment

    # Traverse backwards to build nested ifs
    for i in range(len(points) - 2, -1, -1):
        p1 = points[i]
        p2 = points[i + 1]
        
        t1, v1 = p1[0], p1[1]
        t2, v2 = p2[0], p2[1]
        
        segment_delta = t2 - t1
        if segment_delta == 0:
            lerp_expr = str(v2)
        else:
            lerp_expr = f"({v1}+({v2}-{v1})*(({eased_t})-{t1})/{segment_delta})"
            
        expr = f"if(lte({eased_t},{t2}),{lerp_expr},{expr})"
        
    return expr

IN_PRESETS = [
    {"id": "fade-in", "group": "in", "channels": {"opacity": {"type": "keyframes", "points": [[0.0, 0.0], [1.0, 1.0]]}}},
    {"id": "slide-left", "group": "in", "channels": {"translateX": {"type": "keyframes", "points": [[0.0, 100.0], [1.0, 0.0]], "easing": "easeOutCubic"}, "opacity": {"type": "keyframes", "points": [[0.0, 0.0], [0.5, 1.0], [1.0, 1.0]]}}},
    {"id": "slide-right", "group": "in", "channels": {"translateX": {"type": "keyframes", "points": [[0.0, -100.0], [1.0, 0.0]], "easing": "easeOutCubic"}, "opacity": {"type": "keyframes", "points": [[0.0, 0.0], [0.5, 1.0], [1.0, 1.0]]}}},
    {"id": "slide-up", "group": "in", "channels": {"translateY": {"type": "keyframes", "points": [[0.0, 100.0], [1.0, 0.0]], "easing": "easeOutCubic"}, "opacity": {"type": "keyframes", "points": [[0.0, 0.0], [0.5, 1.0], [1.0, 1.0]]}}},
    {"id": "slide-down", "group": "in", "channels": {"translateY": {"type": "keyframes", "points": [[0.0, -100.0], [1.0, 0.0]], "easing": "easeOutCubic"}, "opacity": {"type": "keyframes", "points": [[0.0, 0.0], [0.5, 1.0], [1.0, 1.0]]}}},
    {"id": "zoom-in", "group": "in", "channels": {"scale": {"type": "keyframes", "points": [[0.0, 0.5], [1.0, 1.0]], "easing": "easeOutCubic"}, "opacity": {"type": "keyframes", "points": [[0.0, 0.0], [0.5, 1.0], [1.0, 1.0]]}}},
    {"id": "zoom-out", "group": "in", "channels": {"scale": {"type": "keyframes", "points": [[0.0, 1.5], [1.0, 1.0]], "easing": "easeOutCubic"}, "opacity": {"type": "keyframes", "points": [[0.0, 0.0], [0.5, 1.0], [1.0, 1.0]]}}},
    {"id": "rotate-in", "group": "in", "safeScale": 1.25, "channels": {"rotation": {"type": "keyframes", "points": [[0.0, -90.0], [1.0, 0.0]], "easing": "easeOutCubic"}, "opacity": {"type": "keyframes", "points": [[0.0, 0.0], [0.5, 1.0], [1.0, 1.0]]}}},
    {"id": "pop-in", "group": "in", "channels": {"scale": {"type": "keyframes", "points": [[0.0, 0.65], [0.55, 1.08], [0.78, 0.98], [1.0, 1.0]], "easing": "linear"}, "opacity": {"type": "keyframes", "points": [[0.0, 0.0], [0.3, 1.0], [1.0, 1.0]]}}},
    {"id": "bounce-in", "group": "in", "channels": {"translateY": {"type": "keyframes", "points": [[0.0, 100.0], [0.45, -15.0], [0.65, 10.0], [0.82, -5.0], [1.0, 0.0]], "easing": "linear"}, "opacity": {"type": "keyframes", "points": [[0.0, 0.0], [0.3, 1.0], [1.0, 1.0]]}}},
    {"id": "blur-in", "group": "in", "channels": {"blur": {"type": "keyframes", "points": [[0.0, 20.0], [1.0, 0.0]], "easing": "easeOutCubic"}, "opacity": {"type": "keyframes", "points": [[0.0, 0.0], [1.0, 1.0]]}}},
]

OUT_PRESETS = [
    {"id": "fade-out", "group": "out", "channels": {"opacity": {"type": "keyframes", "points": [[0.0, 1.0], [1.0, 0.0]]}}},
    {"id": "slide-left", "group": "out", "channels": {"translateX": {"type": "keyframes", "points": [[0.0, 0.0], [1.0, -100.0]], "easing": "easeInSine"}, "opacity": {"type": "keyframes", "points": [[0.0, 1.0], [0.5, 1.0], [1.0, 0.0]]}}},
    {"id": "slide-right", "group": "out", "channels": {"translateX": {"type": "keyframes", "points": [[0.0, 0.0], [1.0, 100.0]], "easing": "easeInSine"}, "opacity": {"type": "keyframes", "points": [[0.0, 1.0], [0.5, 1.0], [1.0, 0.0]]}}},
    {"id": "slide-up", "group": "out", "channels": {"translateY": {"type": "keyframes", "points": [[0.0, 0.0], [1.0, -100.0]], "easing": "easeInSine"}, "opacity": {"type": "keyframes", "points": [[0.0, 1.0], [0.5, 1.0], [1.0, 0.0]]}}},
    {"id": "slide-down", "group": "out", "channels": {"translateY": {"type": "keyframes", "points": [[0.0, 0.0], [1.0, 100.0]], "easing": "easeInSine"}, "opacity": {"type": "keyframes", "points": [[0.0, 1.0], [0.5, 1.0], [1.0, 0.0]]}}},
    {"id": "zoom-out", "group": "out", "channels": {"scale": {"type": "keyframes", "points": [[0.0, 1.0], [1.0, 1.5]], "easing": "easeInSine"}, "opacity": {"type": "keyframes", "points": [[0.0, 1.0], [0.5, 1.0], [1.0, 0.0]]}}},
    {"id": "shrink", "group": "out", "channels": {"scale": {"type": "keyframes", "points": [[0.0, 1.0], [1.0, 0.0]], "easing": "easeInSine"}, "opacity": {"type": "keyframes", "points": [[0.0, 1.0], [0.5, 1.0], [1.0, 0.0]]}}},
    {"id": "rotate-out", "group": "out", "safeScale": 1.25, "channels": {"rotation": {"type": "keyframes", "points": [[0.0, 0.0], [1.0, 90.0]], "easing": "easeInSine"}, "opacity": {"type": "keyframes", "points": [[0.0, 1.0], [0.5, 1.0], [1.0, 0.0]]}}},
    {"id": "blur-out", "group": "out", "channels": {"blur": {"type": "keyframes", "points": [[0.0, 0.0], [1.0, 20.0]], "easing": "easeInSine"}, "opacity": {"type": "keyframes", "points": [[0.0, 1.0], [1.0, 0.0]]}}},
]

COMBO_PRESETS = [
    {"id": "slow-zoom-in", "group": "combo", "channels": {"scale": {"type": "keyframes", "points": [[0.0, 1.0], [1.0, 1.15]], "easing": "linear"}}},
    {"id": "slow-zoom-out", "group": "combo", "channels": {"scale": {"type": "keyframes", "points": [[0.0, 1.15], [1.0, 1.0]], "easing": "linear"}}},
    {"id": "pan-left", "group": "combo", "safeScale": 1.15, "channels": {"translateX": {"type": "keyframes", "points": [[0.0, 5.0], [1.0, -5.0]], "easing": "linear"}}},
    {"id": "pan-right", "group": "combo", "safeScale": 1.15, "channels": {"translateX": {"type": "keyframes", "points": [[0.0, -5.0], [1.0, 5.0]], "easing": "linear"}}},
    {"id": "pan-up", "group": "combo", "safeScale": 1.15, "channels": {"translateY": {"type": "keyframes", "points": [[0.0, 5.0], [1.0, -5.0]], "easing": "linear"}}},
    {"id": "pan-down", "group": "combo", "safeScale": 1.15, "channels": {"translateY": {"type": "keyframes", "points": [[0.0, -5.0], [1.0, 5.0]], "easing": "linear"}}},
    {"id": "ken-burns", "group": "combo", "safeScale": 1.15, "channels": {"scale": {"type": "keyframes", "points": [[0.0, 1.0], [1.0, 1.10]], "easing": "linear"}, "translateX": {"type": "keyframes", "points": [[0.0, -2.5], [1.0, 2.5]], "easing": "linear"}, "translateY": {"type": "keyframes", "points": [[0.0, -2.5], [1.0, 2.5]], "easing": "linear"}}},
    {"id": "float", "group": "combo", "safeScale": 1.15, "channels": {"translateY": {"type": "keyframes", "points": [[0.0, 0.0], [0.25, -5.0], [0.5, 0.0], [0.75, 5.0], [1.0, 0.0]], "easing": "easeInOutSine"}}},
    {"id": "gentle-rotate", "group": "combo", "safeScale": 1.25, "channels": {"rotation": {"type": "keyframes", "points": [[0.0, -3.0], [0.5, 3.0], [1.0, -3.0]], "easing": "easeInOutSine"}}},
    {"id": "shake", "group": "combo", "safeScale": 1.10, "channels": {"translateX": {"type": "keyframes", "points": [[0.0, 0.0], [0.1, -2.0], [0.2, 2.0], [0.3, -2.0], [0.4, 2.0], [0.5, -2.0], [0.6, 2.0], [0.7, -2.0], [0.8, 2.0], [0.9, -2.0], [1.0, 0.0]], "easing": "linear"}}},
    {"id": "pulse", "group": "combo", "channels": {"scale": {"type": "keyframes", "points": [[0.0, 1.0], [0.25, 1.08], [0.5, 1.0], [0.75, 1.08], [1.0, 1.0]], "easing": "easeInOutSine"}}},
    {"id": "swing", "group": "combo", "safeScale": 1.20, "channels": {"rotation": {"type": "keyframes", "points": [[0.0, -5.0], [0.5, 5.0], [1.0, -5.0]], "easing": "easeInOutSine"}}},
]

PRESETS_MAP = {f"{p['group']}:{p['id']}": p for p in IN_PRESETS + OUT_PRESETS + COMBO_PRESETS}
