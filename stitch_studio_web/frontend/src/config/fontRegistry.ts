export type FontCategory =
  | 'Sans / clean'
  | 'Modern / subtitle'
  | 'Friendly / rounded'
  | 'Impact / attention'
  | 'Mono / utility';

export type FontSource = 'fontsource';

export interface FontRegistryItem {
  id: string;
  label: string;
  family: string;
  category: FontCategory;
  weights: number[];
  source: FontSource;
}

export const DEFAULT_FONT_FAMILY = 'Inter';

export const FONT_REGISTRY: FontRegistryItem[] = [
  { id: 'inter', label: 'Inter', family: 'Inter', category: 'Sans / clean', weights: [400, 700, 900], source: 'fontsource' },
  { id: 'roboto', label: 'Roboto', family: 'Roboto', category: 'Sans / clean', weights: [400, 700, 900], source: 'fontsource' },
  { id: 'open-sans', label: 'Open Sans', family: 'Open Sans', category: 'Sans / clean', weights: [400, 700], source: 'fontsource' },
  { id: 'lato', label: 'Lato', family: 'Lato', category: 'Sans / clean', weights: [400, 700, 900], source: 'fontsource' },
  { id: 'nunito', label: 'Nunito', family: 'Nunito', category: 'Sans / clean', weights: [400, 700, 900], source: 'fontsource' },
  { id: 'work-sans', label: 'Work Sans', family: 'Work Sans', category: 'Sans / clean', weights: [400, 700, 900], source: 'fontsource' },
  { id: 'dm-sans', label: 'DM Sans', family: 'DM Sans', category: 'Sans / clean', weights: [400, 700, 900], source: 'fontsource' },
  { id: 'ibm-plex-sans', label: 'IBM Plex Sans', family: 'IBM Plex Sans', category: 'Sans / clean', weights: [400, 700], source: 'fontsource' },
  { id: 'noto-sans', label: 'Noto Sans', family: 'Noto Sans', category: 'Sans / clean', weights: [400, 700, 900], source: 'fontsource' },

  { id: 'montserrat', label: 'Montserrat', family: 'Montserrat', category: 'Modern / subtitle', weights: [400, 700, 900], source: 'fontsource' },
  { id: 'poppins', label: 'Poppins', family: 'Poppins', category: 'Modern / subtitle', weights: [400, 700, 900], source: 'fontsource' },
  { id: 'oswald', label: 'Oswald', family: 'Oswald', category: 'Modern / subtitle', weights: [400, 700], source: 'fontsource' },
  { id: 'archivo-black', label: 'Archivo Black', family: 'Archivo Black', category: 'Modern / subtitle', weights: [400], source: 'fontsource' },
  { id: 'anton', label: 'Anton', family: 'Anton', category: 'Modern / subtitle', weights: [400], source: 'fontsource' },
  { id: 'bebas-neue', label: 'Bebas Neue', family: 'Bebas Neue', category: 'Modern / subtitle', weights: [400], source: 'fontsource' },
  { id: 'outfit', label: 'Outfit', family: 'Outfit', category: 'Modern / subtitle', weights: [400, 700, 900], source: 'fontsource' },
  { id: 'raleway', label: 'Raleway', family: 'Raleway', category: 'Modern / subtitle', weights: [400, 700, 900], source: 'fontsource' },
  { id: 'manrope', label: 'Manrope', family: 'Manrope', category: 'Modern / subtitle', weights: [400, 700], source: 'fontsource' },
  { id: 'urbanist', label: 'Urbanist', family: 'Urbanist', category: 'Modern / subtitle', weights: [400, 700, 900], source: 'fontsource' },

  { id: 'baloo-2', label: 'Baloo 2', family: 'Baloo 2', category: 'Friendly / rounded', weights: [400, 700], source: 'fontsource' },
  { id: 'fredoka', label: 'Fredoka', family: 'Fredoka', category: 'Friendly / rounded', weights: [400, 700], source: 'fontsource' },
  { id: 'rubik', label: 'Rubik', family: 'Rubik', category: 'Friendly / rounded', weights: [400, 700, 900], source: 'fontsource' },

  { id: 'bangers', label: 'Bangers', family: 'Bangers', category: 'Impact / attention', weights: [400], source: 'fontsource' },
  { id: 'luckiest-guy', label: 'Luckiest Guy', family: 'Luckiest Guy', category: 'Impact / attention', weights: [400], source: 'fontsource' },
  { id: 'lilita-one', label: 'Lilita One', family: 'Lilita One', category: 'Impact / attention', weights: [400], source: 'fontsource' },
  { id: 'titan-one', label: 'Titan One', family: 'Titan One', category: 'Impact / attention', weights: [400], source: 'fontsource' },

  { id: 'jetbrains-mono', label: 'JetBrains Mono', family: 'JetBrains Mono', category: 'Mono / utility', weights: [400, 700], source: 'fontsource' },
  { id: 'fira-code', label: 'Fira Code', family: 'Fira Code', category: 'Mono / utility', weights: [400, 700], source: 'fontsource' },
];

export const FONT_CATEGORIES: FontCategory[] = [
  'Sans / clean',
  'Modern / subtitle',
  'Friendly / rounded',
  'Impact / attention',
  'Mono / utility',
];

export function fontByFamily(family?: string) {
  const normalized = (family || DEFAULT_FONT_FAMILY).replace(/["']/g, '').trim().toLowerCase();
  return FONT_REGISTRY.find((font) => font.family.toLowerCase() === normalized || font.id === normalized);
}

export function fontStack(family?: string) {
  const font = fontByFamily(family);
  const resolved = font?.family || DEFAULT_FONT_FAMILY;
  const fallback = font?.category === 'Mono / utility' ? 'ui-monospace, SFMono-Regular, Menlo, Consolas, monospace' : 'Arial, sans-serif';
  return `"${resolved}", ${fallback}`;
}
