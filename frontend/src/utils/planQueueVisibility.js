function oldestVisibleDate(businessDate) {
  if (typeof businessDate !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(businessDate)) return '';
  const day = new Date(`${businessDate}T00:00:00.000Z`);
  if (Number.isNaN(day.getTime()) || day.toISOString().slice(0, 10) !== businessDate) return '';
  day.setUTCDate(day.getUTCDate() - 1);
  return day.toISOString().slice(0, 10);
}

export function isRecentPlanDate(targetDate, businessDate) {
  const cutoff = oldestVisibleDate(businessDate);
  return !cutoff || (typeof targetDate === 'string' && targetDate >= cutoff);
}

export function visibleManualQueuePlans(queues, { dateFilter = '', businessDate = '' } = {}) {
  return queues
    .filter(queue => isRecentPlanDate(queue.target_date, businessDate))
    .filter(queue => (queue.candidates?.length || dateFilter)
      && (!dateFilter || queue.target_date === dateFilter))
    .sort((left, right) => left.target_date.localeCompare(right.target_date)
      || String(left.plan_id).localeCompare(String(right.plan_id)));
}

export function visibleIntentPlans(plans, { dateFilter = '', businessDate = '' } = {}) {
  return plans
    .filter(plan => isRecentPlanDate(plan.intent?.target_date, businessDate))
    .filter(plan => !dateFilter || plan.intent?.target_date === dateFilter)
    .sort((left, right) => left.intent.target_date.localeCompare(right.intent.target_date)
      || String(left.plan_id).localeCompare(String(right.plan_id)));
}
