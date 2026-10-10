import { describe, expect, it } from 'vitest';
async function helpers() { const m=await import('./planForm.js').catch(()=>null); expect(m).not.toBeNull(); return m; }
describe('exact draft price conversion',()=>{
 it('converts digit strings without losing decimal precision',async()=>{const m=await helpers(); expect(m.decimalToMinor('12.34',2)).toBe(1234);expect(m.decimalToMinor('0.29',2)).toBe(29);expect(m.decimalToMinor('90071992547409.91',2)).toBe(9007199254740991);expect(m.minorToDecimal(1234,2)).toBe('12.34');expect(m.decimalToMinor('',null)).toBeNull();expect(m.decimalToMinor('42',0)).toBe(42);});
 it('rejects excessive precision, unsafe integers, non-decimal inputs and missing currency',async()=>{const m=await helpers();for(const [value,exponent] of [['1.001',2],['90071992547409.92',2],['1e2',2],['-1',2],['1.',2],['1',null],['1.1',0]])expect(()=>m.decimalToMinor(value,exponent)).toThrow();});
});
