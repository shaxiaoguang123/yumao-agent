"""Opt-in live DeepSeek evaluation. Synthetic dialogue data, real billed provider calls.

Run manually with --env-file and --output; unittest discovery never executes this file.
No database, booking credential, upstream availability, booking, payment, or executor is used.
"""
from __future__ import annotations

import argparse
import ast
import json
import hashlib
import re
import os
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from backend.ai.planning import PlanningService, assistant_history_entry
from backend.ai.provider import ProviderConfig, ProviderFailure, PinnedChatCompletionsTransport
from backend.ai.queue_draft import deserialize_draft
from backend.ai.queue_turn import SENSITIVE_TEXT
from backend.ai.service import AIModelError
from backend.plans.models import PlanInterpretationContext
from backend.plans.service import PlanError


def local_ms(day=21, hour=12, minute=0):
    return int(datetime(2026, 10, day, hour, minute, tzinfo=ZoneInfo('Asia/Shanghai')).timestamp()*1000)


def load_key(path):
    selected = {}
    for line in Path(path).read_text().splitlines():
        name, separator, value = line.strip().removeprefix('export ').partition('=')
        if separator and name.strip().lower() in {'deepseek_api', 'deepseek_api_key', 'model'}:
            raw = value.strip()
            if raw.startswith(('"', "'")):
                try:
                    raw = ast.literal_eval(raw)
                except (SyntaxError, ValueError):
                    raise RuntimeError("Invalid quoted API configuration") from None
            else:
                raw = raw.split(' #', 1)[0].strip()
            selected[name.strip().lower()] = raw
    key = os.environ.get('DEEPSEEK_API_KEY') or selected.get('deepseek_api') or selected.get('deepseek_api_key')
    if not key:
        raise RuntimeError('DeepSeek API key is not configured')
    return key, selected.get('model')


class DiagnosticTransport(PinnedChatCompletionsTransport):
    def __init__(self):
        super().__init__()
        self.responses=[]

    def _exchange(self, config, method, suffix, body=None):
        raw=super()._exchange(config,method,suffix,body)
        if method=='POST':
            try:
                parsed=json.loads(raw)
                choice=parsed['choices'][0]
                content=choice.get('message',{}).get('content')
                self.responses.append({'finish_reason':choice.get('finish_reason'),
                                       'content_characters':len(content) if isinstance(content,str) else None,
                                       'usage':{key:value for key,value in (parsed.get('usage') or {}).items() if key in {'prompt_tokens','completion_tokens','total_tokens','reasoning_tokens','prompt_cache_hit_tokens','prompt_cache_miss_tokens'} and type(value) is int}})
            except (ValueError,KeyError,IndexError,TypeError):
                self.responses.append({'invalid_response_envelope':True})
        return raw


class LiveProvider:
    def __init__(self, key, requested_model=None):
        self.transport = DiagnosticTransport()
        self.config = ProviderConfig('live-eval', 'DeepSeek live evaluation', 'https://api.deepseek.com', '', 'bearer', key)
        catalog = self.transport.list_models(self.config)
        models = [item['id'] for item in catalog if type(item) is dict and isinstance(item.get('id'),str)]
        chosen = requested_model if requested_model in models else next((model for model in ('deepseek-flash','deepseek-chat') if model in models), None)
        if chosen is None:
            raise RuntimeError('No supported DeepSeek chat model in catalog')
        self.config = replace(self.config, model=chosen)
        self.calls = 0
        self.diagnostics = []

    def chat(self, _user_id, messages, **_kwargs):
        self.calls += 1
        try:
            content = self.transport.chat(self.config, messages)
        except ProviderFailure as exc:
            raise AIModelError(exc.code, exc.status) from None
        try:
            parsed=json.loads(re.sub(r"\A```(?:json)?\s*|\s*```\Z", "", content.strip(), flags=re.I))
            if type(parsed) is dict:
                allowed={'intent','kind','updates','unresolved','next_field','next_question','next_action','dialogue_focus','dialogue_action'}
                diagnostic={key:value for key,value in parsed.items() if key in allowed}
                diagnostic['keys']=[key for key in parsed if re.fullmatch('[a-z_]{1,40}',key)]
                encoded=json.dumps(diagnostic,ensure_ascii=False)
                if self.config.api_key in encoded or SENSITIVE_TEXT.search(encoded):
                    diagnostic={'redacted':True}
                self.diagnostics.append(diagnostic)
            else:
                self.diagnostics.append({'json_type':type(parsed).__name__})
        except (ValueError,TypeError):
            self.diagnostics.append({'invalid_json':True,'content_characters':len(content),'fenced':content.strip().startswith('```')})
        return content, {'name':self.config.name, 'model':self.config.model}


class Scenario:
    def __init__(self, service):
        self.service, self.messages, self.asked, self.history = service, [], [], []
        self.previous = None

    def send(self, text, expected, *, now=None):
        now = now or local_ms()
        self.messages.append(text)
        if self.previous:
            self.asked.append(self.previous['conversation']['asking'])
        previous = self.previous['conversation'] if self.previous else {}
        result = self.service.propose(
            'synthetic-live-eval', self.messages[0], now, answers=self.messages[1:], asked_fields=self.asked,
            scope_label='羽毛球', require_model=True,
            reference_date=datetime.fromtimestamp(local_ms()/1000,ZoneInfo('Asia/Shanghai')).date(),
            agent_state=previous.get('_agent_state'), previous_turn_kinds=previous.get('turn_kinds'),
            assistant_history=self.history,
        )
        self.previous = result
        self.history.append(assistant_history_entry(result))
        view = result['conversation']
        state = view['_agent_state']
        draft = deserialize_draft(state['draft'])
        observed = {'status':result['status'], 'asking':view['asking'],
                    'target_date':draft.dates[0].isoformat() if draft.dates else None,
                    'windows_2h':draft.g2.windows, 'courts_2h':draft.g2.courts,
                    'windows_1h':draft.g1.windows, 'courts_1h':draft.g1.courts,
                    'pending':view.get('pending_edit'), 'count':(result.get('proposal') or {}).get('entry_count'),
                    'reply':view.get('contextual_reply',''), 'questions':result['questions'], 'turn_trace':view.get('turn_trace')}
        errors=[]
        for key,value in expected.items():
            if key == 'pending_fields':
                actual = (observed['pending'] or {}).get('remaining')
            elif key == 'reply_mentions':
                actual = all(any(part in observed['reply'] for part in alternatives) for alternatives in value)
                value = True
            else:
                actual = observed[key]
            if actual != value:
                errors.append({'field':key,'expected':value,'actual':actual})
        return {'input':text,'business_date':view['business_date'],'ok':not errors,'errors':errors,'observed':observed}


def scenarios():
    initial='2026年10月26日，只抢2小时，14-16，1号和2号场。'
    return [
        ('compound_operations_undo_preview_edit',[
            (initial,{'status':'ready','count':2}),
            ('去掉1号场，再加4号场',{'status':'ready','courts_2h':[2,4]}),
            ('撤销刚才的场地修改',{'status':'ready','courts_2h':[1,2]}),
            ('时段改成18-20',{'status':'ready','windows_2h':[(1080,1200)]}),
        ]),
        ('historical_edit_and_resume',[
            ('2026年10月26日，只抢2小时，14-16。',{'asking':'courts_2h'}),
            ('先改一下日期',{'status':'needs_input','pending_fields':['target_date']}),
            ('改成明天',{'target_date':'2026-10-22','asking':'courts_2h','pending':None}),
            ('1号场',{'status':'ready','count':1}),
        ]),
        ('cancel_partial_local_edit',[
            (initial,{'status':'ready'}),
            ('我要一起修改2小时时段和场地',{'pending_fields':['windows_2h','courts_2h']}),
            ('时段换成18-20',{'pending_fields':['courts_2h']}),
            ('取消这次修改',{'status':'ready','windows_2h':[(840,960)],'courts_2h':[1,2]}),
        ]),
        ('overlap_reference',[
            ('2026年10月26日，只抢2小时，14-16和15-17，1号场。',{'asking':'overlap_2h'}),
            ('去掉后一个',{'status':'ready','windows_2h':[(840,960)]}),
        ]),
        ('cross_midnight_relative_date',[
            ('明天只抢2小时，14-16，1号场。',{'status':'ready','target_date':'2026-10-22'},local_ms(21,23,59)),
            ('场地再加4号场',{'target_date':'2026-10-22','courts_2h':[1,4]},local_ms(22,0,1)),
            ('日期换成后天',{'target_date':'2026-10-24'},local_ms(22,0,2)),
        ]),
        ('repair_candidate_limit',[
            ('2026年10月26日只抢2小时，10-12、12-14、14-16、16-18，场地1到10号场。',{'status':'needs_input','asking':'courts_2h'}),
            ('去掉9号和10号场',{'status':'ready','count':32}),
        ]),
        ('repair_invalid_court_range',[
            ('2026年10月26日只抢2小时，14-16，1到11号场。',{'status':'needs_input','asking':'courts_2h'}),
            ('去掉11号场',{'status':'ready','count':10}),
        ]),
        ('invalid_window_is_retained',[
            ('2026年10月26日只抢2小时，14-16和25-27，1号场。',{'status':'needs_input','asking':'windows_2h'}),
            ('时段改成18-20',{'status':'ready','windows_2h':[(1080,1200)]}),
        ]),
        ('conflicting_duration_is_clarified',[
            ('2026年10月26日只抢2小时，14-16打3小时，1号场。',{'status':'needs_input','asking':'windows_2h'}),
            ('不是三小时，按2小时',{'status':'ready','count':1}),
        ]),
        ('contextual_question_without_losing_progress',[
            ('2026年10月26日只抢2小时，14-16。',{'asking':'courts_2h'}),
            ('我们确定了什么，还缺哪一步？',{'asking':'courts_2h','reply_mentions':[['26','十月二十六'],['14','下午2'],['场地','几号场']]}),
            ('2号场',{'status':'ready','courts_2h':[2]}),
        ]),
        ('short_positional_mode_choice',[
            ('2026年10月26日，14-16，1号场。',{'asking':'booking_mode'}),
            ('最后一个',{'asking':'windows_1h','courts_2h':[1]}),
            ('1小时18-19，4号场',{'status':'ready','count':2,'courts_2h':[1],'courts_1h':[4]}),
        ]),
        ('independent_duration_groups',[
            ('2026年10月26日两种都抢，2小时14-16选1号场，1小时18-19选4号场。',{'status':'ready','count':2,'courts_2h':[1],'courts_1h':[4]}),
            ('2小时场地加上3号场，1小时场地去掉4号场换成5号场',{'status':'ready','courts_2h':[1,3],'courts_1h':[5]}),
        ]),
    ]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env-file',required=True)
    parser.add_argument('--output',required=True)
    parser.add_argument('--model')
    parser.add_argument('--case',action='append',default=[])
    args=parser.parse_args()
    report={'provider_kind':'real DeepSeek API','data_kind':'synthetic user dialogues','cases':[],
            'database_used':False,'booking_or_payment_tools':False}
    output=Path(args.output)
    def save():
        output.write_text(json.dumps(report,ensure_ascii=False,indent=2))
    record = None
    try:
        key, configured_model=load_key(args.env_file)
        provider=LiveProvider(key,args.model or configured_model)
        report['model']=provider.config.model
        source=Path(__file__).resolve().parents[1]/'ai'
        report['source_sha256']={str(file.relative_to(source)):hashlib.sha256(file.read_bytes()).hexdigest() for file in [*source.glob('*.py'),*source.glob('nlu/*.py')]}
        plans=SimpleNamespace(active_context=PlanInterpretationContext('Asia/Shanghai','CNY',2))
        service=PlanningService(plans,provider)
        selected = [(name, steps) for name, steps in scenarios() if not args.case or name in args.case]
        if not selected or set(args.case) - {name for name, _steps in selected}:
            raise RuntimeError('Unknown evaluation case')
        report['expected_cases'] = len(selected)
        for name, steps in selected:
            scenario=Scenario(service)
            record={'name':name,'steps':[],'expected_steps':len(steps),'ok':False,'completed':False}
            report['cases'].append(record)
            for step in steps:
                try:
                    result=scenario.send(step[0],step[1],now=step[2] if len(step)>2 else None)
                except PlanError as exc:
                    result={'input':step[0],'ok':False,'errors':[{'service_error':exc.code}],
                            'protocol_diagnostics':provider.diagnostics[-2:]}
                record['steps'].append(result)
                if not result['ok']:
                    record['ok']=False
                    break
            record['completed'] = len(record['steps']) == len(steps)
            record['ok'] = record['completed'] and all(step['ok'] for step in record['steps'])
            report['provider_calls']=provider.calls
            record['last_protocol_diagnostics']=provider.diagnostics[-2:]
            record['last_transport_diagnostics']=provider.transport.responses[-2:]
            save()
            print(json.dumps({'case':name,'ok':record['ok'],'steps':len(record['steps'])}),flush=True)
        report['ok']=len(report['cases'])==report['expected_cases'] and all(case['ok'] for case in report['cases'])
        save()
        return 0 if report['ok'] else 1
    except (AIModelError,ProviderFailure,PlanError) as exc:
        report['ok']=False
        report['provider_or_service_error']=exc.code
        if record is not None:
            record['ok']=False
            record['interrupted_by']=exc.code
        if 'provider' in locals():
            report['provider_calls']=provider.calls
        save()
        print(json.dumps({'error':exc.code}),flush=True)
        return 2


if __name__=='__main__':
    raise SystemExit(main())
