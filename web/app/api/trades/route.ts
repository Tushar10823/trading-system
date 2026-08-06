import { NextResponse } from "next/server";
import { query } from "@/lib/db";

export async function GET() {
  try {
    const trades = await query(`
      SELECT id, signal_id, symbol, side, qty, entry_price,
             alpaca_order_id, status, created_at
      FROM trades
      ORDER BY created_at DESC
      LIMIT 50
    `);
    return NextResponse.json(trades);
  } catch (error) {
    return NextResponse.json(
      { error: "Failed to fetch trades", details: String(error) },
      { status: 500 }
    );
  }
}
