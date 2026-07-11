// The brand's signature element: a teacher's grading seal (con dấu). The ring carries the
// product's two voices — Vietnamese first, English inside — and the center holds the mark.
// Decorative everywhere it appears; always pass aria-hidden context from the parent.
type Props = {
  className?: string
}

export function BrandSeal({ className }: Props) {
  return (
    <svg className={className} viewBox="0 0 120 120" role="img" aria-hidden focusable="false">
      <defs>
        <path id="seal-ring" d="M 60,60 m -44,0 a 44,44 0 1,1 88,0 a 44,44 0 1,1 -88,0" />
      </defs>
      <circle cx="60" cy="60" r="57" fill="none" stroke="currentColor" strokeWidth="2.5" />
      <circle cx="60" cy="60" r="52" fill="none" stroke="currentColor" strokeWidth="1" opacity="0.75" />
      <circle cx="60" cy="60" r="31" fill="none" stroke="currentColor" strokeWidth="1" opacity="0.75" />
      <text
        fill="currentColor"
        fontFamily="'JetBrains Mono Variable', 'JetBrains Mono', monospace"
        fontSize="9.5"
        fontWeight="600"
        letterSpacing="1.6"
      >
        <textPath href="#seal-ring" startOffset="0%">
          LUYỆN PHỎNG VẤN · INTERVIEW COACH
        </textPath>
      </text>
      <text
        x="60"
        y="60"
        dominantBaseline="central"
        textAnchor="middle"
        fill="currentColor"
        fontFamily="'Phudu Variable', 'Phudu', sans-serif"
        fontSize="30"
        fontWeight="700"
      >
        PV
      </text>
    </svg>
  )
}
