import { NextResponse } from "next/server";
import { query } from "@/lib/db";

export async function GET() {
  try {
    const signals = await query(`
      SELECT id, symbol, action, confidence, reasoning, created_at
      FROM signals
      ORDER BY created_at DESC
      LIMIT 50
    `);
    return NextResponse.json(signals);
  } catch (error) {
    return NextResponse.json(
      { error: "Failed to fetch signals", details: String(error) },
      { status: 500 }
    );
  }
}
