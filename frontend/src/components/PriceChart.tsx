import type { HistoryPoint } from '../types';
import { dateTime, money } from '../lib/format';

const WIDTH = 720;
const HEIGHT = 240;
const PADDING = { top: 16, right: 16, bottom: 30, left: 62 };

/** Dependency-free SVG line chart for the price history. */
export function PriceChart({ points, currency = 'EUR' }: { points: HistoryPoint[]; currency?: string }) {
  const usable = points.filter((p) => p.lowest_price !== null);
  if (usable.length === 0) {
    return <p className="muted">Noch keine Preisdaten für einen Verlauf vorhanden.</p>;
  }

  const values: number[] = [];
  usable.forEach((point) => {
    if (point.lowest_price !== null) values.push(point.lowest_price);
    if (point.highest_price !== null) values.push(point.highest_price);
  });
  const rawMin = Math.min(...values);
  const rawMax = Math.max(...values);
  const span = Math.max(rawMax - rawMin, Math.max(rawMax * 0.02, 10));
  const min = rawMin - span * 0.15;
  const max = rawMax + span * 0.15;

  const innerWidth = WIDTH - PADDING.left - PADDING.right;
  const innerHeight = HEIGHT - PADDING.top - PADDING.bottom;

  const times = usable.map((p) => new Date(p.timestamp).getTime());
  const tMin = Math.min(...times);
  const tMax = Math.max(...times);
  const tSpan = tMax - tMin || 1;

  const x = (index: number) =>
    usable.length === 1
      ? PADDING.left + innerWidth / 2
      : PADDING.left + ((times[index] - tMin) / tSpan) * innerWidth;
  const y = (value: number) => PADDING.top + innerHeight - ((value - min) / (max - min)) * innerHeight;

  const lowLine = usable
    .map((point, index) => `${index === 0 ? 'M' : 'L'} ${x(index).toFixed(1)} ${y(point.lowest_price as number).toFixed(1)}`)
    .join(' ');
  const area = `${lowLine} L ${x(usable.length - 1).toFixed(1)} ${(PADDING.top + innerHeight).toFixed(1)} L ${x(0).toFixed(1)} ${(
    PADDING.top + innerHeight
  ).toFixed(1)} Z`;

  const highPoints = usable.filter((p) => p.highest_price !== null);
  const highLine = highPoints
    .map((point, index) => {
      const originalIndex = usable.indexOf(point);
      return `${index === 0 ? 'M' : 'L'} ${x(originalIndex).toFixed(1)} ${y(point.highest_price as number).toFixed(1)}`;
    })
    .join(' ');

  const ticks = [min, (min + max) / 2, max];

  return (
    <div className="chart-wrap">
      <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} className="chart" role="img" aria-label="Preisverlauf">
        {ticks.map((tick) => (
          <g key={tick}>
            <line x1={PADDING.left} x2={WIDTH - PADDING.right} y1={y(tick)} y2={y(tick)} className="chart-grid" />
            <text x={PADDING.left - 8} y={y(tick) + 4} className="chart-axis" textAnchor="end">
              {Math.round(tick).toLocaleString('de-DE')}
            </text>
          </g>
        ))}
        <path d={area} className="chart-area" />
        {highLine && <path d={highLine} className="chart-line chart-line-high" />}
        <path d={lowLine} className="chart-line" />
        {usable.map((point, index) => (
          <circle key={point.id} cx={x(index)} cy={y(point.lowest_price as number)} r={4} className="chart-dot">
            <title>{`${dateTime(point.timestamp)}: ${money(point.lowest_price, currency)}${
              point.highest_price !== null ? ` (höchster: ${money(point.highest_price, currency)})` : ''
            }`}</title>
          </circle>
        ))}
        <text x={PADDING.left} y={HEIGHT - 8} className="chart-axis">
          {dateTime(usable[0].timestamp)}
        </text>
        <text x={WIDTH - PADDING.right} y={HEIGHT - 8} className="chart-axis" textAnchor="end">
          {dateTime(usable[usable.length - 1].timestamp)}
        </text>
      </svg>
      <div className="chart-legend">
        <span className="legend legend-low">niedrigster Preis</span>
        <span className="legend legend-high">höchster Preis</span>
      </div>
    </div>
  );
}
