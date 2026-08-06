import { query } from "@/lib/db";
import { ActionBadge, ConfidenceBadge } from "@/components/Badge";

interface Signal {
  id: number;
  symbol: string;
  action: string;
  confidence: number;
  reasoning: string;
  created_at: string;
}

export const dynamic = "force-dynamic";

export default async function SignalsPage() {
  let signals: Signal[] = [];
  try {
    signals = await query<Signal>(`
      SELECT id, symbol, action, confidence, reasoning, created_at
      FROM signals
      ORDER BY created_at DESC
      LIMIT 100
    `);
  } catch {
    signals = [];
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Signal History</h1>
        <p className="mt-1 text-sm text-zinc-500">
          All BUY / SELL / HOLD decisions from Ollama
        </p>
      </div>

      {signals.length === 0 ? (
        <p className="text-sm text-zinc-500">No signals recorded yet.</p>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-zinc-800">
          <table className="w-full text-sm">
            <thead className="bg-zinc-900 text-left text-zinc-500">
              <tr>
                <th className="px-4 py-2">Time</th>
                <th className="px-4 py-2">Symbol</th>
                <th className="px-4 py-2">Action</th>
                <th className="px-4 py-2">Confidence</th>
                <th className="px-4 py-2">Reasoning</th>
              </tr>
            </thead>
            <tbody>
              {signals.map((s) => (
                <tr key={s.id} className="border-t border-zinc-800">
                  <td className="whitespace-nowrap px-4 py-2 text-zinc-400">
                    {new Date(s.created_at).toLocaleString()}
                  </td>
                  <td className="px-4 py-2 font-medium">{s.symbol}</td>
                  <td className="px-4 py-2">
                    <ActionBadge action={s.action} />
                  </td>
                  <td className="px-4 py-2">
                    <ConfidenceBadge value={s.confidence} />
                  </td>
                  <td className="max-w-md px-4 py-2 text-zinc-400">
                    {s.reasoning}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
