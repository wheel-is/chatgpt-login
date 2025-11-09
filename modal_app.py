"""
Modal app for conversation pricing and deduplication.
This wraps the conversation_pricing.py logic into a Modal web endpoint.
"""

import modal
from typing import Dict, List, Any, Optional, Tuple, Union
import hashlib
import math
import re
import statistics
from dataclasses import dataclass, asdict
from datetime import datetime
import json

# -----------------------
# Conversation pricing logic (copied from conversation_pricing.py)
# -----------------------

VOWELS = set("aeiou")
COMMON_DOMAIN_KEYWORDS = {
    "coding": {"python","java","javascript","function","class","error","stack trace","bug","debug","compile","regex","api","library","package","npm","pip","stack overflow","typescript","node","react","django","flask","docker","kubernetes","sql","query","database"},
    "medical": {"diagnosis","symptom","treatment","prescription","side effect","dose","medication","disease","condition","patient","doctor","clinic","contraindication","bp","blood pressure","glucose","insulin","fever","pain","nausea"},
    "legal": {"statute","precedent","case law","tort","contract","liability","indemnify","jurisdiction","complaint","plaintiff","defendant","appeal","motion","discovery","nda","non-disclosure","copyright","patent","trademark","intellectual property"},
    "finance": {"stock","equity","bond","dividend","earning","revenue","profit","loss","cash flow","valuation","npv","irr","forecast","hedge","option","derivative","etf","portfolio","alpha","beta","volatility"},
    "math": {"theorem","proof","lemma","integral","derivative","limit","matrix","vector","eigen","gradient","p-value","statistic","bayes","posterior","prior","likelihood","probability","variance","mean","median"},
    "education": {"homework","assignment","tutor","lesson","curriculum","exam","quiz","practice","study","explain","teach","learn"},
}

def normalize_text(s: str) -> str:
    s = s.lower()
    s = re.sub(r"\s+", " ", s).strip()
    return s

def approx_token_count(s: str) -> int:
    return max(1, int(len(s) / 4))

def shannon_entropy(s: str) -> float:
    if not s:
        return 0.0
    from math import log2
    counts = {}
    for ch in s:
        counts[ch] = counts.get(ch, 0) + 1
    N = len(s)
    return -sum((c / N) * log2(c / N) for c in counts.values())

def vowel_ratio(s: str) -> float:
    letters = [c for c in s.lower() if c.isalpha()]
    if not letters:
        return 0.0
    v = sum(1 for c in letters if c in VOWELS)
    return v / len(letters)

def alpha_ratio(s: str) -> float:
    if not s:
        return 0.0
    alphas = sum(1 for c in s if c.isalpha() or c.isspace())
    return alphas / len(s)

def word_list(s: str) -> List[str]:
    return re.findall(r"[A-Za-z]+(?:'[A-Za-z]+)?", s)

def simhash(tokens: List[str], bits: int = 64) -> int:
    v = [0] * bits
    for token in tokens:
        h = int(hashlib.md5(token.encode("utf-8")).hexdigest(), 16)
        for i in range(bits):
            bit = (h >> i) & 1
            v[i] += 1 if bit else -1
    fingerprint = 0
    for i, val in enumerate(v):
        if val >= 0:
            fingerprint |= (1 << i)
    return fingerprint

def hamming_distance(x: int, y: int) -> int:
    return (x ^ y).bit_count()


def coerce_timestamp(value: Union[str, float, int, None]) -> float:
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            # Handle ISO strings; replace trailing Z with UTC offset
            cleaned = value.strip()
            if cleaned.endswith('Z'):
                cleaned = cleaned[:-1] + '+00:00'
            return datetime.fromisoformat(cleaned).timestamp()
        except Exception:
            pass
        try:
            return float(value)
        except Exception:
            return 0.0
    return 0.0

@dataclass
class Message:
    role: str
    text: str

@dataclass
class Conversation:
    conversation_id: str
    title: str
    create_time: float
    update_time: float
    messages: List[Message]

    @property
    def full_text(self) -> str:
        return "\n".join(f"{m.role}: {m.text}" for m in self.messages)

@dataclass
class ConversationFeatures:
    n_user_msgs: int
    n_assistant_msgs: int
    n_msgs: int
    total_chars: int
    approx_tokens: int
    avg_chars_per_msg: float
    avg_tokens_per_msg: float
    turns_score: float
    length_score: float
    coherence_score: float
    diversity_score: float
    domain_flags: Dict[str, bool]
    domain_bonus: float

class FeatureExtractor:
    @staticmethod
    def detect_domains(text: str) -> Dict[str, bool]:
        flags = {}
        t = text.lower()
        for dom, kws in COMMON_DOMAIN_KEYWORDS.items():
            flags[dom] = any(kw in t for kw in kws)
        return flags

    @staticmethod
    def compute_scores(conv: Conversation) -> ConversationFeatures:
        texts = [m.text for m in conv.messages]
        full = "\n".join(texts)
        total_chars = len(full)
        tokens = approx_token_count(full)
        n_msgs = len(texts)
        n_user = sum(1 for m in conv.messages if m.role == "user")
        n_asst = sum(1 for m in conv.messages if m.role == "assistant")

        avg_chars = (total_chars / n_msgs) if n_msgs else 0.0
        avg_tokens = (tokens / n_msgs) if n_msgs else 0.0

        turns_score = min(1.0, n_msgs / 10.0)
        length_score = min(1.0, total_chars / 600.0)

        coherences = []
        for t in texts:
            vr = vowel_ratio(t)
            ar = alpha_ratio(t)
            ent = shannon_entropy(t)
            wl = len(word_list(t))
            c = 0.0
            if wl >= 3:
                c += 0.5
            if 0.2 <= vr <= 0.6:
                c += 0.25
            if ar >= 0.6:
                c += 0.25
            if 2.5 <= ent <= 4.5:
                c += 0.1
            coherences.append(min(1.0, c))
        coherence_score = statistics.fmean(coherences) if coherences else 0.0

        words = word_list(full.lower())
        uniq_words = len(set(words))
        diversity_score = min(1.0, (uniq_words / max(1, len(words))) * 2.0)

        dflags = FeatureExtractor.detect_domains(full)
        domain_bonus = 0.0
        if any(dflags.values()):
            if dflags.get("coding") or dflags.get("medical") or dflags.get("legal"):
                domain_bonus = 0.3
            else:
                domain_bonus = 0.2

        return ConversationFeatures(
            n_user_msgs=n_user,
            n_assistant_msgs=n_asst,
            n_msgs=n_msgs,
            total_chars=total_chars,
            approx_tokens=tokens,
            avg_chars_per_msg=avg_chars,
            avg_tokens_per_msg=avg_tokens,
            turns_score=turns_score,
            length_score=length_score,
            coherence_score=coherence_score,
            diversity_score=diversity_score,
            domain_flags=dflags,
            domain_bonus=domain_bonus,
        )

@dataclass
class SpamResult:
    is_spam: bool
    reason: str
    spam_score: float

class SpamDetector:
    @staticmethod
    def score(conv: Conversation, feats: ConversationFeatures) -> SpamResult:
        # Fraud detection disabled; always treat conversations as valid.
        return SpamResult(False, "", 0.0)

# -----------------------
# Deduplication index
# -----------------------

@dataclass
class DupResult:
    status: str  # "UNIQUE" | "EXACT_DUPLICATE" | "NEAR_DUPLICATE"
    match_id: Optional[str]
    similarity: float  # for near-dup: 0..1, exact = 1.0

class DuplicateIndex:
    """Duplicate detection disabled; always mark conversations as unique."""

    def __init__(self, near_dup_threshold_hamming: int = 5):
        self.near_dup_threshold_hamming = near_dup_threshold_hamming

    def check_and_add(self, conv: Conversation) -> DupResult:
        return DupResult("UNIQUE", None, 0.0)

@dataclass
class RateCard:
    tier1_min: float = 0.02
    tier1_max: float = 0.05
    tier2_min: float = 0.005
    tier2_max: float = 0.015
    tier3_min: float = 0.001
    tier3_max: float = 0.003
    min_conv_tier1: float = 0.25
    min_conv_tier2: float = 0.10
    min_conv_tier3: float = 0.01

@dataclass
class PriceResult:
    tier: str
    quality_score: float
    price_per_message: float
    messages_count: int
    conversation_price: float

class PricingEngine:
    @staticmethod
    def compute_quality(feats: ConversationFeatures, spam: SpamResult) -> float:
        q = (
            0.4 * feats.turns_score +
            0.25 * feats.length_score +
            0.25 * feats.coherence_score +
            0.10 * feats.diversity_score +
            feats.domain_bonus
        )
        q = max(0.0, min(1.0, q))
        # Moderated spam penalty; stronger for short/low-quality content
        penalty = 0.35 * spam.spam_score
        if feats.n_msgs >= 3 and feats.total_chars >= 120:
            penalty *= 0.5
        if feats.domain_bonus >= 0.2:
            penalty *= 0.6
        q *= (1.0 - penalty)
        return max(0.0, min(1.0, q))

    @staticmethod
    def assign_tier(feats: ConversationFeatures, quality: float) -> str:
        if quality >= 0.60 and feats.n_msgs >= 3 and feats.total_chars >= 150:
            return "tier1"
        if quality >= 0.30 and feats.n_msgs >= 2 and feats.total_chars >= 70:
            return "tier2"
        return "tier3"

    @staticmethod
    def price_conversation(feats: ConversationFeatures, spam: SpamResult, rate: RateCard) -> PriceResult:
        if spam.is_spam:
            return PriceResult("reject_spam", 0.0, 0.0, feats.n_msgs, 0.0)

        quality = PricingEngine.compute_quality(feats, spam)
        tier = PricingEngine.assign_tier(feats, quality)

        if tier == "tier1":
            pmin, pmax, pmin_conv = rate.tier1_min, rate.tier1_max, rate.min_conv_tier1
        elif tier == "tier2":
            pmin, pmax, pmin_conv = rate.tier2_min, rate.tier2_max, rate.min_conv_tier2
        else:
            pmin, pmax, pmin_conv = rate.tier3_min, rate.tier3_max, rate.min_conv_tier3

        price_per_message = pmin + (pmax - pmin) * quality
        conv_price = price_per_message * feats.n_msgs
        if feats.n_msgs >= 4 and feats.total_chars >= 180:
            conv_price *= 1.1
        conv_price = max(conv_price, pmin_conv)

        return PriceResult(tier, quality, price_per_message, feats.n_msgs, round(conv_price, 4))

@dataclass
class Decision:
    decision: str
    reason: str

@dataclass
class ConversationDecision:
    conversation_id: str
    title: str
    features: ConversationFeatures
    spam: SpamResult
    duplicate: DupResult
    price: PriceResult
    decision: Decision
    log: Dict[str, Any]

class ConversationParser:
    @staticmethod
    def parse_chatgpt_export(obj: Dict[str, Any]) -> Conversation:
        mapping = obj.get("mapping")

        # If there is no mapping (e.g. conversation list items), try to fall back to any
        # provided message list or return an empty conversation shell.
        if not isinstance(mapping, dict) or not mapping:
            messages: List[Message] = []
            raw_messages = obj.get("messages")
            if isinstance(raw_messages, list):
                for raw in raw_messages:
                    if not isinstance(raw, dict):
                        continue
                    role = raw.get("role") or raw.get("author", {}).get("role")
                    if role not in {"user", "assistant"}:
                        continue
                    content = raw.get("content")
                    parts: List[str] = []
                    if isinstance(content, dict):
                        if content.get("content_type") == "text":
                            parts = [p for p in content.get("parts", []) if isinstance(p, str)]
                    elif isinstance(content, list):
                        parts = [p for p in content if isinstance(p, str)]
                    elif isinstance(content, str):
                        parts = [content]
                    text = "\n".join(parts).strip()
                    if text:
                        messages.append(Message(role=role, text=text))

            return Conversation(
                conversation_id=obj.get("conversation_id") or obj.get("id") or "unknown",
                title=obj.get("title") or "",
                create_time=coerce_timestamp(obj.get("create_time")),
                update_time=coerce_timestamp(obj.get("update_time")),
                messages=messages,
            )

        current_id = obj.get("current_node")
        if current_id is None:
            leaves = [k for k, v in mapping.items() if isinstance(v, dict) and not v.get("children")]
            current_id = leaves[0] if leaves else next(iter(mapping.keys()), None)

        path_ids = []
        visited = set()
        while current_id and current_id not in visited:
            visited.add(current_id)
            path_ids.append(current_id)
            node = mapping.get(current_id, {}) or {}
            current_id = node.get("parent")
        path_ids.reverse()

        messages = []
        for nid in path_ids:
            node = mapping.get(nid) or {}
            msg = node.get("message") or {}
            if not isinstance(msg, dict):
                continue
            role = msg.get("author", {}).get("role")
            content = msg.get("content", {}) or {}
            ctype = content.get("content_type")

            if role in {"user", "assistant"} and ctype == "text":
                parts = content.get("parts", []) or []
                text = "\n".join(p for p in parts if isinstance(p, str))
                text = text.strip()
                if text:
                    messages.append(Message(role=role, text=text))

        return Conversation(
            conversation_id=obj.get("conversation_id") or obj.get("id") or "unknown",
            title=obj.get("title") or "",
            create_time=coerce_timestamp(obj.get("create_time")),
            update_time=coerce_timestamp(obj.get("update_time")),
            messages=messages,
        )

class BuyerModule:
    def __init__(self, rate_card: Optional[RateCard] = None, near_dup_hamming: int = 5, log: bool = False):
        self.rate_card = rate_card or RateCard()
        self.dup_index = DuplicateIndex(near_dup_threshold_hamming=near_dup_hamming)
        self.log = log

    def evaluate(self, objs: List[Dict[str, Any]]) -> List[ConversationDecision]:
        results: List[ConversationDecision] = []
        for obj in objs:
            conv = ConversationParser.parse_chatgpt_export(obj)
            feats = FeatureExtractor.compute_scores(conv)
            spam = SpamDetector.score(conv, feats)
            dup = self.dup_index.check_and_add(conv)

            price = PricingEngine.price_conversation(feats, spam, self.rate_card)

            decision = "ACCEPT"
            reason = ""

            if self.log:
                log_payload = {
                    "conversation_id": conv.conversation_id,
                    "title": conv.title,
                    "n_msgs": feats.n_msgs,
                    "total_chars": feats.total_chars,
                    "approx_tokens": feats.approx_tokens,
                    "turns_score": round(feats.turns_score, 3),
                    "length_score": round(feats.length_score, 3),
                    "coherence_score": round(feats.coherence_score, 3),
                    "diversity_score": round(feats.diversity_score, 3),
                    "domain_flags": {k: v for k, v in feats.domain_flags.items() if v},
                    "spam_score": round(spam.spam_score, 3),
                    "is_spam": spam.is_spam,
                    "dup_status": dup.status,
                    "dup_match": dup.match_id,
                    "dup_similarity": dup.similarity,
                    "quality": round(price.quality_score, 3),
                    "tier": price.tier,
                    "price_per_message": round(price.price_per_message, 4),
                    "conversation_price": price.conversation_price,
                    "decision": decision,
                    "reason": reason,
                }
                print(json.dumps(log_payload, ensure_ascii=False))
            else:
                log_payload = {}

            results.append(
                ConversationDecision(
                    conversation_id=conv.conversation_id,
                    title=conv.title,
                    features=feats,
                    spam=spam,
                    duplicate=dup,
                    price=price,
                    decision=Decision(decision, reason),
                    log=log_payload,
                )
            )
        return results

# -----------------------
# Modal app setup
# -----------------------

# Create Modal app with the required dependencies
image = modal.Image.debian_slim().pip_install([
    "pandas",  # Optional dependency for conversation_pricing.py
    "fastapi[standard]"  # For web endpoints
])

app = modal.App("conversation-pricing", image=image)

# Global buyer module instance for deduplication across calls
buyer_module = None

def get_buyer_module(log: bool = False):
    """Get or create the global buyer module instance."""
    global buyer_module
    if buyer_module is None:
        buyer_module = BuyerModule(log=log)
    elif log and not buyer_module.log:
        buyer_module.log = True
    return buyer_module

@app.function()
@modal.fastapi_endpoint(method="POST", docs=True)
def price_conversations(conversations: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Price and deduplicate a list of conversations.

    Args:
        conversations: List of ChatGPT conversation JSON objects

    Returns:
        Dictionary containing pricing results and deduplication status for each conversation
    """
    buyer_module = get_buyer_module(log=True)

    # Process conversations through the pricing pipeline
    decisions = buyer_module.evaluate(conversations)

    # Convert results to a more web-friendly format
    results = {}
    for decision in decisions:
        results[decision.conversation_id] = {
            "title": decision.title,
            "pricing": {
                "tier": decision.price.tier,
                "quality_score": round(decision.price.quality_score, 3),
                "price_per_message": round(decision.price.price_per_message, 4),
                "messages_count": decision.price.messages_count,
                "conversation_price_usd": decision.price.conversation_price,
            },
            "duplication": {
                "status": decision.duplicate.status,
                "match_id": decision.duplicate.match_id,
                "similarity": decision.duplicate.similarity,
            },
            "spam": {
                "is_spam": decision.spam.is_spam,
                "spam_score": round(decision.spam.spam_score, 3),
                "reason": decision.spam.reason,
            },
            "decision": {
                "decision": decision.decision.decision,
                "reason": decision.decision.reason,
            },
            "features": {
                "n_user_msgs": decision.features.n_user_msgs,
                "n_assistant_msgs": decision.features.n_assistant_msgs,
                "n_msgs": decision.features.n_msgs,
                "total_chars": decision.features.total_chars,
                "approx_tokens": decision.features.approx_tokens,
                "coherence_score": round(decision.features.coherence_score, 3),
                "diversity_score": round(decision.features.diversity_score, 3),
                "domain_flags": decision.features.domain_flags,
            },
            "log": decision.log,
        }

    return results

@app.function()
@modal.fastapi_endpoint(method="POST", docs=True)
def price_single_conversation(conversation: Dict[str, Any]) -> Dict[str, Any]:
    """
    Price and check duplication for a single conversation.

    Args:
        conversation: Single ChatGPT conversation JSON object

    Returns:
        Dictionary containing pricing results and deduplication status
    """
    buyer_module = get_buyer_module(log=True)
    result = price_conversations([conversation])
    return list(result.values())[0]

@app.function()
@modal.fastapi_endpoint(method="POST", docs=True)
def reset_deduplication_state() -> Dict[str, str]:
    """
    Reset the deduplication index. Useful for testing or when starting fresh.
    """
    global buyer_module
    buyer_module = BuyerModule(log=True)
    return {"status": "Deduplication state reset successfully"}

@app.function()
@modal.fastapi_endpoint(method="GET", docs=True)
def health_check() -> Dict[str, str]:
    """
    Health check endpoint to verify the service is running.
    """
    global buyer_module
    status = "healthy"
    details = "Service is running"
    if buyer_module is None:
        status = "initializing"
        details = "Buyer module not yet initialized"

    return {
        "status": status,
        "details": details,
        "service": "conversation-pricing"
    }
