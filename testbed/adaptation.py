from datetime import datetime
from typing import Any, Literal, Protocol
from pydantic import BaseModel, Field

Action = Literal['none', 'retry', 'fallback', 'escalate', 'lookup', 'reassign', 'prioritise', 'update_rule']
PRESETS = ['none', 'retry', 'retry_fallback', 'full', 'escalate']


class AdaptationRequest(BaseModel):
    request_id: str
    run_id: str
    case_id: str
    timestamp: datetime
    trigger: str
    element: str
    disruption_label: str
    case_state: dict[str, Any]
    allowed_actions: list[Action]
    attempt: int = 0


class AdaptationResponse(BaseModel):
    request_id: str
    action: Action
    params: dict[str, Any] = Field(default_factory=dict)
    handler: str = 'L0-rules'


class Handler(Protocol):
    def respond(self, request: AdaptationRequest) -> AdaptationResponse: ...


class L0:
    def __init__(self, strategy='full', retry_max=2):
        if strategy not in PRESETS: raise ValueError(strategy)
        self.strategy=strategy; self.retry_max=retry_max

    def respond(self, request):
        action='none'; kind=request.disruption_label
        if self.strategy=='escalate': action='escalate'
        elif self.strategy!='none':
            if kind in ('service_outage','timeout'):
                if request.attempt<self.retry_max: action='retry'
                elif self.strategy in ('retry_fallback','full'): action='fallback'
            elif kind=='missing_data' and self.strategy in ('retry_fallback','full'): action='lookup'
            elif self.strategy=='full':
                action={'resource_shortage':'reassign','sla_risk':'prioritise','rule_change':'update_rule'}.get(kind,'none')
        if action not in request.allowed_actions: action='none'
        return AdaptationResponse(request_id=request.request_id,action=action)
