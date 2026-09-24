"""The question-answering agent.

    question -> router -> {sql_gen -> executor} and/or {rag} -> synthesis -> answer

The router is the load-bearing part. Numeric questions ("what was Apple's FY2023
gross margin") must go to SQL, because retrieval over prose returns a sentence
that mentions a number rather than the number. Narrative questions ("what does
Apple say about supply chain risk") must go to RAG, because the warehouse has no
prose in it. Getting that split right matters more to answer quality than any
amount of prompt tuning on either path, which is why the eval set measures
routing separately.
"""

from finlens.agent.orchestrator import Agent, answer_question
from finlens.agent.types import Answer, Citation, Route, RouteDecision

__all__ = ["Agent", "Answer", "Citation", "Route", "RouteDecision", "answer_question"]
