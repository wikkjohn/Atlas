import { currencyDigits, formatMoney, toMinorUnits } from "@/services/format";

describe("money formatting", () => {
  it("uses each currency's minor unit", () => {
    expect(currencyDigits("USD")).toBe(2);
    expect(currencyDigits("JPY")).toBe(0);
    expect(currencyDigits("KWD")).toBe(3);
    expect(formatMoney(8_250_000, "USD")).toBe("$82,500");
    expect(formatMoney(6_500_000, "JPY")).toBe("¥6,500,000");
    expect(toMinorUnits(82_500, "USD")).toBe(8_250_000);
    expect(toMinorUnits(6_500_000, "JPY")).toBe(6_500_000);
  });
});
