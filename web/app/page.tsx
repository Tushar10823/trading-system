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

interface Snapshot {
  symbol: string;
  price_json: Record<string, unknown>;
  created_at: string;
}

interface Trade {
  id: number;
  symbol: string;
  side: string;
  qty: number;
  status: string;
  created_at: string;
}

async function getLatestSignals(): Promise<Signal[]> {
  try {
    return await query<Signal>(`
      SELECT DISTINCT ON (symbol) id, symbol, action, confidence, reasoning, created_at
      FROM signals
      ORDER BY symbol, created_at DESC
    `);
  } catch {
    return [];
  }
}

async function getLatestSnapshots(): Promise<Snapshot[]> {
  try {
    return await query<Snapshot>(`
      SELECT DISTINCT ON (symbol) symbol, price_json, created_at
      FROM market_snapshots
      ORDER BY symbol, created_at DESC
    `);
  } catch {
    return [];
  }
}

async function getRecentTrades(): Promise<Trade[]> {
  try {
    return await query<Trade>(`
      SELECT id, symbol, side, qty, status, created_at
      FROM trades
      ORDER BY created_at DESC
      LIMIT 5
    `);
  } catch {
    return [];
  }
}

export const dynamic = "force-dynamic";

export default async function DashboardPage() {
  const [signals, snapshots, trades] = await Promise.all([
    getLatestSignals(),
    getLatestSnapshots(),
    getRecentTrades(),
  ]);

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-bold">Dashboard</h1>
        <p className="mt-1 text-sm text-zinc-500">
          Latest signals and market data from the automated pipeline
        </p>
      </div>

      <section>
        <h2 className="mb-4 text-lg font-semibold text-zinc-300">
          Latest Signals
        </h2>
        {signals.length === 0 ? (
          <p className="text-sm text-zinc-500">
            No signals yet. Run the n8n workflows to generate data.
          </p>
        ) : (
          <div className="grid gap-4 sm:grid-cols-2">
            {signals.map((s) => (
              <div
                key={s.id}
                className="rounded-lg border border-zinc-800 bg-zinc-900 p-4"
              >
                <div className="flex items-center justify-between">
                  <span className="text-lg font-bold">{s.symbol}</span>
                  <div className="flex items-center gap-2">
                    <ActionBadge action={s.action} />
                    <ConfidenceBadge value={s.confidence} />
                  </div>
                </div>
                <p className="mt-2 text-sm text-zinc-400 line-clamp-2">
                  {s.reasoning}
                </p>
                <p className="mt-2 text-xs text-zinc-600">
                  {new Date(s.created_at).toLocaleString()}
                </p>
              </div>
            ))}
          </div>
        )}
      </section>

      <section>
        <h2 className="mb-4 text-lg font-semibold text-zinc-300">
          Market Snapshots
        </h2>
        {snapshots.length === 0 ? (
          <p className="text-sm text-zinc-500">No snapshots yet.</p>
        ) : (
          <div className="grid gap-4 sm:grid-cols-2">
            {snapshots.map((s) => (
              <div
                key={s.symbol}
                className="rounded-lg border border-zinc-800 bg-zinc-900 p-4"
              >
                <div className="flex items-center justify-between">
                  <span className="font-bold">{s.symbol}</span>
                  <span className="text-xs text-zinc-500">
                    {new Date(s.created_at).toLocaleString()}
                  </span>
                </div>
                <pre className="mt-2 max-h-24 overflow-auto text-xs text-zinc-500">
                  {JSON.stringify(s.price_json, null, 2)}
                </pre>
              </div>
            ))}
          </div>
        )}
      </section>

      <section>
        <h2 className="mb-4 text-lg font-semibold text-zinc-300">
          Recent Trades
        </h2>
        {trades.length === 0 ? (
          <p className="text-sm text-zinc-500">No trades executed yet.</p>
        ) : (
          <div className="overflow-x-auto rounded-lg border border-zinc-800">
            <table className="w-full text-sm">
              <thead className="bg-zinc-900 text-left text-zinc-500">
                <tr>
                  <th className="px-4 py-2">Time</th>
                  <th className="px-4 py-2">Symbol</th>
                  <th className="px-4 py-2">Side</th>
                  <th className="px-4 py-2">Qty</th>
                  <th className="px-4 py-2">Status</th>
                </tr>
              </thead>
              <tbody>
                {trades.map((t) => (
                  <tr key={t.id} className="border-t border-zinc-800">
                    <td className="px-4 py-2 text-zinc-400">
                      {new Date(t.created_at).toLocaleString()}
                    </td>
                    <td className="px-4 py-2 font-medium">{t.symbol}</td>
                    <td className="px-4 py-2">
                      <ActionBadge action={t.side.toUpperCase()} />
                    </td>
                    <td className="px-4 py-2 font-mono">{t.qty}</td>
                    <td className="px-4 py-2 text-zinc-400">{t.status}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
