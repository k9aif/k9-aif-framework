from pydantic import BaseModel
from typing import Optional, Dict, Any


class InferenceRequest(BaseModel):
    prompt: str
    system_prompt: Optional[str] = None
    task_type: Optional[str] = None

    max_tokens: Optional[int] = None
    temperature: Optional[float] = None

    sensitivity: Optional[str] = None

    metadata: Optional[Dict[str, Any]] = None