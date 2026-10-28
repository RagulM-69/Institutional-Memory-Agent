"""
Citation verifier and honest abstention evaluator for Institutional Memory Agent.
Enforces evidence discipline: verbatim quote checks, strict provenance verification,
honest abstention, and zero confidence percentages.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from uuid import UUID

from apps.api.retrieval.search import EvidenceChunk

logger = logging.getLogger(__name__)


@dataclass
class VerifiedClaim:
    """A claim verified against retrieved verbatim evidence."""
    claim_text: str
    record_id: str
    record_version_id: str
    chunk_id: str
    exact_quote: str
    quote_offset: Optional[int]
    verification_status: str  # 'verified', 'unsupported', 'dropped'
    evidence_type: str        # 'documented', 'inferred', 'unknown'
    record_title: str
    record_url: Optional[str]
    record_type: Optional[str] = None


@dataclass
class CandidateClaim:
    """Unverified claim proposal from LLM output."""
    claim_text: str
    chunk_id: Optional[str] = None
    exact_quote: Optional[str] = None
    evidence_type: str = "documented"


@dataclass
class VerificationResult:
    """Comprehensive result of verifying an agent response and its claims."""
    answer_text: str
    evidence_level: str        # 'documented', 'inferred', 'unknown'
    evidence_reason: str
    is_abstention: bool
    verified_claims: List[VerifiedClaim] = field(default_factory=list)
    unsupported_claims: List[CandidateClaim] = field(default_factory=list)
    cited_chunks: List[EvidenceChunk] = field(default_factory=list)


class CitationVerifier:
    """
    Deterministic citation verifier.
    Validates that exact quotes are >= 10 characters and exist as exact substrings
    of retrieved evidence chunks. Rejects altered quotes, fabricated citations,
    and missing evidence.
    """

    MIN_QUOTE_LENGTH = 10

    def verify(
        self,
        question: str,
        raw_answer: str,
        candidate_claims: List[CandidateClaim],
        retrieved_chunks: List[EvidenceChunk],
    ) -> VerificationResult:
        """
        Verify all candidate claims against the retrieved evidence set.
        Determine honest abstention if evidence is absent, insufficient, or invalid.
        """
        # If no chunks were retrieved at all, must abstain
        if not retrieved_chunks:
            return VerificationResult(
                answer_text=(
                    f"I cannot answer this question based on the verified institutional memory. "
                    f"No relevant records, commits, or discussions were found in the knowledge base."
                ),
                evidence_level="unknown",
                evidence_reason="No relevant evidence was retrieved from institutional memory for the query.",
                is_abstention=True,
                verified_claims=[],
                unsupported_claims=candidate_claims,
                cited_chunks=[],
            )

        # Index retrieved chunks by chunk_id
        chunk_map: Dict[str, EvidenceChunk] = {
            str(c.chunk_id): c for c in retrieved_chunks
        }

        verified_claims: List[VerifiedClaim] = []
        unsupported_claims: List[CandidateClaim] = []
        cited_chunk_ids: set[str] = set()

        for cand in candidate_claims:
            claim_text = cand.claim_text.strip()
            if not claim_text:
                continue

            chunk_id = str(cand.chunk_id).strip() if cand.chunk_id else None
            exact_quote = cand.exact_quote.strip() if cand.exact_quote else ""

            # Check 1: Chunk must exist in retrieved chunks for this session
            if not chunk_id or chunk_id not in chunk_map:
                logger.warning(
                    "Claim rejected: cited chunk_id '%s' was not in retrieved chunks.", chunk_id
                )
                unsupported_claims.append(cand)
                continue

            chunk = chunk_map[chunk_id]

            # Check 2: Verbatim quote length
            if len(exact_quote) < self.MIN_QUOTE_LENGTH:
                logger.warning(
                    "Claim rejected: quote '%s' is shorter than %d characters.",
                    exact_quote,
                    self.MIN_QUOTE_LENGTH,
                )
                unsupported_claims.append(cand)
                continue

            # Check 3: Quote must be an exact substring of chunk content
            offset = chunk.content.find(exact_quote)
            if offset == -1:
                logger.warning(
                    "Claim rejected: quote '%s' is not an exact verbatim substring of chunk %s.",
                    exact_quote[:40],
                    chunk_id,
                )
                unsupported_claims.append(cand)
                continue

            # Verified!
            cited_chunk_ids.add(chunk_id)
            verified_claims.append(
                VerifiedClaim(
                    claim_text=claim_text,
                    record_id=str(chunk.record_id),
                    record_version_id=str(chunk.record_version_id),
                    chunk_id=str(chunk.chunk_id),
                    exact_quote=exact_quote,
                    quote_offset=offset,
                    verification_status="verified",
                    evidence_type="documented" if cand.evidence_type != "inferred" else "inferred",
                    record_title=chunk.record_title,
                    record_url=chunk.record_url,
                    record_type=chunk.record_type,
                )
            )

        # Build list of cited EvidenceChunk objects
        cited_chunks = [chunk_map[cid] for cid in cited_chunk_ids if cid in chunk_map]

        # Evaluate abstention and evidence level
        if not verified_claims:
            # If no claims could be verified against retrieved chunks, abstain
            reason = (
                f"Retrieved {len(retrieved_chunks)} evidence chunks, but could not verify any verbatim claims "
                f"supporting the answer."
            )
            abstention_answer = (
                f"I cannot provide a verified answer to this question based on the available institutional memory. "
                f"Although {len(retrieved_chunks)} relevant items were inspected, none contained direct verified "
                f"statements confirming this topic."
            )
            return VerificationResult(
                answer_text=abstention_answer,
                evidence_level="unknown",
                evidence_reason=reason,
                is_abstention=True,
                verified_claims=[],
                unsupported_claims=candidate_claims,
                cited_chunks=[],
            )

        # Determine overall evidence level
        # If all verified claims are documented, answer is 'documented'
        # If any verified claim is inferred, answer is 'inferred'
        has_inferred = any(c.evidence_type == "inferred" for c in verified_claims)
        evidence_level = "inferred" if has_inferred else "documented"

        # Evidence reason
        doc_count = sum(1 for c in verified_claims if c.evidence_type == "documented")
        inf_count = sum(1 for c in verified_claims if c.evidence_type == "inferred")
        unsupported_count = len(unsupported_claims)

        reason_parts = []
        if doc_count:
            reason_parts.append(f"{doc_count} claim(s) verified by verbatim quotes from primary sources")
        if inf_count:
            reason_parts.append(f"{inf_count} claim(s) inferred from source evidence")
        if unsupported_count:
            reason_parts.append(f"{unsupported_count} unverified claim(s) omitted")

        evidence_reason = "; ".join(reason_parts) + "."

        return VerificationResult(
            answer_text=raw_answer.strip(),
            evidence_level=evidence_level,
            evidence_reason=evidence_reason,
            is_abstention=False,
            verified_claims=verified_claims,
            unsupported_claims=unsupported_claims,
            cited_chunks=cited_chunks,
        )

