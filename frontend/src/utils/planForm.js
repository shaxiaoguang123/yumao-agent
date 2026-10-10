export function decimalToMinor(text, exponent) {
  if (text.trim() === '') return null;
  if (!Number.isInteger(exponent) || exponent < 0 || exponent > 4) throw new Error('部署尚未配置货币。');
  const match = /^(\d+)(?:\.(\d+))?$/.exec(text.trim());
  if (!match || (match[2]?.length || 0) > exponent) throw new Error(`价格最多保留 ${exponent} 位小数，请输入非负十进制金额。`);
  const minor = BigInt(match[1]) * (10n ** BigInt(exponent)) + BigInt((match[2] || '').padEnd(exponent,'0') || '0');
  if (minor > 9007199254740991n) throw new Error('价格上限超出可保存范围。');
  return Number(minor);
}
export function minorToDecimal(value, exponent) {
  if (value === null || value === undefined) return '';
  const digits = String(value).padStart(exponent + 1,'0');
  return exponent ? `${digits.slice(0,-exponent)}.${digits.slice(-exponent)}` : digits;
}
export const copy = (value) => JSON.parse(JSON.stringify(value));
export function newIntent(targetDate) {
  return { target_date:targetDate,preferred_start_times:['18:00'],duration_minutes:120,venue_preference:'',court_preferences:[],fallback_policy:{allow_any_court_in_venue:false,allow_time_shift:false,allowed_start_time_range:null},price_ceiling_minor:null };
}
