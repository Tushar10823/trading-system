import { query } from "@/lib/db";
import { ActionBadge } from "@/components/Badge";

interface Trade {
  id: number;
  signal_id: number | null;
  symbol: string;
  side: string;
  qty: number;
  entry_price: number | null;
  alpaca_order_id: string | null;
  status: string;
  created_at: string;
}

export const dynamic = "force-dynamic";

export default async function TradesPage() {
  let trades: Trade[] = [];
  try {
    trades = await query<Trade>(`
      SELECT id, signal_id, symbol, side, qty, entry_price,
             alpaca_order_id, status, created_at
      FROM trades
      ORDER BY created_at DESC
      LIMIT 100
    `);
  } catch {
    trades = [];
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Trade History</h1>
        <p className="mt-1 text-sm text-zinc-500">
          Paper trades executed via Alpaca
        </p>
      </div>

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
                <th className="px-4 py-2">Price</th>
                <th className="px-4 py-2">Order ID</th>
                <th className="px-4 py-2">Status</th>
              </tr>
            </thead>
            <tbody>
              {trades.map((t) => (
                <tr key={t.id} className="border-t border-zinc-800">
                  <td className="whitespace-nowrap px-4 py-2 text-zinc-400">
                    {new Date(t.created_at).toLocaleString()}
                  </td>
                  <td className="px-4 py-2 font-medium">{t.symbol}</td>
                  <td className="px-4 py-2">
                    <ActionBadge action={t.side.toUpperCase()} />
                  </td>
                  <td className="px-4 py-2 font-mono">{t.qty}</td>
                  <td className="px-4 py-2 font-mono text-zinc-400">
                    {t.entry_price ? `$${Number(t.entry_price).toFixed(2)}` : "—"}
                  </td>
                  <td className="px-4 py-2 font-mono text-xs text-zinc-500">
                    {t.alpaca_order_id || "—"}
                  </td>
                  <td className="px-4 py-2 text-zinc-400">{t.status}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
