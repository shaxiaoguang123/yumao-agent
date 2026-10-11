import { describe, expect, it, vi } from 'vitest';
import { createAvailabilitySimulationApi } from './availabilitySimulation.js';
describe('simulation API',()=>{
 it('submits only a saved plan reference, version and synthetic scenario',async()=>{
  const client={request:vi.fn(async()=>({}))};const api=createAvailabilitySimulationApi(client);await api.options();await api.match('plan/one',7,'complete');
  expect(client.request).toHaveBeenLastCalledWith('/api/availability/simulation/plans/plan%2Fone',{method:'POST',body:{base_version:7,scenario:'complete'}});
 });
 it('sends only semantic manual intent fields for the ephemeral grid preview',async()=>{
  const client={request:vi.fn(async()=>({}))};const api=createAvailabilitySimulationApi(client);
  const manual={target_date:'2026-10-20',duration_minutes:60,venue_preference:'人工输入场馆',court_preferences:['6号场','5号场']};
  await api.gridPreview(manual);
  expect(client.request).toHaveBeenCalledWith('/api/availability/simulation/grid',{method:'POST',body:manual});
  expect(JSON.stringify(client.request.mock.calls[0][1].body)).not.toMatch(/nodeid|coordinate|timeIndex|courtIndex|token/i);
 });
});
