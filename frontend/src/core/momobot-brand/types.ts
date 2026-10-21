/** Shapes served by `/api/momobot-brand/*`. The server strips `price` unless show_pricing is true. */
export interface BrandPrice {
  package?: string;
  monthly_usd: number | null;
  status?: string;
  shared_with?: string[];
  note?: string;
}

export interface BrandAgent {
  id: string;
  order: number;
  name: string;
  short_name: string;
  job: string;
  color: string;
  icon: string;
  icon_alt: string;
  price?: BrandPrice;
}

export interface BrandVideo {
  /** Display title from the kit, e.g. "Meet Max Plus"; falls back to the key. */
  title?: string;
  seconds: number;
  landscape: string;
  vertical: string;
  poster_landscape: string;
  poster_vertical: string;
}

export interface BrandMaxPlus {
  id: string;
  name: string;
  job: string;
  tagline: string;
  bundle_line: string;
  color: string;
  icon: string;
  hero_art?: string;
  includes: string[];
  price?: BrandPrice;
}

export interface BrandKit {
  name: string;
  show_pricing: boolean;
  brand?: { end_card_line?: string };
  max_plus: BrandMaxPlus;
  agents: BrandAgent[];
  videos: Record<string, BrandVideo>;
}

export interface BrandAbout {
  markdown: string;
  show_pricing: boolean;
}
