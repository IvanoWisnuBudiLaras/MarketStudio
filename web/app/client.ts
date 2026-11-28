export type Workspace = { workspace_id: string; name: string; timezone: string; business_type: string };
export type Offering = { offering_id: string; name: string; unit: string; unit_price_idr: number; unit_cost_idr: number | null; requires_stock_movement: boolean };
export type DailyReport = {
  period: { date: string; timezone: string };
  revenue_idr: number;
  cogs_idr: number | null;
  gross_profit_idr: number | null;
  cash_in_idr: number;
  cash_out_idr: number;
  net_cash_flow_idr: number;
  ending_inventory: { total_value_idr: number; items: { offering_id: string; name: string; unit: string; qty_remaining: string; value_idr: number }[] };
  drill_down: { purchases: { purchase_id: string; total_cost_idr: number }[]; sales: { sale_id: string; total_revenue_idr: number }[] };
};

export class ApiError extends Error {
  constructor(readonly status: number, message: string) { super(message); }
}

export async function api<T>(path: string, token = "", body?: object, key?: string, method = body ? "POST" : "GET"): Promise<T> {
  const headers = new Headers();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (key) headers.set("Idempotency-Key", key);
  if (body) headers.set("Content-Type", "application/json");
  const response = await fetch(`/api/${path}`, {
    method, headers, cache: "no-store",
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await response.json();
  if (!response.ok) {
    const details = Object.values(data.field_errors ?? {}).join(" ");
    throw new ApiError(response.status, [data.message, details].filter(Boolean).join(" "));
  }
  return data;
}
