import React, { useMemo } from 'react';

export const PixelDispersalPattern: React.FC = () => {
  const squares = useMemo(() => {
    // Deterministic pseudorandom generator for consistent rendering
    let seed = 1337;
    const rand = () => {
      seed = (seed * 1664525 + 1013904223) % 4294967296;
      return seed / 4294967296;
    };

    const cols = 80;
    const rows = 24;
    const cellSize = 10;
    const gap = 2;
    const list: { key: string; x: number; y: number; size: number; opacity: number; fill: string }[] = [];
    const colors = ['#d7d0d0ff', '#b5b5b9ff', '#a6a6abff', '#9b9b9cff', '#5e5e66ff', '#48484eff', '#353538ff'];

    for (let r = 0; r < rows; r++) {
      // depth: 0 at top (r=0), 1 at bottom (r=rows-1)
      const depth = r / (rows - 1);
      // Density increases toward bottom
      const prob = Math.pow(depth, 2.0) * 0.85;

      for (let c = 0; c < cols; c++) {
        if (rand() < prob) {
          const x = c * (cellSize + gap);
          const y = r * (cellSize + gap);
          const opacity = Number((0.08 + Math.pow(depth, 1.4) * (0.22 + 0.42 * rand())).toFixed(3));
          const fill = colors[Math.floor(rand() * colors.length)];
          list.push({ key: `${r}-${c}`, x, y, size: cellSize, opacity, fill });
        }
      }
    }
    return list;
  }, []);

  return (
    <div className="absolute inset-0 pointer-events-none overflow-hidden rounded-3xl z-0">
      <svg
        viewBox="0 0 960 288"
        preserveAspectRatio="xMidYMax slice"
        className="w-full h-full object-cover select-none"
        style={{
          maskImage: 'linear-gradient(to top, rgba(0,0,0,0.95) 0%, rgba(0,0,0,0.8) 35%, rgba(0,0,0,0.25) 70%, transparent 100%)',
          WebkitMaskImage: 'linear-gradient(to top, rgba(0,0,0,0.95) 0%, rgba(0,0,0,0.8) 35%, rgba(0,0,0,0.25) 70%, transparent 100%)',
        }}
        aria-hidden="true"
      >
        {squares.map((sq) => (
          <rect
            key={sq.key}
            x={sq.x}
            y={sq.y}
            width={sq.size}
            height={sq.size}
            fill={sq.fill}
            opacity={sq.opacity}
            rx={1.5}
          />
        ))}
      </svg>
    </div>
  );
};

