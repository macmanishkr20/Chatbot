import {
  Component,
  ChangeDetectionStrategy,
  ElementRef,
  AfterViewInit,
  ViewChild,
  ViewEncapsulation,
  inject,
  PLATFORM_ID,
} from '@angular/core';
import { CommonModule, isPlatformBrowser } from '@angular/common';
import { geoMercator, geoPath, geoGraticule } from 'd3-geo';
import { feature } from 'topojson-client';

/**
 * Decorative map backdrop — renders Northern Europe + MENA country
 * outlines as a soft glowing background behind the chat content.
 *
 * Pure presentation: no app state, no inputs, no events. Reacts to
 * the existing `[data-theme]` attribute via CSS variables.
 */
@Component({
  selector: 'app-map-backdrop',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './map-backdrop.component.html',
  styleUrl: './map-backdrop.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
  // SVG nodes are created via document.createElementNS, so they don't carry
  // Angular's _ngcontent attribute. Disable encapsulation and namespace all
  // selectors with `app-map-backdrop` instead.
  encapsulation: ViewEncapsulation.None,
})
export class MapBackdropComponent implements AfterViewInit {
  @ViewChild('svgEl', { static: true }) svgEl!: ElementRef<SVGSVGElement>;
  private readonly platformId = inject(PLATFORM_ID);

  // ── ISO numeric codes (Natural Earth) ──
  private static readonly SCANDI_IDS = new Set(['578', '752', '246', '208', '352']);
  private static readonly MENA_IDS = new Set([
    // North Africa
    '012', '434', '504', '729', '732', '788', '818',
    // Middle East
    '048', '364', '368', '376', '400', '414', '422', '512', '634',
    '682', '275', '760', '784', '792', '887',
  ]);

  // ── Cities to dot ──
  private static readonly CITIES = [
    { name: 'Oslo',       lon: 10.7522, lat: 59.9139, side: 'right' as const },
    { name: 'Copenhagen', lon: 12.5683, lat: 55.6761, side: 'right' as const },
    { name: 'Helsinki',   lon: 24.9384, lat: 60.1699, side: 'right' as const },
    { name: 'Istanbul',   lon: 28.9784, lat: 41.0082, side: 'left'  as const },
    { name: 'Cairo',      lon: 31.2357, lat: 30.0444, side: 'left'  as const },
    { name: 'Tunis',      lon: 10.1815, lat: 36.8065, side: 'left'  as const },
    { name: 'Beirut',     lon: 35.5018, lat: 33.8938, side: 'right' as const },
    { name: 'Dubai',      lon: 55.2708, lat: 25.2048, side: 'right' as const },
    { name: 'Doha',       lon: 51.5310, lat: 25.2854, side: 'left'  as const },
  ];

  private static readonly HUBS = [
    { name: 'Scandinavian Hub', lon: 18.0686, lat: 59.3293 },
    { name: 'Middle East Hub',  lon: 46.6753, lat: 24.7136 },
  ];

  private static readonly VBOX = { w: 1600, h: 900 };
  private static readonly ATLAS_URL =
    'https://cdn.jsdelivr.net/npm/world-atlas@2/countries-50m.json';

  /** Topojson cache shared across instances so we only fetch once. */
  private static atlasPromise: Promise<any> | null = null;

  ngAfterViewInit(): void {
    if (!isPlatformBrowser(this.platformId)) return;
    this.render();
  }

  private async render(): Promise<void> {
    try {
      if (!MapBackdropComponent.atlasPromise) {
        MapBackdropComponent.atlasPromise = fetch(MapBackdropComponent.ATLAS_URL)
          .then(r => r.json());
      }
      const world = await MapBackdropComponent.atlasPromise;
      const land: any = feature(world, world.objects.countries);
      const wanted = land.features.filter(
        (f: any) =>
          MapBackdropComponent.SCANDI_IDS.has(f.id) ||
          MapBackdropComponent.MENA_IDS.has(f.id),
      );

      const VBOX = MapBackdropComponent.VBOX;
      const projection = geoMercator()
        .center([28, 44])
        .scale(820)
        .translate([VBOX.w / 2, VBOX.h / 2]);
      const path = geoPath(projection as any);

      const svg = this.svgEl.nativeElement;
      const ns = 'http://www.w3.org/2000/svg';

      const layer = (sel: string) => svg.querySelector(sel) as SVGGElement;
      const graticuleLayer = layer('.graticule-layer');
      const regionLayer = layer('.region-layer');
      const linkLayer = layer('.link-layer');
      const cityLayer = layer('.city-layer');
      const hubLayer = layer('.hub-layer');

      // Graticule
      const grat = geoGraticule().step([10, 10]);
      const gPath = document.createElementNS(ns, 'path');
      gPath.setAttribute('class', 'graticule');
      const d = path(grat() as any);
      if (d) gPath.setAttribute('d', d);
      graticuleLayer.appendChild(gPath);

      // Country regions
      for (const f of wanted) {
        const p = document.createElementNS(ns, 'path');
        p.setAttribute('class', 'region');
        const dd = path(f);
        if (dd) p.setAttribute('d', dd);
        regionLayer.appendChild(p);
      }

      // Hub-to-hub curved link
      const [x1, y1] = projection([
        MapBackdropComponent.HUBS[0].lon,
        MapBackdropComponent.HUBS[0].lat,
      ])!;
      const [x2, y2] = projection([
        MapBackdropComponent.HUBS[1].lon,
        MapBackdropComponent.HUBS[1].lat,
      ])!;
      const cx = (x1 + x2) / 2;
      const cy = Math.min(y1, y2) - 100;
      const link = document.createElementNS(ns, 'path');
      link.setAttribute('class', 'link');
      link.setAttribute('d', `M ${x1} ${y1} Q ${cx} ${cy} ${x2} ${y2}`);
      linkLayer.appendChild(link);

      // Cities
      for (const c of MapBackdropComponent.CITIES) {
        const [px, py] = projection([c.lon, c.lat])!;
        const dot = document.createElementNS(ns, 'circle');
        dot.setAttribute('class', 'node-soft');
        dot.setAttribute('cx', String(px));
        dot.setAttribute('cy', String(py));
        dot.setAttribute('r', '2.2');
        cityLayer.appendChild(dot);

        const label = document.createElementNS(ns, 'text');
        label.setAttribute('class', 'city-label');
        const tx = c.side === 'left' ? px - 8 : px + 8;
        label.setAttribute('x', String(tx));
        label.setAttribute('y', String(py + 3));
        label.setAttribute('text-anchor', c.side === 'left' ? 'end' : 'start');
        label.textContent = c.name;
        cityLayer.appendChild(label);
      }

      // Hubs
      for (const h of MapBackdropComponent.HUBS) {
        const [hx, hy] = projection([h.lon, h.lat])!;
        const pulse1 = document.createElementNS(ns, 'circle');
        pulse1.setAttribute('class', 'pulse');
        pulse1.setAttribute('cx', String(hx));
        pulse1.setAttribute('cy', String(hy));
        pulse1.setAttribute('r', '2');
        hubLayer.appendChild(pulse1);

        const pulse2 = document.createElementNS(ns, 'circle');
        pulse2.setAttribute('class', 'pulse delay');
        pulse2.setAttribute('cx', String(hx));
        pulse2.setAttribute('cy', String(hy));
        pulse2.setAttribute('r', '2');
        hubLayer.appendChild(pulse2);

        const node = document.createElementNS(ns, 'circle');
        node.setAttribute('class', 'node');
        node.setAttribute('cx', String(hx));
        node.setAttribute('cy', String(hy));
        node.setAttribute('r', '4');
        hubLayer.appendChild(node);

        const halo = document.createElementNS(ns, 'circle');
        halo.setAttribute('class', 'node-soft');
        halo.setAttribute('cx', String(hx));
        halo.setAttribute('cy', String(hy));
        halo.setAttribute('r', '9');
        hubLayer.appendChild(halo);

        const labelW = h.name.length * 6.6 + 16;
        const lx = hx + 18;
        const ly = hy - 7;

        const connector = document.createElementNS(ns, 'line');
        connector.setAttribute('x1', String(hx + 4));
        connector.setAttribute('y1', String(hy));
        connector.setAttribute('x2', String(lx - 2));
        connector.setAttribute('y2', String(ly + 7));
        connector.setAttribute('stroke', 'var(--map-link-soft)');
        connector.setAttribute('stroke-width', '0.6');
        hubLayer.appendChild(connector);

        const bg = document.createElementNS(ns, 'rect');
        bg.setAttribute('class', 'hub-label-bg');
        bg.setAttribute('x', String(lx));
        bg.setAttribute('y', String(ly));
        bg.setAttribute('width', String(labelW));
        bg.setAttribute('height', '14');
        bg.setAttribute('rx', '3');
        hubLayer.appendChild(bg);

        const tag = document.createElementNS(ns, 'text');
        tag.setAttribute('class', 'hub-label');
        tag.setAttribute('x', String(lx + 8));
        tag.setAttribute('y', String(ly + 10));
        tag.textContent = h.name;
        hubLayer.appendChild(tag);
      }
    } catch (err) {
      // Silent — backdrop is purely decorative; never block the chat UI.
      console.warn('MapBackdrop render failed:', err);
    }
  }
}
