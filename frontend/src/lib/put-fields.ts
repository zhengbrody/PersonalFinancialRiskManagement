export const initialPutFields = { underlying: "", expiry: "", strike: "", premium_per_share: "", assumed_spot: "",
  contracts: "1", fees_total: "", other_reserved_cash: "", cash_buffer: "" };
export const putFieldLabels: Record<keyof typeof initialPutFields, string> = {
  underlying: "Put underlying", expiry: "Put expiry", strike: "Strike (USD per share)",
  premium_per_share: "Assumed premium (USD per share)", assumed_spot: "Assumed underlying price (USD)",
  contracts: "Contracts (100 shares each)", fees_total: "Estimated total fees (USD)",
  other_reserved_cash: "Other cash holds, excluding listed put collateral (USD)", cash_buffer: "Cash buffer to preserve (USD)",
};
export type PutFields = typeof initialPutFields;
