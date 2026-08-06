type Action = "BUY" | "SELL" | "HOLD";

const colors: Record<Action, string> = {
  BUY: "bg-emerald-500/20 text-emerald-400 border-emerald-500/30",
  SELL: "bg-red-500/20 text-red-400 border-red-500/30",
  HOLD: "bg-zinc-500/20 text-zinc-400 border-zinc-500/30",
};

export function ActionBadge({ action }: { action: string }) {
  const key = (action.toUpperCase() as Action) || "HOLD";
  return (
    <span
      className={`inline-block rounded border px-2 py-0.5 text-xs font-medium ${colors[key] || colors.HOLD}`}
    >
      {key}
    </span>
  );
}

export function ConfidenceBadge({ value }: { value: number }) {
  const color =
    value >= 70
      ? "text-emerald-400"
      : value >= 40
        ? "text-yellow-400"
        : "text-red-400";
  return <span className={`font-mono text-sm font-semibold ${color}`}>{value}%</span>;
}
