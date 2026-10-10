from datetime import datetime, timezone

NOW = int(datetime(2026,10,10,2,tzinfo=timezone.utc).timestamp()*1000)


def draft(**changes):
    value = {
        'target_date':'2026-10-20', 'preferred_start_times':['18:00','19:00'],
        'duration_minutes':120, 'venue_preference':'人工意向场馆',
        'court_preferences':['6号场优先','5号场备选'],
        'fallback_policy':{'allow_any_court_in_venue':False,'allow_time_shift':False,'allowed_start_time_range':None},
        'price_ceiling_minor':None,
    }
    value.update(changes)
    return value
