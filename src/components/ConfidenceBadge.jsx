const LEVELS = {
  high: { label: 'High Confidence', cls: 'bg-emerald-500/15 text-emerald-400 border-emerald-500/20' },
  medium: { label: 'Medium Confidence', cls: 'bg-amber-500/15 text-amber-400 border-amber-500/20' },
  low: { label: 'Low Confidence', cls: 'bg-red-500/15 text-red-400 border-red-500/20' },
};

function levelFromScore(score) {
  if (score == null) return null;
  if (score >= 70) return 'high';
  if (score >= 30) return 'medium';
  return 'low';
}

export default function ConfidenceBadge({ confidence }) {
  if (!confidence) return null;
  const level = confidence.label || levelFromScore(confidence.score);
  if (!level || !LEVELS[level]) return null;
  const { label, cls } = LEVELS[level];

  return (
    <span
      title={confidence.reason || ''}
      className={`inline-flex items-center gap-1.5 text-[10px] px-2.5 py-1 rounded-full font-medium border ${cls}`}
    >
      <span className="w-1.5 h-1.5 rounded-full bg-current" />
      {label}
    </span>
  );
}
