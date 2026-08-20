import type { ImageAnimationPresetSpec, AnimationDelta } from './types';

// Canonical Preset Specification for Image Animations
// Shared source of truth between frontend evaluator and backend FFmpeg builder.

export const IN_PRESETS: ImageAnimationPresetSpec[] = [
  {
    id: 'fade-in',
    group: 'in',
    channels: {
      opacity: {
        type: 'keyframes',
        points: [[0.0, 0.0], [1.0, 1.0]],
      },
    },
  },
  {
    id: 'slide-left',
    group: 'in',
    channels: {
      translateX: {
        type: 'keyframes',
        points: [[0.0, 100.0], [1.0, 0.0]],
        easing: 'easeOutCubic',
      },
      opacity: {
        type: 'keyframes',
        points: [[0.0, 0.0], [0.5, 1.0], [1.0, 1.0]],
      }
    },
  },
  {
    id: 'slide-right',
    group: 'in',
    channels: {
      translateX: {
        type: 'keyframes',
        points: [[0.0, -100.0], [1.0, 0.0]],
        easing: 'easeOutCubic',
      },
      opacity: {
        type: 'keyframes',
        points: [[0.0, 0.0], [0.5, 1.0], [1.0, 1.0]],
      }
    },
  },
  {
    id: 'slide-up',
    group: 'in',
    channels: {
      translateY: {
        type: 'keyframes',
        points: [[0.0, 100.0], [1.0, 0.0]],
        easing: 'easeOutCubic',
      },
      opacity: {
        type: 'keyframes',
        points: [[0.0, 0.0], [0.5, 1.0], [1.0, 1.0]],
      }
    },
  },
  {
    id: 'slide-down',
    group: 'in',
    channels: {
      translateY: {
        type: 'keyframes',
        points: [[0.0, -100.0], [1.0, 0.0]],
        easing: 'easeOutCubic',
      },
      opacity: {
        type: 'keyframes',
        points: [[0.0, 0.0], [0.5, 1.0], [1.0, 1.0]],
      }
    },
  },
  {
    id: 'zoom-in',
    group: 'in',
    channels: {
      scale: {
        type: 'keyframes',
        points: [[0.0, 0.5], [1.0, 1.0]],
        easing: 'easeOutCubic',
      },
      opacity: {
        type: 'keyframes',
        points: [[0.0, 0.0], [0.5, 1.0], [1.0, 1.0]],
      }
    },
  },
  {
    id: 'zoom-out',
    group: 'in',
    channels: {
      scale: {
        type: 'keyframes',
        points: [[0.0, 1.5], [1.0, 1.0]],
        easing: 'easeOutCubic',
      },
      opacity: {
        type: 'keyframes',
        points: [[0.0, 0.0], [0.5, 1.0], [1.0, 1.0]],
      }
    },
  },
  {
    id: 'rotate-in',
    group: 'in',
    safeScale: 1.25,
    channels: {
      rotation: {
        type: 'keyframes',
        points: [[0.0, -90.0], [1.0, 0.0]],
        easing: 'easeOutCubic',
      },
      opacity: {
        type: 'keyframes',
        points: [[0.0, 0.0], [0.5, 1.0], [1.0, 1.0]],
      }
    },
  },
  {
    id: 'pop-in',
    group: 'in',
    channels: {
      scale: {
        type: 'keyframes',
        points: [
          [0.00, 0.65],
          [0.55, 1.08],
          [0.78, 0.98],
          [1.00, 1.00]
        ],
        easing: 'linear',
      },
      opacity: {
        type: 'keyframes',
        points: [[0.0, 0.0], [0.3, 1.0], [1.0, 1.0]],
      }
    },
  },
  {
    id: 'bounce-in',
    group: 'in',
    channels: {
      translateY: {
        type: 'keyframes',
        points: [
          [0.00, 100.0],
          [0.45, -15.0],
          [0.65, 10.0],
          [0.82, -5.0],
          [1.00, 0.0]
        ],
        easing: 'linear',
      },
      opacity: {
        type: 'keyframes',
        points: [[0.0, 0.0], [0.3, 1.0], [1.0, 1.0]],
      }
    },
  },
  {
    id: 'blur-in',
    group: 'in',
    channels: {
      blur: {
        type: 'keyframes',
        points: [[0.0, 20.0], [1.0, 0.0]],
        easing: 'easeOutCubic',
      },
      opacity: {
        type: 'keyframes',
        points: [[0.0, 0.0], [1.0, 1.0]],
      }
    },
  }
];

export const OUT_PRESETS: ImageAnimationPresetSpec[] = [
  {
    id: 'fade-out',
    group: 'out',
    channels: {
      opacity: {
        type: 'keyframes',
        points: [[0.0, 1.0], [1.0, 0.0]],
      },
    },
  },
  {
    id: 'slide-left',
    group: 'out',
    channels: {
      translateX: {
        type: 'keyframes',
        points: [[0.0, 0.0], [1.0, -100.0]],
        easing: 'easeInSine',
      },
      opacity: {
        type: 'keyframes',
        points: [[0.0, 1.0], [0.5, 1.0], [1.0, 0.0]],
      }
    },
  },
  {
    id: 'slide-right',
    group: 'out',
    channels: {
      translateX: {
        type: 'keyframes',
        points: [[0.0, 0.0], [1.0, 100.0]],
        easing: 'easeInSine',
      },
      opacity: {
        type: 'keyframes',
        points: [[0.0, 1.0], [0.5, 1.0], [1.0, 0.0]],
      }
    },
  },
  {
    id: 'slide-up',
    group: 'out',
    channels: {
      translateY: {
        type: 'keyframes',
        points: [[0.0, 0.0], [1.0, -100.0]],
        easing: 'easeInSine',
      },
      opacity: {
        type: 'keyframes',
        points: [[0.0, 1.0], [0.5, 1.0], [1.0, 0.0]],
      }
    },
  },
  {
    id: 'slide-down',
    group: 'out',
    channels: {
      translateY: {
        type: 'keyframes',
        points: [[0.0, 0.0], [1.0, 100.0]],
        easing: 'easeInSine',
      },
      opacity: {
        type: 'keyframes',
        points: [[0.0, 1.0], [0.5, 1.0], [1.0, 0.0]],
      }
    },
  },
  {
    id: 'zoom-out',
    group: 'out',
    channels: {
      scale: {
        type: 'keyframes',
        points: [[0.0, 1.0], [1.0, 1.5]],
        easing: 'easeInSine',
      },
      opacity: {
        type: 'keyframes',
        points: [[0.0, 1.0], [0.5, 1.0], [1.0, 0.0]],
      }
    },
  },
  {
    id: 'shrink',
    group: 'out',
    channels: {
      scale: {
        type: 'keyframes',
        points: [[0.0, 1.0], [1.0, 0.0]],
        easing: 'easeInSine',
      },
      opacity: {
        type: 'keyframes',
        points: [[0.0, 1.0], [0.5, 1.0], [1.0, 0.0]],
      }
    },
  },
  {
    id: 'rotate-out',
    group: 'out',
    safeScale: 1.25,
    channels: {
      rotation: {
        type: 'keyframes',
        points: [[0.0, 0.0], [1.0, 90.0]],
        easing: 'easeInSine',
      },
      opacity: {
        type: 'keyframes',
        points: [[0.0, 1.0], [0.5, 1.0], [1.0, 0.0]],
      }
    },
  },
  {
    id: 'blur-out',
    group: 'out',
    channels: {
      blur: {
        type: 'keyframes',
        points: [[0.0, 0.0], [1.0, 20.0]],
        easing: 'easeInSine',
      },
      opacity: {
        type: 'keyframes',
        points: [[0.0, 1.0], [1.0, 0.0]],
      }
    },
  }
];

export const COMBO_PRESETS: ImageAnimationPresetSpec[] = [
  {
    id: 'slow-zoom-in',
    group: 'combo',
    channels: {
      scale: {
        type: 'keyframes',
        points: [[0.0, 1.0], [1.0, 1.15]],
        easing: 'linear',
      }
    }
  },
  {
    id: 'slow-zoom-out',
    group: 'combo',
    channels: {
      scale: {
        type: 'keyframes',
        points: [[0.0, 1.15], [1.0, 1.0]],
        easing: 'linear',
      }
    }
  },
  {
    id: 'pan-left',
    group: 'combo',
    safeScale: 1.15,
    channels: {
      translateX: {
        type: 'keyframes',
        points: [[0.0, 5.0], [1.0, -5.0]],
        easing: 'linear',
      }
    }
  },
  {
    id: 'pan-right',
    group: 'combo',
    safeScale: 1.15,
    channels: {
      translateX: {
        type: 'keyframes',
        points: [[0.0, -5.0], [1.0, 5.0]],
        easing: 'linear',
      }
    }
  },
  {
    id: 'pan-up',
    group: 'combo',
    safeScale: 1.15,
    channels: {
      translateY: {
        type: 'keyframes',
        points: [[0.0, 5.0], [1.0, -5.0]],
        easing: 'linear',
      }
    }
  },
  {
    id: 'pan-down',
    group: 'combo',
    safeScale: 1.15,
    channels: {
      translateY: {
        type: 'keyframes',
        points: [[0.0, -5.0], [1.0, 5.0]],
        easing: 'linear',
      }
    }
  },
  {
    id: 'ken-burns',
    group: 'combo',
    safeScale: 1.15, // Need to scale up slightly to allow panning
    channels: {
      scale: {
        type: 'keyframes',
        points: [[0.0, 1.0], [1.0, 1.10]],
        easing: 'linear',
      },
      translateX: {
        type: 'keyframes',
        points: [[0.0, -2.5], [1.0, 2.5]],
        easing: 'linear',
      },
      translateY: {
        type: 'keyframes',
        points: [[0.0, -2.5], [1.0, 2.5]],
        easing: 'linear',
      }
    }
  },
  {
    id: 'float',
    group: 'combo',
    safeScale: 1.15,
    channels: {
      translateY: {
        type: 'keyframes',
        points: [[0.0, 0.0], [0.25, -5.0], [0.5, 0.0], [0.75, 5.0], [1.0, 0.0]],
        easing: 'easeInOutSine',
      }
    }
  },
  {
    id: 'gentle-rotate',
    group: 'combo',
    safeScale: 1.25,
    channels: {
      rotation: {
        type: 'keyframes',
        points: [[0.0, -3.0], [0.5, 3.0], [1.0, -3.0]],
        easing: 'easeInOutSine',
      }
    }
  },
  {
    id: 'shake',
    group: 'combo',
    safeScale: 1.10,
    channels: {
      translateX: {
        type: 'keyframes',
        points: [
          [0.0, 0.0], [0.1, -2.0], [0.2, 2.0], [0.3, -2.0], [0.4, 2.0], 
          [0.5, -2.0], [0.6, 2.0], [0.7, -2.0], [0.8, 2.0], [0.9, -2.0], [1.0, 0.0]
        ],
        easing: 'linear',
      }
    }
  },
  {
    id: 'pulse',
    group: 'combo',
    channels: {
      scale: {
        type: 'keyframes',
        points: [[0.0, 1.0], [0.5, 1.08], [1.0, 1.0]],
        easing: 'easeInOutSine',
      }
    }
  },
  {
    id: 'zoom-in-out',
    group: 'combo',
    channels: {
      scale: {
        type: 'keyframes',
        points: [[0.0, 1.0], [0.5, 1.16], [1.0, 1.0]],
        easing: 'easeInOutSine',
      }
    }
  },
  {
    id: 'elastic-wobble',
    group: 'combo',
    safeScale: 1.26,
    channels: {
      rotation: {
        type: 'keyframes',
        points: [[0.0, 0.0], [0.12, 7.0], [0.26, -5.5], [0.42, 3.5], [0.60, -2.0], [0.78, 0.8], [1.0, 0.0]],
        easing: 'easeInOutSine',
      },
      translateX: {
        type: 'keyframes',
        points: [[0.0, 0.0], [0.12, 1.5], [0.26, -1.2], [0.42, 0.8], [0.60, -0.4], [0.78, 0.15], [1.0, 0.0]],
        easing: 'easeInOutSine',
      }
    }
  },
  {
    id: 'swing',
    group: 'combo',
    safeScale: 1.20,
    channels: {
      rotation: {
        type: 'keyframes',
        points: [[0.0, -5.0], [0.5, 5.0], [1.0, -5.0]],
        easing: 'easeInOutSine',
      }
    }
  }
];

export const PRESETS_MAP = new Map<string, ImageAnimationPresetSpec>();
[...IN_PRESETS, ...OUT_PRESETS, ...COMBO_PRESETS].forEach(p => PRESETS_MAP.set(`${p.group}:${p.id}`, p));

export function defaultComboLoopMode(presetId: string | null | undefined): 'repeat' | 'pingPong' {
  return ['slow-zoom-in', 'slow-zoom-out', 'pan-left', 'pan-right', 'pan-up', 'pan-down', 'ken-burns'].includes(presetId || '')
    ? 'pingPong'
    : 'repeat';
}

export function getPresetSpec(id?: string | null, group?: 'in' | 'out' | 'combo'): ImageAnimationPresetSpec | null {
  if (!id) return null;
  if (group) return PRESETS_MAP.get(`${group}:${id}`) || null;
  return PRESETS_MAP.get(`in:${id}`) || PRESETS_MAP.get(`out:${id}`) || PRESETS_MAP.get(`combo:${id}`) || null;
}

export function getDefaultAnimationDelta(): AnimationDelta {
  return {
    translateX: 0.0,
    translateY: 0.0,
    scale: 1.0,
    rotation: 0.0,
    opacity: 1.0,
    blur: 0.0,
  };
}
