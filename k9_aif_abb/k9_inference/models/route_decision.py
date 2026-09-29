# SPDX-License-Identifier: Apache-2.0
# K9-AIF Framework

from pydantic import BaseModel
from typing import Dict, Optional


class RouteDecision(BaseModel):
    model_alias: str
    provider: Optional[str] = None

    score: Optional[float] = None
    predicted_cost: Optional[float] = None
    predicted_latency_ms: Optional[int] = None

    rationale: Optional[str] = None

    # Learned routing (K9ModelRouter): "rules" or "learned", the chosen
    # model's predicted quality (0-100), and every candidate's prediction.
    strategy: Optional[str] = None
    predicted_quality: Optional[float] = None
    predictions: Optional[Dict[str, float]] = None