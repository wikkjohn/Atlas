/** Procurement and vendor management (Phase 57). Amounts are in minor units of the vendor's currency. */

export interface Vendor {
  id: string;
  vendor_number: string;
  name: string;
  country: string;
  currency: string;
  category: string;
  bank_account: string;
  pending_bank_account: string | null;
  risk_tier: "low" | "medium" | "high";
  sanctions_hit: boolean;
  status: "pending" | "approved" | "rejected" | "suspended";
  created_at: string;
}

export interface OrderLine {
  description: string;
  quantity: number;
  unit_price: number;
}

export interface PurchaseOrder {
  id: string;
  order_number: string;
  vendor_number: string;
  vendor_name: string;
  department: string;
  description: string;
  lines: OrderLine[];
  total: number;
  total_usd: number;
  currency: string;
  received_amount: number;
  invoiced: number;
  status: "requested" | "approved" | "received" | "rejected" | "closed";
  created_at: string;
}

export interface VendorInvoice {
  id: string;
  invoice_number: string;
  vendor_reference: string;
  order_number: string;
  vendor_name: string;
  amount: number;
  currency: string;
  invoice_date: string;
  status: "recorded" | "held" | "paid" | "rejected";
  hold_reason: string | null;
  paid_to: string | null;
  entry_number: string | null;
  created_at: string;
}

export interface ProcurementSummary {
  vendors_to_approve: number;
  vendors_approved: number;
  bank_changes_to_verify: number;
  orders_to_approve: number;
  orders_open: number;
  invoices_to_pay: number;
  invoices_held: number;
}

export interface ProcurementDepartment {
  id: string;
  name: string;
  country: string | null;
  currency: string | null;
}
