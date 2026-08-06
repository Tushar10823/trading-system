import { NextResponse } from "next/server";
import { query } from "@/lib/db";

export async function GET() {
  try {
    const snapshots = await query(`
      SELECT DISTINCT ON (symbol) id, symbol, price_json, news_json, created_at
      FROM market_snapshots
      ORDER BY symbol, created_at DESC
    `);
    return NextResponse.json(snapshots);
  } catch (error) {
    return NextResponse.json(
      { error: "Failed to fetch snapshots", details: String(error) },
      { status: 500 }
    );
  }
}
