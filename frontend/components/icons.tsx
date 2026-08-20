// Small set of shape-distinct icons used alongside color + text on every
// badge, so meaning survives in greyscale / for colorblind users (spec §57A).
// Decorative only — the accessible name always comes from adjacent text.

export type IconShape =
  | "triangle"
  | "octagon"
  | "diamond"
  | "square"
  | "circle"
  | "check-circle"
  | "x-circle"
  | "help-circle"
  | "clock"
  | "hex";

export function ShapeIcon({
  shape,
  className,
}: {
  shape: IconShape;
  className?: string;
}) {
  const common = {
    width: 14,
    height: 14,
    viewBox: "0 0 24 24",
    "aria-hidden": true,
    focusable: false,
    className,
  } as const;

  switch (shape) {
    case "triangle":
      return (
        <svg {...common} fill="none">
          <path
            d="M12 3.5 22 20.5H2L12 3.5Z"
            fill="currentColor"
            fillOpacity="0.25"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinejoin="round"
          />
          <line x1="12" y1="10" x2="12" y2="14.5" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
          <circle cx="12" cy="17.5" r="1.2" fill="currentColor" />
        </svg>
      );
    case "octagon":
      return (
        <svg {...common} fill="none">
          <path
            d="M8 2.5h8L21.5 8v8L16 21.5H8L2.5 16V8L8 2.5Z"
            fill="currentColor"
            fillOpacity="0.25"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinejoin="round"
          />
          <line x1="8.5" y1="8.5" x2="15.5" y2="15.5" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
          <line x1="15.5" y1="8.5" x2="8.5" y2="15.5" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
        </svg>
      );
    case "diamond":
      return (
        <svg {...common} fill="none">
          <path
            d="M12 2.5 21.5 12 12 21.5 2.5 12 12 2.5Z"
            fill="currentColor"
            fillOpacity="0.25"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinejoin="round"
          />
        </svg>
      );
    case "square":
      return (
        <svg {...common} fill="none">
          <rect
            x="3.5"
            y="3.5"
            width="17"
            height="17"
            rx="3"
            fill="currentColor"
            fillOpacity="0.25"
            stroke="currentColor"
            strokeWidth="2"
          />
        </svg>
      );
    case "check-circle":
      return (
        <svg {...common} fill="none">
          <circle cx="12" cy="12" r="9.5" fill="currentColor" fillOpacity="0.25" stroke="currentColor" strokeWidth="2" />
          <path d="M7.5 12.5 10.3 15.3 16.5 9" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" fill="none" />
        </svg>
      );
    case "x-circle":
      return (
        <svg {...common} fill="none">
          <circle cx="12" cy="12" r="9.5" fill="currentColor" fillOpacity="0.25" stroke="currentColor" strokeWidth="2" />
          <line x1="8.5" y1="8.5" x2="15.5" y2="15.5" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
          <line x1="15.5" y1="8.5" x2="8.5" y2="15.5" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
        </svg>
      );
    case "help-circle":
      return (
        <svg {...common} fill="none">
          <circle cx="12" cy="12" r="9.5" fill="currentColor" fillOpacity="0.25" stroke="currentColor" strokeWidth="2" />
          <path
            d="M9.3 9.6a2.7 2.7 0 1 1 4.2 2.25c-.85.58-1.5 1.02-1.5 2.15"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            fill="none"
          />
          <circle cx="12" cy="17.2" r="1.1" fill="currentColor" />
        </svg>
      );
    case "clock":
      return (
        <svg {...common} fill="none">
          <circle cx="12" cy="12" r="9.5" fill="currentColor" fillOpacity="0.25" stroke="currentColor" strokeWidth="2" />
          <path d="M12 6.5V12l4 2.4" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" fill="none" />
        </svg>
      );
    case "hex":
      return (
        <svg {...common} fill="none">
          <path
            d="M8 3h8l4.5 8L16 19H8L3.5 11 8 3Z"
            fill="currentColor"
            fillOpacity="0.25"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinejoin="round"
          />
          <line x1="12" y1="8.5" x2="12" y2="12.5" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
          <circle cx="12" cy="15" r="1.1" fill="currentColor" />
        </svg>
      );
    case "circle":
    default:
      return (
        <svg {...common} fill="none">
          <circle cx="12" cy="12" r="9.5" fill="currentColor" fillOpacity="0.25" stroke="currentColor" strokeWidth="2" />
        </svg>
      );
  }
}
