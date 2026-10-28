import type { OrganizationType, Region } from "@/types/enterprise";

export const REGION_LABELS: Record<Region, string> = {
  americas: "Americas",
  europe: "Europe",
  middle_east_africa: "Middle East & Africa",
  asia_pacific: "Asia-Pacific",
};

export const ORG_TYPE_LABELS: Record<OrganizationType, string> = {
  global_bank: "Global bank",
  regional_headquarters: "Regional HQ",
  country_subsidiary: "Country subsidiary",
  business_division: "Business division",
  department: "Department",
  team: "Team",
};

/** The type a child of each organization type must have (mirrors the backend rules). */
export const CHILD_TYPE: Record<OrganizationType, OrganizationType | null> = {
  global_bank: "regional_headquarters",
  regional_headquarters: "country_subsidiary",
  country_subsidiary: "business_division",
  business_division: "department",
  department: "team",
  team: null,
};

/** Number of decimal places in a currency's minor unit, per the platform's Intl data. */
export function currencyDigits(currency: string): number {
  try {
    return new Intl.NumberFormat("en", { style: "currency", currency }).resolvedOptions()
      .maximumFractionDigits ?? 2;
  } catch {
    return 2;
  }
}

/** Format an integer amount of minor units (cents, yen, …) as currency. */
export function formatMoney(minorUnits: number, currency: string): string {
  const digits = currencyDigits(currency);
  const major = minorUnits / 10 ** digits;
  try {
    return new Intl.NumberFormat("en", {
      style: "currency",
      currency,
      maximumFractionDigits: 0,
    }).format(major);
  } catch {
    return `${major.toLocaleString()} ${currency}`;
  }
}

/** Convert a whole-number major amount typed by a user into minor units. */
export function toMinorUnits(major: number, currency: string): number {
  return Math.round(major * 10 ** currencyDigits(currency));
}

export function humanize(value: string): string {
  return value.replaceAll("_", " ").replace(/^\w/, (c) => c.toUpperCase());
}
