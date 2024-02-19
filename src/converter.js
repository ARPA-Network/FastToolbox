import { fromHex } from "viem";

export function decToBin(num) {
  return BigInt(num).toString(2);
}
export function decToHex(num) {
  return BigInt(num).toString(16).toUpperCase();
}

export function hexToDec(hexstr) {
  if (!hexstr.startsWith("0x")) {
    hexstr = "0x" + hexstr;
  }
  return fromHex(hexstr, "bigint").toString(10);
}
export function hexToBin(hexstr) {
  if (!hexstr.startsWith("0x")) {
    hexstr = "0x" + hexstr;
  }
  return fromHex(hexstr, "bigint").toString(2);
}
