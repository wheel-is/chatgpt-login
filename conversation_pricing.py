# We'll create a comprehensive Python module that:
# - Parses ChatGPT-style conversation JSON (like the user's examples)
# - Reconstructs the conversation path
# - Extracts messages (user/assistant) and features
# - Scores quality & spam likelihood with lightweight heuristics
# - Deduplicates (exact + near-duplicate via simhash)
# - Prices each conversation for payout
#
# We'll save it as /mnt/data/conversation_pricing.py and then demo it on the two example conversations.

from __future__ import annotations

import hashlib
import math
import re
import statistics
from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional, Tuple

# --- Optional: we will use pandas for a nice tabular demo if available.
try:
    import pandas as pd
    HAVE_PANDAS = True
except Exception:
    HAVE_PANDAS = False

# -----------------------
# Utility functions
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
    # Lowercase, collapse whitespace, remove excessive punctuation spacing
    s = s.lower()
    s = re.sub(r"\s+", " ", s).strip()
    return s

def approx_token_count(s: str) -> int:
    # Rough heuristic: ~4 chars per token
    # Safeguard against empty
    return max(1, int(len(s) / 4))

def shannon_entropy(s: str) -> float:
    if not s:
        return 0.0
    # Simple character-level entropy
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

def unique_char_ratio(s: str) -> float:
    if not s:
        return 0.0
    return len(set(s)) / max(1, len(s))

def simhash(tokens: List[str], bits: int = 64) -> int:
    """Simple simhash over tokens; good enough for near-duplicate detection."""
    v = [0] * bits
    for token in tokens:
        h = int(hashlib.md5(token.encode("utf-8")).hexdigest(), 16)
        for i in range(bits):
            bit = (h >> i) & 1
            v[i] += 1 if bit else -1
    # Build final hash
    fingerprint = 0
    for i, val in enumerate(v):
        if val >= 0:
            fingerprint |= (1 << i)
    return fingerprint

def hamming_distance(x: int, y: int) -> int:
    return (x ^ y).bit_count()

# -----------------------
# Data classes
# -----------------------

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

    @property
    def user_text(self) -> str:
        return "\n".join(m.text for m in self.messages if m.role == "user")

    @property
    def assistant_text(self) -> str:
        return "\n".join(m.text for m in self.messages if m.role == "assistant")

# -----------------------
# Parsing from ChatGPT-like JSON
# -----------------------

class ConversationParser:
    @staticmethod
    def parse_chatgpt_export(obj: Dict[str, Any]) -> Conversation:
        """
        Reconstructs a single linear conversation from ChatGPT-style export.
        Uses 'current_node' to follow parent pointers back to root, then reverses.
        Extracts user/assistant messages with text content.
        """
        mapping: Dict[str, Any] = obj.get("mapping", {})
        current_id = obj.get("current_node")
        # Fallback: if no current_node, try to find a leaf with no children
        if current_id is None:
            leaves = [k for k, v in mapping.items() if not v.get("children")]
            current_id = leaves[0] if leaves else next(iter(mapping.keys()), None)

        # Walk back to root
        path_ids = []
        visited = set()
        while current_id and current_id not in visited:
            visited.add(current_id)
            path_ids.append(current_id)
            node = mapping.get(current_id, {})
            current_id = node.get("parent")
        path_ids.reverse()

        # Extract messages
        messages: List[Message] = []
        for nid in path_ids:
            node = mapping.get(nid, {})
            msg = node.get("message")
            if not msg:
                continue
            role = msg.get("author", {}).get("role")
            content = msg.get("content", {})
            ctype = content.get("content_type")

            # We only want human/assistant text
            if role in {"user", "assistant"} and ctype == "text":
                parts = content.get("parts", [])
                # Join parts; they are usually a single string
                text = "\n".join(p for p in parts if isinstance(p, str))
                text = text.strip()
                if text:
                    messages.append(Message(role=role, text=text))

        return Conversation(
            conversation_id=obj.get("conversation_id") or "unknown",
            title=obj.get("title") or "",
            create_time=float(obj.get("create_time") or 0.0),
            update_time=float(obj.get("update_time") or 0.0),
            messages=messages,
        )

# -----------------------
# Feature extraction & heuristics
# -----------------------

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

        # Turn score: saturate by 10 messages
        turns_score = min(1.0, n_msgs / 10.0)

        # Length score: saturate by ~600 characters total or ~150 tokens
        length_score = min(1.0, total_chars / 600.0)

        # Coherence proxy: penalize extremely short, vowel-poor, or low alpha ratio
        # Compute per-message heuristics and aggregate
        coherences = []
        for t in texts:
            vr = vowel_ratio(t)
            ar = alpha_ratio(t)
            ent = shannon_entropy(t)
            wl = len(word_list(t))
            # A crude coherence score per message
            c = 0.0
            if wl >= 3:
                c += 0.5
            if 0.2 <= vr <= 0.6:
                c += 0.25
            if ar >= 0.6:
                c += 0.25
            # Reward moderate entropy; penalize extremely low/high
            if 2.5 <= ent <= 4.5:
                c += 0.1
            coherences.append(min(1.0, c))
        coherence_score = statistics.fmean(coherences) if coherences else 0.0

        # Diversity score: based on unique word ratio
        words = word_list(full.lower())
        uniq_words = len(set(words))
        diversity_score = min(1.0, (uniq_words / max(1, len(words))) * 2.0)  # scaled

        # Domain flags & bonus
        dflags = FeatureExtractor.detect_domains(full)
        domain_bonus = 0.0
        if any(dflags.values()):
            # Up to +0.2 if it hits any domain; +0.3 if coding or medical/legal
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

# -----------------------
# Spam detection
# -----------------------

@dataclass
class SpamResult:
    is_spam: bool
    reason: str
    spam_score: float  # 0..1

class SpamDetector:
    @staticmethod
    def score(conv: Conversation, feats: ConversationFeatures) -> SpamResult:
        full = conv.full_text
        # Start with baseline from coherence (invert)
        spam = 1.0 - feats.coherence_score

        # Heuristics: very short conversations are likely low value
        if feats.n_msgs <= 1 or feats.total_chars < 15:
            spam += 0.5

        # Vowel ratio extremes per message -> spammy
        vr_list = [vowel_ratio(m.text) for m in conv.messages]
        if vr_list:
            bad_vowels = sum(1 for v in vr_list if v < 0.15 or v > 0.7)
            spam += bad_vowels * 0.1

        # Non-alpha heavy content (but allow some code/math)
        ar_list = [alpha_ratio(m.text) for m in conv.messages]
        if ar_list and statistics.fmean(ar_list) < 0.5:
            spam += 0.2

        # Many one-word messages or extremely repetitive chars
        one_word_msgs = sum(1 for m in conv.messages if len(word_list(m.text)) <= 1)
        if one_word_msgs >= max(1, feats.n_msgs // 2):
            spam += 0.4

        # Entropy extremes
        ent_list = [shannon_entropy(m.text) for m in conv.messages if m.text]
        if ent_list:
            too_low = sum(1 for e in ent_list if e < 2.0)
            too_high = sum(1 for e in ent_list if e > 5.0)
            spam += (too_low * 0.1 + too_high * 0.05)

        # Normalize and cap between 0 and 1
        spam_score = max(0.0, min(1.0, spam))

        # Thresholds
        if spam_score >= 0.8:
            return SpamResult(True, "Spam-like: too short/gibberish/low coherence", spam_score)
        if feats.n_msgs < 2 or feats.total_chars < 20:
            return SpamResult(True, "Too short to be valuable", max(spam_score, 0.8))
        return SpamResult(False, "", spam_score)

# -----------------------
# Deduplication index
# -----------------------

@dataclass
class DupResult:
    status: str  # "UNIQUE" | "EXACT_DUPLICATE" | "NEAR_DUPLICATE"
    match_id: Optional[str]
    similarity: float  # for near-dup: 0..1, exact = 1.0

class DuplicateIndex:
    """
    Keeps track of seen conversations via canonical SHA-256 and simhash.
    """
    def __init__(self, near_dup_threshold_hamming: int = 3):
        self.hash_to_id: Dict[str, str] = {}
        self.id_to_simhash: Dict[str, int] = {}
        self.near_dup_threshold_hamming = near_dup_threshold_hamming

    @staticmethod
    def canonicalize_text(text: str) -> str:
        s = normalize_text(text)
        # drop multiple spaces and punctuation for canonical form
        s = re.sub(r"[^\w\s]", " ", s)
        s = re.sub(r"\s+", " ", s).strip()
        return s

    def check_and_add(self, conv: Conversation) -> DupResult:
        text = conv.full_text
        can = self.canonicalize_text(text)
        sha = hashlib.sha256(can.encode("utf-8")).hexdigest()

        if sha in self.hash_to_id:
            return DupResult("EXACT_DUPLICATE", self.hash_to_id[sha], 1.0)

        # Compute simhash
        tokens = word_list(can)
        fp = simhash(tokens) if tokens else 0
        # Search for near-dup by hamming distance
        best_dist = None
        best_id = None
        for cid, other_fp in self.id_to_simhash.items():
            dist = hamming_distance(fp, other_fp)
            if best_dist is None or dist < best_dist:
                best_dist = dist
                best_id = cid

        if best_dist is not None and best_dist <= self.near_dup_threshold_hamming:
            # similarity ~ (1 - dist/bits)
            sim = 1.0 - (best_dist / 64.0)
            return DupResult("NEAR_DUPLICATE", best_id, sim)

        # Add as new
        self.hash_to_id[sha] = conv.conversation_id
        self.id_to_simhash[conv.conversation_id] = fp
        return DupResult("UNIQUE", None, 0.0)

# -----------------------
# Pricing
# -----------------------

@dataclass
class RateCard:
    # per-message ranges
    tier1_min: float = 0.02
    tier1_max: float = 0.05
    tier2_min: float = 0.005
    tier2_max: float = 0.015
    tier3_min: float = 0.001
    tier3_max: float = 0.003

    # per-conversation minimums (avoid micropennies)
    min_conv_tier1: float = 0.25
    min_conv_tier2: float = 0.10
    min_conv_tier3: float = 0.01

@dataclass
class PriceResult:
    tier: str
    quality_score: float  # 0..1
    price_per_message: float
    messages_count: int
    conversation_price: float

class PricingEngine:
    @staticmethod
    def compute_quality(feats: ConversationFeatures, spam: SpamResult) -> float:
        # Weighted sum of features + domain bonus - spam
        q = (
            0.4 * feats.turns_score +
            0.25 * feats.length_score +
            0.25 * feats.coherence_score +
            0.10 * feats.diversity_score +
            feats.domain_bonus
        )
        # Penalize by spam score
        q *= (1.0 - 0.5 * spam.spam_score)
        return max(0.0, min(1.0, q))

    @staticmethod
    def assign_tier(feats: ConversationFeatures, quality: float) -> str:
        # Simple rules
        if quality >= 0.75 and feats.n_msgs >= 6:
            return "tier1"
        if quality >= 0.45 and feats.n_msgs >= 3:
            return "tier2"
        return "tier3"

    @staticmethod
    def price_conversation(feats: ConversationFeatures, spam: SpamResult, rate: RateCard) -> PriceResult:
        if spam.is_spam:
            return PriceResult("reject_spam", 0.0, 0.0, feats.n_msgs, 0.0)

        quality = PricingEngine.compute_quality(feats, spam)
        tier = PricingEngine.assign_tier(feats, quality)

        # Map tier to per-message range
        if tier == "tier1":
            pmin, pmax, pmin_conv = rate.tier1_min, rate.tier1_max, rate.min_conv_tier1
        elif tier == "tier2":
            pmin, pmax, pmin_conv = rate.tier2_min, rate.tier2_max, rate.min_conv_tier2
        else:
            pmin, pmax, pmin_conv = rate.tier3_min, rate.tier3_max, rate.min_conv_tier3

        # Interpolate by quality within tier
        price_per_message = pmin + (pmax - pmin) * quality
        conv_price = price_per_message * feats.n_msgs

        # Enforce per-conversation minimums to reduce micropayments
        conv_price = max(conv_price, pmin_conv)

        return PriceResult(tier, quality, price_per_message, feats.n_msgs, round(conv_price, 4))

# -----------------------
# Orchestrator
# -----------------------

@dataclass
class Decision:
    decision: str  # "ACCEPT" | "REVIEW" | "REJECT"
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

class BuyerModule:
    def __init__(self, rate_card: Optional[RateCard] = None, near_dup_hamming: int = 3):
        self.rate_card = rate_card or RateCard()
        self.dup_index = DuplicateIndex(near_dup_threshold_hamming=near_dup_hamming)

    def evaluate(self, objs: List[Dict[str, Any]]) -> List[ConversationDecision]:
        results: List[ConversationDecision] = []
        for obj in objs:
            conv = ConversationParser.parse_chatgpt_export(obj)
            feats = FeatureExtractor.compute_scores(conv)
            spam = SpamDetector.score(conv, feats)
            dup = self.dup_index.check_and_add(conv)

            # Pricing (0 if spam) then adjust for dup
            price = PricingEngine.price_conversation(feats, spam, self.rate_card)

            decision = "ACCEPT"
            reason = ""

            if spam.is_spam:
                decision = "REJECT"
                reason = spam.reason

            if dup.status == "EXACT_DUPLICATE":
                decision = "REJECT"
                reason = f"Exact duplicate of {dup.match_id}"
                price = PriceResult("reject_duplicate", 0.0, 0.0, feats.n_msgs, 0.0)
            elif dup.status == "NEAR_DUPLICATE" and decision != "REJECT":
                # Pay a small fraction and mark for review
                price = PriceResult(price.tier, price.quality_score, price.price_per_message, price.messages_count, round(price.conversation_price * 0.25, 4))
                decision = "REVIEW"
                reason = f"Near-duplicate of {dup.match_id} (similarity ~{dup.similarity:.2f})"

            results.append(ConversationDecision(
                conversation_id=conv.conversation_id,
                title=conv.title,
                features=feats,
                spam=spam,
                duplicate=dup,
                price=price,
                decision=Decision(decision, reason),
            ))
        return results

    @staticmethod
    def to_table(results: List[ConversationDecision]) -> "pd.DataFrame|List[Dict[str, Any]]":
        rows = []
        for r in results:
            rows.append({
                "conversation_id": r.conversation_id,
                "title": r.title,
                "n_msgs": r.features.n_msgs,
                "approx_tokens": r.features.approx_tokens,
                "coherence": round(r.features.coherence_score, 3),
                "diversity": round(r.features.diversity_score, 3),
                "turns_score": round(r.features.turns_score, 3),
                "length_score": round(r.features.length_score, 3),
                "domain_flags": {k: v for k, v in r.features.domain_flags.items() if v},
                "spam_score": round(r.spam.spam_score, 3),
                "dup_status": r.duplicate.status,
                "dup_match": r.duplicate.match_id,
                "price_tier": r.price.tier,
                "quality": round(r.price.quality_score, 3),
                "price_per_message": round(r.price.price_per_message, 4),
                "messages_count": r.price.messages_count,
                "conversation_price_usd": r.price.conversation_price,
                "decision": r.decision.decision,
                "reason": r.decision.reason,
            })
        if HAVE_PANDAS:
            return pd.DataFrame(rows)
        return rows

example1 = {
  "title": "Swim joke",
  "create_time": 1761369605.24448,
  "update_time": 1761369606.945839,
  "mapping": {
    "client-created-root": {
      "id": "client-created-root",
      "message": None,
      "parent": None,
      "children": [
        "f20734e3-7eb5-43ed-af3e-82865c8806c5"
      ]
    },
    "f20734e3-7eb5-43ed-af3e-82865c8806c5": {
      "id": "f20734e3-7eb5-43ed-af3e-82865c8806c5",
      "message": {
        "id": "f20734e3-7eb5-43ed-af3e-82865c8806c5",
        "author": {"role": "system","name": None,"metadata": {}},
        "create_time": None,
        "update_time": None,
        "content": {"content_type": "text","parts": [""]},
        "status": "finished_successfully","end_turn": True,"weight": 0,
        "metadata": {"is_visually_hidden_from_conversation": True},
        "recipient": "all","channel": None
      },
      "parent": "client-created-root",
      "children": ["d48880e3-9ce3-4f9f-a2b3-5d62e938ed66"]
    },
    "d48880e3-9ce3-4f9f-a2b3-5d62e938ed66": {
      "id": "d48880e3-9ce3-4f9f-a2b3-5d62e938ed66",
      "message": {
        "id": "d48880e3-9ce3-4f9f-a2b3-5d62e938ed66",
        "author": {"role": "user","name": None,"metadata": {}},
        "create_time": 1761369604.816,
        "update_time": None,
        "content": {"content_type": "text","parts": ["tell me a joke about swimming"]},
        "status": "finished_successfully","end_turn": None,"weight": 1,
        "metadata": {"selected_github_repos": [],"serialization_metadata": {"custom_symbol_offsets": []},
                     "request_id": "0c7946de-d985-4d61-b8f2-d6fdfe396906","message_source": None,
                     "turn_exchange_id": "59f59c82-67ab-4e5b-8c38-b4e26a1f6336","timestamp_": "absolute"},
        "recipient": "all","channel": None
      },
      "parent": "f20734e3-7eb5-43ed-af3e-82865c8806c5",
      "children": ["9bd2d0e0-8bd0-4a9f-b474-272bb5dd4be8"]
    },
    "9bd2d0e0-8bd0-4a9f-b474-272bb5dd4be8": {
      "id": "9bd2d0e0-8bd0-4a9f-b474-272bb5dd4be8",
      "message": {
        "id": "9bd2d0e0-8bd0-4a9f-b474-272bb5dd4be8",
        "author": {"role": "assistant","name": None,"metadata": {}},
        "create_time": 1761369605.172606,
        "update_time": None,
        "content": {"content_type": "model_editable_context","model_set_context": ""},
        "status": "finished_successfully","end_turn": None,"weight": 1,
        "metadata": {"request_id": "0c7946de-d985-4d61-b8f2-d6fdfe396906","message_type": "next",
                     "model_slug": "gpt-5","default_model_slug": "auto",
                     "parent_id": "d48880e3-9ce3-4f9f-a2b3-5d62e938ed66",
                     "turn_exchange_id": "59f59c82-67ab-4e5b-8c38-b4e26a1f6336","timestamp_": "absolute",
                     "model_switcher_deny": []},
        "recipient": "all","channel": None
      },
      "parent": "d48880e3-9ce3-4f9f-a2b3-5d62e938ed66",
      "children": ["b28d1036-ee51-4176-b55b-61f3a4573310"]
    },
    "b28d1036-ee51-4176-b55b-61f3a4573310": {
      "id": "b28d1036-ee51-4176-b55b-61f3a4573310",
      "message": {
        "id": "b28d1036-ee51-4176-b55b-61f3a4573310",
        "author": {"role": "assistant","name": None,"metadata": {}},
        "create_time": 1761369605.185346,
        "update_time": 1761369605.893026,
        "content": {"content_type": "text","parts": ["Why did the swimmer bring a pencil to the pool?  \n\nBecause she wanted to *draw* a lane! 🏊‍♀️✏️"]},
        "status": "finished_successfully","end_turn": True,"weight": 1,
        "metadata": {"is_complete": True},
        "recipient": "all","channel": None
      },
      "parent": "9bd2d0e0-8bd0-4a9f-b474-272bb5dd4be8",
      "children": []
    }
  },
  "moderation_results": [],
  "current_node": "b28d1036-ee51-4176-b55b-61f3a4573310",
  "plugin_ids": None,
  "conversation_id": "68fc5e01-696c-8330-928d-b0b76a052584",
  "default_model_slug": "auto",
}

example2 = {
  "title": "Tell a joke",
  "create_time": 1761369596.790355,
  "update_time": 1761369598.112881,
  "mapping": {
    "client-created-root": {
      "id": "client-created-root",
      "message": None,
      "parent": None,
      "children": [
        "d0b7e0ae-8c08-4bfb-b0c9-7b8d842cab01"
      ]
    },
    "d0b7e0ae-8c08-4bfb-b0c9-7b8d842cab01": {
      "id": "d0b7e0ae-8c08-4bfb-b0c9-7b8d842cab01",
      "message": {
        "id": "d0b7e0ae-8c08-4bfb-b0c9-7b8d842cab01",
        "author": {"role": "system","name": None,"metadata": {}},
        "create_time": None,
        "update_time": None,
        "content": {"content_type": "text","parts": [""]},
        "status": "finished_successfully",
        "end_turn": True,"weight": 0,
        "metadata": {"is_visually_hidden_from_conversation": True},
        "recipient": "all","channel": None
      },
      "parent": "client-created-root",
      "children": ["c2f280af-8b53-45e3-90d3-5c0ff30a1cd5"]
    },
    "c2f280af-8b53-45e3-90d3-5c0ff30a1cd5": {
      "id": "c2f280af-8b53-45e3-90d3-5c0ff30a1cd5",
      "message": {
        "id": "c2f280af-8b53-45e3-90d3-5c0ff30a1cd5",
        "author": {"role": "user","name": None,"metadata": {}},
        "create_time": 1761369596.148,
        "update_time": None,
        "content": {"content_type": "text","parts": ["tell me a joke"]},
        "status": "finished_successfully","end_turn": None,"weight": 1,
        "metadata": {"request_id": "cd5d41e0-973e-4648-b8a0-57b5c959951f","turn_exchange_id": "a9f7b8cf-549c-458c-a829-e2626f4266b1"},
        "recipient": "all","channel": None
      },
      "parent": "d0b7e0ae-8c08-4bfb-b0c9-7b8d842cab01",
      "children": ["74890903-5870-4ba0-8df8-9bd4fe6f4ad0"]
    },
    "74890903-5870-4ba0-8df8-9bd4fe6f4ad0": {
      "id": "74890903-5870-4ba0-8df8-9bd4fe6f4ad0",
      "message": {
        "id": "74890903-5870-4ba0-8df8-9bd4fe6f4ad0",
        "author": {"role": "assistant","name": None,"metadata": {}},
        "create_time": 1761369596.7124305,
        "update_time": None,
        "content": {"content_type": "model_editable_context","model_set_context": ""},
        "status": "finished_successfully","end_turn": None,"weight": 1,
        "metadata": {"request_id": "cd5d41e0-973e-4648-b8a0-57b5c959951f","turn_exchange_id": "a9f7b8cf-549c-458c-a829-e2626f4266b1"},
        "recipient": "all","channel": None
      },
      "parent": "c2f280af-8b53-45e3-90d3-5c0ff30a1cd5",
      "children": ["fa246746-1785-42b3-8672-86954aed37ee"]
    },
    "fa246746-1785-42b3-8672-86954aed37ee": {
      "id": "fa246746-1785-42b3-8672-86954aed37ee",
      "message": {
        "id": "fa246746-1785-42b3-8672-86954aed37ee",
        "author": {"role": "assistant","name": None,"metadata": {}},
        "create_time": 1761369596.725993,
        "update_time": 1761369597.255921,
        "content": {"content_type": "text","parts": ["Why did the scarecrow win an award?  \n\nBecause he was *outstanding* in his field. 🌾😄"]},
        "status": "finished_successfully","end_turn": True,"weight": 1,
        "metadata": {"is_complete": True},
        "recipient": "all","channel": None
      },
      "parent": "74890903-5870-4ba0-8df8-9bd4fe6f4ad0",
      "children": []
    }
  },
  "moderation_results": [],
  "current_node": "fa246746-1785-42b3-8672-86954aed37ee",
  "conversation_id": "68fc5dfa-a514-8329-afe3-6790cfb41b3f",
  "default_model_slug": "auto",
}

# Module ready for import and use
