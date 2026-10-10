import { describe, expect, it, vi } from 'vitest';
import { createAvailabilitySimulationApi } from './availabilitySimulation.js';
describe('simulation API',()=>{
 it('submits only a saved plan reference, version and synthetic scenario',async()=>{
  const client={request:vi.fn(async()=>({}))};const api=createAvailabilitySimulationApi(client);await api.options();await api.match('plan/one',7,'complete');
  expect(client.request).toHaveBeenLastCalledWith('/api/availability/simulation/plans/plan%2Fone',{method:'POST',body:{base_version:7,scenario:'complete'}});
 });
});
