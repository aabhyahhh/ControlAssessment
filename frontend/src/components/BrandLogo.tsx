/**
 * Local, self-contained brand mark.
 *
 * Previously the logo was hot-linked from upload.wikimedia.org, which made
 * the app depend on public internet access to render its own chrome — it
 * would break in an air-gapped or offline deployment, and leaked a referrer
 * on every page load. This renders inline instead: no network fetch, no
 * binary asset to ship, and `currentColor` lets it invert cleanly against
 * the navy sidebar.
 */

interface BrandLogoProps {
  className?: string;
  height?: number;
  title?: string;
}

export default function BrandLogo({ className, height = 32, title = "KPMG" }: BrandLogoProps) {
  return (
    <svg
      className={className}
      height={height}
      viewBox="0 0 160 44"
      role="img"
      aria-label={title}
      fill="currentColor"
      style={{ display: "block", width: "auto" }}
    >
      <title>{title}</title>
      <text
        x="0"
        y="32"
        fontFamily="Inter, 'Segoe UI', system-ui, sans-serif"
        fontSize="34"
        fontWeight="700"
        letterSpacing="-1.5"
      >
        KPMG
      </text>
      <rect x="0" y="38" width="104" height="3" rx="1.5" />
    </svg>
  );
}
