import { type SVGProps } from "react";

type DiceIconProps = SVGProps<SVGSVGElement> & {
  size?: number;
};

// D2 — coin (heads/tails)
export function D2Icon({ size = 24, className = "", ...props }: DiceIconProps) {
  return (
    <svg
      viewBox="0 0 24 24"
      width={size}
      height={size}
      className={className}
      fill="currentColor"
      {...props}
    >
      <ellipse cx="12" cy="12" rx="10" ry="10" fill="none" stroke="currentColor" strokeWidth="1.5" />
      <ellipse cx="12" cy="12" rx="7" ry="7" fill="none" stroke="currentColor" strokeWidth="1" opacity="0.5" />
      <text x="12" y="14" textAnchor="middle" fontSize="8" fill="currentColor" fontWeight="bold">1|2</text>
    </svg>
  );
}

// D4 — tetrahedron (triangle)
export function D4Icon({ size = 24, className = "", ...props }: DiceIconProps) {
  return (
    <svg
      viewBox="0 0 24 24"
      width={size}
      height={size}
      className={className}
      fill="currentColor"
      {...props}
    >
      <path d="M12 2L2 20h20L12 2zm0 5l5.5 10h-11L12 7z" />
      <circle cx="12" cy="14" r="1.5" />
    </svg>
  );
}

// D6 — cube
export function D6Icon({ size = 24, className = "", ...props }: DiceIconProps) {
  return (
    <svg
      viewBox="0 0 24 24"
      width={size}
      height={size}
      className={className}
      fill="currentColor"
      {...props}
    >
      <path d="M19 3H5c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2zM7.5 18c-.83 0-1.5-.67-1.5-1.5S6.67 15 7.5 15s1.5.67 1.5 1.5S8.33 18 7.5 18zm0-9C6.67 9 6 8.33 6 7.5S6.67 6 7.5 6 9 6.67 9 7.5 8.33 9 7.5 9zm4.5 4.5c-.83 0-1.5-.67-1.5-1.5s.67-1.5 1.5-1.5 1.5.67 1.5 1.5-.67 1.5-1.5 1.5zm4.5 4.5c-.83 0-1.5-.67-1.5-1.5s.67-1.5 1.5-1.5 1.5.67 1.5 1.5-.67 1.5-1.5 1.5zm0-9c-.83 0-1.5-.67-1.5-1.5S15.67 6 16.5 6s1.5.67 1.5 1.5S17.33 9 16.5 9z" />
    </svg>
  );
}

// D8 — octahedron (rhombic bipyramid)
export function D8Icon({ size = 24, className = "", ...props }: DiceIconProps) {
  return (
    <svg
      viewBox="0 0 24 24"
      width={size}
      height={size}
      className={className}
      fill="currentColor"
      {...props}
    >
      <path d="M12 2L3 12l9 10 9-10L12 2zm0 3.5L17.5 12 12 18.5 6.5 12 12 5.5z" />
      <circle cx="12" cy="12" r="1.5" />
    </svg>
  );
}

// D10 — pentagonal trapezohedron
export function D10Icon({ size = 24, className = "", ...props }: DiceIconProps) {
  return (
    <svg
      viewBox="0 0 24 24"
      width={size}
      height={size}
      className={className}
      fill="currentColor"
      {...props}
    >
      <path d="M12 2L4 8l8 14 8-14-8-6zm0 4l4 3-4 7-4-7 4-3z" />
      <text x="12" y="14" textAnchor="middle" fontSize="6" fill="currentColor" fontWeight="bold">0</text>
    </svg>
  );
}

// D12 — dodecahedron
export function D12Icon({ size = 24, className = "", ...props }: DiceIconProps) {
  return (
    <svg
      viewBox="0 0 24 24"
      width={size}
      height={size}
      className={className}
      fill="currentColor"
      {...props}
    >
      <path d="M12 2L4.5 7v10L12 22l7.5-5V7L12 2zm0 3l5 3.5v7L12 19l-5-3.5v-7L12 5z" />
      <circle cx="12" cy="12" r="2" />
    </svg>
  );
}

// D20 — icosahedron
export function D20Icon({ size = 24, className = "", ...props }: DiceIconProps) {
  return (
    <svg
      viewBox="0 0 24 24"
      width={size}
      height={size}
      className={className}
      fill="currentColor"
      {...props}
    >
      <path d="M12 2L3 7v10l9 5 9-5V7l-9-5zm0 2.5l6 3.3v8.4l-6 3.3-6-3.3V7.8l6-3.3z" />
      <path d="M12 7l-4 2.5v5L12 17l4-2.5v-5L12 7z" />
      <text x="12" y="13.5" textAnchor="middle" fontSize="5" fill="currentColor" fontWeight="bold">20</text>
    </svg>
  );
}

// D100 — percentile (paired D10s)
export function D100Icon({ size = 24, className = "", ...props }: DiceIconProps) {
  return (
    <svg
      viewBox="0 0 24 24"
      width={size}
      height={size}
      className={className}
      fill="currentColor"
      {...props}
    >
      <path d="M8 3L2 8l6 10 6-10-6-5zm0 3l3 2.5-3 5-3-5L8 6z" />
      <path d="M16 6l-6 5 6 10 6-10-6-5zm0 3l3 2.5-3 5-3-5 3-2.5z" />
    </svg>
  );
}

export type DiceType = "d2" | "d4" | "d6" | "d8" | "d10" | "d12" | "d20" | "d100";

const DICE_ICONS: Record<DiceType, React.ComponentType<DiceIconProps>> = {
  d2: D2Icon,
  d4: D4Icon,
  d6: D6Icon,
  d8: D8Icon,
  d10: D10Icon,
  d12: D12Icon,
  d20: D20Icon,
  d100: D100Icon,
};

export function parseDiceType(expression?: string): DiceType {
  if (!expression) return "d20";
  const match = expression.match(/d(\d+)/i);
  if (match) {
    const sides = match[1];
    if (sides === "2") return "d2";
    if (sides === "4") return "d4";
    if (sides === "6") return "d6";
    if (sides === "8") return "d8";
    if (sides === "10") return "d10";
    if (sides === "12") return "d12";
    if (sides === "20") return "d20";
    if (sides === "100") return "d100";
  }
  return "d20";
}

export function DiceIcon({
  diceType,
  expression,
  size = 24,
  className = "",
  ...props
}: DiceIconProps & { diceType?: DiceType; expression?: string }) {
  const type = diceType || parseDiceType(expression);
  const IconComponent = DICE_ICONS[type] || D20Icon;
  return <IconComponent size={size} className={className} {...props} />;
}

export default DiceIcon;
