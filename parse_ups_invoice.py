from typing import Any, Dict, List, Optional

def parse_ups(text: str) -> List[Dict[str, Any]]:
    return []

def parse_summary(text: str) -> Dict[str, Any]:
    return {}

def parse_shipment_by_tracking(text: str, tracking: str) -> Dict[str, Any]:
    return {"tracking": tracking, "error": "UPS parser not implemented"}

def parse_shipment_by_reference(text: str, ref2: str, ref1: Optional[str] = None) -> Dict[str, Any]:
    return {"ref2": ref2, "ref1": ref1, "error": "UPS parser not implemented"}
